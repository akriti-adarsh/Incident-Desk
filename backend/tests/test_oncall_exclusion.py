"""The on-call overlap rule is a database constraint, proven by real inserts."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import ServiceTier

NOON = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


async def _schedule(db_session: AsyncSession) -> tuple[models.OnCallSchedule, models.User]:
    org = models.Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    user = models.User(
        email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x", full_name="On Call"
    )
    db_session.add_all([org, user])
    await db_session.flush()
    service = models.Service(org_id=org.id, name="edge", tier=ServiceTier.TIER1)
    db_session.add(service)
    await db_session.flush()
    schedule = models.OnCallSchedule(org_id=org.id, service_id=service.id, name="primary")
    db_session.add(schedule)
    await db_session.flush()
    return schedule, user


def _shift(
    schedule: models.OnCallSchedule, user: models.User, start_hours: float, end_hours: float
) -> models.OnCallShift:
    return models.OnCallShift(
        schedule_id=schedule.id,
        user_id=user.id,
        starts_at=NOON + timedelta(hours=start_hours),
        ends_at=NOON + timedelta(hours=end_hours),
    )


async def test_overlapping_shift_on_same_schedule_fails_at_the_database(
    db_session: AsyncSession,
) -> None:
    schedule, user = await _schedule(db_session)
    db_session.add(_shift(schedule, user, 0, 2))
    await db_session.flush()

    db_session.add(_shift(schedule, user, 1, 3))
    with pytest.raises(IntegrityError) as excinfo:
        await db_session.flush()
    assert "ex_on_call_shifts_no_overlap" in str(excinfo.value)


async def test_contained_shift_also_fails(db_session: AsyncSession) -> None:
    schedule, user = await _schedule(db_session)
    db_session.add(_shift(schedule, user, 0, 8))
    await db_session.flush()

    db_session.add(_shift(schedule, user, 2, 3))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_adjacent_shifts_do_not_conflict(db_session: AsyncSession) -> None:
    """tstzrange is half-open: a shift ending at T and one starting at T touch, not overlap."""
    schedule, user = await _schedule(db_session)
    db_session.add(_shift(schedule, user, 0, 2))
    await db_session.flush()
    db_session.add(_shift(schedule, user, 2, 4))
    await db_session.flush()


async def test_same_window_on_a_different_schedule_is_allowed(db_session: AsyncSession) -> None:
    schedule_a, user = await _schedule(db_session)
    schedule_b, _ = await _schedule(db_session)
    db_session.add(_shift(schedule_a, user, 0, 2))
    await db_session.flush()
    db_session.add(_shift(schedule_b, user, 0, 2))
    await db_session.flush()
