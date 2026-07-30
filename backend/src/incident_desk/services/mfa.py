"""TOTP MFA: two-phase enrolment, login challenge, recovery codes.

Enrolment writes a pending secret; MFA is enforced only after the user proves
the authenticator works (``mfa_enabled_at``). Accepted TOTP timesteps are
recorded so a captured code cannot be replayed. Recovery codes are hashed,
single-use, and returned in plaintext exactly once at enrolment.
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import Settings
from incident_desk.db import models
from incident_desk.errors import AppError, ConflictError, UnauthorizedError
from incident_desk.security import totp
from incident_desk.security.jwt import decode_mfa_token
from incident_desk.security.tokens import hash_token
from incident_desk.services.sessions import SessionTokens, issue_session

RECOVERY_CODE_COUNT = 10


class MfaAlreadyEnabledError(ConflictError):
    code = "mfa_already_enabled"


class MfaNotEnrolledError(AppError):
    status_code = 400
    code = "mfa_not_enrolled"


class InvalidMfaCodeError(UnauthorizedError):
    code = "invalid_mfa_code"


def _now() -> datetime:
    return datetime.now(UTC)


def _generate_recovery_code() -> str:
    raw = secrets.token_hex(4)
    return f"{raw[:4]}-{raw[4:]}"


async def start_enrollment(
    session: AsyncSession, settings: Settings, user: models.User
) -> tuple[str, str]:
    """Create a pending secret and return it with its otpauth:// URI."""
    if user.mfa_enabled_at is not None:
        raise MfaAlreadyEnabledError("MFA is already enabled for this account")
    secret = totp.generate_secret()
    user.mfa_secret = secret
    await session.flush()
    uri = totp.provisioning_uri(secret, account_name=user.email, issuer=settings.app_name)
    return secret, uri


async def confirm_enrollment(session: AsyncSession, user: models.User, code: str) -> list[str]:
    """Verify the first code from the authenticator and enable MFA.

    Returns the plaintext recovery codes; only their hashes are stored.
    """
    if user.mfa_enabled_at is not None:
        raise MfaAlreadyEnabledError("MFA is already enabled for this account")
    if user.mfa_secret is None:
        raise MfaNotEnrolledError("Start MFA enrolment before verifying a code")
    counter = totp.match_code(user.mfa_secret, code, _now())
    if counter is None:
        raise InvalidMfaCodeError("The code is not valid; check your authenticator app")
    user.mfa_enabled_at = _now()
    user.mfa_last_counter = counter

    codes = [_generate_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    session.add_all(
        models.MfaRecoveryCode(user_id=user.id, code_hash=hash_token(code_)) for code_ in codes
    )
    await session.flush()
    return codes


async def _try_totp(session: AsyncSession, user: models.User, code: str) -> bool:
    if user.mfa_secret is None:
        return False
    counter = totp.match_code(user.mfa_secret, code, _now())
    if counter is None:
        return False
    if user.mfa_last_counter is not None and counter <= user.mfa_last_counter:
        # A code from an already-consumed timestep: replay.
        return False
    user.mfa_last_counter = counter
    await session.flush()
    return True


async def _try_recovery_code(session: AsyncSession, user: models.User, code: str) -> bool:
    row = await session.scalar(
        select(models.MfaRecoveryCode).where(
            models.MfaRecoveryCode.user_id == user.id,
            models.MfaRecoveryCode.code_hash == hash_token(code.strip().lower()),
            models.MfaRecoveryCode.used_at.is_(None),
        )
    )
    if row is None:
        return False
    row.used_at = _now()
    await session.flush()
    return True


async def complete_challenge(
    session: AsyncSession, settings: Settings, *, mfa_token: str, code: str
) -> SessionTokens:
    """Second login step: exchange the MFA token plus a valid code for a session."""
    claims = decode_mfa_token(settings, mfa_token)
    user = await session.get(models.User, claims.user_id)
    if (
        user is None
        or not user.is_active
        or user.token_version != claims.token_version
        or user.mfa_enabled_at is None
    ):
        raise InvalidMfaCodeError("MFA challenge failed; log in again")
    if not await _try_totp(session, user, code) and not await _try_recovery_code(
        session, user, code
    ):
        raise InvalidMfaCodeError("The code is not valid or was already used")
    return await issue_session(session, settings, user)
