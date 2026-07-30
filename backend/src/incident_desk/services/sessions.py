"""Login sessions: short-lived access JWTs plus rotating refresh-token families.

Refresh tokens rotate on every use: the presented token is consumed and a new
one is issued in the same family. Presenting an already-consumed token is
treated as evidence of theft; the entire family is revoked and the user must
log in again. Families are also revoked wholesale on logout.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import Settings
from incident_desk.db import models
from incident_desk.errors import UnauthorizedError
from incident_desk.security.jwt import create_access_token
from incident_desk.security.passwords import hash_password, verify_password
from incident_desk.security.tokens import generate_token, hash_token


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"


class EmailUnverifiedError(UnauthorizedError):
    code = "email_unverified"


class InvalidRefreshError(UnauthorizedError):
    code = "invalid_refresh"


class RefreshReusedError(UnauthorizedError):
    """Raised on refresh-token reuse. The family revocation must still be
    committed by the caller even though the request fails."""

    code = "refresh_reused"


class SessionTokens(NamedTuple):
    access_token: str
    refresh_token: str
    expires_in: int


# Verified against when the email does not match any user, so failed logins
# cost the same argon2 work whether or not the account exists.
_TIMING_EQUALIZER_HASH = hash_password("timing-equalizer-not-a-real-password")


def _now() -> datetime:
    return datetime.now(UTC)


async def authenticate(session: AsyncSession, *, email: str, password: str) -> models.User:
    """Check credentials. Unknown email and wrong password fail identically."""
    user = await session.scalar(
        select(models.User).where(models.User.email == email.strip().lower())
    )
    if user is None:
        verify_password(_TIMING_EQUALIZER_HASH, password)
        raise InvalidCredentialsError("Email or password is incorrect")
    if not verify_password(user.password_hash, password) or not user.is_active:
        raise InvalidCredentialsError("Email or password is incorrect")
    if user.email_verified_at is None:
        raise EmailUnverifiedError("Verify your email address before logging in")
    return user


async def issue_session(
    session: AsyncSession, settings: Settings, user: models.User
) -> SessionTokens:
    """Start a new refresh-token family and mint the first token pair."""
    family_id = uuid.uuid4()
    tokens = await _mint(session, settings, user, family_id)
    user.last_login_at = _now()
    await session.flush()
    return tokens


async def _mint(
    session: AsyncSession, settings: Settings, user: models.User, family_id: uuid.UUID
) -> SessionTokens:
    raw_refresh = generate_token()
    session.add(
        models.RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_token(raw_refresh),
            expires_at=_now() + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await session.flush()
    access = create_access_token(settings, user_id=user.id, token_version=user.token_version)
    return SessionTokens(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_seconds,
    )


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(models.RefreshToken)
        .where(
            models.RefreshToken.family_id == family_id,
            models.RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )


async def rotate_refresh(
    session: AsyncSession, settings: Settings, raw_refresh: str
) -> SessionTokens:
    """Consume a refresh token and issue the next pair in its family."""
    token = await session.scalar(
        select(models.RefreshToken).where(models.RefreshToken.token_hash == hash_token(raw_refresh))
    )
    if token is None:
        raise InvalidRefreshError("Refresh token is invalid")
    if token.revoked_at is not None:
        raise InvalidRefreshError("Refresh token is invalid")
    if token.consumed_at is not None:
        # Reuse of a consumed token: someone is replaying an old value.
        # Kill the whole family so the thief's copy dies too.
        await _revoke_family(session, token.family_id)
        raise RefreshReusedError("Refresh token reuse detected; log in again")
    if token.expires_at <= _now():
        raise InvalidRefreshError("Refresh token is invalid")

    user = await session.get(models.User, token.user_id)
    if user is None or not user.is_active:
        raise InvalidRefreshError("Refresh token is invalid")

    token.consumed_at = _now()
    return await _mint(session, settings, user, token.family_id)


async def revoke_session(session: AsyncSession, raw_refresh: str) -> None:
    """Logout: revoke the whole family of the presented refresh token.

    Unknown tokens are ignored so logout is idempotent and leaks nothing.
    """
    token = await session.scalar(
        select(models.RefreshToken).where(models.RefreshToken.token_hash == hash_token(raw_refresh))
    )
    if token is not None:
        await _revoke_family(session, token.family_id)


async def revoke_all_sessions(session: AsyncSession, user: models.User) -> None:
    """Revoke every refresh token and invalidate outstanding access tokens."""
    await session.execute(
        update(models.RefreshToken)
        .where(
            models.RefreshToken.user_id == user.id,
            models.RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    user.token_version += 1
    await session.flush()
