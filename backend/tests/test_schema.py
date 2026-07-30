"""Schema conventions, verified by introspecting the migrated test database.

These tests run against what Alembic actually created, not against the models,
so drift between models and migrations shows up here as well as in CI.
"""

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import make_url
from sqlalchemy.engine.reflection import Inspector


@pytest.fixture(scope="session")
def inspector(database_url: str) -> Iterator[Inspector]:
    sync_url = make_url(database_url).set(drivername="postgresql+psycopg")
    engine = sa.create_engine(sync_url)
    yield sa.inspect(engine)
    engine.dispose()


def _domain_tables(inspector: Inspector) -> list[str]:
    return [t for t in inspector.get_table_names() if t != "alembic_version"]


def test_all_expected_tables_exist(inspector: Inspector) -> None:
    expected = {
        "organizations",
        "users",
        "memberships",
        "services",
        "incidents",
        "incident_events",
        "comments",
        "attachments",
        "on_call_schedules",
        "on_call_shifts",
        "audit_log",
        "api_keys",
        "organization_counters",
    }
    assert expected <= set(_domain_tables(inspector))


def test_every_foreign_key_is_indexed(inspector: Inspector) -> None:
    missing: list[str] = []
    for table in _domain_tables(inspector):
        leading: set[str] = set()
        for index in inspector.get_indexes(table):
            if index["column_names"] and index["column_names"][0] is not None:
                leading.add(index["column_names"][0])
        pk_columns = inspector.get_pk_constraint(table)["constrained_columns"]
        if pk_columns:
            leading.add(pk_columns[0])
        for unique in inspector.get_unique_constraints(table):
            if unique["column_names"]:
                leading.add(unique["column_names"][0])
        for fk in inspector.get_foreign_keys(table):
            column = fk["constrained_columns"][0]
            if column not in leading:
                missing.append(f"{table}.{column}")
    assert missing == [], f"foreign keys without a covering index: {missing}"


def test_every_table_has_timestamps(inspector: Inspector) -> None:
    missing: list[str] = []
    for table in _domain_tables(inspector):
        columns = {c["name"] for c in inspector.get_columns(table)}
        for required in ("created_at", "updated_at"):
            if required not in columns:
                missing.append(f"{table}.{required}")
    assert missing == []


def test_tenant_scoped_uniqueness(inspector: Inspector) -> None:
    """Uniqueness that matters is per-organisation, or global only where global is right."""
    org_slug = [i for i in inspector.get_indexes("organizations") if i["column_names"] == ["slug"]]
    assert org_slug and org_slug[0]["unique"]

    user_email = [i for i in inspector.get_indexes("users") if i["column_names"] == ["email"]]
    assert user_email and user_email[0]["unique"]

    incident_uniques = {
        tuple(u["column_names"]) for u in inspector.get_unique_constraints("incidents")
    }
    assert ("org_id", "sequence_number") in incident_uniques

    service_uniques = {
        tuple(u["column_names"]) for u in inspector.get_unique_constraints("services")
    }
    assert ("org_id", "name") in service_uniques
