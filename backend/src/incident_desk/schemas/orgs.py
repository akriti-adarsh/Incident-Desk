"""Organisation schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from incident_desk.enums import Role

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="Display name")
    slug: str = Field(
        min_length=2,
        max_length=100,
        pattern=SLUG_PATTERN,
        description="URL-safe identifier: lowercase letters, digits, hyphens",
    )


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    settings: dict[str, Any] | None = Field(default=None, description="Free-form org settings blob")


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: str
    settings: dict[str, Any]
    created_at: datetime


class OrgWithRoleOut(OrgOut):
    role: Role = Field(description="The caller's role in this organisation")
