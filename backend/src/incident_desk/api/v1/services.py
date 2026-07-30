"""Service catalogue endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.common import Data
from incident_desk.schemas.services import ServiceCreate, ServiceOut, ServiceUpdate
from incident_desk.services import catalog

router = APIRouter(prefix="/orgs/{org_slug}/services", tags=["services"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ViewCtx = Annotated[AuthContext, Depends(require(Permission.SERVICE_VIEW))]
ManageCtx = Annotated[AuthContext, Depends(require(Permission.SERVICE_MANAGE))]


@router.get("", summary="List services")
async def list_services(ctx: ViewCtx, session: SessionDep) -> Data[list[ServiceOut]]:
    services = await catalog.list_services(session, ctx.org)
    return Data(data=[ServiceOut.model_validate(s) for s in services])


@router.post("", status_code=201, summary="Create a service")
async def create_service(
    payload: ServiceCreate, ctx: ManageCtx, session: SessionDep
) -> Data[ServiceOut]:
    service = await catalog.create_service(
        session,
        ctx.org,
        name=payload.name,
        description=payload.description,
        owner_team=payload.owner_team,
        tier=payload.tier,
    )
    await session.commit()
    return Data(data=ServiceOut.model_validate(service))


@router.get("/{service_id}", summary="Get a service")
async def get_service(service_id: UUID, ctx: ViewCtx, session: SessionDep) -> Data[ServiceOut]:
    service = await catalog.get_service(session, ctx.org, service_id)
    return Data(data=ServiceOut.model_validate(service))


@router.patch("/{service_id}", summary="Update a service")
async def update_service(
    service_id: UUID, payload: ServiceUpdate, ctx: ManageCtx, session: SessionDep
) -> Data[ServiceOut]:
    service = await catalog.update_service(
        session,
        ctx.org,
        service_id,
        name=payload.name,
        description=payload.description,
        owner_team=payload.owner_team,
        tier=payload.tier,
    )
    await session.commit()
    return Data(data=ServiceOut.model_validate(service))


@router.delete(
    "/{service_id}",
    status_code=204,
    summary="Delete a service",
    description="Refused while incidents reference the service; history is kept.",
)
async def delete_service(service_id: UUID, ctx: ManageCtx, session: SessionDep) -> None:
    await catalog.delete_service(session, ctx.org, service_id)
    await session.commit()
