"""Smoke tests for the app skeleton: health, error envelope, request ids."""

import httpx
import pytest
from fastapi import FastAPI

from incident_desk.errors import ConflictError
from incident_desk.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_health_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(response.headers["X-Request-ID"]) == 32


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
