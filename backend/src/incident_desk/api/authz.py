"""The org-scoped authorisation dependency.

``require(*permissions)`` builds a FastAPI dependency that:

1. authenticates the caller (bearer access JWT, or an ``ik_`` API key),
2. resolves the organisation named by the ``org_slug`` path parameter
   together with the caller's standing in it. An org that does not exist,
   an org the user does not belong to, and an org an API key was not minted
   for are all indistinguishable: 404, so tenants cannot probe each other,
3. checks every required permission: against the member's role for users,
   against the granted scopes for API keys (403 either way; the caller is
   inside the org, so nothing is leaked).

The returned ``AuthContext`` carries the org, so every downstream query can
apply the org scope at the query level. Some actions inherently need a human
(authoring incidents, comments, uploads); handlers call
``ctx.require_user()`` and API keys get a 403 there.

Dependencies built here expose ``required_permissions``; the
route-registration test uses it to fail any org route that forgot to declare
one.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.deps import ApiKeyPrincipal, Principal, get_principal
from incident_desk.authz import ROLE_PERMISSIONS, Permission
from incident_desk.db import models
from incident_desk.db.engine import get_db_session
from incident_desk.enums import Role
from incident_desk.errors import ForbiddenError, NotFoundError


class UserRequiredError(ForbiddenError):
    code = "user_required"


@dataclass(frozen=True)
class AuthContext:
    org: models.Organization
    user: models.User | None
    membership: models.Membership | None
    api_key: models.ApiKey | None = None

    @property
    def role(self) -> Role:
        """The effective role for role-based guards.

        API keys act with admin-shaped standing bounded by their scopes;
        they can never pass owner-only guards.
        """
        if self.membership is not None:
            return self.membership.role
        return Role.ADMIN

    @property
    def actor_id(self) -> UUID | None:
        return self.user.id if self.user is not None else None

    def require_user(self) -> models.User:
        if self.user is None:
            raise UserRequiredError(
                "This action needs a user session; API keys cannot author content"
            )
        return self.user


def require(
    *permissions: Permission,
) -> Callable[..., Awaitable[AuthContext]]:
    async def dependency(
        org_slug: Annotated[str, Path(description="Organisation slug from the URL")],
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> AuthContext:
        if isinstance(principal, ApiKeyPrincipal):
            org = await session.scalar(
                select(models.Organization).where(
                    models.Organization.slug == org_slug,
                    models.Organization.id == principal.api_key.org_id,
                )
            )
            if org is None:
                # Wrong org for this key, or no such org: identical answer.
                raise NotFoundError("Organization not found")
            granted_scopes = set(principal.api_key.scopes)
            for permission in permissions:
                if permission.value not in granted_scopes:
                    raise ForbiddenError("This API key does not have the required scope")
            return AuthContext(org=org, user=None, membership=None, api_key=principal.api_key)

        row = (
            await session.execute(
                select(models.Organization, models.Membership)
                .join(
                    models.Membership,
                    models.Membership.org_id == models.Organization.id,
                )
                .where(
                    models.Organization.slug == org_slug,
                    models.Membership.user_id == principal.id,
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
        return AuthContext(org=org, user=principal, membership=membership)

    dependency.required_permissions = permissions  # type: ignore[attr-defined]
    return dependency
