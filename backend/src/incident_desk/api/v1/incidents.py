"""Incident endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.authz import Permission, role_has
from incident_desk.config import get_settings
from incident_desk.db.engine import get_db_session
from incident_desk.enums import IncidentStatus, Severity
from incident_desk.errors import AppError
from incident_desk.schemas.common import Data, Page
from incident_desk.schemas.incidents import (
    AttachmentOut,
    CommentCreate,
    CommentOut,
    EventOut,
    IncidentCreate,
    IncidentOut,
    IncidentUpdate,
    StatusChangeRequest,
)
from incident_desk.services import attachments as attachment_service
from incident_desk.services import comments as comment_service
from incident_desk.services import idempotency, timeline
from incident_desk.services import incidents as incident_service

router = APIRouter(prefix="/orgs/{org_slug}/incidents", tags=["incidents"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ViewCtx = Annotated[AuthContext, Depends(require(Permission.INCIDENT_VIEW))]
CreateCtx = Annotated[AuthContext, Depends(require(Permission.INCIDENT_CREATE))]
UpdateCtx = Annotated[AuthContext, Depends(require(Permission.INCIDENT_UPDATE))]


class PreconditionRequiredError(AppError):
    status_code = 428
    code = "precondition_required"


class InvalidPreconditionError(AppError):
    status_code = 400
    code = "invalid_precondition"


def _parse_if_match(value: str) -> int:
    """Accepts '3', '\"3\"', or 'W/\"3\"'."""
    cleaned = value.strip().removeprefix("W/").strip().strip('"')
    if not cleaned.isdigit():
        raise InvalidPreconditionError("If-Match must carry the incident's version ETag")
    return int(cleaned)


def _etag(version: int) -> str:
    return f'"{version}"'


def _replay(stored_status: int, stored_body: str) -> Response:
    return Response(
        content=stored_body,
        status_code=stored_status,
        media_type="application/json",
        headers={"Idempotency-Replayed": "true"},
    )


@router.post(
    "",
    status_code=201,
    response_model=Data[IncidentOut],
    summary="Report an incident",
    description=(
        "Creates the incident with the organisation's next gapless number "
        "(INC-1, INC-2, ...). Send an Idempotency-Key header to make retries "
        "safe: the same key returns the original response instead of "
        "creating a duplicate."
    ),
)
async def create_incident(
    payload: IncidentCreate,
    ctx: CreateCtx,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> Response:
    if idempotency_key is not None:
        existing = await idempotency.stored_response(session, ctx.org.id, idempotency_key)
        if existing is not None:
            return _replay(existing.status_code, existing.response_body)

    incident = await incident_service.create_incident(
        session,
        ctx.org,
        service_id=payload.service_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        reported_by=ctx.user,
        assigned_to=payload.assigned_to,
        started_at=payload.started_at,
        tags=payload.tags,
    )
    body = Data(data=IncidentOut.model_validate(incident)).model_dump_json()

    if idempotency_key is not None:
        winner = await idempotency.store(session, ctx.org.id, idempotency_key, 201, body)
        if winner is not None:
            # A concurrent retry won the key: discard our incident, replay theirs.
            await session.rollback()
            return _replay(winner.status_code, winner.response_body)
    await session.commit()
    return Response(content=body, status_code=201, media_type="application/json")


@router.get(
    "",
    summary="List incidents",
    description=(
        "Filterable, searchable, cursor-paginated, newest first. Cursors are "
        "keyset-based (never OFFSET) so pages stay stable under concurrent "
        "writes; see the next_cursor field."
    ),
)
async def list_incidents(
    ctx: ViewCtx,
    session: SessionDep,
    status: Annotated[list[IncidentStatus] | None, Query()] = None,
    severity: Annotated[list[Severity] | None, Query()] = None,
    service_id: Annotated[UUID | None, Query()] = None,
    assigned_to: Annotated[UUID | None, Query()] = None,
    tag: Annotated[str | None, Query(max_length=100)] = None,
    q: Annotated[str | None, Query(max_length=200, description="Full-text search")] = None,
    sort: Annotated[str, Query(pattern="^(created_at|started_at)$")] = "created_at",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[IncidentOut]:
    incidents, next_cursor = await incident_service.list_incidents(
        session,
        ctx.org,
        statuses=status,
        severities=severity,
        service_id=service_id,
        assigned_to=assigned_to,
        tag=tag,
        q=q,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    return Page(data=[IncidentOut.model_validate(i) for i in incidents], next_cursor=next_cursor)


@router.get("/{incident_id}", summary="Get an incident")
async def get_incident(
    incident_id: UUID, ctx: ViewCtx, session: SessionDep, response: Response
) -> Data[IncidentOut]:
    incident = await incident_service.get_incident(session, ctx.org, incident_id)
    response.headers["ETag"] = _etag(incident.version)
    return Data(data=IncidentOut.model_validate(incident))


@router.post(
    "/{incident_id}/status",
    summary="Change an incident's status",
    description=(
        "Applies one legal state-machine transition. Acknowledging stamps "
        "acknowledged_at; resolving requires a resolution summary and stamps "
        "resolved_at. Illegal transitions answer 409 with the allowed targets."
    ),
)
async def change_status(
    incident_id: UUID, payload: StatusChangeRequest, ctx: UpdateCtx, session: SessionDep
) -> Data[IncidentOut]:
    incident = await incident_service.transition_status(
        session,
        ctx.org,
        incident_id,
        new_status=payload.status,
        actor=ctx.user,
        resolution_summary=payload.resolution_summary,
    )
    await session.commit()
    return Data(data=IncidentOut.model_validate(incident))


@router.patch(
    "/{incident_id}",
    summary="Edit an incident",
    description=(
        "Field edits; every change is recorded on the timeline. Requires an "
        "If-Match header with the version ETag from the last read; a stale "
        "version answers 409 with the server's current state."
    ),
)
async def update_incident(
    incident_id: UUID,
    payload: IncidentUpdate,
    ctx: UpdateCtx,
    session: SessionDep,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Data[IncidentOut]:
    if if_match is None:
        raise PreconditionRequiredError("Send the If-Match header with the version you last read")
    incident = await incident_service.update_incident(
        session,
        ctx.org,
        incident_id,
        actor=ctx.user,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        tags=payload.tags,
        assigned_to=payload.assigned_to,
        assignee_provided="assigned_to" in payload.model_fields_set,
        expected_version=_parse_if_match(if_match),
    )
    await session.commit()
    response.headers["ETag"] = _etag(incident.version)
    return Data(data=IncidentOut.model_validate(incident))


@router.get(
    "/{incident_id}/events",
    summary="The incident timeline",
    description="Append-only event log, oldest first: the source of truth for what happened.",
)
async def list_events(
    incident_id: UUID,
    ctx: ViewCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[EventOut]:
    incident = await incident_service.get_incident(session, ctx.org, incident_id)
    events, next_cursor = await timeline.list_events(
        session, incident.id, limit=limit, cursor=cursor
    )
    return Page(data=[EventOut.model_validate(e) for e in events], next_cursor=next_cursor)


CommentCtx = Annotated[AuthContext, Depends(require(Permission.COMMENT_CREATE))]
UploadCtx = Annotated[AuthContext, Depends(require(Permission.ATTACHMENT_UPLOAD))]


@router.get("/{incident_id}/comments", summary="List comments")
async def list_comments(
    incident_id: UUID,
    ctx: ViewCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[CommentOut]:
    comments, next_cursor = await comment_service.list_comments(
        session, ctx.org, incident_id, limit=limit, cursor=cursor
    )
    return Page(data=[CommentOut.model_validate(c) for c in comments], next_cursor=next_cursor)


@router.post("/{incident_id}/comments", status_code=201, summary="Add a comment")
async def add_comment(
    incident_id: UUID, payload: CommentCreate, ctx: CommentCtx, session: SessionDep
) -> Data[CommentOut]:
    comment = await comment_service.add_comment(
        session, ctx.org, incident_id, author=ctx.user, body=payload.body
    )
    await session.commit()
    return Data(data=CommentOut.model_validate(comment))


@router.patch(
    "/{incident_id}/comments/{comment_id}",
    summary="Edit a comment",
    description="Author only; the comment is marked as edited.",
)
async def edit_comment(
    incident_id: UUID,
    comment_id: UUID,
    payload: CommentCreate,
    ctx: CommentCtx,
    session: SessionDep,
) -> Data[CommentOut]:
    comment = await comment_service.edit_comment(
        session, ctx.org, incident_id, comment_id, actor=ctx.user, body=payload.body
    )
    await session.commit()
    return Data(data=CommentOut.model_validate(comment))


@router.delete(
    "/{incident_id}/comments/{comment_id}",
    status_code=204,
    summary="Delete a comment",
    description="Soft delete by the author, or by an admin (comment moderation).",
)
async def delete_comment(
    incident_id: UUID, comment_id: UUID, ctx: CommentCtx, session: SessionDep
) -> None:
    await comment_service.delete_comment(
        session,
        ctx.org,
        incident_id,
        comment_id,
        actor=ctx.user,
        can_moderate=role_has(ctx.role, Permission.COMMENT_MODERATE),
    )
    await session.commit()


@router.get("/{incident_id}/attachments", summary="List attachments")
async def list_attachments(
    incident_id: UUID, ctx: ViewCtx, session: SessionDep
) -> Data[list[AttachmentOut]]:
    attachments = await attachment_service.list_attachments(session, ctx.org, incident_id)
    return Data(data=[AttachmentOut.model_validate(a) for a in attachments])


@router.post(
    "/{incident_id}/attachments",
    status_code=201,
    summary="Upload an attachment",
    description="Multipart upload, streamed to storage with a SHA-256 checksum.",
)
async def upload_attachment(
    incident_id: UUID, file: UploadFile, ctx: UploadCtx, session: SessionDep
) -> Data[AttachmentOut]:
    attachment = await attachment_service.save_attachment(
        session, get_settings(), ctx.org, incident_id, uploader=ctx.user, upload=file
    )
    await session.commit()
    return Data(data=AttachmentOut.model_validate(attachment))


@router.get(
    "/{incident_id}/attachments/{attachment_id}/download",
    summary="Download an attachment",
    response_class=FileResponse,
)
async def download_attachment(
    incident_id: UUID, attachment_id: UUID, ctx: ViewCtx, session: SessionDep
) -> FileResponse:
    attachment = await attachment_service.get_attachment(
        session, ctx.org, incident_id, attachment_id
    )
    return FileResponse(
        attachment_service.storage_path(get_settings(), attachment.storage_key),
        media_type=attachment.content_type,
        filename=attachment.filename,
    )
