"""Shared test plumbing.

Strategy (docs/BUILD_SPEC.md section 15, "Async SQLAlchemy + test isolation"):

- one session-scoped event loop (pytest-asyncio config in pyproject.toml)
- a fresh, fully migrated test database per test session (dropped schema,
  ``alembic upgrade head`` from scratch, so migrations are exercised on every run)
- each test runs inside an outer transaction; sessions join it via savepoints
  (``join_transaction_mode="create_savepoint"``) and the outer transaction is
  rolled back at test end, so tests never observe each other's data
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from incident_desk.config import get_settings
from incident_desk.db.engine import get_db_session

BACKEND_DIR = Path(__file__).resolve().parent.parent

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://incident:incident@localhost:55433/incident_desk_test"
)


def _sync_dsn(url: URL, database: str | None = None) -> str:
    plain = url.set(drivername="postgresql")
    if database is not None:
        plain = plain.set(database=database)
    return plain.render_as_string(hide_password=False)


def _prepare_database(async_url: str) -> None:
    """Create the test database if missing and migrate it from an empty schema."""
    url = make_url(async_url)
    assert url.database is not None
    with psycopg.connect(_sync_dsn(url, database="postgres"), autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)
        ).fetchone()
        if row is None:
            conn.execute(f'CREATE DATABASE "{url.database}"')
    with psycopg.connect(_sync_dsn(url), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")

    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    os.environ["ALEMBIC_DATABASE_URL"] = url.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    _prepare_database(url)
    return url


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
async def app(
    database_url: str, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FastAPI]:
    from incident_desk.main import create_app

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    application = create_app()
    application.dependency_overrides[get_db_session] = lambda: db_session
    async with LifespanManager(application):
        yield application
    get_settings.cache_clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
