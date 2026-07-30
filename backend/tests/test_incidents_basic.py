"""Incident creation, numbering, retrieval, and role gating."""

from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.enums import Role
from tests.factories import (
    make_incident,
    make_member,
    make_org,
    make_service,
    make_user,
)

Login = Callable[[str], Awaitable[dict[str, str]]]


async def test_incidents_get_sequential_numbers(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents"

    numbers = []
    for title in ("First fire", "Second fire", "Third fire"):
        response = await client.post(
            base,
            json={"service_id": str(service.id), "title": title, "severity": "sev2"},
            headers=headers,
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["status"] == "open"
        numbers.append(data["number"])
    assert numbers == ["INC-1", "INC-2", "INC-3"]


async def test_get_and_list_incidents(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner, title="DB down")
    headers = await auth_headers(owner.email)

    fetched = await client.get(f"/api/v1/orgs/{org.slug}/incidents/{incident.id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["title"] == "DB down"

    listed = await client.get(f"/api/v1/orgs/{org.slug}/incidents", headers=headers)
    assert [i["title"] for i in listed.json()["data"]] == ["DB down"]


async def test_foreign_incident_id_is_invisible(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner_a = await make_user(db_session)
    owner_b = await make_user(db_session)
    org_a = await make_org(db_session, owner=owner_a)
    org_b = await make_org(db_session, owner=owner_b)
    service_b = await make_service(db_session, org_b)
    foreign = await make_incident(db_session, org_b, service_b, owner_b)

    response = await client.get(
        f"/api/v1/orgs/{org_a.slug}/incidents/{foreign.id}",
        headers=await auth_headers(owner_a.email),
    )
    assert response.status_code == 404


async def test_create_validations(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    outsider = await make_user(db_session)
    other_owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    other_org = await make_org(db_session, owner=other_owner)
    foreign_service = await make_service(db_session, other_org)
    service = await make_service(db_session, org)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents"

    foreign = await client.post(
        base,
        json={"service_id": str(foreign_service.id), "title": "x", "severity": "sev3"},
        headers=headers,
    )
    assert foreign.status_code == 404

    bad_assignee = await client.post(
        base,
        json={
            "service_id": str(service.id),
            "title": "x",
            "severity": "sev3",
            "assigned_to": str(outsider.id),
        },
        headers=headers,
    )
    assert bad_assignee.status_code == 409
    assert bad_assignee.json()["error"]["code"] == "assignee_not_a_member"

    bad_severity = await client.post(
        base,
        json={"service_id": str(service.id), "title": "x", "severity": "sev9"},
        headers=headers,
    )
    assert bad_severity.status_code == 422


async def test_role_gating_for_creation(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    viewer = await make_user(db_session)
    responder = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    await make_member(db_session, org, viewer, Role.VIEWER)
    await make_member(db_session, org, responder, Role.RESPONDER)
    base = f"/api/v1/orgs/{org.slug}/incidents"
    payload = {"service_id": str(service.id), "title": "spike", "severity": "sev3"}

    denied = await client.post(base, json=payload, headers=await auth_headers(viewer.email))
    assert denied.status_code == 403

    allowed = await client.post(base, json=payload, headers=await auth_headers(responder.email))
    assert allowed.status_code == 201
    assert allowed.json()["data"]["reported_by"] == str(responder.id)
