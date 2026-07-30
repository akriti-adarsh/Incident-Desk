"""Fifty simultaneous incident creations: numbers 1..50, no duplicates, no gaps.

Unlike the rest of the suite, this test cannot run inside the rolled-back
outer transaction: real concurrency needs real, separate database
transactions. It therefore commits its fixtures for real through the app's
own session machinery, fires 50 requests concurrently, and cleans up after
itself.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from incident_desk.db import models
from incident_desk.db.engine import get_db_session
from incident_desk.enums import Role, ServiceTier
from incident_desk.services.incidents import allocate_sequence_number
from tests.factories import PASSWORD_HASH

CREATORS = 50


@dataclass
class CommittedOrg:
    email: str = field(default="")
    slug: str = field(default="")
    user_id: uuid.UUID = field(default_factory=uuid.uuid4)
    org_id: uuid.UUID = field(default_factory=uuid.uuid4)
    service_id: uuid.UUID = field(default_factory=uuid.uuid4)


@pytest.fixture
async def committed_org(engine: AsyncEngine) -> AsyncIterator[CommittedOrg]:
    """A real, committed org + owner + service; deleted again on teardown."""
    ctx = CommittedOrg()
    ctx.email = f"conc-{uuid.uuid4().hex[:10]}@example.com"
    ctx.slug = f"conc-{uuid.uuid4().hex[:10]}"

    async with AsyncSession(engine) as session:
        user = models.User(
            email=ctx.email,
            password_hash=PASSWORD_HASH,
            full_name="Concurrent Carla",
            email_verified_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()
        org = models.Organization(name="Concurrency Org", slug=ctx.slug)
        session.add(org)
        await session.flush()
        service = models.Service(org_id=org.id, name="hot-path", tier=ServiceTier.TIER1)
        session.add_all(
            [
                models.Membership(user_id=user.id, org_id=org.id, role=Role.OWNER),
                models.OrganizationCounter(org_id=org.id),
                service,
            ]
        )
        await session.flush()
        ctx.user_id, ctx.org_id, ctx.service_id = user.id, org.id, service.id
        await session.commit()

    yield ctx

    async with AsyncSession(engine) as session:
        await session.execute(
            delete(models.Organization).where(models.Organization.id == ctx.org_id)
        )
        await session.execute(delete(models.User).where(models.User.id == ctx.user_id))
        await session.commit()


async def test_fifty_concurrent_creates_yield_gapless_numbers(
    app: FastAPI,
    client: httpx.AsyncClient,
    committed_org: CommittedOrg,
    engine: AsyncEngine,
) -> None:
    ctx = committed_org
    # Drop the test override: every request now uses the app's real session
    # factory, i.e. a genuinely separate database transaction per request.
    app.dependency_overrides.pop(get_db_session)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": ctx.email, "password": "correct-horse-battery-9"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    async def create(n: int) -> tuple[int, int]:
        response = await client.post(
            f"/api/v1/orgs/{ctx.slug}/incidents",
            json={
                "service_id": str(ctx.service_id),
                "title": f"stampede {n}",
                "severity": "sev3",
            },
            headers=headers,
        )
        return response.status_code, (
            response.json()["data"]["sequence_number"] if response.status_code == 201 else -1
        )

    results = await asyncio.gather(*(create(n) for n in range(CREATORS)))

    statuses = [status for status, _ in results]
    assert statuses == [201] * CREATORS, f"non-201 responses: {statuses}"

    numbers = sorted(number for _, number in results)
    assert numbers == list(range(1, CREATORS + 1)), "duplicates or gaps in sequence"

    # The database agrees: exactly CREATORS incidents, numbered 1..CREATORS.
    async with AsyncSession(engine) as session:
        stored = sorted(
            (
                await session.scalars(
                    select(models.Incident.sequence_number).where(
                        models.Incident.org_id == ctx.org_id
                    )
                )
            ).all()
        )
    assert stored == list(range(1, CREATORS + 1))


async def test_service_level_allocation_is_also_safe(
    committed_org: CommittedOrg, engine: AsyncEngine
) -> None:
    """Twenty direct allocations through separate sessions stay unique and dense."""
    ctx = committed_org
    start_from = 0

    async def allocate() -> int:
        async with AsyncSession(engine) as session, session.begin():
            return await allocate_sequence_number(session, ctx.org_id)

    numbers = sorted(await asyncio.gather(*(allocate() for _ in range(20))))
    assert numbers == list(range(start_from + 1, start_from + 21))
