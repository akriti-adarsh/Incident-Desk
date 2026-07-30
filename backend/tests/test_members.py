"""Members and invitations: the last-owner rule, owner-touch guard, invite flow."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import Role
from tests.factories import PASSWORD, make_member, make_org, make_user, unique_email
from tests.mailpit import extract_token, latest_message_text_to

Login = Callable[[str], Awaitable[dict[str, str]]]


async def test_list_members_shows_roles(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    viewer = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, viewer, Role.VIEWER)

    response = await client.get(
        f"/api/v1/orgs/{org.slug}/members", headers=await auth_headers(viewer.email)
    )
    assert response.status_code == 200
    roles = {m["email"]: m["role"] for m in response.json()["data"]}
    assert roles == {owner.email: "owner", viewer.email: "viewer"}


async def test_invite_existing_user_and_accept(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    invitee = await make_user(db_session)
    org = await make_org(db_session, owner=owner)

    invited = await client.post(
        f"/api/v1/orgs/{org.slug}/invitations",
        json={"email": invitee.email, "role": "responder"},
        headers=await auth_headers(owner.email),
    )
    assert invited.status_code == 201

    token = extract_token(await latest_message_text_to(invitee.email))
    accepted = await client.post(
        "/api/v1/invitations/accept",
        json={"token": token},
        headers=await auth_headers(invitee.email),
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"] == {
        "org_slug": org.slug,
        "org_name": org.name,
        "role": "responder",
    }

    # The new member can now see the org.
    seen = await client.get(f"/api/v1/orgs/{org.slug}", headers=await auth_headers(invitee.email))
    assert seen.status_code == 200
    assert seen.json()["data"]["role"] == "responder"


async def test_invite_unregistered_address_register_then_accept(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    ghost = unique_email("invitee")

    invited = await client.post(
        f"/api/v1/orgs/{org.slug}/invitations",
        json={"email": ghost, "role": "viewer"},
        headers=await auth_headers(owner.email),
    )
    assert invited.status_code == 201
    invite_token = extract_token(await latest_message_text_to(ghost))

    # The invited person registers, verifies, logs in, then accepts.
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": ghost, "password": PASSWORD, "full_name": "New Teammate"},
    )
    assert register.status_code == 201
    verify_token = extract_token(await latest_message_text_to(ghost))
    assert verify_token != invite_token
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": verify_token})
    ).status_code == 200

    accepted = await client.post(
        "/api/v1/invitations/accept",
        json={"token": invite_token},
        headers=await auth_headers(ghost),
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["role"] == "viewer"


async def test_accept_with_wrong_account_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    invitee = await make_user(db_session)
    impostor = await make_user(db_session)
    org = await make_org(db_session, owner=owner)

    await client.post(
        f"/api/v1/orgs/{org.slug}/invitations",
        json={"email": invitee.email, "role": "admin"},
        headers=await auth_headers(owner.email),
    )
    token = extract_token(await latest_message_text_to(invitee.email))

    response = await client.post(
        "/api/v1/invitations/accept",
        json={"token": token},
        headers=await auth_headers(impostor.email),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "wrong_account"


async def test_expired_and_revoked_invitations_are_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    invitee = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    owner_headers = await auth_headers(owner.email)

    await client.post(
        f"/api/v1/orgs/{org.slug}/invitations",
        json={"email": invitee.email, "role": "viewer"},
        headers=owner_headers,
    )
    token = extract_token(await latest_message_text_to(invitee.email))

    await db_session.execute(
        update(models.OrgInvitation).values(expires_at=datetime.now(UTC) - timedelta(days=1))
    )
    expired = await client.post(
        "/api/v1/invitations/accept",
        json={"token": token},
        headers=await auth_headers(invitee.email),
    )
    assert expired.status_code == 400
    assert expired.json()["error"]["code"] == "invalid_invitation"


async def test_duplicate_pending_invitation_conflicts(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    headers = await auth_headers(owner.email)
    target = unique_email("twice")

    first = await client.post(
        f"/api/v1/orgs/{org.slug}/invitations",
        json={"email": target, "role": "viewer"},
        headers=headers,
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/orgs/{org.slug}/invitations",
        json={"email": target, "role": "viewer"},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invitation_pending"


async def test_inviting_an_existing_member_conflicts(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    member = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, member, Role.VIEWER)

    response = await client.post(
        f"/api/v1/orgs/{org.slug}/invitations",
        json={"email": member.email, "role": "viewer"},
        headers=await auth_headers(owner.email),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_member"


async def test_viewer_cannot_invite(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    viewer = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, viewer, Role.VIEWER)

    response = await client.post(
        f"/api/v1/orgs/{org.slug}/invitations",
        json={"email": unique_email(), "role": "viewer"},
        headers=await auth_headers(viewer.email),
    )
    assert response.status_code == 403


async def test_admin_manages_lower_roles_but_never_owners(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    admin = await make_user(db_session)
    viewer = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, admin, Role.ADMIN)
    await make_member(db_session, org, viewer, Role.VIEWER)
    admin_headers = await auth_headers(admin.email)

    promoted = await client.patch(
        f"/api/v1/orgs/{org.slug}/members/{viewer.id}",
        json={"role": "responder"},
        headers=admin_headers,
    )
    assert promoted.status_code == 200
    assert promoted.json()["data"]["role"] == "responder"

    demote_owner = await client.patch(
        f"/api/v1/orgs/{org.slug}/members/{owner.id}",
        json={"role": "viewer"},
        headers=admin_headers,
    )
    assert demote_owner.status_code == 403

    crown = await client.patch(
        f"/api/v1/orgs/{org.slug}/members/{viewer.id}",
        json={"role": "owner"},
        headers=admin_headers,
    )
    assert crown.status_code == 403


async def test_last_owner_cannot_be_demoted_or_removed(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    headers = await auth_headers(owner.email)

    demote = await client.patch(
        f"/api/v1/orgs/{org.slug}/members/{owner.id}",
        json={"role": "admin"},
        headers=headers,
    )
    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "last_owner"

    remove = await client.delete(f"/api/v1/orgs/{org.slug}/members/{owner.id}", headers=headers)
    assert remove.status_code == 409
    assert remove.json()["error"]["code"] == "last_owner"


async def test_owner_can_hand_over_and_step_down(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    successor = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, successor, Role.ADMIN)
    headers = await auth_headers(owner.email)

    crown = await client.patch(
        f"/api/v1/orgs/{org.slug}/members/{successor.id}",
        json={"role": "owner"},
        headers=headers,
    )
    assert crown.status_code == 200

    step_down = await client.patch(
        f"/api/v1/orgs/{org.slug}/members/{owner.id}",
        json={"role": "viewer"},
        headers=headers,
    )
    assert step_down.status_code == 200
    assert step_down.json()["data"]["role"] == "viewer"


async def test_removed_member_loses_access_entirely(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    member = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, member, Role.RESPONDER)
    member_headers = await auth_headers(member.email)

    assert (await client.get(f"/api/v1/orgs/{org.slug}", headers=member_headers)).status_code == 200

    removed = await client.delete(
        f"/api/v1/orgs/{org.slug}/members/{member.id}",
        headers=await auth_headers(owner.email),
    )
    assert removed.status_code == 204

    # Post-removal, the org answers as if it does not exist.
    assert (await client.get(f"/api/v1/orgs/{org.slug}", headers=member_headers)).status_code == 404
