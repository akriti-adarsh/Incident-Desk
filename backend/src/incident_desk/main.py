"""Application factory and process-level wiring."""

from fastapi import APIRouter, FastAPI

from incident_desk import __version__
from incident_desk.config import get_settings
from incident_desk.errors import register_error_handlers
from incident_desk.middleware import RequestIDMiddleware

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process is up and serving requests."""
    return {"status": "ok"}


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__)
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    return app


app = create_app()
