"""Access-token JWTs via PyJWT.

Every decode validates the signature, ``exp``, ``iss``, and ``aud``; a token
that fails any check is rejected with a 401 and no detail about why.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from incident_desk.config import Settings
from incident_desk.errors import UnauthorizedError

ALGORITHM = "HS256"
LEEWAY_SECONDS = 10
MFA_TOKEN_TTL_SECONDS = 300


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    token_version: int
    jti: str


def _create(
    settings: Settings, *, user_id: uuid.UUID, token_version: int, token_type: str, ttl_seconds: int
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "ver": token_version,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": token_type,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def _decode(settings: Settings, token: str, *, expected_type: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "jti"]},
        )
        user_id = uuid.UUID(str(payload["sub"]))
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise UnauthorizedError("Token is invalid or expired") from exc
    if payload.get("type") != expected_type:
        raise UnauthorizedError("Token is invalid or expired")
    return AccessClaims(
        user_id=user_id,
        token_version=int(payload.get("ver", 0)),
        jti=str(payload["jti"]),
    )


def create_access_token(settings: Settings, *, user_id: uuid.UUID, token_version: int) -> str:
    return _create(
        settings,
        user_id=user_id,
        token_version=token_version,
        token_type="access",
        ttl_seconds=settings.access_token_ttl_seconds,
    )


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    return _decode(settings, token, expected_type="access")


def create_mfa_token(settings: Settings, *, user_id: uuid.UUID, token_version: int) -> str:
    """Short-lived proof that the password step of login succeeded."""
    return _create(
        settings,
        user_id=user_id,
        token_version=token_version,
        token_type="mfa",
        ttl_seconds=MFA_TOKEN_TTL_SECONDS,
    )


def decode_mfa_token(settings: Settings, token: str) -> AccessClaims:
    return _decode(settings, token, expected_type="mfa")
