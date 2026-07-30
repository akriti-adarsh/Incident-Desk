"""State machine transitions (every cell), milestone timestamps, and the timeline."""

from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk import state_machine
from incident_desk.enums import IncidentStatus, Role
from tests.factories import (
    make_incident,
    make_member,
    make_org,
    make_service,
    make_user,
)

Login = Callable[[str], Awaitable[dict[str, str]]]

ALL_STATUSES = list(IncidentStatus)


def test_state_machine_shape() -> None:
    """Unit-level: the machine covers every status and postmortem is terminal."""
    assert set(state_machine.LEGAL_TRANSITIONS) == set(IncidentStatus)
    assert state_machine.allowed_targets(IncidentStatus.POSTMORTEM) == frozenset()
    assert not state_machine.is_legal(IncidentStatus.OPEN, IncidentStatus.OPEN)


@pytest.mark.parametrize("target", ALL_STATUSES)
@pytest.mark.parametrize("start", ALL_STATUSES)
async def test_every_transition_cell(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    auth_headers: Login,
    start: IncidentStatus,
    target: IncidentStatus,
) -> None:
    """All 25 (start, target) pairs: legal ones succeed, illegal ones 409."""
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    incident.status = start
    if start in (IncidentStatus.RESOLVED, IncidentStatus.POSTMORTEM):
        incident.resolution_summary = "already written"
    await db_session.flush()

    response = await client.post(
        f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/status",
        json={"status": target.value, "resolution_summary": "Rolled back the deploy"},
        headers=await auth_headers(owner.email),
    )
    if state_machine.is_legal(start, target):
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == target.value
    else:
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "illegal_transition"
        assert error["details"]["from"] == start.value


async def test_resolving_requires_a_summary(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    incident.status = IncidentStatus.ACKNOWLEDGED
    await db_session.flush()
    headers = await auth_headers(owner.email)
    url = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/status"

    bare = await client.post(url, json={"status": "resolved"}, headers=headers)
    assert bare.status_code == 400
    assert bare.json()["error"]["code"] == "resolution_required"

    resolved = await client.post(
        url,
        json={"status": "resolved", "resolution_summary": "Failed node drained"},
        headers=headers,
    )
    assert resolved.status_code == 200
    data = resolved.json()["data"]
    assert data["resolution_summary"] == "Failed node drained"
    assert data["resolved_at"] is not None


async def test_acknowledge_stamps_the_clock_once(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    headers = await auth_headers(owner.email)

    acked = await client.post(
        f"/api/v1/orgs/{org.slug}/incidents/{incident.id}/status",
        json={"status": "acknowledged"},
        headers=headers,
    )
    assert acked.status_code == 200
    assert acked.json()["data"]["acknowledged_at"] is not None


async def test_timeline_records_the_whole_story(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    responder = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    await make_member(db_session, org, responder, Role.RESPONDER)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents"

    created = await client.post(
        base,
        json={"service_id": str(service.id), "title": "Latency spike", "severity": "sev2"},
        headers=headers,
    )
    incident_id = created.json()["data"]["id"]

    await client.post(
        f"{base}/{incident_id}/status", json={"status": "acknowledged"}, headers=headers
    )
    await client.patch(
        f"{base}/{incident_id}",
        json={"assigned_to": str(responder.id), "severity": "sev1"},
        headers=headers,
    )

    events = await client.get(f"{base}/{incident_id}/events", headers=headers)
    assert events.status_code == 200
    types = [e["event_type"] for e in events.json()["data"]]
    assert types == [
        "incident.created",
        "status.changed",
        "severity.changed",
        "assignment.changed",
    ]
    payloads = {e["event_type"]: e["payload"] for e in events.json()["data"]}
    assert payloads["status.changed"] == {"from": "open", "to": "acknowledged"}
    assert payloads["severity.changed"] == {"from": "sev2", "to": "sev1"}
    assert payloads["assignment.changed"]["to"] == str(responder.id)


async def test_patch_edits_and_unassignment(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    incident.assigned_to = owner.id
    await db_session.flush()
    headers = await auth_headers(owner.email)
    url = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}"

    edited = await client.patch(
        url,
        json={"title": "Clearer title", "tags": ["db", "latency"], "assigned_to": None},
        headers=headers,
    )
    assert edited.status_code == 200
    data = edited.json()["data"]
    assert data["title"] == "Clearer title"
    assert data["tags"] == ["db", "latency"]
    assert data["assigned_to"] is None

    events = await client.get(f"{url}/events", headers=headers)
    types = [e["event_type"] for e in events.json()["data"]]
    assert "assignment.changed" in types
    assert "incident.updated" in types


async def test_viewer_cannot_transition_or_edit(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    viewer = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    await make_member(db_session, org, viewer, Role.VIEWER)
    headers = await auth_headers(viewer.email)
    url = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}"

    assert (
        await client.post(f"{url}/status", json={"status": "acknowledged"}, headers=headers)
    ).status_code == 403
    assert (await client.patch(url, json={"title": "sneaky"}, headers=headers)).status_code == 403
    # But the viewer can read the timeline.
    assert (await client.get(f"{url}/events", headers=headers)).status_code == 200


async def test_events_of_foreign_incident_are_invisible(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner_a = await make_user(db_session)
    owner_b = await make_user(db_session)
    org_a = await make_org(db_session, owner=owner_a)
    org_b = await make_org(db_session, owner=owner_b)
    service_b = await make_service(db_session, org_b)
    foreign = await make_incident(db_session, org_b, service_b, owner_b)

    response = await client.get(
        f"/api/v1/orgs/{org_a.slug}/incidents/{foreign.id}/events",
        headers=await auth_headers(owner_a.email),
    )
    assert response.status_code == 404
