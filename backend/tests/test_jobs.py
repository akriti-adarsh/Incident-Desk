"""Background jobs: escalation on a controllable clock, metrics rollup, dead-lettering."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.enums import IncidentStatus, Severity
from incident_desk.jobs import escalation
from incident_desk.jobs.tasks import compute_daily_metrics_for
from incident_desk.jobs.worker import DEAD_LETTER_KEY, MAX_TRIES
from tests.factories import make_incident, make_org, make_service, make_user
from tests.jobs_util import drain_jobs

BASE = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def worker_env(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the ARQ worker's own engine at the test database."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()


def _config(chain: list[str], minutes: int = 15) -> escalation.EscalationConfig:
    return escalation.parse_config({"escalation": {"ack_timeout_minutes": minutes, "chain": chain}})


def test_no_escalation_before_the_timeout() -> None:
    on_call = uuid4()
    decision = escalation.plan(
        severity=Severity.SEV1,
        status=IncidentStatus.OPEN,
        acknowledged_at=None,
        started_at=BASE,
        config=_config([]),
        on_call=on_call,
        level=0,
        now=BASE + timedelta(minutes=14),
    )
    assert decision.notify_user_ids == []
    assert decision.reason == "not_due"


def test_first_level_notifies_on_call_then_walks_the_chain() -> None:
    on_call = uuid4()
    second = uuid4()
    third = uuid4()
    config = _config([str(second), str(third)])

    level0 = escalation.plan(
        severity=Severity.SEV1,
        status=IncidentStatus.OPEN,
        acknowledged_at=None,
        started_at=BASE,
        config=config,
        on_call=on_call,
        level=0,
        now=BASE + timedelta(minutes=16),
    )
    assert level0.notify_user_ids == [on_call]
    assert level0.next_level == 1

    level1 = escalation.plan(
        severity=Severity.SEV1,
        status=IncidentStatus.OPEN,
        acknowledged_at=None,
        started_at=BASE,
        config=config,
        on_call=on_call,
        level=1,
        now=BASE + timedelta(minutes=31),
    )
    assert level1.notify_user_ids == [second]

    level2 = escalation.plan(
        severity=Severity.SEV1,
        status=IncidentStatus.OPEN,
        acknowledged_at=None,
        started_at=BASE,
        config=config,
        on_call=on_call,
        level=2,
        now=BASE + timedelta(minutes=46),
    )
    assert level2.notify_user_ids == [third]
    assert level2.next_level is None  # chain exhausted


def test_acknowledged_incident_stops_escalating() -> None:
    decision = escalation.plan(
        severity=Severity.SEV1,
        status=IncidentStatus.ACKNOWLEDGED,
        acknowledged_at=BASE + timedelta(minutes=5),
        started_at=BASE,
        config=_config([str(uuid4())]),
        on_call=uuid4(),
        level=0,
        now=BASE + timedelta(minutes=30),
    )
    assert decision.notify_user_ids == []
    assert decision.reason == "acknowledged"


def test_non_sev1_never_escalates() -> None:
    decision = escalation.plan(
        severity=Severity.SEV3,
        status=IncidentStatus.OPEN,
        acknowledged_at=None,
        started_at=BASE,
        config=_config([str(uuid4())]),
        on_call=uuid4(),
        level=0,
        now=BASE + timedelta(hours=2),
    )
    assert decision.reason == "not_sev1"


async def test_metrics_rollup_upserts_per_org(
    db_session: AsyncSession,
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    day = datetime(2026, 7, 20, tzinfo=UTC)

    a = await make_incident(db_session, org, service, owner)
    a.started_at = day + timedelta(hours=1)
    a.acknowledged_at = day + timedelta(hours=1, seconds=120)
    a.resolved_at = day + timedelta(hours=2)
    a.status = IncidentStatus.RESOLVED
    b = await make_incident(db_session, org, service, owner)
    b.started_at = day + timedelta(hours=3)
    b.acknowledged_at = day + timedelta(hours=3, seconds=240)
    await db_session.flush()

    count = await compute_daily_metrics_for(db_session, "2026-07-20")
    assert count == 1

    row = await db_session.get(models.OrgMetricsDaily, (org.id, day.date()))
    assert row is not None
    assert row.incidents_created == 2
    assert row.incidents_resolved == 1
    assert row.mtta_seconds == 180.0  # (120 + 240) / 2
    assert row.mttr_seconds == 3600.0

    # Re-running the same day updates in place rather than duplicating.
    await compute_daily_metrics_for(db_session, "2026-07-20")
    rows = (
        await db_session.scalars(
            select(models.OrgMetricsDaily).where(models.OrgMetricsDaily.org_id == org.id)
        )
    ).all()
    assert len(rows) == 1


def test_config_defaults_are_sane() -> None:
    config = escalation.parse_config({})
    assert config.ack_timeout == timedelta(minutes=15)
    assert config.chain == []
    # Garbage in the chain is dropped, not fatal.
    dirty = escalation.parse_config({"escalation": {"chain": ["not-a-uuid", str(uuid4())]}})
    assert len(dirty.chain) == 1


@pytest.mark.timeout(60)
async def test_job_that_fails_three_times_is_dead_lettered() -> None:
    """The dead-letter policy: retries 1..2 re-raise silently; the final failure
    is parked in the dead-letter set. Driven through the real wrapper against a
    real Redis, simulating arq's per-attempt ctx (job_try) across MAX_TRIES."""
    from incident_desk.jobs.tasks import always_fails
    from incident_desk.jobs.worker import with_dead_letter

    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    wrapped = with_dead_letter(always_fails)
    marker = uuid.uuid4().hex
    try:
        await redis.delete(DEAD_LETTER_KEY)
        for attempt in range(1, MAX_TRIES + 1):
            ctx = {
                "redis": redis,
                "job_id": f"job-{marker}",
                "job_try": attempt,
                "max_tries": MAX_TRIES,
            }
            with pytest.raises(RuntimeError):
                await wrapped(ctx, marker)
            dead = await redis.smembers(DEAD_LETTER_KEY)
            if attempt < MAX_TRIES:
                assert dead == set(), f"dead-lettered too early on attempt {attempt}"
            else:
                assert dead, "the exhausted job was not dead-lettered"

        entry = next(json.loads(d) for d in await redis.smembers(DEAD_LETTER_KEY))
        assert entry["attempts"] == MAX_TRIES
        assert entry["task"] == "always_fails"
        assert entry["error"] == "RuntimeError"
    finally:
        await redis.delete(DEAD_LETTER_KEY)
        await redis.aclose()


