"""Aggregate router for ``/api/v1``."""

from fastapi import APIRouter

from incident_desk.api.v1 import auth, members, oncall, orgs, services

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth.router)
api_v1_router.include_router(orgs.router)
api_v1_router.include_router(members.router)
api_v1_router.include_router(members.accept_router)
api_v1_router.include_router(services.router)
api_v1_router.include_router(oncall.router)
