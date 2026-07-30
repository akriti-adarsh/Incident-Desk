"""ARQ worker configuration.

Run with: ``uv run arq incident_desk.jobs.worker.WorkerSettings``

Retry policy: every task may be retried up to MAX_TRIES times. Each task is
wrapped so that a failure on the final attempt is recorded in a Redis
dead-letter set before the exception propagates, so an exhausted job is
parked for inspection rather than lost. Failures on earlier attempts still
re-raise and trigger arq's normal retry.
"""

import functools
import json
from collections.abc import Awaitable, Callable
from typing import Any

from arq.connections import RedisSettings

from incident_desk.config import get_settings
from incident_desk.db.engine import create_engine, create_sessionmaker
from incident_desk.jobs.tasks import (
    always_fails,
    check_escalation,
    compute_daily_metrics,
    scan_attachment,
    send_email,
)

MAX_TRIES = 3
DEAD_LETTER_KEY = "incident_desk:dead_letter"

Task = Callable[..., Awaitable[Any]]


def with_dead_letter(task: Task) -> Task:
    """Wrap a task so its final-attempt failure is dead-lettered, then re-raised."""

    @functools.wraps(task)
    async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return await task(ctx, *args, **kwargs)
        except Exception as exc:
            if ctx.get("job_try", 1) >= ctx.get("max_tries", MAX_TRIES):
                await ctx["redis"].sadd(
                    DEAD_LETTER_KEY,
                    json.dumps(
                        {
                            "job_id": ctx.get("job_id"),
                            "task": task.__name__,
                            "attempts": ctx.get("job_try"),
                            "error": type(exc).__name__,
                        }
                    ),
                )
            raise

    return wrapper


functions = [
    with_dead_letter(send_email),
    with_dead_letter(check_escalation),
    with_dead_letter(scan_attachment),
    with_dead_letter(compute_daily_metrics),
    with_dead_letter(always_fails),
]


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    ctx["engine"] = engine
    ctx["sessionmaker"] = create_sessionmaker(engine)
    # ctx["redis"] (the ArqRedis pool) is provided by arq itself; expose it
    # under the name tasks use for follow-up enqueues.
    ctx["arq"] = ctx["redis"]


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = functions
    on_startup = startup
    on_shutdown = shutdown
    max_tries = MAX_TRIES
    retry_jobs = True
    job_timeout = 60
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
