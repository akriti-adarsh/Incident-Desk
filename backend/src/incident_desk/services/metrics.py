"""Org metrics, computed in SQL (window functions), never in Python loops."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models


@dataclass(frozen=True)
class MetricsSummary:
    mtta_seconds: float | None
    mttr_seconds: float | None
    weekly_by_severity: list[dict[str, Any]]
    top_services: list[dict[str, Any]]


async def summary(
    session: AsyncSession, org: models.Organization, *, weeks: int = 12
) -> MetricsSummary:
    response_times = (
        await session.execute(
            text(
                """
                SELECT
                    avg(EXTRACT(EPOCH FROM (acknowledged_at - started_at)))
                        FILTER (WHERE acknowledged_at IS NOT NULL) AS mtta,
                    avg(EXTRACT(EPOCH FROM (resolved_at - started_at)))
                        FILTER (WHERE resolved_at IS NOT NULL) AS mttr
                FROM incidents
                WHERE org_id = :org_id
                """
            ),
            {"org_id": org.id},
        )
    ).one()

    # Weekly counts per severity plus a running total per severity:
    # the running total is the window function doing real work.
    weekly = (
        await session.execute(
            text(
                """
                WITH weekly AS (
                    SELECT
                        date_trunc('week', started_at) AS week,
                        severity,
                        count(*) AS incident_count
                    FROM incidents
                    WHERE org_id = :org_id
                      AND started_at >= now() - make_interval(weeks => :weeks)
                    GROUP BY 1, 2
                )
                SELECT
                    week,
                    severity,
                    incident_count,
                    sum(incident_count) OVER (
                        PARTITION BY severity ORDER BY week
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS cumulative_count
                FROM weekly
                ORDER BY week, severity
                """
            ),
            {"org_id": org.id, "weeks": weeks},
        )
    ).all()

    top = (
        await session.execute(
            text(
                """
                SELECT
                    s.id AS service_id,
                    s.name,
                    count(i.id) AS incident_count,
                    rank() OVER (ORDER BY count(i.id) DESC) AS rank
                FROM incidents i
                JOIN services s ON s.id = i.service_id
                WHERE i.org_id = :org_id
                GROUP BY s.id, s.name
                ORDER BY rank, s.name
                LIMIT 5
                """
            ),
            {"org_id": org.id},
        )
    ).all()

    return MetricsSummary(
        mtta_seconds=float(response_times.mtta) if response_times.mtta is not None else None,
        mttr_seconds=float(response_times.mttr) if response_times.mttr is not None else None,
        weekly_by_severity=[
            {
                "week": row.week.date().isoformat(),
                "severity": row.severity,
                "count": int(row.incident_count),
                "cumulative": int(row.cumulative_count),
            }
            for row in weekly
        ],
        top_services=[
            {
                "service_id": str(row.service_id),
                "name": row.name,
                "count": int(row.incident_count),
                "rank": int(row.rank),
            }
            for row in top
        ],
    )
