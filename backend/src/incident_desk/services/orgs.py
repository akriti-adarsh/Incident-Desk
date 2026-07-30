"""Organisation lifecycle."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import Role
from incident_desk.errors import ConflictError


class SlugTakenError(ConflictError):
    code = "slug_taken"


async def create_organization(
    session: AsyncSession, *, name: str, slug: str, owner: models.User
) -> models.Organization:
    """Create an org with its owner membership and its sequence-counter row."""
    existing = await session.scalar(
        select(models.Organization.id).where(models.Organization.slug == slug)
    )
    if existing is not None:
        raise SlugTakenError("This slug is already in use")
    org = models.Organization(name=name, slug=slug)
    session.add(org)
    try:
        # SAVEPOINT around the flush: on constraint failure only this
        # statement is rolled back and the session stays healthy.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:  # lost a race on the unique constraint
        raise SlugTakenError("This slug is already in use") from exc
    session.add(models.Membership(user_id=owner.id, org_id=org.id, role=Role.OWNER))
    session.add(models.OrganizationCounter(org_id=org.id))
    await session.flush()
    return org


async def organizations_for(
    session: AsyncSession, user: models.User
) -> list[tuple[models.Organization, Role]]:
    rows = await session.execute(
        select(models.Organization, models.Membership.role)
        .join(models.Membership, models.Membership.org_id == models.Organization.id)
        .where(models.Membership.user_id == user.id)
        .order_by(models.Organization.name, models.Organization.id)
    )
    return [(org, role) for org, role in rows.tuples()]
