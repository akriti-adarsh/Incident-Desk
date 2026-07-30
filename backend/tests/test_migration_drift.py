"""Migration integrity: up/down/up cycles cleanly, and models match migrations.

Two classic production bugs are caught here: a migration that cannot be rolled
back, and a model changed without a matching migration (autogenerate would
produce a diff). Both run on a scratch database so the main test schema is
untouched.
"""

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, make_url

from incident_desk.db import models  # noqa: F401  (registers all tables)
from incident_desk.db.base import Base
from tests.conftest import BACKEND_DIR


@pytest.fixture
def scratch_db(database_url: str) -> Iterator[str]:
    """A throwaway database for destructive migration testing."""
    url = make_url(database_url)
    name = f"drift_{uuid.uuid4().hex[:10]}"
    admin = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield url.set(drivername="postgresql+psycopg", database=name).render_as_string(
            hide_password=False
        )
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (name,),
            )
            conn.execute(f'DROP DATABASE "{name}"')


def _alembic_config(sync_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    os.environ["ALEMBIC_DATABASE_URL"] = sync_url
    return cfg


def test_upgrade_downgrade_upgrade_is_clean(scratch_db: str) -> None:
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    # If any of the three steps raised, the test would have failed already.


def test_models_match_migrations_no_autogenerate_diff(scratch_db: str) -> None:
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")

    engine = create_engine(scratch_db)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn, opts={"compare_type": True, "target_metadata": Base.metadata}
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], (
        "Models and migrations have drifted. Generate a migration with "
        f"`alembic revision --autogenerate`. Diff: {diff}"
    )
