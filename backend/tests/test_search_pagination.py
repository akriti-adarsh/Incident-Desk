"""Full-text search, filters, and keyset pagination (including the collision case)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import Severity
from tests.factories import make_incident, make_org, make_service, make_user

Login = Callable[[str], Awaitable[dict[str, str]]]


async def test_full_text_search_matches_title_and_description(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    await make_incident(db_session, org, service, owner, title="Database connection pool saturated")
    noisy = await make_incident(db_session, org, service, owner, title="Frontend build broken")
    noisy.description = "The saturation of connection retries hides the real error"
    await db_session.flush()
    await make_incident(db_session, org, service, owner, title="Certificate expiring")
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents"

    # Stemming: "saturated" and "saturation" both match "saturat".
    found = await client.get(base, params={"q": "saturation"}, headers=headers)
    titles = {i["title"] for i in found.json()["data"]}
    assert titles == {"Database connection pool saturated", "Frontend build broken"}

    none = await client.get(base, params={"q": "kubernetes"}, headers=headers)
    assert none.json()["data"] == []


async def test_filters_combine(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service_a = await make_service(db_session, org)
    service_b = await make_service(db_session, org)
    sev1 = await make_incident(
        db_session, org, service_a, owner, title="big one", severity=Severity.SEV1
    )
    sev1.tags = ["db"]
    await make_incident(db_session, org, service_a, owner, severity=Severity.SEV3)
    await make_incident(db_session, org, service_b, owner, severity=Severity.SEV1)
    await db_session.flush()
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents"

    response = await client.get(
        base,
        params={"severity": "sev1", "service_id": str(service_a.id), "tag": "db"},
        headers=headers,
    )
    assert [i["title"] for i in response.json()["data"]] == ["big one"]


async def test_pagination_with_identical_timestamps_never_skips_or_repeats(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    """The classic keyset failure mode: every row shares one created_at."""
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    created = [await make_incident(db_session, org, service, owner) for _ in range(7)]
    frozen = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db_session.execute(update(models.Incident).values(created_at=frozen))
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents"

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str] = {"limit": "2"}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get(base, params=params, headers=headers)).json()
        seen.extend(i["id"] for i in page["data"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert pages < 10, "cursor loop did not terminate"

    assert len(seen) == 7
    assert len(set(seen)) == 7, "a row was skipped or duplicated across pages"
    assert {str(i.id) for i in created} == set(seen)


async def test_invalid_cursor_is_a_400(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    headers = await auth_headers(owner.email)
    response = await client.get(
        f"/api/v1/orgs/{org.slug}/incidents",
        params={"cursor": "not-a-cursor!!"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_event_and_comment_pagination(
    client: httpx.AsyncClient, db_session: AsyncSession, auth_headers: Login
) -> None:
    owner = await make_user(db_session)
    org = await make_org(db_session, owner=owner)
    service = await make_service(db_session, org)
    incident = await make_incident(db_session, org, service, owner)
    headers = await auth_headers(owner.email)
    base = f"/api/v1/orgs/{org.slug}/incidents/{incident.id}"

    for n in range(5):
        await client.post(f"{base}/comments", json={"body": f"comment {n}"}, headers=headers)

    first = (await client.get(f"{base}/comments", params={"limit": "3"}, headers=headers)).json()
    assert [c["body"] for c in first["data"]] == ["comment 0", "comment 1", "comment 2"]
    assert first["next_cursor"] is not None

    second = (
        await client.get(
            f"{base}/comments",
            params={"limit": "3", "cursor": first["next_cursor"]},
            headers=headers,
        )
    ).json()
    assert [c["body"] for c in second["data"]] == ["comment 3", "comment 4"]
    assert second["next_cursor"] is None

    # Events paginate the same way (5 comment.added events).
    events_page = (
        await client.get(f"{base}/events", params={"limit": "2"}, headers=headers)
    ).json()
    assert len(events_page["data"]) == 2
    assert events_page["next_cursor"] is not None
