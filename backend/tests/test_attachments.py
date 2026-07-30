"""Attachments: streamed upload, checksums, size cap, org-scoped download."""

import hashlib
from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.enums import Role
from tests.factories import (
    make_incident,
    make_member,
    make_org,
    make_service,
    make_user,
)

Login = Callable[[str], Awaitable[dict[str, str]]]

CONTENT = b"stack trace: NullPointerException at line 42\n" * 100


async def _setup(
    db_session: AsyncSession,
) -> tuple[models.Organization, models.Incident, models.User]:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    return org, incident, owner


async def test_upload_download_round_trip(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, owner = await _setup(db_session)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/attachments"

    uploaded = await client.post(
        base,
        files={"file": ("trace.log", CONTENT, "text/plain")},
        headers=headers,
    )
    assert uploaded.status_code == 201
    data = uploaded.json()["data"]
    assert data["filename"] == "trace.log"
    assert data["size_bytes"] == len(CONTENT)
    assert data["checksum"] == hashlib.sha256(CONTENT).hexdigest()

    listed = await client.get(base, headers=headers)
    assert [a["filename"] for a in listed.json()["data"]] == ["trace.log"]

    downloaded = await client.get(f"{base}/{data['id']}/download", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.content == CONTENT
    assert downloaded.headers["content-type"].startswith("text/plain")


async def test_upload_lands_on_the_timeline(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, owner = await _setup(db_session)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}"

    await client.post(
        f"{base}/attachments",
        files={"file": ("shot.png", b"\x89PNG fake", "image/png")},
        headers=headers,
    )
    events = await client.get(f"{base}/events", headers=headers)
    assert "attachment.added" in [e["event_type"] for e in events.json()["data"]]


async def test_oversized_upload_is_rejected(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    auth_headers: Login,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, incident, owner = await _setup(db_session)
    headers = await auth_headers(owner.email)
    monkeypatch.setattr(get_settings(), "attachment_max_bytes", 128)

    response = await client.post(
        f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/attachments",
        files={"file": ("big.bin", b"x" * 1024, "application/octet-stream")},
        headers=headers,
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "attachment_too_large"

    # Nothing was kept: neither a row nor a file.
    listed = await client.get(
        f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/attachments", headers=headers
    )
    assert listed.json()["data"] == []


async def test_viewer_cannot_upload(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, _ = await _setup(db_session)
    viewer = await make_user(db_session)
    await make_member(db_session, org, viewer, Role.VIEWER)

    response = await client.post(
        f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/attachments",
        files={"file": ("x.txt", b"data", "text/plain")},
        headers=await auth_headers(viewer.email),
    )
    assert response.status_code == 403


async def test_foreign_attachment_is_invisible(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org_a_owner = await make_user(db_session)
    org_a = await make_org(db_session, owner=org_a_owner)
    service_a = await make_service(db_session, org_a)
    incident_a = await make_incident(db_session, org_a, service_a, org_a_owner)

    org_b, incident_b, owner_b = await _setup(db_session)
    headers_b = await auth_headers(owner_b.email)
    uploaded = await client.post(
        f"/api/v1/orgs/{org_b.slug}/incidents/{incident_b.id}/attachments",
        files={"file": ("secret.txt", b"org b data", "text/plain")},
        headers=headers_b,
    )
    attachment_id = uploaded.json()["data"]["id"]

    # Org A's owner cannot reach org B's attachment through their own org,
    # even when guessing the right incident and attachment ids.
    response = await client.get(
        f"/api/v1/orgs/{org_a.slug}/incidents/{incident_b.id}/attachments/{attachment_id}/download",
        headers=await auth_headers(org_a_owner.email),
    )
    assert response.status_code == 404
    assert incident_a is not None
