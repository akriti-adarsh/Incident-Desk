"""Comments: authorship, editing, soft deletion, moderation."""

from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _setup(
    db_session: AsyncSession,
) -> tuple[models.Organization, models.Incident, models.User]:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    return org, incident, owner


async def test_comment_lifecycle(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, owner = await _setup(db_session)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/comments"

    created = await client.post(base, json={"body": "Looking into it"}, headers=headers)
    assert created.status_code == 201
    comment = created.json()["data"]
    assert comment["edited_at"] is None

    edited = await client.patch(
        f"{base}/{comment['id']}", json={"body": "Root cause found"}, headers=headers
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["body"] == "Root cause found"
    assert edited.json()["data"]["edited_at"] is not None

    listed = await client.get(base, headers=headers)
    assert [c["body"] for c in listed.json()["data"]] == ["Root cause found"]

    deleted = await client.delete(f"{base}/{comment['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(base, headers=headers)).json()["data"] == []

    # Soft delete: the row survives with deleted_at set.
    row = await db_session.scalar(select(models.Comment).where(models.Comment.id == comment["id"]))
    assert row is not None and row.deleted_at is not None


async def test_comments_keep_insertion_order(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, owner = await _setup(db_session)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/comments"

    for body in ("first", "second", "third"):
        assert (await client.post(base, json={"body": body}, headers=headers)).status_code == 201
    listed = await client.get(base, headers=headers)
    assert [c["body"] for c in listed.json()["data"]] == ["first", "second", "third"]


async def test_only_the_author_edits(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, owner = await _setup(db_session)
    other = await make_user(db_session)
    await make_member(db_session, org, other, Role.ADMIN)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/comments"

    comment = (
        await client.post(base, json={"body": "mine"}, headers=await auth_headers(owner.email))
    ).json()["data"]

    # Even an admin cannot edit someone else's words.
    response = await client.patch(
        f"{base}/{comment['id']}",
        json={"body": "hijacked"},
        headers=await auth_headers(other.email),
    )
    assert response.status_code == 403


async def test_moderation_rules_for_deletion(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, owner = await _setup(db_session)
    responder = await make_user(db_session)
    admin = await make_user(db_session)
    await make_member(db_session, org, responder, Role.RESPONDER)
    await make_member(db_session, org, admin, Role.ADMIN)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/comments"

    comment = (
        await client.post(base, json={"body": "hot take"}, headers=await auth_headers(owner.email))
    ).json()["data"]

    # A responder (no moderate permission) cannot delete someone else's comment.
    denied = await client.delete(
        f"{base}/{comment['id']}", headers=await auth_headers(responder.email)
    )
    assert denied.status_code == 403

    # An admin can: comment moderation.
    allowed = await client.delete(
        f"{base}/{comment['id']}", headers=await auth_headers(admin.email)
    )
    assert allowed.status_code == 204


async def test_viewer_reads_but_cannot_comment(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, _ = await _setup(db_session)
    viewer = await make_user(db_session)
    await make_member(db_session, org, viewer, Role.VIEWER)
    headers = await auth_headers(viewer.email)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/comments"

    assert (await client.get(base, headers=headers)).status_code == 200
    assert (await client.post(base, json={"body": "hi"}, headers=headers)).status_code == 403


async def test_comment_added_lands_on_the_timeline(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    org, incident, owner = await _setup(db_session)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}"

    await client.post(f"{base}/comments", json={"body": "note"}, headers=headers)
    events = await client.get(f"{base}/events", headers=headers)
    assert "comment.added" in [e["event_type"] for e in events.json()["data"]]
