"""Aggregate router for ``/api/v1``."""

from fastapi import APIRouter

from incident_desk.api.v1 import auth

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth.router)
