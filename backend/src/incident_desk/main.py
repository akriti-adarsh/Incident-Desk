"""Application factory and process-level wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk import __version__
from incident_desk.api.realtime_ws import router as ws_router
from incident_desk.api.v1.router import api_v1_router
from incident_desk.config import get_settings
from incident_desk.db.engine import create_engine, create_sessionmaker, get_db_session
from incident_desk.errors import AppError, register_error_handlers
from incident_desk.logging_setup import AccessLogMiddleware, configure_logging
from incident_desk.middleware import RequestIDMiddleware
from incident_desk.ratelimit import SlidingWindowLimiter
from incident_desk.services.realtime import RealtimeBroker


class NotReadyError(AppError):
    status_code = 503
    code = "not_ready"


health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process is up and serving requests."""
    return {"status": "ok"}


@health_router.get("/health/ready")
async def ready(session: Annotated[AsyncSession, Depends(get_db_session)]) -> dict[str, str]:
    """Readiness probe: the app can reach its database."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise NotReadyError("Database is unreachable") from exc
    return {"status": "ready"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = redis
    app.state.rate_limiter = SlidingWindowLimiter(redis, settings.rate_limit_namespace)
    broker = RealtimeBroker(redis)
    app.state.broker = broker
    await broker.start()
    try:
        yield
    finally:
        await broker.stop()
        await redis.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(json_output=settings.environment == "prod")
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_v1_router)
    app.include_router(ws_router)
    return app


app = create_app()
