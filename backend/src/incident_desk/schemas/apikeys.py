"""API key schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from incident_desk.authz import Permission


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="What this key is for")
    scopes: list[Permission] = Field(min_length=1, description="Permissions the key may exercise")
    expires_at: datetime | None = Field(default=None, description="Optional expiry")


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str = Field(description="Identifies the key in logs; not a secret")
    scopes: list[str]
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    api_key: str = Field(
        description="The full key (ik_<prefix>_<secret>). Shown exactly once; store it now."
    )
