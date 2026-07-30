"""Run the real ARQ worker in burst mode: process everything ready, then stop."""

from arq.connections import RedisSettings
from arq.worker import Worker

from incident_desk.config import get_settings
from incident_desk.jobs.worker import MAX_TRIES, functions, shutdown, startup


async def drain_jobs() -> None:
    """Process every ready job with the real worker configuration.

    Uses the same wrapped functions the production worker runs (retry policy
    and dead-letter hook included). Deferred jobs (escalations scheduled for
    later) stay queued; burst mode only runs what is due now.
    """
    worker = Worker(
        functions=functions,  # type: ignore[arg-type]
        redis_settings=RedisSettings.from_dsn(get_settings().redis_url),
        on_startup=startup,
        on_shutdown=shutdown,
        burst=True,
        max_tries=MAX_TRIES,
        retry_jobs=True,
        poll_delay=0.05,
        handle_signals=False,
        log_results=False,
    )
    try:
        await worker.main()
    finally:
        # arq's close() emits a shutdown log via signal.SIGUSR1 when signals
        # are unhandled; that signal is Unix-only. Flip the flag so close()
        # skips it and still tears the pool down cleanly on every platform.
        worker._handle_signals = True
        await worker.close()
