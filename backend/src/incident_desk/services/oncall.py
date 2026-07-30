"""On-call schedules, shifts, and the "who is on call right now" question."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.errors import ConflictError, NotFoundError


class ShiftOverlapError(ConflictError):
    code = "shift_overlap"


class NotAMemberError(ConflictError):
    code = "not_a_member"


def _now() -> datetime:
    return datetime.now(UTC)


async def list_schedules(
    session: AsyncSession, org: models.Organization, service_id: UUID | None = None
) -> list[models.OnCallSchedule]:
    query = select(models.OnCallSchedule).where(models.OnCallSchedule.org_id == org.id)
    if service_id is not None:
        query = query.where(models.OnCallSchedule.service_id == service_id)
    rows = await session.scalars(query.order_by(models.OnCallSchedule.name))
    return list(rows)


async def get_schedule(
    session: AsyncSession, org: models.Organization, schedule_id: UUID
) -> models.OnCallSchedule:
    schedule = await session.scalar(
        select(models.OnCallSchedule).where(
            models.OnCallSchedule.org_id == org.id,
            models.OnCallSchedule.id == schedule_id,
        )
    )
    if schedule is None:
        raise NotFoundError("Schedule not found")
    return schedule


async def create_schedule(
    session: AsyncSession,
    org: models.Organization,
    *,
    service_id: UUID,
    name: str,
    rotation: dict[str, object] | None,
) -> models.OnCallSchedule:
    service = await session.scalar(
        select(models.Service).where(
            models.Service.org_id == org.id, models.Service.id == service_id
        )
    )
    if service is None:
        raise NotFoundError("Service not found")
    schedule = models.OnCallSchedule(
        org_id=org.id, service_id=service.id, name=name, rotation=rotation or {}
    )
    session.add(schedule)
    await session.flush()
    return schedule


async def add_shift(
    session: AsyncSession,
    org: models.Organization,
    schedule_id: UUID,
    *,
    user_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
) -> models.OnCallShift:
    schedule = await get_schedule(session, org, schedule_id)
    membership = await session.get(models.Membership, (user_id, org.id))
    if membership is None:
        raise NotAMemberError("Only organisation members can be put on call")
    shift = models.OnCallShift(
        schedule_id=schedule.id, user_id=user_id, starts_at=starts_at, ends_at=ends_at
    )
    session.add(shift)
    try:
        # SAVEPOINT around the flush: on constraint failure only this
        # statement is rolled back and the session stays healthy.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        # The database's exclusion constraint is the authority on overlaps.
        raise ShiftOverlapError(
            "This shift overlaps an existing shift on the same schedule"
        ) from exc
    return shift


async def list_shifts(
    session: AsyncSession,
    org: models.Organization,
    schedule_id: UUID,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> list[models.OnCallShift]:
    schedule = await get_schedule(session, org, schedule_id)
    query = select(models.OnCallShift).where(models.OnCallShift.schedule_id == schedule.id)
    if window_start is not None:
        query = query.where(models.OnCallShift.ends_at > window_start)
    if window_end is not None:
        query = query.where(models.OnCallShift.starts_at < window_end)
    rows = await session.scalars(query.order_by(models.OnCallShift.starts_at))
    return list(rows)


async def delete_shift(
    session: AsyncSession, org: models.Organization, schedule_id: UUID, shift_id: UUID
) -> None:
    schedule = await get_schedule(session, org, schedule_id)
    shift = await session.scalar(
        select(models.OnCallShift).where(
            models.OnCallShift.schedule_id == schedule.id, models.OnCallShift.id == shift_id
        )
    )
    if shift is None:
        raise NotFoundError("Shift not found")
    await session.delete(shift)
    await session.flush()


async def who_is_on_call(
    session: AsyncSession,
    org: models.Organization,
    *,
    service_id: UUID,
    at: datetime | None = None,
) -> list[tuple[models.OnCallSchedule, models.User | None]]:
    """For each schedule of the service: the user on shift at ``at`` (or None)."""
    moment = at or _now()
    schedules = await list_schedules(session, org, service_id=service_id)
    result: list[tuple[models.OnCallSchedule, models.User | None]] = []
    for schedule in schedules:
        row = await session.execute(
            select(models.User)
            .join(models.OnCallShift, models.OnCallShift.user_id == models.User.id)
            .where(
                models.OnCallShift.schedule_id == schedule.id,
                models.OnCallShift.starts_at <= moment,
                models.OnCallShift.ends_at > moment,
            )
            .limit(1)
        )
        user = row.scalar_one_or_none()
        result.append((schedule, user))
    return result
