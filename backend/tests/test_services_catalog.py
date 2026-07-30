"""Service catalogue: CRUD, per-org uniqueness, deletion protection, role gating."""

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


async def test_service_crud_round_trip(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/services"

    created = await client.post(
        base,
        json={"name": "checkout", "description": "Payments path", "tier": "tier1"},
        headers=headers,
    )
    assert created.status_code == 201
    service = created.json()["data"]
    assert service["tier"] == "tier1"

    listed = await client.get(base, headers=headers)
    assert [s["name"] for s in listed.json()["data"]] == ["checkout"]

    patched = await client.patch(
        f"{base}/{service['id']}", json={"owner_team": "payments"}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["owner_team"] == "payments"

    deleted = await client.delete(f"{base}/{service['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(f"{base}/{service['id']}", headers=headers)).status_code == 404


async def test_duplicate_service_name_in_org_conflicts(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_service(db_session, org, name="api-gateway")
    response = await client.post(
        f"/api/v1/orgs/{org.slug}/services",
        json={"name": "api-gateway"},
        headers=await auth_headers(owner.email),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "service_name_taken"


async def test_same_service_name_in_another_org_is_fine(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner_a = await make_user(db_session)
    owner_b = await make_user(db_session)
    org_a = await make_org(db_session, owner=owner_a)
    org_b = await make_org(db_session, owner=owner_b)
    await make_service(db_session, org_a, name="edge")

    response = await client.post(
        f"/api/v1/orgs/{org_b.slug}/services",
        json={"name": "edge"},
        headers=await auth_headers(owner_b.email),
    )
    assert response.status_code == 201


async def test_foreign_service_id_is_a_404_even_for_members(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    """The org scope is applied in the query: a real id from another org is invisible."""
    owner_a = await make_user(db_session)
    owner_b = await make_user(db_session)
    org_a = await make_org(db_session, owner=owner_a)
    org_b = await make_org(db_session, owner=owner_b)
    foreign = await make_service(db_session, org_b, name="their-db")

    response = await client.get(
        f"/api/v1/orgs/{org_a.slug}/services/{foreign.id}",
        headers=await auth_headers(owner_a.email),
    )
    assert response.status_code == 404


async def test_service_with_incidents_cannot_be_deleted(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    await make_incident(db_session, org, service, owner)

    response = await client.delete(
        f"/api/v1/orgs/{org.slug}/services/{service.id}",
        headers=await auth_headers(owner.email),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "service_in_use"


async def test_viewer_reads_but_cannot_write(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    viewer = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    await make_member(db_session, org, viewer, Role.VIEWER)
    headers = await auth_headers(viewer.email)
    base = f"/api/v1/orgs/{org.slug}/services"

    assert (await client.get(base, headers=headers)).status_code == 200
    assert (await client.get(f"{base}/{service.id}", headers=headers)).status_code == 200
    assert (await client.post(base, json={"name": "nope"}, headers=headers)).status_code == 403
    assert (
        await client.patch(f"{base}/{service.id}", json={"name": "x"}, headers=headers)
    ).status_code == 403
    assert (await client.delete(f"{base}/{service.id}", headers=headers)).status_code == 403
