"""Organisation endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.api.deps import CurrentUser
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.common import Data
from incident_desk.schemas.orgs import OrgCreate, OrgOut, OrgUpdate, OrgWithRoleOut
from incident_desk.services import orgs as org_service

router = APIRouter(prefix="/orgs", tags=["organizations"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "",
    status_code=201,
    summary="Create an organisation",
    description="Creates the organisation and makes the caller its owner.",
)
async def create_org(payload: OrgCreate, user: CurrentUser, session: SessionDep) -> Data[OrgOut]:
    org = await org_service.create_organization(
        session, name=payload.name, slug=payload.slug, owner=user
    )
    await session.commit()
    return Data(data=OrgOut.model_validate(org))


@router.get(
    "",
    summary="List my organisations",
    description="Every organisation the caller belongs to, with their role in each.",
)
async def list_orgs(user: CurrentUser, session: SessionDep) -> Data[list[OrgWithRoleOut]]:
    pairs = await org_service.organizations_for(session, user)
    return Data(
        data=[
            OrgWithRoleOut(**OrgOut.model_validate(org).model_dump(), role=role)
            for org, role in pairs
        ]
    )


@router.get(
    "/{org_slug}",
    summary="Get an organisation",
)
async def get_org(
    ctx: Annotated[AuthContext, Depends(require(Permission.ORG_VIEW))],
) -> Data[OrgWithRoleOut]:
    return Data(data=OrgWithRoleOut(**OrgOut.model_validate(ctx.org).model_dump(), role=ctx.role))


@router.patch(
    "/{org_slug}",
    summary="Update an organisation",
    description="Owner only: rename the organisation or replace its settings blob.",
)
async def update_org(
    payload: OrgUpdate,
    ctx: Annotated[AuthContext, Depends(require(Permission.ORG_MANAGE))],
    session: SessionDep,
) -> Data[OrgOut]:
    if payload.name is not None:
        ctx.org.name = payload.name
    if payload.settings is not None:
        ctx.org.settings = payload.settings
    await session.flush()
    await session.commit()
    return Data(data=OrgOut.model_validate(ctx.org))
