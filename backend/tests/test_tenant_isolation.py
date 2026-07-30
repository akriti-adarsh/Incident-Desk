"""Tenant isolation, parametrised over the route table.

Every route under ``/api/v1/orgs/{org_slug}`` is called by a user who is an
OWNER of a different organisation. The caller uses the victim org's slug and
must receive **404, not 403**: a tenant probing another tenant's URLs learns
nothing about whether the org, or anything inside it, exists. Being owner in
their own org guarantees the failure cannot be a role-based 403.

New org-scoped routes are picked up automatically at collection time; nothing
here needs editing when the API grows.
"""

import re
import uuid
from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.main import create_app
from tests.factories import make_org, make_user
from tests.route_table import iter_api_routes

Login = Callable[[str], Awaitable[dict[str, str]]]


def _org_scoped_routes() -> list[tuple[str, str]]:
    return sorted(
        (route.method, route.path)
        for route in iter_api_routes(create_app())
        if "{org_slug}" in route.path
    )


ROUTES = _org_scoped_routes()


def test_route_table_is_not_empty() -> None:
    """If collection breaks, fail loudly instead of silently testing nothing."""
    assert len(ROUTES) >= 2


def _fill_path(path: str, org_slug: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "org_slug":
            return org_slug
        # Resource ids are UUIDs everywhere; a random one is a plausible probe.
        return str(uuid.uuid4())

    return re.sub(r"\{(\w+)\}", replace, path)


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_cross_tenant_request_is_a_404(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    auth_headers: Login,
    method: str,
    path: str,
) -> None:
    attacker = await make_user(db_session)
    victim = await make_user(db_session)
    await make_org(db_session, owner=attacker)  # owner elsewhere: 403 is impossible
    victim_org = await make_org(db_session, owner=victim)

    headers = await auth_headers(attacker.email)
    url = _fill_path(path, victim_org.slug)
    response = await client.request(method, url, headers=headers, json={})

    assert response.status_code == 404, (
        f"{method} {path} answered {response.status_code} for a cross-tenant probe; "
        "it must be 404 so existence is never leaked"
    )
    assert response.json()["error"]["code"] == "not_found"
