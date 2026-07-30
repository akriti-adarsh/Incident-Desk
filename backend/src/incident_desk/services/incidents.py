"""Incident lifecycle: creation, updates, and state-machine transitions."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk import pagination, state_machine
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


class VersionConflictError(ConflictError):
    code = "version_conflict"


def _conflict_snapshot(incident: models.Incident) -> dict[str, object]:
    """What the server has now, so a conflicting client can show the diff."""
    return {
        "current_version": incident.version,
        "current": {
            "title": incident.title,
            "description": incident.description,
            "severity": incident.severity.value,
            "status": incident.status.value,
            "assigned_to": str(incident.assigned_to) if incident.assigned_to else None,
            "tags": incident.tags,
        },
    }


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
    actor: models.User | None,
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
    incident.version += 1
    if new_status is IncidentStatus.ACKNOWLEDGED and incident.acknowledged_at is None:
        incident.acknowledged_at = _now()
    if new_status is IncidentStatus.RESOLVED:
        incident.resolved_at = _now()
        incident.resolution_summary = (resolution_summary or "").strip()
    await session.flush()
    await timeline.record(
        session,
        incident_id=incident.id,
        actor_id=actor.id if actor else None,
        event_type="status.changed",
        payload={"from": previous.value, "to": new_status.value},
    )
    return incident


async def update_incident(
    session: AsyncSession,
    org: models.Organization,
    incident_id: UUID,
    *,
    actor: models.User | None,
    title: str | None = None,
    description: str | None = None,
    severity: Severity | None = None,
    tags: list[str] | None = None,
    assigned_to: UUID | None = None,
    assignee_provided: bool = False,
    expected_version: int | None = None,
) -> models.Incident:
    """Field updates, each recorded on the timeline.

    When ``expected_version`` is given (the If-Match ETag), a mismatch means
    someone else changed the incident since the client read it: 409 with the
    server's current state so the client can show what changed.
    """
    incident = await get_incident(session, org, incident_id)
    if expected_version is not None and incident.version != expected_version:
        raise VersionConflictError(
            "The incident changed since you loaded it",
            details=_conflict_snapshot(incident),
        )
    edited_fields: list[str] = []

    if severity is not None and severity != incident.severity:
        await timeline.record(
            session,
            incident_id=incident.id,
            actor_id=actor.id if actor else None,
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
            actor_id=actor.id if actor else None,
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
            actor_id=actor.id if actor else None,
            event_type="incident.updated",
            payload={"fields": edited_fields},
        )
    incident.version += 1
    await session.flush()
    return incident


SORT_FIELDS = {
    "created_at": models.Incident.created_at,
    "started_at": models.Incident.started_at,
}


async def list_incidents(
    session: AsyncSession,
    org: models.Organization,
    *,
    statuses: list[IncidentStatus] | None = None,
    severities: list[Severity] | None = None,
    service_id: UUID | None = None,
    assigned_to: UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
    sort: str = "created_at",
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[models.Incident], str | None]:
    """Filtered, searched, cursor-paginated incident listing (newest first).

    The ORDER BY is (sort_field DESC, id DESC); the cursor holds the last
    row's pair, and the keyset predicate is a row-value comparison, so pages
    stay stable even when every row shares one timestamp.
    """
    sort_col = SORT_FIELDS[sort]
    query = select(models.Incident).where(models.Incident.org_id == org.id)
    if statuses:
        query = query.where(models.Incident.status.in_(statuses))
    if severities:
        query = query.where(models.Incident.severity.in_(severities))
    if service_id is not None:
        query = query.where(models.Incident.service_id == service_id)
    if assigned_to is not None:
        query = query.where(models.Incident.assigned_to == assigned_to)
    if tag is not None:
        query = query.where(models.Incident.tags.contains([tag]))
    if q:
        query = query.where(
            models.Incident.search_vector.op("@@")(func.websearch_to_tsquery("english", q))
        )
    if cursor is not None:
        sort_value, row_id = pagination.decode_uuid_cursor(cursor)
        try:
            pivot = datetime.fromisoformat(sort_value)
        except ValueError as exc:
            raise pagination.InvalidCursorError(
                "The cursor is not valid; request the first page again"
            ) from exc
        # Keyset predicate, spelled out so the tiebreaker is explicit:
        # rows strictly after (pivot, row_id) in (sort DESC, id DESC) order.
        query = query.where(
            or_(
                sort_col < pivot,
                and_(sort_col == pivot, models.Incident.id < row_id),
            )
        )

    query = query.order_by(sort_col.desc(), models.Incident.id.desc()).limit(limit + 1)
    rows = list(await session.scalars(query))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = pagination.encode_cursor(getattr(last, sort).isoformat(), last.id)
    return rows, next_cursor
