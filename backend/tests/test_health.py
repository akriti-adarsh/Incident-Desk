"""Smoke tests for the app skeleton: health, readiness, error envelope, request ids."""

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db.engine import get_db_session
from incident_desk.errors import ConflictError


async def test_health_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(response.headers["X-Request-ID"]) == 32


async def test_cors_preflight_is_allowed_for_the_frontend_origin(
    client: httpx.AsyncClient,
) -> None:
    # The SPA is served from a different origin than the API; without CORS the
    # browser's preflight fails and every request is blocked.
    response = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"


async def test_ready_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_reports_503_when_database_is_unreachable(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    class BrokenSession:
        async def execute(self, statement: object) -> None:
            raise OSError("connection refused")

    app.dependency_overrides[get_db_session] = lambda: BrokenSession()
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"


async def test_ready_through_real_session_dependency(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Without the test override, the dependency builds a session from app.state."""
    app.dependency_overrides.pop(get_db_session)
    response = await client.get("/health/ready")
    assert response.status_code == 200


async def test_ready_uses_real_database(db_session: AsyncSession) -> None:
    value = (await db_session.execute(text("SELECT 41 + 1"))).scalar_one()
    assert value == 42


async def test_unknown_route_returns_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Request-ID"]


async def test_inbound_request_id_is_honoured(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "trace-1234"})
    assert response.headers["X-Request-ID"] == "trace-1234"


async def test_garbage_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "no spaces!"})
    assert response.headers["X-Request-ID"] != "no spaces!"
    assert len(response.headers["X-Request-ID"]) == 32


async def test_app_error_renders_envelope(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise ConflictError("Version mismatch", details={"expected": 2, "got": 1})

    response = await client.get("/boom")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert error["message"] == "Version mismatch"
    assert error["details"] == {"expected": 2, "got": 1}


async def test_validation_error_renders_envelope(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/needs-int")
    async def needs_int(n: int) -> dict[str, int]:
        return {"n": n}

    response = await client.get("/needs-int", params={"n": "not-a-number"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["query", "n"]
