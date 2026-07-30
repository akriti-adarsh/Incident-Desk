"""Metrics endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.common import Data
from incident_desk.services import metrics

router = APIRouter(prefix="/orgs/{org_slug}/metrics", tags=["metrics"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
MetricsCtx = Annotated[AuthContext, Depends(require(Permission.METRICS_VIEW))]


class MetricsSummaryOut(BaseModel):
    mtta_seconds: float | None = Field(
        description="Mean time to acknowledge, in seconds; null with no acknowledged incidents"
    )
    mttr_seconds: float | None = Field(
        description="Mean time to resolve, in seconds; null with no resolved incidents"
    )
    weekly_by_severity: list[dict[str, Any]] = Field(
        description="Per-week, per-severity counts with a running total per severity"
    )
    top_services: list[dict[str, Any]] = Field(
        description="Services ranked by incident count (top 5)"
    )


@router.get(
    "/summary",
    summary="Org metrics summary",
    description=(
        "MTTA, MTTR, weekly incident counts by severity, and the most "
        "affected services. Computed in SQL."
    ),
)
async def metrics_summary(ctx: MetricsCtx, session: SessionDep) -> Data[MetricsSummaryOut]:
    result = await metrics.summary(session, ctx.org)
    return Data(
        data=MetricsSummaryOut(
            mtta_seconds=result.mtta_seconds,
            mttr_seconds=result.mttr_seconds,
            weekly_by_severity=result.weekly_by_severity,
            top_services=result.top_services,
        )
    )
