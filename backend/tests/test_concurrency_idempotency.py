"""Optimistic concurrency (If-Match ETags) and idempotency-key replay."""

import uuid
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from tests.factories import make_incident, make_org, make_service, make_user

Login = Callable[[str], Awaitable[dict[str, str]]]


async def test_etag_round_trip_and_conflict(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner, title="original")
    headers = await auth_headers(owner.email)
    url = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}"

    read = await client.get(url, headers=headers)
    assert read.headers["ETag"] == '"1"'
    assert read.json()["data"]["version"] == 1

    updated = await client.patch(
        url, json={"title": "edited"}, headers={**headers, "If-Match": '"1"'}
    )
    assert updated.status_code == 200
    assert updated.headers["ETag"] == '"2"'

    # A second writer still holding version 1 conflicts, and the response
    # carries the server's current state so a UI can show what changed.
    stale = await client.patch(
        url, json={"title": "from a stale tab"}, headers={**headers, "If-Match": '"1"'}
    )
    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["current_version"] == 2
    assert error["details"]["current"]["title"] == "edited"


async def test_missing_and_malformed_if_match(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    headers = await auth_headers(owner.email)
    url = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}"

    missing = await client.patch(url, json={"title": "x"}, headers=headers)
    assert missing.status_code == 428
    assert missing.json()["error"]["code"] == "precondition_required"

    malformed = await client.patch(
        url, json={"title": "x"}, headers={**headers, "If-Match": "banana"}
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "invalid_precondition"


async def test_status_changes_bump_the_version_too(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    headers = await auth_headers(owner.email)
    url = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}"

    await client.post(f"{url}/status", json={"status": "acknowledged"}, headers=headers)
    read = await client.get(url, headers=headers)
    assert read.headers["ETag"] == '"2"'


async def test_idempotency_key_replays_byte_for_byte(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents"
    key = f"create-{uuid.uuid4().hex}"
    payload = {"service_id": str(service.id), "title": "retried once", "severity": "sev2"}

    first = await client.post(base, json=payload, headers={**headers, "Idempotency-Key": key})
    assert first.status_code == 201
    assert "Idempotency-Replayed" not in first.headers

    retry = await client.post(base, json=payload, headers={**headers, "Idempotency-Key": key})
    assert retry.status_code == 201
    assert retry.headers["Idempotency-Replayed"] == "true"
    assert retry.content == first.content, "replay must be byte-for-byte identical"

    count = await db_session.scalar(
        select(func.count()).select_from(models.Incident).where(models.Incident.org_id == org.id)
    )
    assert count == 1

    # The gapless counter was not consumed by the replay.
    counter = await db_session.get(models.OrganizationCounter, org.id)
    assert counter is not None and counter.incident_seq == 1


async def test_different_keys_create_different_incidents(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents"
    payload = {"service_id": str(service.id), "title": "twice", "severity": "sev3"}

    a = await client.post(base, json=payload, headers={**headers, "Idempotency-Key": "k-1"})
    b = await client.post(base, json=payload, headers={**headers, "Idempotency-Key": "k-2"})
    assert a.json()["data"]["number"] == "INC-1"
    assert b.json()["data"]["number"] == "INC-2"


async def test_idempotency_keys_are_scoped_per_org(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner_a = await make_user(db_session)
    owner_b = await make_user(db_session)
    org_a = await make_org(db_session, owner=owner_a)
    org_b = await make_org(db_session, owner=owner_b)
    service_a = await make_service(db_session, org_a)
    service_b = await make_service(db_session, org_b)
    key = "shared-key"

    a = await client.post(
        f"/api/v1/orgs/{org_a.slug}/incidents",
        json={"service_id": str(service_a.id), "title": "a", "severity": "sev3"},
        headers={**(await auth_headers(owner_a.email)), "Idempotency-Key": key},
    )
    b = await client.post(
        f"/api/v1/orgs/{org_b.slug}/incidents",
        json={"service_id": str(service_b.id), "title": "b", "severity": "sev3"},
        headers={**(await auth_headers(owner_b.email)), "Idempotency-Key": key},
    )
    assert a.status_code == 201 and "Idempotency-Replayed" not in a.headers
    assert b.status_code == 201 and "Idempotency-Replayed" not in b.headers
    assert a.json()["data"]["title"] == "a"
    assert b.json()["data"]["title"] == "b"
