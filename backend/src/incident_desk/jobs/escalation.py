"""Escalation policy: pure decisions on an injectable clock.

A sev1 incident that nobody acknowledges within the timeout notifies the
person on call; each further silent interval walks one step down the
configured chain. All timing decisions take ``now`` as a parameter, so tests
drive the clock instead of sleeping.

Configuration lives in the organisation's settings blob::

    {"escalation": {"ack_timeout_minutes": 15, "chain": ["<user-id>", ...]}}
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from incident_desk.enums import IncidentStatus, Severity

DEFAULT_ACK_TIMEOUT_MINUTES = 15


@dataclass(frozen=True)
class EscalationConfig:
    ack_timeout: timedelta
    chain: list[UUID]


@dataclass(frozen=True)
class EscalationDecision:
    notify_user_ids: list[UUID]
    next_level: int | None
    next_check_in: timedelta | None
    reason: str


def parse_config(org_settings: dict[str, Any]) -> EscalationConfig:
    raw = org_settings.get("escalation") or {}
    minutes = raw.get("ack_timeout_minutes", DEFAULT_ACK_TIMEOUT_MINUTES)
    try:
        timeout = timedelta(minutes=max(0, int(minutes)))
    except (TypeError, ValueError):
        timeout = timedelta(minutes=DEFAULT_ACK_TIMEOUT_MINUTES)
    chain: list[UUID] = []
    for entry in raw.get("chain", []):
        try:
            chain.append(UUID(str(entry)))
        except ValueError:
            continue
    return EscalationConfig(ack_timeout=timeout, chain=chain)


def plan(
    *,
    severity: Severity,
    status: IncidentStatus,
    acknowledged_at: datetime | None,
    started_at: datetime,
    config: EscalationConfig,
    on_call: UUID | None,
    level: int,
    now: datetime,
) -> EscalationDecision:
    """Decide what escalation level ``level`` should do at time ``now``."""
    if severity is not Severity.SEV1:
        return EscalationDecision([], None, None, "not_sev1")
    if acknowledged_at is not None or status is not IncidentStatus.OPEN:
        return EscalationDecision([], None, None, "acknowledged")

    due_at = started_at + config.ack_timeout * (level + 1)
    if now < due_at:
        return EscalationDecision([], level, due_at - now, "not_due")

    if level == 0:
        targets = [on_call] if on_call is not None else config.chain[:1]
    else:
        targets = config.chain[level - 1 : level]

    next_level = level + 1 if level < len(config.chain) else None
    next_check_in = config.ack_timeout if next_level is not None else None
    if not targets:
        return EscalationDecision([], next_level, next_check_in, "no_target")
    return EscalationDecision(list(targets), next_level, next_check_in, "notify")
