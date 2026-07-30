"""Incident lifecycle: creation, updates, and state-machine transitions."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk import state_machine
from incident_desk.db import models
from incident_desk.enums import IncidentStatus, Severity
from incident_desk.errors import AppError, ConflictError, NotFoundError
from incident_desk.services import timeline


class AssigneeNotAMemberError(ConflictError):
    code = "assignee_not_a_member"


class IllegalTransitionError(ConflictError):
    code = "illegal_transition"


class ResolutionSummaryRequiredError(AppError):
    status_code = 400
    code = "resolution_required"


def _now() -> datetime:
    return datetime.now(UTC)


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
    await timeline.record(
        session,
        incident_id=incident.id,
        actor_id=reported_by.id,
        event_type="incident.created",
        payload={
            "severity": severity.value,
            "service_id": str(service.id),
            "number": display_number(sequence_number),
        },
    )
    return incident


async def transition_status(
    session: AsyncSession,
    org: models.Organization,
    incident_id: UUID,
    *,
    new_status: IncidentStatus,
    actor: models.User,
    resolution_summary: str | None = None,
) -> models.Incident:
    """Move an incident along the state machine, stamping the milestone times."""
    incident = await get_incident(session, org, incident_id)
    if not state_machine.is_legal(incident.status, new_status):
        raise IllegalTransitionError(
            f"Cannot move from {incident.status.value} to {new_status.value}",
            details={
                "from": incident.status.value,
                "to": new_status.value,
                "allowed": sorted(t.value for t in state_machine.allowed_targets(incident.status)),
            },
        )
    if new_status is IncidentStatus.RESOLVED and not (resolution_summary or "").strip():
        raise ResolutionSummaryRequiredError("Resolving an incident requires a resolution summary")

    previous = incident.status
    incident.status = new_status
    if new_status is IncidentStatus.ACKNOWLEDGED and incident.acknowledged_at is None:
        incident.acknowledged_at = _now()
    if new_status is IncidentStatus.RESOLVED:
        incident.resolved_at = _now()
        incident.resolution_summary = (resolution_summary or "").strip()
    await session.flush()
    await timeline.record(
        session,
        incident_id=incident.id,
        actor_id=actor.id,
        event_type="status.changed",
        payload={"from": previous.value, "to": new_status.value},
    )
    return incident


async def update_incident(
    session: AsyncSession,
    org: models.Organization,
    incident_id: UUID,
    *,
    actor: models.User,
    title: str | None = None,
    description: str | None = None,
    severity: Severity | None = None,
    tags: list[str] | None = None,
    assigned_to: UUID | None = None,
    assignee_provided: bool = False,
) -> models.Incident:
    """Field updates, each recorded on the timeline."""
    incident = await get_incident(session, org, incident_id)
    edited_fields: list[str] = []

    if severity is not None and severity != incident.severity:
        await timeline.record(
            session,
            incident_id=incident.id,
            actor_id=actor.id,
            event_type="severity.changed",
            payload={"from": incident.severity.value, "to": severity.value},
        )
        incident.severity = severity
    if assignee_provided and assigned_to != incident.assigned_to:
        if assigned_to is not None:
            await _require_member(session, org.id, assigned_to)
        await timeline.record(
            session,
            incident_id=incident.id,
            actor_id=actor.id,
            event_type="assignment.changed",
            payload={
                "from": str(incident.assigned_to) if incident.assigned_to else None,
                "to": str(assigned_to) if assigned_to else None,
            },
        )
        incident.assigned_to = assigned_to
    for name, value in (("title", title), ("description", description), ("tags", tags)):
        if value is not None and value != getattr(incident, name):
            setattr(incident, name, value)
            edited_fields.append(name)
    if edited_fields:
        await timeline.record(
            session,
            incident_id=incident.id,
            actor_id=actor.id,
            event_type="incident.updated",
            payload={"fields": edited_fields},
        )
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
