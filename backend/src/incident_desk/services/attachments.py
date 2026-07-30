"""Incident attachments: streamed to local storage with checksums.

Files land under ``settings.attachments_dir`` keyed by incident and a random
name; the database row carries the metadata (size, checksum, content type)
and the storage key. Virus scanning is a declared hook for a later milestone,
not a hidden no-op.
"""

import hashlib
import uuid
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import Settings
from incident_desk.db import models
from incident_desk.errors import AppError, NotFoundError
from incident_desk.services import timeline
from incident_desk.services.incidents import get_incident

CHUNK_SIZE = 1024 * 1024


class AttachmentTooLargeError(AppError):
    status_code = 413
    code = "attachment_too_large"


def storage_path(settings: Settings, storage_key: str) -> Path:
    return Path(settings.attachments_dir) / storage_key


async def save_attachment(
    session: AsyncSession,
    settings: Settings,
    org: models.Organization,
    incident_id: UUID,
    *,
    uploader: models.User,
    upload: UploadFile,
) -> models.Attachment:
    incident = await get_incident(session, org, incident_id)
    filename = Path(upload.filename or "attachment").name or "attachment"
    storage_key = f"{incident.id}/{uuid.uuid4().hex}"
    target = storage_path(settings, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > settings.attachment_max_bytes:
                    raise AttachmentTooLargeError(
                        f"Attachments are limited to {settings.attachment_max_bytes} bytes"
                    )
                digest.update(chunk)
                out.write(chunk)
    except AttachmentTooLargeError:
        target.unlink(missing_ok=True)
        raise

    attachment = models.Attachment(
        incident_id=incident.id,
        uploader_id=uploader.id,
        filename=filename,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=size,
        storage_key=storage_key,
        checksum=digest.hexdigest(),
    )
    session.add(attachment)
    await session.flush()
    await timeline.record(
        session,
        incident_id=incident.id,
        actor_id=uploader.id,
        event_type="attachment.added",
        payload={"attachment_id": str(attachment.id), "filename": filename, "bytes": size},
    )
    return attachment


async def list_attachments(
    session: AsyncSession, org: models.Organization, incident_id: UUID
) -> list[models.Attachment]:
    incident = await get_incident(session, org, incident_id)
    rows = await session.scalars(
        select(models.Attachment)
        .where(models.Attachment.incident_id == incident.id)
        .order_by(models.Attachment.created_at, models.Attachment.id)
    )
    return list(rows)


async def get_attachment(
    session: AsyncSession, org: models.Organization, incident_id: UUID, attachment_id: UUID
) -> models.Attachment:
    attachment = await session.scalar(
        select(models.Attachment)
        .join(models.Incident, models.Incident.id == models.Attachment.incident_id)
        .where(
            models.Incident.org_id == org.id,
            models.Attachment.incident_id == incident_id,
            models.Attachment.id == attachment_id,
        )
    )
    if attachment is None:
        raise NotFoundError("Attachment not found")
    return attachment
