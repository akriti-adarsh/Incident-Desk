"""Incident lifecycle: creation with gapless per-org sequence numbers."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import Severity
from incident_desk.errors import ConflictError, NotFoundError


class AssigneeNotAMemberError(ConflictError):
    code = "assignee_not_a_member"


def display_number(sequence_number: int) -> str:
    return f"INC-{sequence_number}"


async def allocate_sequence_number(session: AsyncSession, org_id: UUID) -> int:
    """Issue the next gapless incident number for an organisation.

    ``SELECT ... FOR UPDATE`` on the per-org counter row serialises concurrent
    creators: each transaction locks the row, increments it, and the incident
    insert commits (or rolls back) together with the bump, so committed
    numbers have no duplicates and no gaps.
    """
    counter = await session.scalar(
        select(models.OrganizationCounter)
        .where(models.OrganizationCounter.org_id == org_id)
        .with_for_update()
    )
    if counter is None:
        raise NotFoundError("Organization not found")
    counter.incident_seq += 1
    await session.flush()
    return counter.incident_seq


async def get_incident(
    session: AsyncSession, org: models.Organization, incident_id: UUID
) -> models.Incident:
    """Org scope applied in the query itself; a foreign id is a plain 404."""
    incident = await session.scalar(
        select(models.Incident).where(
            models.Incident.org_id == org.id, models.Incident.id == incident_id
        )
    )
    if incident is None:
        raise NotFoundError("Incident not found")
    return incident


async def _require_member(session: AsyncSession, org_id: UUID, user_id: UUID) -> None:
    membership = await session.get(models.Membership, (user_id, org_id))
    if membership is None:
        raise AssigneeNotAMemberError("The assignee must be a member of this organisation")


async def create_incident(
    session: AsyncSession,
    org: models.Organization,
    *,
    service_id: UUID,
    title: str,
    description: str,
    severity: Severity,
    reported_by: models.User,
    assigned_to: UUID | None,
    started_at: datetime | None,
    tags: list[str],
) -> models.Incident:
    service = await session.scalar(
        select(models.Service).where(
            models.Service.org_id == org.id, models.Service.id == service_id
        )
    )
    if service is None:
        raise NotFoundError("Service not found")
    if assigned_to is not None:
        await _require_member(session, org.id, assigned_to)

    sequence_number = await allocate_sequence_number(session, org.id)
    incident = models.Incident(
        org_id=org.id,
        service_id=service.id,
        sequence_number=sequence_number,
        title=title,
        description=description,
        severity=severity,
        reported_by=reported_by.id,
        assigned_to=assigned_to,
        tags=tags,
    )
    if started_at is not None:
        incident.started_at = started_at
    session.add(incident)
    await session.flush()
    return incident


async def list_recent_incidents(
    session: AsyncSession, org: models.Organization, limit: int = 50
) -> list[models.Incident]:
    rows = await session.scalars(
        select(models.Incident)
        .where(models.Incident.org_id == org.id)
        .order_by(models.Incident.created_at.desc(), models.Incident.id.desc())
        .limit(limit)
    )
    return list(rows)
