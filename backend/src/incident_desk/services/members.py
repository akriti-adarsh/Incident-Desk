"""Membership management: invitations, role changes, removal, last-owner rule."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import Role
from incident_desk.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from incident_desk.security.tokens import generate_token, hash_token
from incident_desk.services.auth_service import normalize_email

INVITATION_TTL = timedelta(days=7)


class AlreadyMemberError(ConflictError):
    code = "already_member"


class DuplicateInvitationError(ConflictError):
    code = "invitation_pending"


class LastOwnerError(ConflictError):
    code = "last_owner"


class InvalidInvitationError(AppError):
    status_code = 400
    code = "invalid_invitation"


class WrongAccountError(AppError):
    status_code = 400
    code = "wrong_account"


def _now() -> datetime:
    return datetime.now(UTC)


async def list_members(
    session: AsyncSession, org: models.Organization
) -> list[tuple[models.User, models.Membership]]:
    rows = await session.execute(
        select(models.User, models.Membership)
        .join(models.Membership, models.Membership.user_id == models.User.id)
        .where(models.Membership.org_id == org.id)
        .order_by(models.User.full_name, models.User.id)
    )
    return [(user, membership) for user, membership in rows.tuples()]


async def _owner_count(session: AsyncSession, org_id: UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(models.Membership)
        .where(models.Membership.org_id == org_id, models.Membership.role == Role.OWNER)
    )
    return int(count or 0)


async def _get_membership(session: AsyncSession, org_id: UUID, user_id: UUID) -> models.Membership:
    membership = await session.get(models.Membership, (user_id, org_id))
    if membership is None:
        raise NotFoundError("Member not found")
    return membership


def _guard_owner_changes(actor_role: Role, target_role: Role, new_role: Role | None) -> None:
    """Only owners may touch the owner role, in either direction."""
    touches_owner = target_role == Role.OWNER or new_role == Role.OWNER
    if touches_owner and actor_role != Role.OWNER:
        raise ForbiddenError("Only an owner can change owner memberships")


async def change_role(
    session: AsyncSession,
    org: models.Organization,
    *,
    actor_role: Role,
    user_id: UUID,
    new_role: Role,
) -> models.Membership:
    membership = await _get_membership(session, org.id, user_id)
    _guard_owner_changes(actor_role, membership.role, new_role)
    if (
        membership.role == Role.OWNER
        and new_role != Role.OWNER
        and await _owner_count(session, org.id) == 1
    ):
        raise LastOwnerError("An organisation must keep at least one owner")
    membership.role = new_role
    await session.flush()
    return membership


async def remove_member(
    session: AsyncSession,
    org: models.Organization,
    *,
    actor_role: Role,
    user_id: UUID,
) -> None:
    membership = await _get_membership(session, org.id, user_id)
    _guard_owner_changes(actor_role, membership.role, None)
    if membership.role == Role.OWNER and await _owner_count(session, org.id) == 1:
        raise LastOwnerError("An organisation must keep at least one owner")
    await session.delete(membership)
    await session.flush()


async def create_invitation(
    session: AsyncSession,
    org: models.Organization,
    *,
    email: str,
    role: Role,
    invited_by: models.User,
    actor_role: Role,
) -> tuple[models.OrgInvitation, str]:
    email = normalize_email(email)
    _guard_owner_changes(actor_role, Role.VIEWER, role)
    existing_user = await session.scalar(select(models.User).where(models.User.email == email))
    if existing_user is not None:
        membership = await session.get(models.Membership, (existing_user.id, org.id))
        if membership is not None:
            raise AlreadyMemberError("This person is already a member")
    pending = await session.scalar(
        select(models.OrgInvitation).where(
            models.OrgInvitation.org_id == org.id,
            models.OrgInvitation.email == email,
            models.OrgInvitation.accepted_at.is_(None),
        )
    )
    if pending is not None:
        raise DuplicateInvitationError("An invitation for this address is already pending")
    raw = generate_token()
    invitation = models.OrgInvitation(
        org_id=org.id,
        email=email,
        role=role,
        invited_by=invited_by.id,
        token_hash=hash_token(raw),
        expires_at=_now() + INVITATION_TTL,
    )
    session.add(invitation)
    await session.flush()
    return invitation, raw


async def list_pending_invitations(
    session: AsyncSession, org: models.Organization
) -> list[models.OrgInvitation]:
    rows = await session.scalars(
        select(models.OrgInvitation)
        .where(
            models.OrgInvitation.org_id == org.id,
            models.OrgInvitation.accepted_at.is_(None),
        )
        .order_by(models.OrgInvitation.created_at, models.OrgInvitation.id)
    )
    return list(rows)


async def revoke_invitation(
    session: AsyncSession, org: models.Organization, invitation_id: UUID
) -> None:
    invitation = await session.scalar(
        select(models.OrgInvitation).where(
            models.OrgInvitation.org_id == org.id,
            models.OrgInvitation.id == invitation_id,
            models.OrgInvitation.accepted_at.is_(None),
        )
    )
    if invitation is None:
        raise NotFoundError("Invitation not found")
    await session.delete(invitation)
    await session.flush()


async def accept_invitation(
    session: AsyncSession, user: models.User, raw_token: str
) -> tuple[models.Organization, models.Membership]:
    """Turn a valid invitation into a membership for the logged-in user."""
    invitation = await session.scalar(
        select(models.OrgInvitation).where(models.OrgInvitation.token_hash == hash_token(raw_token))
    )
    if invitation is None or invitation.accepted_at is not None or invitation.expires_at <= _now():
        raise InvalidInvitationError("Invitation is invalid or has expired")
    if invitation.email != user.email:
        raise WrongAccountError(
            "This invitation was sent to a different email address; log in with the invited account"
        )
    org = await session.get(models.Organization, invitation.org_id)
    if org is None:
        raise InvalidInvitationError("Invitation is invalid or has expired")
    existing = await session.get(models.Membership, (user.id, org.id))
    if existing is not None:
        invitation.accepted_at = _now()
        await session.flush()
        return org, existing
    membership = models.Membership(user_id=user.id, org_id=org.id, role=invitation.role)
    session.add(membership)
    invitation.accepted_at = _now()
    await session.flush()
    return org, membership
