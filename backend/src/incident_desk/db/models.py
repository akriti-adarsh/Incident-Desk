"""Core domain schema.

Conventions enforced here and verified by ``tests/test_schema.py``:
every foreign key carries an index, every table carries timestamps, and
cross-tenant uniqueness is expressed per organisation, never globally.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from incident_desk.db.base import Base, TimestampMixin
from incident_desk.enums import IncidentStatus, Role, ServiceTier, Severity


def _enum(enum_cls: type[Any], name: str) -> Enum:
    """Non-native enum: VARCHAR plus a CHECK constraint, storing the ``.value``."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=20,
        create_constraint=True,
        values_callable=lambda e: [member.value for member in e],
    )


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, server_default="free")
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # TOTP enrolment is two-phase: a pending secret exists once enrolment
    # starts, but MFA is enforced only after the first valid code confirms it
    # (mfa_enabled_at set). mfa_last_counter records the last accepted TOTP
    # timestep so a captured code cannot be replayed inside its window.
    mfa_secret: Mapped[str | None] = mapped_column(String(100))
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_last_counter: Mapped[int | None] = mapped_column(Integer)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped to invalidate every outstanding access token for this user
    # (password reset, forced logout). Access JWTs carry the version they
    # were minted with; a mismatch is a 401.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[Role] = mapped_column(_enum(Role, "membership_role"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Service(TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    owner_team: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    tier: Mapped[ServiceTier] = mapped_column(
        _enum(ServiceTier, "service_tier"), nullable=False, server_default=ServiceTier.TIER3.value
    )


class Incident(TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("org_id", "sequence_number"),
        Index("ix_incidents_search_vector", "search_vector", postgresql_using="gin"),
        # Composite index matching the incident-list keyset query
        # (WHERE org_id = ? ORDER BY created_at DESC, id DESC). Postgres scans
        # the b-tree backwards for the DESC order, turning the per-org
        # scan-and-sort into an index range scan; see docs/performance.md.
        Index("ix_incidents_org_created_id", "org_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "incident_severity"), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        _enum(IncidentStatus, "incident_status"),
        nullable=False,
        server_default=IncidentStatus.OPEN.value,
    )
    reported_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    # Optimistic concurrency: bumped on every mutation; clients send the
    # version they saw as an If-Match ETag and conflicting writes get a 409.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # Kept in step by Postgres itself (generated column); GIN-indexed for
    # full-text search over title + description.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', title || ' ' || description)", persisted=True),
        deferred=True,
    )


class IncidentEvent(TimestampMixin, Base):
    """Append-only timeline; the source of truth for what happened on an incident."""

    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_id_seq", "incident_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Monotonic insert order. Timestamps cannot order events written in the
    # same transaction (now() is constant within one), an ordered log can.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_incident_id_seq", "incident_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Monotonic insert order; see IncidentEvent.seq for why timestamps are not enough.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)


class OnCallSchedule(TimestampMixin, Base):
    __tablename__ = "on_call_schedules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    rotation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class OnCallShift(TimestampMixin, Base):
    __tablename__ = "on_call_shifts"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="shift_ends_after_start"),
        # Database-level guarantee that two shifts on one schedule never overlap.
        # Requires btree_gist (created in the same migration as this constraint).
        ExcludeConstraint(
            (literal_column("schedule_id"), "="),
            (literal_column("tstzrange(starts_at, ends_at)"), "&&"),
            using="gist",
            name="ex_on_call_shifts_no_overlap",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("on_call_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_org_id_created_at", "org_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(400))


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(TimestampMixin, Base):
    """One link in a rotating refresh-token family.

    ``family_id`` names the lineage started at login. Rotation consumes the
    presented token and issues the next link; presenting an already-consumed
    token is treated as theft and revokes the whole family.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MfaRecoveryCode(TimestampMixin, Base):
    """Single-use fallback codes for a user who lost their authenticator."""

    __tablename__ = "mfa_recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrgInvitation(TimestampMixin, Base):
    """A pending offer of membership, delivered by email as a hashed token."""

    __tablename__ = "org_invitations"
    __table_args__ = (
        # One live invitation per address per org; accepted ones stop counting.
        Index(
            "uq_org_invitations_pending",
            "org_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "membership_role"), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailVerificationToken(TimestampMixin, Base):
    """Single-use, time-limited proof of mailbox ownership. Only the hash is stored."""

    __tablename__ = "email_verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(TimestampMixin, Base):
    """Single-use, 30-minute token proving control of the account's mailbox."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(TimestampMixin, Base):
    """Stored response for a creation request, replayed byte-for-byte on retry.

    Written in the same transaction as the created resource, so either both
    exist or neither does. Pruned after 24 hours by the retention job.
    """

    __tablename__ = "idempotency_keys"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)


class OrgMetricsDaily(TimestampMixin, Base):
    """Nightly per-org rollup so dashboards read a small table, not raw incidents."""

    __tablename__ = "org_metrics_daily"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    incidents_created: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    incidents_resolved: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    mtta_seconds: Mapped[float | None] = mapped_column(Float)
    mttr_seconds: Mapped[float | None] = mapped_column(Float)


class OrganizationCounter(TimestampMixin, Base):
    """Per-org counter row locked with ``SELECT ... FOR UPDATE`` to issue gapless
    incident sequence numbers."""

    __tablename__ = "organization_counters"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    incident_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
