"""Rate limiting (sliding window, per-identity buckets) and request tracing."""

import logging
from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from tests.factories import PASSWORD, make_org, make_user
from tests.test_api_keys import key_headers, make_key

Login = Callable[[str], Awaitable[dict[str, str]]]


async def test_rate_limit_headers_are_present(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    user = await make_user(db_session)
    headers = await auth_headers(user.email)
    response = await client.get("/api/v1/orgs", headers=headers)
    assert response.status_code == 200
    limit = int(response.headers["X-RateLimit-Limit"])
    remaining = int(response.headers["X-RateLimit-Remaining"])
    assert limit == get_settings().rate_limit_per_minute
    assert 0 <= remaining < limit
    assert int(response.headers["X-RateLimit-Reset"]) > 0


async def test_login_bucket_is_stricter_and_keyed_per_ip(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user(db_session)
    monkeypatch.setattr(get_settings(), "rate_limit_login_per_minute", 3)

    for _ in range(3):
        attempt = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong-password-1"},
        )
        assert attempt.status_code == 401  # wrong creds still consume the budget

    blocked = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


async def test_api_bucket_is_keyed_per_user(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    auth_headers: Login,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_a = await make_user(db_session)
    user_b = await make_user(db_session)
    headers_a = await auth_headers(user_a.email)
    headers_b = await auth_headers(user_b.email)
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 3)

    for _ in range(3):
        assert (await client.get("/api/v1/orgs", headers=headers_a)).status_code == 200
    assert (await client.get("/api/v1/orgs", headers=headers_a)).status_code == 429

    # A different user has an untouched window.
    assert (await client.get("/api/v1/orgs", headers=headers_b)).status_code == 200


async def test_api_keys_get_their_own_window(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    auth_headers: Login,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    headers = await auth_headers(owner.email)
    _, token = await make_key(client, org.slug, headers, ["incident:view"])
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 3)

    url = f"/api/v1/orgs/{org.slug}/incidents"
    # The user's window already holds the key-creation call; walk it to the
    # edge and confirm it closes.
    statuses = []
    for _ in range(4):
        statuses.append((await client.get(url, headers=headers)).status_code)
    assert 200 in statuses
    assert statuses[-1] == 429

    # The key's window is separate from the user's.
    assert (await client.get(url, headers=key_headers(token))).status_code == 200


async def test_access_log_carries_request_id_and_scrubs_tokens(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="incident_desk.access"):
        response = await client.get("/health", params={"token": "super-secret-value"})
    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert request_id in joined
    assert "super-secret-value" not in joined
    assert "token=%5Bredacted%5D" in joined or "[redacted]" in joined
