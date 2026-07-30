"""Redis sliding-window rate limiting.

A true sliding window over a Redis sorted set: each request lands as a
timestamped member, old members fall out of the window, and the cardinality
is the current spend. Compared with fixed windows there is no boundary burst
(2x the limit around the reset moment).

If Redis is unreachable the limiter fails open: availability of the API wins
over strictness of the limit, and the failure is logged loudly.
"""

import time
import uuid
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from incident_desk.errors import AppError

logger = structlog.get_logger("incident_desk.ratelimit")


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after_seconds: int


class SlidingWindowLimiter:
    def __init__(self, redis: Redis, namespace: str) -> None:
        self._redis = redis
        self._namespace = namespace

    async def check(
        self, *, bucket: str, identity: str, limit: int, window_seconds: int = 60
    ) -> RateDecision:
        key = f"{self._namespace}:{bucket}:{identity}"
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.zremrangebyscore(key, 0, now - window_seconds)
            pipe.zadd(key, {member: now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds)
            _, _, count, _ = await pipe.execute()

            if int(count) > limit:
                # Over budget: this attempt does not consume the window.
                await self._redis.zrem(key, member)
                oldest = await self._redis.zrange(key, 0, 0, withscores=True)
                oldest_score = float(oldest[0][1]) if oldest else now
                retry_after = max(1, int(window_seconds - (now - oldest_score)) + 1)
                return RateDecision(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_seconds=retry_after,
                    retry_after_seconds=retry_after,
                )
            return RateDecision(
                allowed=True,
                limit=limit,
                remaining=max(0, limit - int(count)),
                reset_seconds=window_seconds,
                retry_after_seconds=0,
            )
        except RedisError:
            logger.warning("rate_limiter_unavailable", bucket=bucket)
            return RateDecision(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_seconds=window_seconds,
                retry_after_seconds=0,
            )
