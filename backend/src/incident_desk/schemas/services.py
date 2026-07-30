"""Service catalogue schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from incident_desk.enums import ServiceTier


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    owner_team: str = Field(default="", max_length=100)
    tier: ServiceTier = Field(
        default=ServiceTier.TIER3, description="tier1 is most critical, tier3 least"
    )


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    owner_team: str | None = Field(default=None, max_length=100)
    tier: ServiceTier | None = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    owner_team: str
    tier: ServiceTier
    created_at: datetime
    updated_at: datetime
