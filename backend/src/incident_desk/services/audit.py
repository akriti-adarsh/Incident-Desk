"""The audit log: who did what, from where, with before and after."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk import pagination
from incident_desk.db import models


async def record(
    session: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    session.add(
        models.AuditLog(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:400] or None,
        )
    )
    await session.flush()


async def list_entries(
    session: AsyncSession,
    org: models.Organization,
    *,
    action: str | None = None,
    resource_type: str | None = None,
    actor_id: UUID | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[models.AuditLog], str | None]:
    """Newest first, keyset-paginated on (created_at, id)."""
    query = select(models.AuditLog).where(models.AuditLog.org_id == org.id)
    if action is not None:
        query = query.where(models.AuditLog.action == action)
    if resource_type is not None:
        query = query.where(models.AuditLog.resource_type == resource_type)
    if actor_id is not None:
        query = query.where(models.AuditLog.actor_id == actor_id)
    if cursor is not None:
        sort_value, row_id = pagination.decode_uuid_cursor(cursor)
        try:
            pivot = datetime.fromisoformat(sort_value)
        except ValueError as exc:
            raise pagination.InvalidCursorError(
                "The cursor is not valid; request the first page again"
            ) from exc
        query = query.where(
            or_(
                models.AuditLog.created_at < pivot,
                and_(models.AuditLog.created_at == pivot, models.AuditLog.id < row_id),
            )
        )
    query = query.order_by(models.AuditLog.created_at.desc(), models.AuditLog.id.desc()).limit(
        limit + 1
    )
    rows = list(await session.scalars(query))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = pagination.encode_cursor(rows[-1].created_at.isoformat(), rows[-1].id)
    return rows, next_cursor
