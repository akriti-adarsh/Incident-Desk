"""The org-scoped authorisation dependency.

``require(*permissions)`` builds a FastAPI dependency that:

1. authenticates the caller (bearer access token),
2. resolves the organisation from the ``org_slug`` path parameter *together
   with* the caller's membership in one query — an org that does not exist
   and an org the caller does not belong to are indistinguishable (404, so
   tenants cannot probe for each other's existence),
3. checks every required permission against the caller's role in that org
   (403 only ever means "you are in this org but your role cannot do this").

The returned ``AuthContext`` carries the org, so every downstream query can
apply the org scope at the query level. Dependencies built here expose
``required_permissions``; the route-registration test uses it to fail any
org route that forgot to declare one.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.deps import get_current_user
from incident_desk.authz import ROLE_PERMISSIONS, Permission
from incident_desk.db import models
from incident_desk.db.engine import get_db_session
from incident_desk.enums import Role
from incident_desk.errors import ForbiddenError, NotFoundError


@dataclass(frozen=True)
class AuthContext:
    user: models.User
    org: models.Organization
    membership: models.Membership

    @property
    def role(self) -> Role:
        return self.membership.role


def require(
    *permissions: Permission,
) -> Callable[..., Awaitable[AuthContext]]:
    async def dependency(
        org_slug: Annotated[str, Path(description="Organisation slug from the URL")],
        user: Annotated[models.User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> AuthContext:
        row = (
            await session.execute(
                select(models.Organization, models.Membership)
                .join(
                    models.Membership,
                    models.Membership.org_id == models.Organization.id,
                )
                .where(
                    models.Organization.slug == org_slug,
                    models.Membership.user_id == user.id,
                )
            )
        ).first()
        if row is None:
            # Not a member or no such org: identical answer either way.
            raise NotFoundError("Organization not found")
        org, membership = row._tuple()
        granted = ROLE_PERMISSIONS[membership.role]
        for permission in permissions:
            if permission not in granted:
                raise ForbiddenError("Your role does not allow this action")
        return AuthContext(user=user, org=org, membership=membership)

    dependency.required_permissions = permissions  # type: ignore[attr-defined]
    return dependency
