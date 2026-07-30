"""Test data factories."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.security.passwords import hash_password

PASSWORD = "correct-horse-battery-9"
# Hashed once at import: argon2 is deliberately slow (~135 ms per hash), and
# every factory user can share one hash of the shared test password.
PASSWORD_HASH = hash_password(PASSWORD)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def make_user(
    db_session: AsyncSession,
    *,
    email: str | None = None,
    full_name: str = "Test User",
    verified: bool = True,
    active: bool = True,
) -> models.User:
    user = models.User(
        email=email or unique_email(),
        password_hash=PASSWORD_HASH,
        full_name=full_name,
        is_active=active,
        email_verified_at=datetime.now(UTC) if verified else None,
    )
    db_session.add(user)
    await db_session.flush()
    return user
