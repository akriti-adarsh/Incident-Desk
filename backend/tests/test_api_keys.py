"""API keys: creation, scoped access, revocation, expiry, and their limits."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

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


async def make_key(
    client: httpx.AsyncClient,
    org_slug: str,
    headers: dict[str, str],
    scopes: list[str],
    expires_at: str | None = None,
) -> tuple[str, str]:
    """Returns (key_id, full_token)."""
    payload: dict[str, object] = {"name": "ci-bot", "scopes": scopes}
    if expires_at is not None:
        payload["expires_at"] = expires_at
    response = await client.post(f"/api/v1/orgs/{org_slug}/api-keys", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    return data["id"], data["api_key"]


def key_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_create_shows_secret_once_and_key_works(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    await make_incident(db_session, org, service, owner)
    headers = await auth_headers(owner.email)

    _, token = await make_key(client, org.slug, headers, ["incident:view"])
    assert token.startswith("ik_")

    listed = await client.get(f"/api/v1/orgs/{org.slug}/api-keys", headers=headers)
    entry = listed.json()["data"][0]
    assert "api_key" not in entry
    assert entry["scopes"] == ["incident:view"]

    incidents = await client.get(f"/api/v1/orgs/{org.slug}/incidents", headers=key_headers(token))
    assert incidents.status_code == 200
    assert len(incidents.json()["data"]) == 1

    # last_used_at is stamped by authentication.
    listed_again = await client.get(f"/api/v1/orgs/{org.slug}/api-keys", headers=headers)
    assert listed_again.json()["data"][0]["last_used_at"] is not None


async def test_scopes_are_enforced(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    headers = await auth_headers(owner.email)
    _, token = await make_key(client, org.slug, headers, ["incident:view"])

    denied = await client.post(
        f"/api/v1/orgs/{org.slug}/services",
        json={"name": "via-key"},
        headers=key_headers(token),
    )
    assert denied.status_code == 403

    _, manage_token = await make_key(client, org.slug, headers, ["service:manage"])
    allowed = await client.post(
        f"/api/v1/orgs/{org.slug}/services",
        json={"name": "via-key"},
        headers=key_headers(manage_token),
    )
    assert allowed.status_code == 201


async def test_key_is_bound_to_its_org(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner_a = await make_user(db_session)
    owner_b = await make_user(db_session)
    org_a = await make_org(db_session, owner=owner_a)
    org_b = await make_org(db_session, owner=owner_b)
    _, token = await make_key(
        client, org_a.slug, await auth_headers(owner_a.email), ["incident:view"]
    )

    response = await client.get(f"/api/v1/orgs/{org_b.slug}/incidents", headers=key_headers(token))
    assert response.status_code == 404
    assert org_b is not None


async def test_revoked_and_expired_keys_fail(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    headers = await auth_headers(owner.email)

    key_id, token = await make_key(client, org.slug, headers, ["incident:view"])
    revoked = await client.delete(f"/api/v1/orgs/{org.slug}/api-keys/{key_id}", headers=headers)
    assert revoked.status_code == 204
    after = await client.get(f"/api/v1/orgs/{org.slug}/incidents", headers=key_headers(token))
    assert after.status_code == 401

    _, stale_token = await make_key(
        client,
        org.slug,
        headers,
        ["incident:view"],
        expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )
    expired = await client.get(
        f"/api/v1/orgs/{org.slug}/incidents", headers=key_headers(stale_token)
    )
    assert expired.status_code == 401


async def test_garbage_key_fails(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    response = await client.get(
        f"/api/v1/orgs/{org.slug}/incidents",
        headers=key_headers("ik_deadbeef_notarealsecret"),
    )
    assert response.status_code == 401


async def test_keys_cannot_author_content_or_reach_user_endpoints(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    headers = await auth_headers(owner.email)
    _, token = await make_key(client, org.slug, headers, ["incident:create", "incident:view"])

    authored = await client.post(
        f"/api/v1/orgs/{org.slug}/incidents",
        json={"service_id": str(service.id), "title": "bot fire", "severity": "sev3"},
        headers=key_headers(token),
    )
    assert authored.status_code == 403
    assert authored.json()["error"]["code"] == "user_required"

    me = await client.get("/api/v1/auth/me", headers=key_headers(token))
    assert me.status_code == 401


async def test_key_can_update_status_as_a_system_actor(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    """Automation may move the state machine; the timeline shows a system actor."""
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    headers = await auth_headers(owner.email)
    _, token = await make_key(client, org.slug, headers, ["incident:update", "incident:view"])

    acked = await client.post(
        f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/status",
        json={"status": "acknowledged"},
        headers=key_headers(token),
    )
    assert acked.status_code == 200

    events = await client.get(
        f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/events",
        headers=key_headers(token),
    )
    status_event = next(e for e in events.json()["data"] if e["event_type"] == "status.changed")
    assert status_event["actor_id"] is None


async def test_only_admins_manage_keys(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    responder = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, responder, Role.RESPONDER)

    response = await client.post(
        f"/api/v1/orgs/{org.slug}/api-keys",
        json={"name": "nope", "scopes": ["incident:view"]},
        headers=await auth_headers(responder.email),
    )
    assert response.status_code == 403
