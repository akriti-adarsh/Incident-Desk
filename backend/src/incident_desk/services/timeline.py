"""The append-only incident timeline: the source of truth for what happened."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def list_events(session: AsyncSession, incident_id: UUID) -> list[models.IncidentEvent]:
    rows = await session.scalars(
        select(models.IncidentEvent)
        .where(models.IncidentEvent.incident_id == incident_id)
        .order_by(models.IncidentEvent.seq)
    )
    return list(rows)
