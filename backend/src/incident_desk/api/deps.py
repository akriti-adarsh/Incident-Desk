"""Request authentication dependencies.

Two kinds of principal reach the API: humans with a bearer access JWT, and
machines with an API key (``ik_<prefix>_<secret>``). ``get_current_user``
accepts only humans (account endpoints); ``get_principal`` accepts both and
feeds the org-scoped authorisation dependency.
"""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.db.engine import get_db_session
from incident_desk.errors import UnauthorizedError
from incident_desk.security.jwt import decode_access_token
from incident_desk.security.tokens import hash_token

bearer_scheme = HTTPBearer(auto_error=False)

API_KEY_TOKEN_PREFIX = "ik_"


@dataclass(frozen=True)
class ApiKeyPrincipal:
    api_key: models.ApiKey


Principal = models.User | ApiKeyPrincipal


async def _resolve_user(session: AsyncSession, token: str) -> models.User:
    claims = decode_access_token(get_settings(), token)
    user = await session.get(models.User, claims.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Token is invalid or expired")
    if user.token_version != claims.token_version:
        # The version was bumped (password reset, forced logout): every access
        # token minted before the bump dies here.
        raise UnauthorizedError("Token is invalid or expired")
    return user


async def _resolve_api_key(session: AsyncSession, token: str) -> ApiKeyPrincipal:
    parts = token.split("_", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        raise UnauthorizedError("API key is invalid or revoked")
    _, prefix, secret = parts
    candidates = await session.scalars(select(models.ApiKey).where(models.ApiKey.prefix == prefix))
    secret_hash = hash_token(secret)
    now = datetime.now(UTC)
    for key in candidates:
        if not hmac.compare_digest(key.key_hash, secret_hash):
            continue
        if key.revoked_at is not None:
            raise UnauthorizedError("API key is invalid or revoked")
        if key.expires_at is not None and key.expires_at <= now:
            raise UnauthorizedError("API key is invalid or revoked")
        key.last_used_at = now
        await session.commit()
        return ApiKeyPrincipal(api_key=key)
    raise UnauthorizedError("API key is invalid or revoked")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> models.User:
    """Human sessions only; API keys are rejected here."""
    if credentials is None:
        raise UnauthorizedError("Authentication required")
    if credentials.credentials.startswith(API_KEY_TOKEN_PREFIX):
        raise UnauthorizedError("This endpoint needs a user session, not an API key")
    return await _resolve_user(session, credentials.credentials)


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Principal:
    if credentials is None:
        raise UnauthorizedError("Authentication required")
    token = credentials.credentials
    if token.startswith(API_KEY_TOKEN_PREFIX):
        return await _resolve_api_key(session, token)
    return await _resolve_user(session, token)


CurrentUser = Annotated[models.User, Depends(get_current_user)]
