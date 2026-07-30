"""Real-time fan-out over Redis pub/sub, plus tickets and presence.

Every app instance runs one ``RealtimeBroker``: local WebSocket subscribers
register per channel, and the broker relays messages arriving on the
corresponding Redis channels. Publishing always goes through Redis, so an
event raised on one instance reaches sockets held by every other instance.

Auth follows the ticket design: a logged-in client POSTs for a single-use,
30-second ticket stored in Redis, connects with ``?ticket=``, and the server
consumes it atomically with GETDEL. Long-lived JWTs never enter a URL.

Presence is a Redis ZSET per incident scored by last-seen time; crashed
clients age out of the window without any cleanup code running.
"""

import asyncio
import contextlib
import json
import time
import uuid
from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger("incident_desk.realtime")

TICKET_TTL_SECONDS = 30
PRESENCE_WINDOW_SECONDS = 45
CHANNEL_PREFIX = "rt"


async def issue_ticket(redis: Redis, user_id: uuid.UUID) -> str:
    ticket = uuid.uuid4().hex + uuid.uuid4().hex
    await redis.setex(f"ws:ticket:{ticket}", TICKET_TTL_SECONDS, str(user_id))
    return ticket


async def consume_ticket(redis: Redis, ticket: str) -> uuid.UUID | None:
    """Atomically consume a ticket: replay of a used ticket finds nothing."""
    if not ticket:
        return None
    raw = await redis.getdel(f"ws:ticket:{ticket}")
    if raw is None:
        return None
    text = raw.decode() if isinstance(raw, bytes) else str(raw)
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


class RealtimeBroker:
    """Bridges Redis pub/sub to local per-connection queues."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._pubsub = redis.pubsub()
        self._local: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        # A pubsub with no subscriptions cannot listen; park it on a control
        # channel nothing publishes to.
        await self._pubsub.subscribe(f"{CHANNEL_PREFIX}:__control__")
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._pubsub.aclose()  # type: ignore[no-untyped-call]

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        await self._redis.publish(f"{CHANNEL_PREFIX}:{channel}", json.dumps(payload))

    async def add_subscriber(self, channel: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            listeners = self._local.setdefault(channel, set())
            if not listeners:
                await self._pubsub.subscribe(f"{CHANNEL_PREFIX}:{channel}")
            listeners.add(queue)

    async def remove_subscriber(self, channel: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            listeners = self._local.get(channel)
            if listeners is None:
                return
            listeners.discard(queue)
            if not listeners:
                del self._local[channel]
                await self._pubsub.unsubscribe(f"{CHANNEL_PREFIX}:{channel}")

    async def _listen(self) -> None:
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            raw_channel = message["channel"]
            channel = raw_channel.removeprefix(f"{CHANNEL_PREFIX}:")
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                logger.warning("realtime_bad_payload", channel=channel)
                continue
            for queue in self._local.get(channel, set()).copy():
                queue.put_nowait(payload)


def _presence_key(incident_id: uuid.UUID | str) -> str:
    return f"presence:incident:{incident_id}"


async def presence_touch(redis: Redis, incident_id: uuid.UUID | str, user_id: str) -> None:
    now = time.time()
    key = _presence_key(incident_id)
    await redis.zadd(key, {user_id: now})
    await redis.expire(key, PRESENCE_WINDOW_SECONDS * 4)


async def presence_leave(redis: Redis, incident_id: uuid.UUID | str, user_id: str) -> None:
    await redis.zrem(_presence_key(incident_id), user_id)


async def presence_viewers(redis: Redis, incident_id: uuid.UUID | str) -> list[str]:
    """Who is viewing now: entries older than the window fall out (crash safety)."""
    key = _presence_key(incident_id)
    await redis.zremrangebyscore(key, 0, time.time() - PRESENCE_WINDOW_SECONDS)
    return [str(member) for member in await redis.zrange(key, 0, -1)]
