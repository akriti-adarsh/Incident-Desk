"""TOTP MFA: enrolment, login enforcement, replay rejection, clock skew, recovery codes."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.security import totp
from tests.factories import PASSWORD, make_user


async def login(client: httpx.AsyncClient, email: str) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})


async def bearer(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    data = (await login(client, email)).json()["data"]
    return {"Authorization": f"Bearer {data['access_token']}"}


async def enroll_and_confirm(client: httpx.AsyncClient, user: models.User) -> tuple[str, list[str]]:
    """Full enrolment; returns the TOTP secret and the recovery codes."""
    headers = await bearer(client, user.email)
    started = await client.post("/api/v1/auth/mfa/enroll", headers=headers)
    assert started.status_code == 201
    secret = started.json()["data"]["secret"]
    assert secret in started.json()["data"]["otpauth_uri"]

    code = totp.code_at(secret, datetime.now(UTC))
    confirmed = await client.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=headers)
    assert confirmed.status_code == 200
    codes: list[str] = confirmed.json()["data"]["recovery_codes"]
    return secret, codes


async def challenge(client: httpx.AsyncClient, mfa_token: str, code: str) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": code}
    )


async def test_enrolment_then_login_requires_mfa(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    secret, codes = await enroll_and_confirm(client, user)
    assert len(codes) == 10
    assert all(len(c) == 9 and c[4] == "-" for c in codes)

    # Password alone no longer yields a session.
    response = await login(client, user.email)
    data = response.json()["data"]
    assert data.get("mfa_required") is True
    assert "access_token" not in data

    # A fresh code completes the login. The enrolment confirmation consumed the
    # current timestep, so step forward one period for a distinct code.
    future_code = totp.code_at(secret, datetime.now(UTC) + timedelta(seconds=30))
    completed = await challenge(client, data["mfa_token"], future_code)
    assert completed.status_code == 200
    assert "access_token" in completed.json()["data"]


async def test_wrong_code_is_rejected(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await enroll_and_confirm(client, user)
    data = (await login(client, user.email)).json()["data"]

    response = await challenge(client, data["mfa_token"], "000000")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_mfa_code"


async def test_replayed_code_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    secret, _ = await enroll_and_confirm(client, user)

    code = totp.code_at(secret, datetime.now(UTC) + timedelta(seconds=30))
    first = (await login(client, user.email)).json()["data"]
    assert (await challenge(client, first["mfa_token"], code)).status_code == 200

    # The same code presented again within its window must fail.
    second = (await login(client, user.email)).json()["data"]
    replay = await challenge(client, second["mfa_token"], code)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_mfa_code"


async def test_clock_skew_window(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    secret, _ = await enroll_and_confirm(client, user)

    # One step behind (already consumed by the enrolment confirmation), so use
    # one step ahead of that: the previous step relative to a future baseline.
    # A code from 90 seconds ago is outside the +/-1 step window and must fail.
    stale_code = totp.code_at(secret, datetime.now(UTC) - timedelta(seconds=90))
    data = (await login(client, user.email)).json()["data"]
    stale = await challenge(client, data["mfa_token"], stale_code)
    assert stale.status_code == 401

    # A code from the next step (30s of skew) is accepted.
    skewed_code = totp.code_at(secret, datetime.now(UTC) + timedelta(seconds=30))
    accepted = await challenge(client, data["mfa_token"], skewed_code)
    assert accepted.status_code == 200


async def test_recovery_code_works_once(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    _, codes = await enroll_and_confirm(client, user)
    recovery = codes[0]

    first = (await login(client, user.email)).json()["data"]
    assert (await challenge(client, first["mfa_token"], recovery)).status_code == 200

    second = (await login(client, user.email)).json()["data"]
    reused = await challenge(client, second["mfa_token"], recovery)
    assert reused.status_code == 401

    # A different, unused recovery code still works.
    assert (await challenge(client, second["mfa_token"], codes[1])).status_code == 200


async def test_enroll_twice_conflicts(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    secret, _ = await enroll_and_confirm(client, user)
    headers = await bearer_after_mfa(client, user, secret)
    response = await client.post("/api/v1/auth/mfa/enroll", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "mfa_already_enabled"


async def bearer_after_mfa(
    client: httpx.AsyncClient, user: models.User, secret: str
) -> dict[str, str]:
    data = (await login(client, user.email)).json()["data"]
    code = totp.code_at(secret, datetime.now(UTC) + timedelta(seconds=30))
    completed = await challenge(client, data["mfa_token"], code)
    assert completed.status_code == 200
    return {"Authorization": f"Bearer {completed.json()['data']['access_token']}"}


async def test_verify_without_enrolment_fails(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    headers = await bearer(client, user.email)
    response = await client.post(
        "/api/v1/auth/mfa/verify", json={"code": "123456"}, headers=headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "mfa_not_enrolled"


@pytest.mark.parametrize("path", ["/api/v1/auth/mfa/enroll", "/api/v1/auth/mfa/verify"])
async def test_mfa_endpoints_require_authentication(client: httpx.AsyncClient, path: str) -> None:
    response = await client.post(path, json={"code": "123456"})
    assert response.status_code == 401


async def test_mfa_token_cannot_be_used_as_access_token(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await enroll_and_confirm(client, user)
    data = (await login(client, user.email)).json()["data"]

    response = await client.post(
        "/api/v1/auth/mfa/enroll", headers={"Authorization": f"Bearer {data['mfa_token']}"}
    )
    assert response.status_code == 401
