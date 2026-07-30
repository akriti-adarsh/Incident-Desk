"""ARQ task functions.

Every task is idempotent by construction: emails are addressed one-shot
messages, escalation re-reads the incident's current state before acting,
the metrics rollup upserts, and the scan hook records an append-only event
keyed to a single attachment. Retries therefore never corrupt state.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Delete, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.jobs import escalation
from incident_desk.services import emails, oncall, timeline

logger = structlog.get_logger("incident_desk.jobs")


async def send_email(ctx: dict[str, Any], to: str, subject: str, body: str) -> None:
    await emails.deliver(get_settings(), emails.EmailSpec(to=to, subject=subject, body=body))


async def always_fails(ctx: dict[str, Any], marker: str) -> None:
    """A task that never succeeds. Exists to exercise retry + dead-lettering."""
    raise RuntimeError(f"always fails: {marker}")


async def check_escalation(ctx: dict[str, Any], incident_id: str, level: int) -> None:
    """One escalation step for a sev1 incident; reschedules itself as needed."""
    sessionmaker = ctx["sessionmaker"]
    settings = get_settings()
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        incident = await session.get(models.Incident, UUID(incident_id))
        if incident is None:
            return
        org = await session.get(models.Organization, incident.org_id)
        if org is None:
            return
        config = escalation.parse_config(org.settings)
        on_call_user: UUID | None = None
        entries = await oncall.who_is_on_call(session, org, service_id=incident.service_id, at=now)
        for _, user in entries:
            if user is not None:
                on_call_user = user.id
                break

        decision = escalation.plan(
            severity=incident.severity,
            status=incident.status,
            acknowledged_at=incident.acknowledged_at,
            started_at=incident.started_at,
            config=config,
            on_call=on_call_user,
            level=level,
            now=now,
        )
        logger.info(
            "escalation_step",
            incident=incident_id,
            level=level,
            reason=decision.reason,
            targets=[str(u) for u in decision.notify_user_ids],
        )

        for user_id in decision.notify_user_ids:
            user = await session.get(models.User, user_id)
            if user is None:
                continue
            spec = emails.escalation_email(
                settings,
                to=user.email,
                org_name=org.name,
                incident_number=f"INC-{incident.sequence_number}",
                title=incident.title,
                level=level,
            )
            await ctx["arq"].enqueue_job("send_email", spec.to, spec.subject, spec.body)
            await timeline.record(
                session,
                incident_id=incident.id,
                actor_id=None,
                event_type="escalation.notified",
                payload={"level": level, "user_id": str(user_id)},
            )
        await session.commit()

        if decision.next_level is not None and decision.next_check_in is not None:
            await ctx["arq"].enqueue_job(
                "check_escalation",
                incident_id,
                decision.next_level,
                _defer_by=decision.next_check_in,
            )


async def prune_retention(ctx: dict[str, Any]) -> dict[str, int]:
    """Nightly cleanup: old idempotency keys, expired auth tokens, aged audit
    entries. Idempotent: re-running only deletes what is now past its window."""
    sessionmaker = ctx["sessionmaker"]
    async with sessionmaker() as session:
        return await prune_retention_now(session)


async def prune_retention_now(session: AsyncSession) -> dict[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    token_cutoff = now - timedelta(days=settings.expired_token_grace_days)

    async def _delete(stmt: Delete) -> int:
        result = await session.execute(stmt)
        return int(result.rowcount)  # type: ignore[attr-defined]

    counts = {
        "idempotency_keys": await _delete(
            delete(models.IdempotencyKey).where(
                models.IdempotencyKey.created_at
                < now - timedelta(hours=settings.idempotency_retention_hours)
            )
        ),
        "audit_log": await _delete(
            delete(models.AuditLog).where(
                models.AuditLog.created_at < now - timedelta(days=settings.audit_retention_days)
            )
        ),
        "refresh_tokens": await _delete(
            delete(models.RefreshToken).where(models.RefreshToken.expires_at < token_cutoff)
        ),
        "reset_tokens": await _delete(
            delete(models.PasswordResetToken).where(
                models.PasswordResetToken.expires_at < token_cutoff
            )
        ),
        "verification_tokens": await _delete(
            delete(models.EmailVerificationToken).where(
                models.EmailVerificationToken.expires_at < token_cutoff
            )
        ),
    }
    await session.commit()
    logger.info("retention_pruned", **counts)
    return counts


async def scan_attachment(ctx: dict[str, Any], attachment_id: str, incident_id: str) -> None:
    """Virus-scan hook. There is no scanner wired up; this records that fact
    honestly on the timeline instead of pretending the file was checked."""
    sessionmaker = ctx["sessionmaker"]
    async with sessionmaker() as session:
        await timeline.record(
            session,
            incident_id=UUID(incident_id),
            actor_id=None,
            event_type="attachment.scan_skipped",
            payload={
                "attachment_id": attachment_id,
                "reason": "no scanner configured; hook point only",
            },
        )
        await session.commit()


async def compute_daily_metrics(ctx: dict[str, Any], day_iso: str | None = None) -> int:
    """Upsert the per-org rollup for one day (default: today, UTC)."""
    sessionmaker = ctx["sessionmaker"]
    async with sessionmaker() as session:
        return await compute_daily_metrics_for(session, day_iso)


async def compute_daily_metrics_for(session: AsyncSession, day_iso: str | None = None) -> int:
    day = datetime.fromisoformat(day_iso).date() if day_iso else datetime.now(UTC).date()
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    end = start + timedelta(days=1)

    created = (
        select(
            models.Incident.org_id,
            func.count().label("created_count"),
            func.avg(
                func.extract("epoch", models.Incident.acknowledged_at - models.Incident.started_at)
            ).label("mtta"),
        )
        .where(models.Incident.started_at >= start, models.Incident.started_at < end)
        .group_by(models.Incident.org_id)
    )
    rows = (await session.execute(created)).all()

    resolved = (
        select(
            models.Incident.org_id,
            func.count().label("resolved_count"),
            func.avg(
                func.extract("epoch", models.Incident.resolved_at - models.Incident.started_at)
            ).label("mttr"),
        )
        .where(models.Incident.resolved_at >= start, models.Incident.resolved_at < end)
        .group_by(models.Incident.org_id)
    )
    resolved_rows = {row.org_id: row for row in (await session.execute(resolved)).all()}

    org_ids = {row.org_id for row in rows} | set(resolved_rows)
    for org_id in org_ids:
        created_row = next((r for r in rows if r.org_id == org_id), None)
        resolved_row = resolved_rows.get(org_id)
        await session.execute(
            text(
                """
                INSERT INTO org_metrics_daily
                    (org_id, day, incidents_created, incidents_resolved,
                     mtta_seconds, mttr_seconds)
                VALUES (:org_id, :day, :created, :resolved, :mtta, :mttr)
                ON CONFLICT (org_id, day) DO UPDATE SET
                    incidents_created = EXCLUDED.incidents_created,
                    incidents_resolved = EXCLUDED.incidents_resolved,
                    mtta_seconds = EXCLUDED.mtta_seconds,
                    mttr_seconds = EXCLUDED.mttr_seconds,
                    updated_at = now()
                """
            ),
            {
                "org_id": org_id,
                "day": day,
                "created": int(created_row.created_count) if created_row else 0,
                "resolved": int(resolved_row.resolved_count) if resolved_row else 0,
                "mtta": float(created_row.mtta) if created_row and created_row.mtta else None,
                "mttr": (float(resolved_row.mttr) if resolved_row and resolved_row.mttr else None),
            },
        )
    await session.commit()
    return len(org_ids)
