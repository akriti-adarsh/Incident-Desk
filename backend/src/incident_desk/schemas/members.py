"""Membership and invitation schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from incident_desk.enums import Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    avatar_url: str | None
    role: Role
    joined_at: datetime


class ChangeRoleRequest(BaseModel):
    role: Role = Field(description="The member's new role in this organisation")


class InviteRequest(BaseModel):
    email: EmailStr = Field(description="Address to invite; they accept by emailed link")
    role: Role = Field(description="Role granted when the invitation is accepted")


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: Role
    expires_at: datetime
    created_at: datetime


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1, description="Token from the invitation email")


class AcceptedInvitationOut(BaseModel):
    org_slug: str
    org_name: str
    role: Role
