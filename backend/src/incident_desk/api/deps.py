"""Request authentication dependencies."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.db.engine import get_db_session
from incident_desk.errors import UnauthorizedError
from incident_desk.security.jwt import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> models.User:
    if credentials is None:
        raise UnauthorizedError("Authentication required")
    claims = decode_access_token(get_settings(), credentials.credentials)
    user = await session.get(models.User, claims.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Token is invalid or expired")
    if user.token_version != claims.token_version:
        # The version was bumped (password reset, forced logout): every access
        # token minted before the bump dies here.
        raise UnauthorizedError("Token is invalid or expired")
    return user


CurrentUser = Annotated[models.User, Depends(get_current_user)]
