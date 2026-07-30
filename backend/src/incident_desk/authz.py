"""Authorisation model: one Permission enum, one role matrix.

Roles are resolved per organisation from the membership row, never globally:
the same user can be an owner in one org and a viewer in another. Route
handlers declare required permissions through the ``require`` dependency in
``incident_desk.api.authz``; nothing else grants access.
"""

from enum import StrEnum

from incident_desk.enums import Role


class Permission(StrEnum):
    ORG_VIEW = "org:view"
    ORG_MANAGE = "org:manage"
    MEMBER_VIEW = "member:view"
    MEMBER_MANAGE = "member:manage"
    SERVICE_VIEW = "service:view"
    SERVICE_MANAGE = "service:manage"
    INCIDENT_VIEW = "incident:view"
    INCIDENT_CREATE = "incident:create"
    INCIDENT_UPDATE = "incident:update"
    COMMENT_CREATE = "comment:create"
    COMMENT_MODERATE = "comment:moderate"
    ATTACHMENT_UPLOAD = "attachment:upload"
    ONCALL_VIEW = "oncall:view"
    ONCALL_MANAGE = "oncall:manage"
    AUDIT_VIEW = "audit:view"
    APIKEY_MANAGE = "apikey:manage"
    METRICS_VIEW = "metrics:view"


_VIEWER = frozenset(
    {
        Permission.ORG_VIEW,
        Permission.MEMBER_VIEW,
        Permission.SERVICE_VIEW,
        Permission.INCIDENT_VIEW,
        Permission.ONCALL_VIEW,
        Permission.METRICS_VIEW,
    }
)

_RESPONDER = _VIEWER | {
    Permission.INCIDENT_CREATE,
    Permission.INCIDENT_UPDATE,
    Permission.COMMENT_CREATE,
    Permission.ATTACHMENT_UPLOAD,
}

_ADMIN = _RESPONDER | {
    Permission.MEMBER_MANAGE,
    Permission.SERVICE_MANAGE,
    Permission.ONCALL_MANAGE,
    Permission.COMMENT_MODERATE,
    Permission.AUDIT_VIEW,
    Permission.APIKEY_MANAGE,
}

_OWNER = _ADMIN | {Permission.ORG_MANAGE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.RESPONDER: frozenset(_RESPONDER),
    Role.ADMIN: frozenset(_ADMIN),
    Role.OWNER: frozenset(_OWNER),
}


def role_has(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
