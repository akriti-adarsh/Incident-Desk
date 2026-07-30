"""Incident endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.common import Data
from incident_desk.schemas.incidents import IncidentCreate, IncidentOut
from incident_desk.services import incidents as incident_service

router = APIRouter(prefix="/orgs/{org_slug}/incidents", tags=["incidents"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ViewCtx = Annotated[AuthContext, Depends(require(Permission.INCIDENT_VIEW))]
CreateCtx = Annotated[AuthContext, Depends(require(Permission.INCIDENT_CREATE))]


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
