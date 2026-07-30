"""Refresh-token reuse detection: the theft scenario, end to end.

The attack this defends against: an attacker steals a refresh token (network
log, backup, XSS) and uses it. Rotation means attacker and victim now race;
whichever party presents the stale token second reveals the theft, and the
server responds by killing the entire family so both copies die.
"""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from tests.factories import PASSWORD, make_user


async def login_pair(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    data: dict[str, str] = response.json()["data"]
    return data


async def rotate(client: httpx.AsyncClient, refresh_token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})


async def test_reuse_of_consumed_token_invalidates_the_entire_family(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    first = await login_pair(client, user.email)

    # Legitimate rotation: first -> second.
    second = (await rotate(client, first["refresh_token"])).json()["data"]

    # Attacker replays the consumed first token.
    replay = await rotate(client, first["refresh_token"])
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_reused"

    # The legitimate holder's current token is now dead too: the family is gone.
    victim = await rotate(client, second["refresh_token"])
    assert victim.status_code == 401
    assert victim.json()["error"]["code"] == "invalid_refresh"

    # Every token in the family is revoked in the database.
    tokens = (await db_session.execute(select(models.RefreshToken))).scalars().all()
    assert len(tokens) == 2
    assert all(t.revoked_at is not None for t in tokens)

    # Recovery is a fresh login, which starts a new, working family.
    fresh = await login_pair(client, user.email)
    assert (await rotate(client, fresh["refresh_token"])).status_code == 200


async def test_reuse_only_kills_the_affected_family(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    laptop = await login_pair(client, user.email)
    phone = await login_pair(client, user.email)

    rotated = (await rotate(client, laptop["refresh_token"])).json()["data"]
    assert (await rotate(client, laptop["refresh_token"])).status_code == 401  # reuse
    assert (await rotate(client, rotated["refresh_token"])).status_code == 401  # family dead

    # The other device's session is untouched.
    assert (await rotate(client, phone["refresh_token"])).status_code == 200


async def test_expired_refresh_token_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    pair = await login_pair(client, user.email)

    await db_session.execute(
        update(models.RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    response = await rotate(client, pair["refresh_token"])
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh"


async def test_unknown_refresh_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await rotate(client, "completely-made-up")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh"


async def test_deactivated_user_cannot_refresh(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    pair = await login_pair(client, user.email)

    user.is_active = False
    await db_session.flush()

    response = await rotate(client, pair["refresh_token"])
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh"
