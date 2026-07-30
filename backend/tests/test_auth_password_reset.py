"""Password reset: single-use tokens, and full session invalidation on reset."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from tests.factories import PASSWORD, make_user, unique_email
from tests.mailpit import extract_token, latest_message_text_to, messages_to

NEW_PASSWORD = "brand-new-secret-42"


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def request_reset_token(client: httpx.AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert response.status_code == 202
    return extract_token(await latest_message_text_to(email))


async def test_reset_flow_changes_password_and_kills_every_session(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    pair = (await login(client, user.email)).json()["data"]
    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    token = await request_reset_token(client, user.email)
    reset = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert reset.status_code == 200

    # Old password is dead; the new one works.
    assert (await login(client, user.email)).status_code == 401
    assert (await login(client, user.email, NEW_PASSWORD)).status_code == 200

    # The pre-reset refresh token is revoked.
    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}
    )
    assert refresh.status_code == 401

    # The pre-reset access token stops validating (token_version bump).
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_reset_token_is_single_use(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    token = await request_reset_token(client, user.email)

    first = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "another-secret-77"}
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "invalid_token"


async def test_expired_reset_token_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    token = await request_reset_token(client, user.email)

    await db_session.execute(
        update(models.PasswordResetToken).values(
            expires_at=datetime.now(UTC) - timedelta(minutes=1)
        )
    )
    response = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert response.status_code == 400


async def test_forgot_password_never_reveals_account_existence(
    client: httpx.AsyncClient,
) -> None:
    ghost = unique_email("ghost")
    response = await client.post("/api/v1/auth/forgot-password", json={"email": ghost})
    assert response.status_code == 202
    assert await messages_to(ghost) == []


async def test_weak_replacement_password_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    token = await request_reset_token(client, user.email)
    response = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "short1A"}
    )
    assert response.status_code == 422


async def test_reset_verifies_an_unverified_account(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Completing a reset proves mailbox ownership, which is what verification asks."""
    user = await make_user(db_session, verified=False)
    token = await request_reset_token(client, user.email)
    reset = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert reset.status_code == 200
    assert reset.json()["data"]["email_verified_at"] is not None
    assert (await login(client, user.email, NEW_PASSWORD)).status_code == 200
