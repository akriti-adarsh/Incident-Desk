"""API key management endpoints (admin and owner only)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.api.deps import AuditDep
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.apikeys import ApiKeyCreate, ApiKeyCreatedOut, ApiKeyOut
from incident_desk.schemas.common import Data
from incident_desk.services import apikeys as apikey_service
from incident_desk.services import audit

router = APIRouter(prefix="/orgs/{org_slug}/api-keys", tags=["api-keys"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ManageCtx = Annotated[AuthContext, Depends(require(Permission.APIKEY_MANAGE))]


@router.get("", summary="List API keys")
async def list_api_keys(ctx: ManageCtx, session: SessionDep) -> Data[list[ApiKeyOut]]:
    keys = await apikey_service.list_api_keys(session, ctx.org)
    return Data(data=[ApiKeyOut.model_validate(k) for k in keys])


@router.post(
    "",
    status_code=201,
    summary="Create an API key",
    description=(
        "Returns the full key exactly once; only its hash is stored. The key "
        "authenticates as this organisation with the granted scopes, and it "
        "can never author content (incidents, comments, uploads need a user)."
    ),
)
async def create_api_key(
    payload: ApiKeyCreate, ctx: ManageCtx, session: SessionDep, info: AuditDep
) -> Data[ApiKeyCreatedOut]:
    key, token = await apikey_service.create_api_key(
        session,
        ctx.org,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    await audit.record(
        session,
        org_id=ctx.org.id,
        actor_id=ctx.actor_id,
        action="apikey.created",
        resource_type="api_key",
        resource_id=key.id,
        after={"name": key.name, "scopes": key.scopes},
        ip_address=info.ip_address,
        user_agent=info.user_agent,
    )
    await session.commit()
    out = ApiKeyCreatedOut(
        **ApiKeyOut.model_validate(key).model_dump(),
        api_key=token,
    )
    return Data(data=out)


@router.delete(
    "/{key_id}",
    status_code=204,
    summary="Revoke an API key",
    description="Revocation is immediate and permanent; the key stays listed for audit.",
)
async def revoke_api_key(key_id: UUID, ctx: ManageCtx, session: SessionDep, info: AuditDep) -> None:
    await apikey_service.revoke_api_key(session, ctx.org, key_id)
    await audit.record(
        session,
        org_id=ctx.org.id,
        actor_id=ctx.actor_id,
        action="apikey.revoked",
        resource_type="api_key",
        resource_id=key_id,
        ip_address=info.ip_address,
        user_agent=info.user_agent,
    )
    await session.commit()
