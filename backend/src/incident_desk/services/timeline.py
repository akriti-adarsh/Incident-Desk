"""The append-only incident timeline: the source of truth for what happened."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk import pagination
from incident_desk.db import models


async def record(
    session: AsyncSession,
    *,
    incident_id: UUID,
    actor_id: UUID | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> models.IncidentEvent:
    """Append one event. Events are never updated or deleted."""
    event = models.IncidentEvent(
        incident_id=incident_id,
        actor_id=actor_id,
        event_type=event_type,
        payload=payload or {},
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(
    session: AsyncSession,
    incident_id: UUID,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[models.IncidentEvent], str | None]:
    """Oldest first, keyset-paginated on the monotonic seq."""
    query = select(models.IncidentEvent).where(models.IncidentEvent.incident_id == incident_id)
    if cursor is not None:
        sort_value, _ = pagination.decode_cursor(cursor)
        try:
            pivot = int(sort_value)
        except ValueError as exc:
            raise pagination.InvalidCursorError(
                "The cursor is not valid; request the first page again"
            ) from exc
        query = query.where(models.IncidentEvent.seq > pivot)
    rows = list(await session.scalars(query.order_by(models.IncidentEvent.seq).limit(limit + 1)))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = pagination.encode_cursor(str(rows[-1].seq), rows[-1].id)
    return rows, next_cursor
