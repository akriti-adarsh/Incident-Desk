"""Deterministic demo seed.

Creates a system that looks used, not empty: 3 organisations, 12 users with
varied cross-org roles, 8 services, 60 incidents spread over 90 days with
realistic status distributions and full event timelines, comments, on-call
schedules with shifts covering the current week, and audit history.

Deterministic under SEED. Prints a credentials table on completion. Safe to
re-run: it wipes the demo organisations and users first.

Run: ``uv run python -m scripts.seed`` (or ``scripts/seed.py``).
"""

import asyncio
import random
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.enums import IncidentStatus, Role, ServiceTier, Severity
from incident_desk.security.passwords import hash_password
from incident_desk.services import timeline

SEED = 1337
DEMO_PASSWORD = "incident-desk-demo-9"

ORGS = [
    ("Northwind Reliability", "northwind"),
    ("Helios Payments", "helios"),
    ("Atlas Logistics", "atlas"),
]

# (name, [(org_slug, role)]) — several people belong to more than one org with
# a different role in each, which is what makes the RBAC worth demonstrating.
PEOPLE = [
    ("Ada Okonkwo", "ada", [("northwind", Role.OWNER), ("helios", Role.RESPONDER)]),
    ("Bruno Sato", "bruno", [("northwind", Role.ADMIN)]),
    ("Chen Wei", "chen", [("northwind", Role.RESPONDER), ("atlas", Role.OWNER)]),
    ("Diana Iversen", "diana", [("northwind", Role.RESPONDER)]),
    ("Emeka Balogun", "emeka", [("northwind", Role.VIEWER), ("helios", Role.ADMIN)]),
    ("Farah Nasser", "farah", [("helios", Role.OWNER)]),
    ("Gabriel Rossi", "gabriel", [("helios", Role.RESPONDER)]),
    ("Hana Kim", "hana", [("helios", Role.RESPONDER), ("atlas", Role.ADMIN)]),
    ("Ivan Petrov", "ivan", [("atlas", Role.RESPONDER)]),
    ("Julia Mendes", "julia", [("atlas", Role.RESPONDER)]),
    ("Kofi Mensah", "kofi", [("atlas", Role.VIEWER)]),
    ("Lena Vogel", "lena", [("northwind", Role.ADMIN), ("atlas", Role.VIEWER)]),
]

SERVICES = [
    ("checkout-api", ServiceTier.TIER1, "payments"),
    ("auth-service", ServiceTier.TIER1, "identity"),
    ("search", ServiceTier.TIER2, "discovery"),
    ("notifications", ServiceTier.TIER3, "growth"),
    ("data-pipeline", ServiceTier.TIER2, "data"),
    ("web-frontend", ServiceTier.TIER2, "web"),
    ("mobile-gateway", ServiceTier.TIER1, "mobile"),
    ("billing-worker", ServiceTier.TIER2, "payments"),
]

INCIDENT_TITLES = [
    "Elevated 5xx from {svc}",
    "{svc} latency above SLO",
    "Database connection pool saturated on {svc}",
    "{svc} deploy rolled back after error spike",
    "Cache stampede degrading {svc}",
    "Certificate expiring for {svc}",
    "Queue backlog growing on {svc}",
    "{svc} returning stale data",
    "Timeout cascade originating in {svc}",
    "Memory leak suspected in {svc}",
]

COMMENTS = [
    "Looking into it now, checking recent deploys.",
    "Rolled back the last change, error rate is dropping.",
    "Root cause looks like a bad config push.",
    "Paging the on-call for the upstream service.",
    "Mitigated by scaling out; monitoring for recurrence.",
    "Confirmed recovery, writing up the postmortem.",
]


def now() -> datetime:
    return datetime.now(UTC)


async def wipe(session: AsyncSession) -> None:
    slugs = [slug for _, slug in ORGS]
    emails = [f"{handle}@example.com" for _, handle, _ in PEOPLE]
    await session.execute(delete(models.Organization).where(models.Organization.slug.in_(slugs)))
    await session.execute(delete(models.User).where(models.User.email.in_(emails)))
    await session.commit()


