"""Registration and email verification, asserted end to end through Mailpit."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from tests.mailpit import extract_token, latest_message_text_to, messages_to

PASSWORD = "correct-horse-battery-9"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def register(
    client: httpx.AsyncClient, email: str, password: str = PASSWORD
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )


async def test_register_verify_and_replay(client: httpx.AsyncClient) -> None:
    email = unique_email()
    response = await register(client, email)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["email"] == email
    assert data["email_verified_at"] is None

    body = await latest_message_text_to(email)
    token = extract_token(body)

    verified = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert verified.json()["data"]["email_verified_at"] is not None

    replayed = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert replayed.status_code == 400
    assert replayed.json()["error"]["code"] == "invalid_token"


async def test_register_normalizes_email_case(client: httpx.AsyncClient) -> None:
    local = f"MiXeD-{uuid.uuid4().hex[:8]}"
    response = await register(client, f"{local}@Example.COM")
    assert response.status_code == 201
    assert response.json()["data"]["email"] == f"{local.lower()}@example.com"


async def test_duplicate_email_is_a_conflict(client: httpx.AsyncClient) -> None:
    email = unique_email()
    assert (await register(client, email)).status_code == 201
    duplicate = await register(client, email)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    "weak",
    [
        "short1A",  # under 10 characters
        "alllowercaseletters",  # no digit or symbol
        "1234567890123",  # no letter
        "password123",  # on the common-password denylist
    ],
)
async def test_weak_passwords_are_rejected(client: httpx.AsyncClient, weak: str) -> None:
    response = await register(client, unique_email(), password=weak)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_unknown_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_token"


async def test_expired_token_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    email = unique_email()
    assert (await register(client, email)).status_code == 201
    token = extract_token(await latest_message_text_to(email))

    await db_session.execute(
        update(models.EmailVerificationToken).values(
            expires_at=datetime.now(UTC) - timedelta(minutes=1)
        )
    )
    response = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_token"


async def test_resend_verification_never_reveals_account_existence(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/auth/resend-verification", json={"email": unique_email("ghost")}
    )
    assert response.status_code == 202


async def test_resend_verification_sends_a_fresh_token(client: httpx.AsyncClient) -> None:
    email = unique_email()
    assert (await register(client, email)).status_code == 201
    first_token = extract_token(await latest_message_text_to(email))

    resent = await client.post("/api/v1/auth/resend-verification", json={"email": email})
    assert resent.status_code == 202
    assert len(await messages_to(email)) == 2

    second_token = extract_token(await latest_message_text_to(email))
    assert second_token != first_token

    verified = await client.post("/api/v1/auth/verify-email", json={"token": second_token})
    assert verified.status_code == 200
