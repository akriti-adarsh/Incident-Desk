"""Model round-trips against the real database: defaults, enums, constraints."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import IncidentStatus, Role, ServiceTier, Severity


def _org(slug: str = "acme") -> models.Organization:
    return models.Organization(name="Acme", slug=slug)


def _user(email: str = "ada@example.com") -> models.User:
    return models.User(email=email, password_hash="x" * 60, full_name="Ada Lovelace")


async def test_incident_defaults_and_enum_round_trip(db_session: AsyncSession) -> None:
    org = _org()
    user = _user()
    service = models.Service(org_id=org.id, name="checkout", tier=ServiceTier.TIER1)
    db_session.add_all([org, user])
    await db_session.flush()
    service.org_id = org.id
    db_session.add(service)
    await db_session.flush()

    incident = models.Incident(
        org_id=org.id,
        service_id=service.id,
        sequence_number=1,
        title="Checkout latency spike",
        severity=Severity.SEV2,
        reported_by=user.id,
    )
    db_session.add(incident)
    await db_session.flush()
    await db_session.refresh(incident)

    assert incident.status is IncidentStatus.OPEN
    assert incident.severity is Severity.SEV2
    assert incident.tags == []
    assert incident.description == ""
    assert incident.started_at is not None
    assert incident.created_at is not None
    assert incident.updated_at is not None


async def test_membership_composite_key_and_cross_org_roles(db_session: AsyncSession) -> None:
    org_a, org_b = _org("org-a"), _org("org-b")
    user = _user("multi@example.com")
    db_session.add_all([org_a, org_b, user])
    await db_session.flush()

    db_session.add_all(
        [
            models.Membership(user_id=user.id, org_id=org_a.id, role=Role.OWNER),
            models.Membership(user_id=user.id, org_id=org_b.id, role=Role.VIEWER),
        ]
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(models.Membership).where(models.Membership.user_id == user.id)
        )
    ).scalars()
    roles = {m.org_id: m.role for m in rows}
    assert roles == {org_a.id: Role.OWNER, org_b.id: Role.VIEWER}


async def test_duplicate_sequence_number_in_same_org_is_rejected(
    db_session: AsyncSession,
) -> None:
    org = _org()
    user = _user()
    db_session.add_all([org, user])
    await db_session.flush()
    service = models.Service(org_id=org.id, name="api", tier=ServiceTier.TIER2)
    db_session.add(service)
    await db_session.flush()

    def incident() -> models.Incident:
        return models.Incident(
            org_id=org.id,
            service_id=service.id,
            sequence_number=7,
            title="dup",
            severity=Severity.SEV3,
            reported_by=user.id,
        )

    db_session.add(incident())
    await db_session.flush()
    db_session.add(incident())
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_shift_check_constraint_rejects_backwards_range(db_session: AsyncSession) -> None:
    org = _org()
    user = _user()
    db_session.add_all([org, user])
    await db_session.flush()
    service = models.Service(org_id=org.id, name="db", tier=ServiceTier.TIER1)
    db_session.add(service)
    await db_session.flush()
    schedule = models.OnCallSchedule(org_id=org.id, service_id=service.id, name="primary")
    db_session.add(schedule)
    await db_session.flush()

    start = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    db_session.add(
        models.OnCallShift(
            schedule_id=schedule.id,
            user_id=user.id,
            starts_at=start,
            ends_at=start - timedelta(hours=1),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_jsonb_and_audit_round_trip(db_session: AsyncSession) -> None:
    org = _org()
    db_session.add(org)
    await db_session.flush()

    entry = models.AuditLog(
        org_id=org.id,
        actor_id=None,
        action="incident.created",
        resource_type="incident",
        resource_id=uuid.uuid4(),
        before=None,
        after={"status": "open", "severity": "sev1"},
        ip_address="203.0.113.7",
        user_agent="pytest",
    )
    db_session.add(entry)
    await db_session.flush()
    await db_session.refresh(entry)
    assert entry.after == {"status": "open", "severity": "sev1"}
    assert entry.before is None


async def test_counter_starts_at_zero(db_session: AsyncSession) -> None:
    org = _org()
    db_session.add(org)
    await db_session.flush()
    counter = models.OrganizationCounter(org_id=org.id)
    db_session.add(counter)
    await db_session.flush()
    await db_session.refresh(counter)
    assert counter.incident_seq == 0
