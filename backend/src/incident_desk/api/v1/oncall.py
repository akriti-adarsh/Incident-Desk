"""On-call endpoints: schedules, shifts, who is on call."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.common import Data
from incident_desk.schemas.oncall import (
    OnCallUserOut,
    ScheduleCreate,
    ScheduleOut,
    ShiftCreate,
    ShiftOut,
    WhoIsOnCallOut,
)
from incident_desk.services import oncall

router = APIRouter(prefix="/orgs/{org_slug}/on-call", tags=["on-call"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ViewCtx = Annotated[AuthContext, Depends(require(Permission.ONCALL_VIEW))]
ManageCtx = Annotated[AuthContext, Depends(require(Permission.ONCALL_MANAGE))]


@router.get("/schedules", summary="List schedules")
async def list_schedules(
    ctx: ViewCtx,
    session: SessionDep,
    service_id: Annotated[UUID | None, Query()] = None,
) -> Data[list[ScheduleOut]]:
    schedules = await oncall.list_schedules(session, ctx.org, service_id=service_id)
    return Data(data=[ScheduleOut.model_validate(s) for s in schedules])


@router.post("/schedules", status_code=201, summary="Create a schedule")
async def create_schedule(
    payload: ScheduleCreate, ctx: ManageCtx, session: SessionDep
) -> Data[ScheduleOut]:
    schedule = await oncall.create_schedule(
        session,
        ctx.org,
        service_id=payload.service_id,
        name=payload.name,
        rotation=payload.rotation,
    )
    await session.commit()
    return Data(data=ScheduleOut.model_validate(schedule))


@router.get("/schedules/{schedule_id}/shifts", summary="List shifts in a window")
async def list_shifts(
    schedule_id: UUID,
    ctx: ViewCtx,
    session: SessionDep,
    window_start: Annotated[datetime | None, Query(alias="from")] = None,
    window_end: Annotated[datetime | None, Query(alias="to")] = None,
) -> Data[list[ShiftOut]]:
    shifts = await oncall.list_shifts(
        session, ctx.org, schedule_id, window_start=window_start, window_end=window_end
    )
    return Data(data=[ShiftOut.model_validate(s) for s in shifts])


@router.post(
    "/schedules/{schedule_id}/shifts",
    status_code=201,
    summary="Add a shift",
    description="Overlapping shifts on one schedule are rejected by the database itself.",
)
async def add_shift(
    schedule_id: UUID, payload: ShiftCreate, ctx: ManageCtx, session: SessionDep
) -> Data[ShiftOut]:
    shift = await oncall.add_shift(
        session,
        ctx.org,
        schedule_id,
        user_id=payload.user_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    await session.commit()
    return Data(data=ShiftOut.model_validate(shift))


@router.delete(
    "/schedules/{schedule_id}/shifts/{shift_id}", status_code=204, summary="Remove a shift"
)
async def delete_shift(
    schedule_id: UUID, shift_id: UUID, ctx: ManageCtx, session: SessionDep
) -> None:
    await oncall.delete_shift(session, ctx.org, schedule_id, shift_id)
    await session.commit()


@router.get("/who-is-on-call", summary="Who is on call right now")
async def who_is_on_call(
    ctx: ViewCtx,
    session: SessionDep,
    service_id: Annotated[UUID, Query()],
) -> Data[list[WhoIsOnCallOut]]:
    entries = await oncall.who_is_on_call(session, ctx.org, service_id=service_id)
    return Data(
        data=[
            WhoIsOnCallOut(
                schedule_id=schedule.id,
                schedule_name=schedule.name,
                on_call=(
                    OnCallUserOut(user_id=user.id, full_name=user.full_name, email=user.email)
                    if user is not None
                    else None
                ),
            )
            for schedule, user in entries
        ]
    )
