"""Test data factories."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import Role
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


def unique_slug(prefix: str = "org") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def make_org(
    db_session: AsyncSession,
    *,
    owner: models.User,
    name: str = "Test Org",
    slug: str | None = None,
) -> models.Organization:
    org = models.Organization(name=name, slug=slug or unique_slug())
    db_session.add(org)
    await db_session.flush()
    db_session.add_all(
        [
            models.Membership(user_id=owner.id, org_id=org.id, role=Role.OWNER),
            models.OrganizationCounter(org_id=org.id),
        ]
    )
    await db_session.flush()
    return org


async def make_member(
    db_session: AsyncSession,
    org: models.Organization,
    user: models.User,
    role: Role,
) -> models.Membership:
    membership = models.Membership(user_id=user.id, org_id=org.id, role=role)
    db_session.add(membership)
    await db_session.flush()
    return membership
