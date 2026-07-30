"""Organisation creation and the org-scoped authorisation dependency in action."""

from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import Role
from tests.factories import make_member, make_org, make_user, unique_slug

Login = Callable[[str], Awaitable[dict[str, str]]]


async def test_create_org_makes_caller_owner_with_counter(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    user = await make_user(db_session)
    headers = await auth_headers(user.email)
    slug = unique_slug()

    created = await client.post(
        "/api/v1/orgs", json={"name": "Acme Response", "slug": slug}, headers=headers
    )
    assert created.status_code == 201
    assert created.json()["data"]["slug"] == slug

    listed = await client.get("/api/v1/orgs", headers=headers)
    entries = {o["slug"]: o["role"] for o in listed.json()["data"]}
    assert entries[slug] == "owner"

    org_id = created.json()["data"]["id"]
    counter = await db_session.get(models.OrganizationCounter, org_id)
    assert counter is not None and counter.incident_seq == 0


async def test_duplicate_slug_conflicts(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    user = await make_user(db_session)
    org = await make_org(db_session, owner=user)
    headers = await auth_headers(user.email)
    response = await client.post(
        "/api/v1/orgs", json={"name": "Copycat", "slug": org.slug}, headers=headers
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slug_taken"


async def test_get_org_as_member_and_as_stranger(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    stranger = await make_user(db_session)
    org = await make_org(db_session, owner=owner)

    ok = await client.get(f"/api/v1/orgs/{org.slug}", headers=await auth_headers(owner.email))
    assert ok.status_code == 200
    assert ok.json()["data"]["role"] == "owner"

    stranger_headers = await auth_headers(stranger.email)
    denied = await client.get(f"/api/v1/orgs/{org.slug}", headers=stranger_headers)
    missing = await client.get(f"/api/v1/orgs/{unique_slug('nope')}", headers=stranger_headers)

    # A real org you don't belong to and a nonexistent org answer identically.
    assert denied.status_code == 404
    assert missing.status_code == 404
    assert denied.json()["error"]["code"] == missing.json()["error"]["code"] == "not_found"


async def test_patch_org_requires_owner_role(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    admin = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, admin, Role.ADMIN)

    renamed = await client.patch(
        f"/api/v1/orgs/{org.slug}",
        json={"name": "Renamed Org"},
        headers=await auth_headers(owner.email),
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["name"] == "Renamed Org"

    forbidden = await client.patch(
        f"/api/v1/orgs/{org.slug}",
        json={"name": "Nope"},
        headers=await auth_headers(admin.email),
    )
    # An admin IS in the org, so this is a 403, not a 404: nothing is leaked.
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


async def test_org_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/orgs")).status_code == 401
    assert (
        await client.post("/api/v1/orgs", json={"name": "X", "slug": "x-y-z"})
    ).status_code == 401


async def test_invalid_slug_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    user = await make_user(db_session)
    headers = await auth_headers(user.email)
    response = await client.post(
        "/api/v1/orgs", json={"name": "Bad", "slug": "Not A Slug!"}, headers=headers
    )
    assert response.status_code == 422
