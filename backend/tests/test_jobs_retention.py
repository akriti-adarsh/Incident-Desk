"""Retention pruning: aged rows go, fresh rows stay, re-running is idempotent."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.jobs.tasks import prune_retention_now
from tests.factories import make_org, make_user


async def test_prune_removes_only_aged_rows(db_session: AsyncSession) -> None:
    settings = get_settings()
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    now = datetime.now(UTC)

    # A fresh and an aged idempotency key.
    db_session.add_all(
        [
            models.IdempotencyKey(org_id=org.id, key="fresh", status_code=201, response_body="{}"),
            models.IdempotencyKey(org_id=org.id, key="stale", status_code=201, response_body="{}"),
        ]
    )
    await db_session.flush()
    stale_cutoff = now - timedelta(hours=settings.idempotency_retention_hours + 1)
    await db_session.execute(
        update(models.IdempotencyKey)
        .where(models.IdempotencyKey.key == "stale")
        .values(created_at=stale_cutoff)
    )

    # A long-expired refresh token, and a still-valid one.
    db_session.add_all(
        [
            models.RefreshToken(
                user_id=owner.id,
                family_id=owner.id,
                token_hash="a" * 64,
                expires_at=now + timedelta(days=30),
            ),
            models.RefreshToken(
                user_id=owner.id,
                family_id=owner.id,
                token_hash="b" * 64,
                expires_at=now - timedelta(days=settings.expired_token_grace_days + 1),
            ),
        ]
    )
    # A long-aged audit entry.
    db_session.add(models.AuditLog(org_id=org.id, actor_id=owner.id, action="x", resource_type="y"))
    await db_session.flush()
    await db_session.execute(
        update(models.AuditLog).values(
            created_at=now - timedelta(days=settings.audit_retention_days + 1)
        )
    )
    await db_session.flush()

    counts = await prune_retention_now(db_session)
    assert counts["idempotency_keys"] == 1
    assert counts["refresh_tokens"] == 1
    assert counts["audit_log"] == 1

    remaining_keys = (
        await db_session.scalars(
            select(models.IdempotencyKey.key).where(models.IdempotencyKey.org_id == org.id)
        )
    ).all()
    assert list(remaining_keys) == ["fresh"]

    live_tokens = await db_session.scalar(select(func.count()).select_from(models.RefreshToken))
    assert live_tokens == 1


async def test_prune_is_idempotent(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    old = datetime.now(UTC) - timedelta(days=get_settings().audit_retention_days + 5)
    db_session.add(models.AuditLog(org_id=org.id, actor_id=owner.id, action="a", resource_type="b"))
    await db_session.flush()
    await db_session.execute(update(models.AuditLog).values(created_at=old))
    await db_session.flush()

    first = await prune_retention_now(db_session)
    assert first["audit_log"] == 1
    second = await prune_retention_now(db_session)
    assert second["audit_log"] == 0  # nothing left to prune


def test_cron_schedule_is_registered() -> None:
    from incident_desk.jobs.worker import WorkerSettings

    names = {c.name for c in WorkerSettings.cron_jobs}
    assert "cron:compute_daily_metrics" in names
    assert "cron:prune_retention" in names