async def seed(session: AsyncSession, rng: random.Random) -> None:
    password_hash = hash_password(DEMO_PASSWORD)

    users: dict[str, models.User] = {}
    for full_name, handle, _ in PEOPLE:
        user = models.User(
            email=f"{handle}@example.com",
            password_hash=password_hash,
            full_name=full_name,
            email_verified_at=now() - timedelta(days=120),
        )
        session.add(user)
        users[handle] = user
    await session.flush()

    orgs: dict[str, models.Organization] = {}
    for name, slug in ORGS:
        org = models.Organization(name=name, slug=slug, plan="pro")
        session.add(org)
        orgs[slug] = org
    await session.flush()

    counter_rows = {slug: models.OrganizationCounter(org_id=orgs[slug].id) for slug in orgs}
    session.add_all(counter_rows.values())
    for _full, handle, memberships in PEOPLE:
        for slug, role in memberships:
            session.add(
                models.Membership(user_id=users[handle].id, org_id=orgs[slug].id, role=role)
            )
    await session.flush()

    # Services: distribute the eight across orgs.
    services: dict[str, list[models.Service]] = {slug: [] for slug in orgs}
    for i, (name, tier, team) in enumerate(SERVICES):
        slug = list(orgs)[i % len(orgs)]
        svc = models.Service(
            org_id=orgs[slug].id,
            name=name,
            owner_team=team,
            tier=tier,
            description=f"The {name} service, owned by {team}.",
        )
        session.add(svc)
        services[slug].append(svc)
    await session.flush()

    org_members: dict[str, list[UUID]] = {slug: [] for slug in orgs}
    for _full, handle, memberships in PEOPLE:
        for slug, _role in memberships:
            org_members[slug].append(users[handle].id)

    # 60 incidents over 90 days with a realistic status mix.
    counters = dict.fromkeys(orgs, 0)
    status_weights = [
        (IncidentStatus.RESOLVED, 0.45),
        (IncidentStatus.POSTMORTEM, 0.15),
        (IncidentStatus.MITIGATED, 0.1),
        (IncidentStatus.ACKNOWLEDGED, 0.15),
        (IncidentStatus.OPEN, 0.15),
    ]
    statuses = [s for s, _ in status_weights]
    weights = [w for _, w in status_weights]

    for _ in range(60):
        slug = rng.choice(list(orgs))
        org = orgs[slug]
        svc = rng.choice(services[slug])
        reporter = rng.choice(org_members[slug])
        counters[slug] += 1
        seq = counters[slug]
        started = now() - timedelta(days=rng.uniform(0, 90), hours=rng.uniform(0, 24))
        severity = rng.choices(
            [Severity.SEV1, Severity.SEV2, Severity.SEV3, Severity.SEV4],
            weights=[0.12, 0.28, 0.4, 0.2],
        )[0]
        status = rng.choices(statuses, weights=weights)[0]
        title = rng.choice(INCIDENT_TITLES).format(svc=svc.name)

        incident = models.Incident(
            org_id=org.id,
            service_id=svc.id,
            sequence_number=seq,
            title=title,
            severity=severity,
            status=status,
            reported_by=reporter,
            started_at=started,
            tags=rng.sample(["prod", "db", "latency", "deploy", "network", "cache"], k=2),
        )
        acked = status != IncidentStatus.OPEN
        if acked:
            incident.acknowledged_at = started + timedelta(minutes=rng.uniform(2, 40))
            incident.assigned_to = rng.choice(org_members[slug])
        if status in (IncidentStatus.RESOLVED, IncidentStatus.POSTMORTEM):
            incident.resolved_at = (incident.acknowledged_at or started) + timedelta(
                minutes=rng.uniform(20, 600)
            )
            incident.resolution_summary = "Mitigated and verified; follow-up tracked."
        session.add(incident)
        await session.flush()

        await timeline.record(
            session,
            incident_id=incident.id,
            actor_id=reporter,
            event_type="incident.created",
            payload={"severity": severity.value, "number": f"INC-{seq}"},
        )
        if acked:
            await timeline.record(
                session,
                incident_id=incident.id,
                actor_id=incident.assigned_to,
                event_type="status.changed",
                payload={"from": "open", "to": "acknowledged"},
            )
        for _ in range(rng.randint(0, 3)):
            author = rng.choice(org_members[slug])
            comment = models.Comment(
                incident_id=incident.id, author_id=author, body=rng.choice(COMMENTS)
            )
            session.add(comment)
            await session.flush()
            await timeline.record(
                session,
                incident_id=incident.id,
                actor_id=author,
                event_type="comment.added",
                payload={"comment_id": str(comment.id)},
            )

        session.add(
            models.AuditLog(
                org_id=org.id,
                actor_id=reporter,
                action="incident.created",
                resource_type="incident",
                resource_id=incident.id,
                after={"number": f"INC-{seq}", "severity": severity.value},
                created_at=started,
            )
        )

    # Advance each org's gapless counter past the seeded incidents, so the
    # first app-created incident continues the sequence instead of colliding.
    for slug, count in counters.items():
        counter_rows[slug].incident_seq = count

    # On-call schedules with shifts covering the current week.
    week_start = now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=now().weekday()
    )
    for slug in orgs:
        for svc in services[slug][:1]:
            schedule = models.OnCallSchedule(
                org_id=orgs[slug].id, service_id=svc.id, name="Primary on-call"
            )
            session.add(schedule)
            await session.flush()
            members = org_members[slug]
            for day in range(7):
                start = week_start + timedelta(days=day)
                session.add(
                    models.OnCallShift(
                        schedule_id=schedule.id,
                        user_id=members[day % len(members)],
                        starts_at=start,
                        ends_at=start + timedelta(days=1),
                    )
                )
    await session.commit()


def print_credentials() -> None:
    print("\n" + "=" * 66)
    print("  incident-desk demo seeded. Sign in at http://localhost:8080")
    print("=" * 66)
    print(f"  Password for every account:  {DEMO_PASSWORD}")
    print("-" * 66)
    print(f"  {'Email':<26} {'Name':<20} Orgs / role")
    print("-" * 66)
    for full_name, handle, memberships in PEOPLE:
        roles = ", ".join(f"{slug}:{role.value}" for slug, role in memberships)
        print(f"  {handle + '@example.com':<26} {full_name:<20} {roles}")
    print("-" * 66)
    print("  Suggested login: ada@example.com (owner of northwind)")
    print("  Captured email (verification, invites): http://localhost:58026")
    print("=" * 66 + "\n")


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    rng = random.Random(SEED)
    async with AsyncSession(engine) as session:
        await wipe(session)
        await seed(session, rng)
        result = await session.execute(select(models.Incident))
        count = len(result.scalars().all())
    await engine.dispose()
    print_credentials()
    print(f"  Total incidents in database: {count}")


if __name__ == "__main__":
    asyncio.run(main())
