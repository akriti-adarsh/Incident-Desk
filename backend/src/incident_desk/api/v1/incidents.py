"""Incident endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.common import Data
from incident_desk.schemas.incidents import (
    EventOut,
    IncidentCreate,
    IncidentOut,
    IncidentUpdate,
    StatusChangeRequest,
)
from incident_desk.services import incidents as incident_service
from incident_desk.services import timeline

router = APIRouter(prefix="/orgs/{org_slug}/incidents", tags=["incidents"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ViewCtx = Annotated[AuthContext, Depends(require(Permission.INCIDENT_VIEW))]
CreateCtx = Annotated[AuthContext, Depends(require(Permission.INCIDENT_CREATE))]
UpdateCtx = Annotated[AuthContext, Depends(require(Permission.INCIDENT_UPDATE))]


@router.post(
    "",
    status_code=201,
    summary="Report an incident",
    description=(
        "Creates the incident with the organisation's next gapless number (INC-1, INC-2, ...)."
    ),
)
async def create_incident(
    payload: IncidentCreate, ctx: CreateCtx, session: SessionDep
) -> Data[IncidentOut]:
    incident = await incident_service.create_incident(
        session,
        ctx.org,
        service_id=payload.service_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        reported_by=ctx.user,
        assigned_to=payload.assigned_to,
        started_at=payload.started_at,
        tags=payload.tags,
    )
    await session.commit()
    return Data(data=IncidentOut.model_validate(incident))


@router.get("", summary="List recent incidents")
async def list_incidents(ctx: ViewCtx, session: SessionDep) -> Data[list[IncidentOut]]:
    incidents = await incident_service.list_recent_incidents(session, ctx.org)
    return Data(data=[IncidentOut.model_validate(i) for i in incidents])


@router.get("/{incident_id}", summary="Get an incident")
async def get_incident(incident_id: UUID, ctx: ViewCtx, session: SessionDep) -> Data[IncidentOut]:
    incident = await incident_service.get_incident(session, ctx.org, incident_id)
    return Data(data=IncidentOut.model_validate(incident))


@router.post(
    "/{incident_id}/status",
    summary="Change an incident's status",
    description=(
        "Applies one legal state-machine transition. Acknowledging stamps "
        "acknowledged_at; resolving requires a resolution summary and stamps "
        "resolved_at. Illegal transitions answer 409 with the allowed targets."
    ),
)
async def change_status(
    incident_id: UUID, payload: StatusChangeRequest, ctx: UpdateCtx, session: SessionDep
) -> Data[IncidentOut]:
    incident = await incident_service.transition_status(
        session,
        ctx.org,
        incident_id,
        new_status=payload.status,
        actor=ctx.user,
        resolution_summary=payload.resolution_summary,
    )
    await session.commit()
    return Data(data=IncidentOut.model_validate(incident))


@router.patch(
    "/{incident_id}",
    summary="Edit an incident",
    description="Field edits; every change is recorded on the timeline.",
)
async def update_incident(
    incident_id: UUID, payload: IncidentUpdate, ctx: UpdateCtx, session: SessionDep
) -> Data[IncidentOut]:
    incident = await incident_service.update_incident(
        session,
        ctx.org,
        incident_id,
        actor=ctx.user,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        tags=payload.tags,
        assigned_to=payload.assigned_to,
        assignee_provided="assigned_to" in payload.model_fields_set,
    )
    await session.commit()
    return Data(data=IncidentOut.model_validate(incident))


@router.get(
    "/{incident_id}/events",
    summary="The incident timeline",
    description="Append-only event log, oldest first: the source of truth for what happened.",
)
async def list_events(incident_id: UUID, ctx: ViewCtx, session: SessionDep) -> Data[list[EventOut]]:
    incident = await incident_service.get_incident(session, ctx.org, incident_id)
    events = await timeline.list_events(session, incident.id)
    return Data(data=[EventOut.model_validate(e) for e in events])
