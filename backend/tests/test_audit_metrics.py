"""Audit log coverage of mutating actions, and SQL-computed metrics."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import IncidentStatus, Role, Severity
from tests.factories import (
    make_incident,
    make_member,
    make_org,
    make_service,
    make_user,
)

Login = Callable[[str], Awaitable[dict[str, str]]]


async def test_actions_land_in_the_audit_log_with_actor_and_diff(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    viewer = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    await make_member(db_session, org, viewer, Role.VIEWER)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}"

    created = await client.post(
        f"{base}/incidents",
        json={"service_id": str(service.id), "title": "audit me", "severity": "sev2"},
        headers=headers,
    )
    incident_id = created.json()["data"]["id"]
    await client.post(
        f"{base}/incidents/{incident_id}/status",
        json={"status": "acknowledged"},
        headers=headers,
    )
    await client.patch(f"{base}/members/{viewer.id}", json={"role": "responder"}, headers=headers)

    log = await client.get(f"{base}/audit-log", headers=headers)
    assert log.status_code == 200
    entries = log.json()["data"]
    by_action = {e["action"]: e for e in entries}

    assert by_action["incident.created"]["resource_id"] == incident_id
    assert by_action["incident.created"]["actor_id"] == str(owner.id)
    assert by_action["incident.created"]["after"]["number"] == "INC-1"

    assert by_action["incident.status_changed"]["before"] == {"status": "open"}
    assert by_action["incident.status_changed"]["after"] == {"status": "acknowledged"}

    assert by_action["member.role_changed"]["before"] == {"role": "viewer"}
    assert by_action["member.role_changed"]["after"] == {"role": "responder"}
    assert by_action["member.role_changed"]["user_agent"] is not None


async def test_audit_filters_and_access_control(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    viewer = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, viewer, Role.VIEWER)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}"

    await client.post(f"{base}/services", json={"name": "svc-one"}, headers=headers)
    await client.post(
        f"{base}/api-keys",
        json={"name": "bot", "scopes": ["incident:view"]},
        headers=headers,
    )

    only_services = await client.get(
        f"{base}/audit-log", params={"resource_type": "service"}, headers=headers
    )
    assert [e["action"] for e in only_services.json()["data"]] == ["service.created"]

    only_keys = await client.get(
        f"{base}/audit-log", params={"action": "apikey.created"}, headers=headers
    )
    assert len(only_keys.json()["data"]) == 1

    # The audit log is admin-only: a viewer gets 403.
    denied = await client.get(f"{base}/audit-log", headers=await auth_headers(viewer.email))
    assert denied.status_code == 403


async def test_metrics_summary_computes_mtta_mttr_and_rankings(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    busy = await make_service(db_session, org, name="busy-service")
    quiet = await make_service(db_session, org, name="quiet-service")

    start = datetime.now(UTC) - timedelta(days=3)
    # Two acknowledged incidents: 300s and 600s to ack -> MTTA 450.
    # One of them resolved after 3600s -> MTTR 3600.
    first = await make_incident(db_session, org, busy, owner, severity=Severity.SEV1)
    first.started_at = start
    first.acknowledged_at = start + timedelta(seconds=300)
    first.resolved_at = start + timedelta(seconds=3600)
    first.status = IncidentStatus.RESOLVED

    second = await make_incident(db_session, org, busy, owner, severity=Severity.SEV2)
    second.started_at = start
    second.acknowledged_at = start + timedelta(seconds=600)

    third = await make_incident(db_session, org, quiet, owner, severity=Severity.SEV2)
    third.started_at = start
    await db_session.flush()

    response = await client.get(
        f"/api/v1/orgs/{org.slug}/metrics/summary",
        headers=await auth_headers(owner.email),
    )
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["mtta_seconds"] == 450.0
    assert data["mttr_seconds"] == 3600.0

    top = {s["name"]: s for s in data["top_services"]}
    assert top["busy-service"]["count"] == 2
    assert top["busy-service"]["rank"] == 1
    assert top["quiet-service"]["rank"] == 2

    weekly = data["weekly_by_severity"]
    assert sum(w["count"] for w in weekly) == 3
    sev2_rows = [w for w in weekly if w["severity"] == "sev2"]
    assert sev2_rows[-1]["cumulative"] == 2


async def test_viewer_can_see_metrics(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    viewer = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    await make_member(db_session, org, viewer, Role.VIEWER)

    response = await client.get(
        f"/api/v1/orgs/{org.slug}/metrics/summary",
        headers=await auth_headers(viewer.email),
    )
    assert response.status_code == 200
    assert response.json()["data"]["mtta_seconds"] is None


async def test_audit_pagination_walks_cleanly(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    headers = await auth_headers(owner.email)
    for n in range(5):
        await client.post(
            f"/api/v1/orgs/{org.slug}/services", json={"name": f"svc-{n}"}, headers=headers
        )

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params = {"limit": "2"}
        if cursor:
            params["cursor"] = cursor
        page = (
            await client.get(f"/api/v1/orgs/{org.slug}/audit-log", params=params, headers=headers)
        ).json()
        seen.extend(e["id"] for e in page["data"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_audit_entries_stay_inside_their_org(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner_a = await make_user(db_session)
    owner_b = await make_user(db_session)
    org_a = await make_org(db_session, owner=owner_a)
    org_b = await make_org(db_session, owner=owner_b)

    await client.post(
        f"/api/v1/orgs/{org_a.slug}/services",
        json={"name": "a-only"},
        headers=await auth_headers(owner_a.email),
    )
    log_b = await client.get(
        f"/api/v1/orgs/{org_b.slug}/audit-log", headers=await auth_headers(owner_b.email)
    )
    assert log_b.json()["data"] == []
    assert isinstance(org_b, models.Organization)
