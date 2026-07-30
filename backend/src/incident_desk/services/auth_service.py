"""Registration and email verification flows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.errors import AppError, ConflictError
from incident_desk.security.passwords import hash_password
from incident_desk.security.tokens import generate_token, hash_token

VERIFICATION_TTL = timedelta(hours=24)


class EmailAlreadyRegisteredError(ConflictError):
    code = "email_taken"


class InvalidTokenError(AppError):
    status_code = 400
    code = "invalid_token"


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def register_user(
    session: AsyncSession, *, email: str, password: str, full_name: str
) -> tuple[models.User, str]:
    """Create an unverified user and return it with a raw verification token."""
    email = normalize_email(email)
    existing = await session.scalar(select(models.User).where(models.User.email == email))
    if existing is not None:
        raise EmailAlreadyRegisteredError("An account with this email already exists")
    user = models.User(
        email=email, password_hash=hash_password(password), full_name=full_name.strip()
    )
    session.add(user)
    await session.flush()
    raw_token = await issue_verification_token(session, user)
    return user, raw_token


async def issue_verification_token(session: AsyncSession, user: models.User) -> str:
    raw = generate_token()
    session.add(
        models.EmailVerificationToken(
            user_id=user.id, token_hash=hash_token(raw), expires_at=_now() + VERIFICATION_TTL
        )
    )
    await session.flush()
    return raw


async def verify_email(session: AsyncSession, raw_token: str) -> models.User:
    """Consume a verification token. Invalid, expired, and replayed all fail alike."""
    token = await session.scalar(
        select(models.EmailVerificationToken).where(
            models.EmailVerificationToken.token_hash == hash_token(raw_token)
        )
    )
    if token is None or token.consumed_at is not None or token.expires_at <= _now():
        raise InvalidTokenError("Verification link is invalid or has expired")
    user = await session.get(models.User, token.user_id)
    if user is None:
        raise InvalidTokenError("Verification link is invalid or has expired")
    token.consumed_at = _now()
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    await session.flush()
    return user
