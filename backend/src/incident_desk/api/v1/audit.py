"""Audit log endpoints (admin and owner only)."""

import uuid as uuid_module
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.common import Page
from incident_desk.services import audit

router = APIRouter(prefix="/orgs/{org_slug}/audit-log", tags=["audit"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
AuditCtx = Annotated[AuthContext, Depends(require(Permission.AUDIT_VIEW))]


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid_module.UUID
    actor_id: uuid_module.UUID | None
    action: str
    resource_type: str
    resource_id: uuid_module.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


@router.get(
    "",
    summary="Browse the audit log",
    description="Every mutating action in the organisation, newest first.",
)
async def list_audit_log(
    ctx: AuditCtx,
    session: SessionDep,
    action: Annotated[str | None, Query(max_length=100)] = None,
    resource_type: Annotated[str | None, Query(max_length=100)] = None,
    actor_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[AuditEntryOut]:
    entries, next_cursor = await audit.list_entries(
        session,
        ctx.org,
        action=action,
        resource_type=resource_type,
        actor_id=actor_id,
        limit=limit,
        cursor=cursor,
    )
    return Page(data=[AuditEntryOut.model_validate(e) for e in entries], next_cursor=next_cursor)
