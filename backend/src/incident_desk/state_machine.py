"""The incident status state machine.

The only legal paths::

    open -> acknowledged -> mitigated -> resolved -> postmortem
                        \\-> resolved (skip mitigation)

``postmortem`` is terminal. Anything else is rejected with a 409 listing the
allowed targets, and the UI only ever offers legal transitions.
"""

from incident_desk.enums import IncidentStatus

LEGAL_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.OPEN: frozenset({IncidentStatus.ACKNOWLEDGED}),
    IncidentStatus.ACKNOWLEDGED: frozenset({IncidentStatus.MITIGATED, IncidentStatus.RESOLVED}),
    IncidentStatus.MITIGATED: frozenset({IncidentStatus.RESOLVED}),
    IncidentStatus.RESOLVED: frozenset({IncidentStatus.POSTMORTEM}),
    IncidentStatus.POSTMORTEM: frozenset(),
}


def allowed_targets(status: IncidentStatus) -> frozenset[IncidentStatus]:
    return LEGAL_TRANSITIONS[status]


def is_legal(current: IncidentStatus, target: IncidentStatus) -> bool:
    return target in LEGAL_TRANSITIONS[current]
