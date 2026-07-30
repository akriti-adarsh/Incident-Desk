"""The per-request rate-limit dependency, attached to the whole /api/v1 router.

Keying follows the review-round rules: JWT requests are limited per user,
API-key requests per key, and only the unauthenticated auth endpoints fall
back to the client IP, with login in its own stricter bucket. Identity is
derived from the credential itself (JWT signature verified, key prefix), so
the limiter never needs a database round trip.
"""

from typing import Annotated

from fastapi import Depends, Request, Response

from incident_desk.config import get_settings
from incident_desk.errors import UnauthorizedError
from incident_desk.ratelimit import RateLimitedError, SlidingWindowLimiter
from incident_desk.security.jwt import decode_access_token

LOGIN_PATH = "/api/v1/auth/login"
AUTH_PREFIX = "/api/v1/auth/"


def _identify(request: Request) -> tuple[str, str]:
    """(kind, identity) for limiter keying; never touches the database."""
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        if token.startswith("ik_"):
            parts = token.split("_", 2)
            if len(parts) == 3 and parts[1]:
                return "key", parts[1]
        else:
            try:
                claims = decode_access_token(get_settings(), token)
            except UnauthorizedError:
                pass
            else:
                return "user", str(claims.user_id)
    client_ip = request.client.host if request.client else "unknown"
    return "ip", client_ip


async def rate_limiter(request: Request, response: Response) -> None:
    settings = get_settings()
    limiter: SlidingWindowLimiter = request.app.state.rate_limiter

    kind, identity = _identify(request)
    path = request.url.path
    if path == LOGIN_PATH:
        bucket, limit = "login", settings.rate_limit_login_per_minute
        kind, identity = "ip", (request.client.host if request.client else "unknown")
    elif path.startswith(AUTH_PREFIX) and kind == "ip":
        bucket, limit = "auth", settings.rate_limit_auth_per_minute
    else:
        bucket, limit = "api", settings.rate_limit_per_minute

    decision = await limiter.check(bucket=bucket, identity=f"{kind}:{identity}", limit=limit)
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    response.headers["X-RateLimit-Reset"] = str(decision.reset_seconds)
    if not decision.allowed:
        raise RateLimitedError(
            "Too many requests; slow down and retry",
            details={"retry_after_seconds": decision.retry_after_seconds},
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(decision.reset_seconds),
            },
        )


RateLimit = Annotated[None, Depends(rate_limiter)]
