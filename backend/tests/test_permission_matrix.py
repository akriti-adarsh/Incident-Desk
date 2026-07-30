"""Exhaustive permission matrix: every role crossed with every permission.

The expected matrix is written out explicitly rather than derived from the
implementation, so loosening a role's permissions requires changing two files
and cannot happen by accident.
"""

import pytest

from incident_desk.authz import ROLE_PERMISSIONS, Permission, role_has
from incident_desk.enums import Role

EXPECTED: dict[Role, set[Permission]] = {
    Role.VIEWER: {
        Permission.ORG_VIEW,
        Permission.MEMBER_VIEW,
        Permission.SERVICE_VIEW,
        Permission.INCIDENT_VIEW,
        Permission.ONCALL_VIEW,
        Permission.METRICS_VIEW,
    },
    Role.RESPONDER: {
        Permission.ORG_VIEW,
        Permission.MEMBER_VIEW,
        Permission.SERVICE_VIEW,
        Permission.INCIDENT_VIEW,
        Permission.ONCALL_VIEW,
        Permission.METRICS_VIEW,
        Permission.INCIDENT_CREATE,
        Permission.INCIDENT_UPDATE,
        Permission.COMMENT_CREATE,
        Permission.ATTACHMENT_UPLOAD,
    },
    Role.ADMIN: {
        Permission.ORG_VIEW,
        Permission.MEMBER_VIEW,
        Permission.SERVICE_VIEW,
        Permission.INCIDENT_VIEW,
        Permission.ONCALL_VIEW,
        Permission.METRICS_VIEW,
        Permission.INCIDENT_CREATE,
        Permission.INCIDENT_UPDATE,
        Permission.COMMENT_CREATE,
        Permission.ATTACHMENT_UPLOAD,
        Permission.MEMBER_MANAGE,
        Permission.SERVICE_MANAGE,
        Permission.ONCALL_MANAGE,
        Permission.COMMENT_MODERATE,
        Permission.AUDIT_VIEW,
        Permission.APIKEY_MANAGE,
    },
    Role.OWNER: {
        Permission.ORG_VIEW,
        Permission.MEMBER_VIEW,
        Permission.SERVICE_VIEW,
        Permission.INCIDENT_VIEW,
        Permission.ONCALL_VIEW,
        Permission.METRICS_VIEW,
        Permission.INCIDENT_CREATE,
        Permission.INCIDENT_UPDATE,
        Permission.COMMENT_CREATE,
        Permission.ATTACHMENT_UPLOAD,
        Permission.MEMBER_MANAGE,
        Permission.SERVICE_MANAGE,
        Permission.ONCALL_MANAGE,
        Permission.COMMENT_MODERATE,
        Permission.AUDIT_VIEW,
        Permission.APIKEY_MANAGE,
        Permission.ORG_MANAGE,
    },
}


def test_matrix_covers_every_role() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    assert set(EXPECTED) == set(Role)


@pytest.mark.parametrize("permission", list(Permission))
@pytest.mark.parametrize("role", list(Role))
def test_role_permission_cell(role: Role, permission: Permission) -> None:
    """One test per cell: 4 roles x every permission, granted and denied alike."""
    assert role_has(role, permission) is (permission in EXPECTED[role])


def test_roles_strictly_escalate() -> None:
    """Each step up the ladder only ever adds permissions."""
    assert ROLE_PERMISSIONS[Role.VIEWER] < ROLE_PERMISSIONS[Role.RESPONDER]
    assert ROLE_PERMISSIONS[Role.RESPONDER] < ROLE_PERMISSIONS[Role.ADMIN]
    assert ROLE_PERMISSIONS[Role.ADMIN] < ROLE_PERMISSIONS[Role.OWNER]


def test_no_permission_is_unreachable() -> None:
    granted_somewhere = set[Permission]().union(*ROLE_PERMISSIONS.values())
    assert granted_somewhere == set(Permission)
