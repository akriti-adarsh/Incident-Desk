"""API keys: machine credentials with scoped permissions.

The full token (``ik_<prefix>_<secret>``) is shown exactly once at creation;
only the SHA-256 of the secret is stored. Keys are revocable, optionally
expiring, and act within an explicit list of permission scopes.
"""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.authz import Permission
from incident_desk.db import models
from incident_desk.errors import NotFoundError
from incident_desk.security.tokens import hash_token


def _format_token(prefix: str, secret: str) -> str:
    return f"ik_{prefix}_{secret}"


async def create_api_key(
    session: AsyncSession,
    org: models.Organization,
    *,
    name: str,
    scopes: list[Permission],
    expires_at: datetime | None,
) -> tuple[models.ApiKey, str]:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    key = models.ApiKey(
        org_id=org.id,
        name=name,
        prefix=prefix,
        key_hash=hash_token(secret),
        scopes=sorted({scope.value for scope in scopes}),
        expires_at=expires_at,
    )
    session.add(key)
    await session.flush()
    return key, _format_token(prefix, secret)


async def list_api_keys(session: AsyncSession, org: models.Organization) -> list[models.ApiKey]:
    rows = await session.scalars(
        select(models.ApiKey)
        .where(models.ApiKey.org_id == org.id)
        .order_by(models.ApiKey.created_at, models.ApiKey.id)
    )
    return list(rows)


async def revoke_api_key(
    session: AsyncSession, org: models.Organization, key_id: UUID
) -> models.ApiKey:
    key = await session.scalar(
        select(models.ApiKey).where(models.ApiKey.org_id == org.id, models.ApiKey.id == key_id)
    )
    if key is None:
        raise NotFoundError("API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await session.flush()
    return key
