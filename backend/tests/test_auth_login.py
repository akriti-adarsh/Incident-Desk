"""Login, token issuance, rotation, and logout."""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.security.jwt import decode_access_token
from tests.factories import PASSWORD, make_user


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_login_returns_working_token_pair(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    response = await login(client, user.email)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900

    claims = decode_access_token(get_settings(), data["access_token"])
    assert claims.user_id == user.id

    await db_session.refresh(user)
    assert user.last_login_at is not None


async def test_wrong_password_and_unknown_email_fail_identically(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    wrong = await login(client, user.email, "not-the-password-1")
    unknown = await login(client, "nobody-here@example.com", "not-the-password-1")
    for response in (wrong, unknown):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"


async def test_unverified_email_cannot_log_in(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session, verified=False)
    response = await login(client, user.email)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "email_unverified"


async def test_inactive_user_cannot_log_in(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session, active=False)
    response = await login(client, user.email)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_refresh_rotates_the_token(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    first = (await login(client, user.email)).json()["data"]

    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert rotated.status_code == 200
    second = rotated.json()["data"]
    assert second["refresh_token"] != first["refresh_token"]

    tokens = (await db_session.execute(select(models.RefreshToken))).scalars().all()
    assert len(tokens) == 2
    consumed = [t for t in tokens if t.consumed_at is not None]
    assert len(consumed) == 1


async def test_logout_revokes_the_family(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    pair = (await login(client, user.email)).json()["data"]

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]})
    assert logout.status_code == 204

    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "invalid_refresh"


async def test_logout_with_unknown_token_is_idempotent(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": "junk"})
    assert response.status_code == 204