@pytest.mark.timeout(60)
async def test_worker_actually_runs_an_enqueued_job(worker_env: None) -> None:
    """The real worker (burst mode) picks up and executes a queued job."""
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job = await redis.enqueue_job("compute_daily_metrics", "2020-01-01")
        assert job is not None
        await drain_jobs()
        result = await job.result(timeout=10)
        assert result == 0  # no incidents that day, but the job ran to completion
    finally:
        await redis.aclose()


@pytest.mark.timeout(90)
async def test_escalation_job_notifies_on_call_on_the_clock(
    database_url: str, worker_env: None
) -> None:
    """The escalation task runs on the real queue and emails the on-call person.

    The 'controllable clock' is the incident's started_at: backdating it past
    the timeout makes escalation due immediately, so the test never sleeps.
    """
    from sqlalchemy import create_engine as create_sync_engine
    from sqlalchemy import delete, make_url
    from sqlalchemy.orm import Session

    from incident_desk.enums import Role
    from tests.mailpit import messages_to

    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    sync_url = make_url(database_url).set(drivername="postgresql+psycopg")
    engine = create_sync_engine(sync_url)
    suffix = uuid.uuid4().hex[:10]
    email = f"esc-{suffix}@example.com"

    with Session(engine) as s:
        user = models.User(
            email=email,
            password_hash="x",
            full_name="On Call",
            email_verified_at=datetime.now(UTC),
        )
        org = models.Organization(name="Esc Org", slug=f"esc-{suffix}")
        s.add_all([user, org])
        s.flush()
        service = models.Service(org_id=org.id, name="esc-svc")
        s.add_all(
            [
                models.Membership(user_id=user.id, org_id=org.id, role=Role.OWNER),
                models.OrganizationCounter(org_id=org.id),
                service,
            ]
        )
        s.flush()
        schedule = models.OnCallSchedule(org_id=org.id, service_id=service.id, name="p")
        s.add(schedule)
        s.flush()
        now = datetime.now(UTC)
        s.add(
            models.OnCallShift(
                schedule_id=schedule.id,
                user_id=user.id,
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=7),
            )
        )
        incident = models.Incident(
            org_id=org.id,
            service_id=service.id,
            sequence_number=1,
            title="prod is down",
            severity=Severity.SEV1,
            reported_by=user.id,
            started_at=now - timedelta(hours=1),  # already past the 15-min timeout
        )
        counter = s.get(models.OrganizationCounter, org.id)
        assert counter is not None
        counter.incident_seq = 1
        s.add(incident)
        s.flush()
        incident_id = str(incident.id)
        org_id = org.id
        s.commit()

    try:
        await redis.enqueue_job("check_escalation", incident_id, 0)
        await drain_jobs()  # escalation decides + enqueues the email
        emails_out = await messages_to(email)  # drains the send_email job too
        assert emails_out, "on-call person was not emailed"
        assert "unacknowledged" in str(emails_out[0]["Subject"])
    finally:
        with Session(engine) as s:
            s.execute(delete(models.Organization).where(models.Organization.id == org_id))
            s.execute(delete(models.User).where(models.User.email == email))
            s.commit()
        engine.dispose()
        await redis.aclose()
