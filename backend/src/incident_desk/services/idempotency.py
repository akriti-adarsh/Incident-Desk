"""Idempotency keys: retried creations return the original response.

The stored row is written in the same transaction as the created resource;
a retry (same org, same key) returns the recorded response byte-for-byte and
creates nothing. Rows expire after 24 hours via the retention job.
"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models


async def stored_response(
    session: AsyncSession, org_id: UUID, key: str
) -> models.IdempotencyKey | None:
    return await session.get(models.IdempotencyKey, (org_id, key))


async def store(
    session: AsyncSession, org_id: UUID, key: str, status_code: int, body: str
) -> models.IdempotencyKey | None:
    """Record the response for a key.

    Returns None on success. If a concurrent request already claimed the key,
    returns the winner's stored row; the caller must discard its own work and
    replay the winner's response instead.
    """
    session.add(
        models.IdempotencyKey(org_id=org_id, key=key, status_code=status_code, response_body=body)
    )
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        await session.rollback()
        return await session.get(models.IdempotencyKey, (org_id, key))
    return None
