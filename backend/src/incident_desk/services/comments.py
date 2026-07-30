"""Incident comments: markdown discussion with soft deletion and moderation."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk import pagination
from incident_desk.db import models
from incident_desk.errors import ForbiddenError, NotFoundError
from incident_desk.services import timeline
from incident_desk.services.incidents import get_incident


def _now() -> datetime:
    return datetime.now(UTC)


async def _get_comment(
    session: AsyncSession, org: models.Organization, incident_id: UUID, comment_id: UUID
) -> models.Comment:
    """Scoped through the incident join, so a foreign comment id is a 404."""
    comment = await session.scalar(
        select(models.Comment)
        .join(models.Incident, models.Incident.id == models.Comment.incident_id)
        .where(
            models.Incident.org_id == org.id,
            models.Comment.incident_id == incident_id,
            models.Comment.id == comment_id,
            models.Comment.deleted_at.is_(None),
        )
    )
    if comment is None:
        raise NotFoundError("Comment not found")
    return comment


async def list_comments(
    session: AsyncSession,
    org: models.Organization,
    incident_id: UUID,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[models.Comment], str | None]:
    incident = await get_incident(session, org, incident_id)
    query = select(models.Comment).where(
        models.Comment.incident_id == incident.id,
        models.Comment.deleted_at.is_(None),
    )
    if cursor is not None:
        sort_value, _ = pagination.decode_cursor(cursor)
        try:
            pivot = int(sort_value)
        except ValueError as exc:
            raise pagination.InvalidCursorError(
                "The cursor is not valid; request the first page again"
            ) from exc
        query = query.where(models.Comment.seq > pivot)
    rows = list(await session.scalars(query.order_by(models.Comment.seq).limit(limit + 1)))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = pagination.encode_cursor(str(rows[-1].seq), rows[-1].id)
    return rows, next_cursor


async def add_comment(
    session: AsyncSession,
    org: models.Organization,
    incident_id: UUID,
    *,
    author: models.User,
    body: str,
) -> models.Comment:
    incident = await get_incident(session, org, incident_id)
    comment = models.Comment(incident_id=incident.id, author_id=author.id, body=body)
    session.add(comment)
    await session.flush()
    await timeline.record(
        session,
        incident_id=incident.id,
        actor_id=author.id,
        event_type="comment.added",
        payload={"comment_id": str(comment.id)},
    )
    return comment


async def edit_comment(
    session: AsyncSession,
    org: models.Organization,
    incident_id: UUID,
    comment_id: UUID,
    *,
    actor: models.User,
    body: str,
) -> models.Comment:
    """Only the author may edit; edits are marked, and logged on the timeline."""
    comment = await _get_comment(session, org, incident_id, comment_id)
    if comment.author_id != actor.id:
        raise ForbiddenError("Only the author can edit a comment")
    comment.body = body
    comment.edited_at = _now()
    await session.flush()
    await timeline.record(
        session,
        incident_id=comment.incident_id,
        actor_id=actor.id,
        event_type="comment.edited",
        payload={"comment_id": str(comment.id)},
    )
    return comment


async def delete_comment(
    session: AsyncSession,
    org: models.Organization,
    incident_id: UUID,
    comment_id: UUID,
    *,
    actor: models.User,
    can_moderate: bool,
) -> None:
    """Soft delete by the author, or by anyone holding comment:moderate."""
    comment = await _get_comment(session, org, incident_id, comment_id)
    if comment.author_id != actor.id and not can_moderate:
        raise ForbiddenError("Only the author or a moderator can delete a comment")
    comment.deleted_at = _now()
    await session.flush()
    await timeline.record(
        session,
        incident_id=comment.incident_id,
        actor_id=actor.id,
        event_type="comment.deleted",
        payload={"comment_id": str(comment.id)},
    )
