"""Incident schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from incident_desk.enums import IncidentStatus, Severity


class IncidentCreate(BaseModel):
    service_id: uuid.UUID = Field(description="The affected service")
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20000, description="Markdown")
    severity: Severity = Field(description="sev1 is the most severe")
    assigned_to: uuid.UUID | None = Field(
        default=None, description="Optional assignee; must be an org member"
    )
    started_at: datetime | None = Field(
        default=None, description="When impact began; defaults to now"
    )
    tags: list[str] = Field(default_factory=list, max_length=20)


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence_number: int
    service_id: uuid.UUID
    title: str
    description: str
    severity: Severity
    status: IncidentStatus
    reported_by: uuid.UUID
    assigned_to: uuid.UUID | None
    started_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution_summary: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime

    @computed_field(description='Human-facing number, e.g. "INC-17"')  # type: ignore[prop-decorator]
    @property
    def number(self) -> str:
        return f"INC-{self.sequence_number}"
