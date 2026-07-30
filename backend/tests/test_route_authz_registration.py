"""Every API route must be registered with authentication and, when it lives
under an organisation, with the org-scoped authorisation dependency.

A route that forgets the dependency fails this suite, not production. The
checker itself is tested against a deliberately unprotected route to prove it
actually catches the mistake.
"""

from collections.abc import Iterator

from fastapi import APIRouter, FastAPI
from fastapi.dependencies.models import Dependant

from incident_desk.api.deps import get_current_user
from incident_desk.main import create_app
from tests.route_table import iter_api_routes

# Routes that are public by design. Everything else under /api/v1 must
# authenticate. Additions to this list should be rare and deliberate.
PUBLIC_ROUTES = {
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/resend-verification"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/mfa/challenge"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
}


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


def _is_authenticated(dependant: Dependant) -> bool:
    return any(d.call is get_current_user for d in _walk(dependant))


def _is_org_scoped_authorized(dependant: Dependant) -> bool:
    return any(hasattr(d.call, "required_permissions") for d in _walk(dependant) if d.call)


def find_unprotected(app: FastAPI) -> list[str]:
    """Return descriptions of every /api/v1 route missing its auth registration."""
    problems: list[str] = []
    for route in iter_api_routes(app):
        if not route.path.startswith("/api/v1"):
            continue
        if (route.method, route.path) in PUBLIC_ROUTES:
            continue
        if not _is_authenticated(route.dependant):
            problems.append(f"{route.method} {route.path}: no authentication dependency")
        if "{org_slug}" in route.path and not _is_org_scoped_authorized(route.dependant):
            problems.append(f"{route.method} {route.path}: no org-scoped require() dependency")
    return problems


def test_every_api_route_is_protected() -> None:
    assert find_unprotected(create_app()) == []


def test_the_checker_catches_a_route_missing_auth() -> None:
    """Prove the guard bites: an unprotected org route must be flagged."""
    app = create_app()
    rogue = APIRouter(prefix="/api/v1")

    @rogue.get("/orgs/{org_slug}/forgotten")
    async def forgotten(org_slug: str) -> dict[str, str]:
        return {"org": org_slug}

    app.include_router(rogue)
    problems = find_unprotected(app)
    assert any("forgotten" in p and "no authentication" in p for p in problems)
    assert any("forgotten" in p and "no org-scoped" in p for p in problems)


def test_public_route_list_matches_reality() -> None:
    """Every entry in PUBLIC_ROUTES exists; a renamed route must update the list."""
    existing = {(r.method, r.path) for r in iter_api_routes(create_app())}
    missing = PUBLIC_ROUTES - existing
    assert missing == set()
