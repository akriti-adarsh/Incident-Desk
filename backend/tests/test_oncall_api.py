"""On-call API: schedules, shifts, database-enforced overlap, who is on call."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.enums import Role
from tests.factories import make_member, make_org, make_service, make_user

Login = Callable[[str], Awaitable[dict[str, str]]]


def iso(dt: datetime) -> str:
    return dt.isoformat()


async def test_schedule_and_shift_lifecycle_with_overlap_rejection(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    responder = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    await make_member(db_session, org, responder, Role.RESPONDER)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/on-call"

    schedule = await client.post(
        f"{base}/schedules",
        json={"service_id": str(service.id), "name": "primary"},
        headers=headers,
    )
    assert schedule.status_code == 201
    schedule_id = schedule.json()["data"]["id"]

    start = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    first = await client.post(
        f"{base}/schedules/{schedule_id}/shifts",
        json={
            "user_id": str(owner.id),
            "starts_at": iso(start),
            "ends_at": iso(start + timedelta(hours=8)),
        },
        headers=headers,
    )
    assert first.status_code == 201

    overlapping = await client.post(
        f"{base}/schedules/{schedule_id}/shifts",
        json={
            "user_id": str(responder.id),
            "starts_at": iso(start + timedelta(hours=4)),
            "ends_at": iso(start + timedelta(hours=12)),
        },
        headers=headers,
    )
    assert overlapping.status_code == 409
    assert overlapping.json()["error"]["code"] == "shift_overlap"

    adjacent = await client.post(
        f"{base}/schedules/{schedule_id}/shifts",
        json={
            "user_id": str(responder.id),
            "starts_at": iso(start + timedelta(hours=8)),
            "ends_at": iso(start + timedelta(hours=16)),
        },
        headers=headers,
    )
    assert adjacent.status_code == 201

    listed = await client.get(
        f"{base}/schedules/{schedule_id}/shifts",
        params={"from": iso(start), "to": iso(start + timedelta(hours=9))},
        headers=headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 2

    shift_id = adjacent.json()["data"]["id"]
    removed = await client.delete(
        f"{base}/schedules/{schedule_id}/shifts/{shift_id}", headers=headers
    )
    assert removed.status_code == 204


async def test_shift_requires_org_membership(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    outsider = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/on-call"

    schedule = await client.post(
        f"{base}/schedules",
        json={"service_id": str(service.id), "name": "primary"},
        headers=headers,
    )
    start = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    response = await client.post(
        f"{base}/schedules/{schedule.json()['data']['id']}/shifts",
        json={
            "user_id": str(outsider.id),
            "starts_at": iso(start),
            "ends_at": iso(start + timedelta(hours=8)),
        },
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_a_member"


async def test_schedule_for_foreign_service_is_404(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner_a = await make_user(db_session)
    owner_b = await make_user(db_session)
    org_a = await make_org(db_session, owner=owner_a)
    org_b = await make_org(db_session, owner=owner_b)
    foreign_service = await make_service(db_session, org_b)

    response = await client.post(
        f"/api/v1/orgs/{org_a.slug}/on-call/schedules",
        json={"service_id": str(foreign_service.id), "name": "sneaky"},
        headers=await auth_headers(owner_a.email),
    )
    assert response.status_code == 404


async def test_backwards_shift_fails_validation(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    headers = await auth_headers(owner.email)
    schedule = await client.post(
        f"/api/v1/orgs/{org.slug}/on-call/schedules",
        json={"service_id": str(service.id), "name": "primary"},
        headers=headers,
    )
    start = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    response = await client.post(
        f"/api/v1/orgs/{org.slug}/on-call/schedules/{schedule.json()['data']['id']}/shifts",
        json={
            "user_id": str(owner.id),
            "starts_at": iso(start),
            "ends_at": iso(start - timedelta(hours=1)),
        },
        headers=headers,
    )
    assert response.status_code == 422


async def test_who_is_on_call_now_and_nobody(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/on-call"

    schedule = await client.post(
        f"{base}/schedules",
        json={"service_id": str(service.id), "name": "primary"},
        headers=headers,
    )
    schedule_id = schedule.json()["data"]["id"]

    nobody = await client.get(
        f"{base}/who-is-on-call", params={"service_id": str(service.id)}, headers=headers
    )
    assert nobody.status_code == 200
    assert nobody.json()["data"][0]["on_call"] is None

    now = datetime.now(UTC)
    await client.post(
        f"{base}/schedules/{schedule_id}/shifts",
        json={
            "user_id": str(owner.id),
            "starts_at": iso(now - timedelta(hours=1)),
            "ends_at": iso(now + timedelta(hours=7)),
        },
        headers=headers,
    )
    somebody = await client.get(
        f"{base}/who-is-on-call", params={"service_id": str(service.id)}, headers=headers
    )
    entry = somebody.json()["data"][0]
    assert entry["schedule_name"] == "primary"
    assert entry["on_call"]["user_id"] == str(owner.id)
