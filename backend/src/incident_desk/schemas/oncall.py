"""On-call schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScheduleCreate(BaseModel):
    service_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    rotation: dict[str, Any] | None = Field(
        default=None, description="Free-form rotation configuration"
    )


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_id: uuid.UUID
    name: str
    rotation: dict[str, Any]
    created_at: datetime


class ShiftCreate(BaseModel):
    user_id: uuid.UUID = Field(description="Must be a member of the organisation")
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def _ends_after_start(self) -> "ShiftCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    schedule_id: uuid.UUID
    user_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime


class OnCallUserOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str


class WhoIsOnCallOut(BaseModel):
    schedule_id: uuid.UUID
    schedule_name: str
    on_call: OnCallUserOut | None = Field(description="Null when nobody is on shift right now")
