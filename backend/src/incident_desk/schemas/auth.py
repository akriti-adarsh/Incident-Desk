"""Auth request/response schemas, including password strength rules."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Small denylist of passwords that satisfy the structural rules but are still
# guessable. Strength here is length + variety + not-on-this-list; the argon2
# work factor is the real defence against offline attacks.
COMMON_PASSWORDS = frozenset(
    {
        "password12", "password123", "password1234", "qwertyuiop1", "1234567890a",
        "letmein12345", "iloveyou123", "admin1234567", "welcome12345", "changeme1234",
        "sunshine1234", "monkey123456", "dragon123456", "football1234", "baseball1234",
    }
)  # fmt: skip


def validate_password_strength(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters")
    if not any(c.isalpha() for c in password):
        raise ValueError("Password must contain at least one letter")
    if not any(not c.isalpha() for c in password):
        raise ValueError("Password must contain at least one digit or symbol")
    if password.lower() in COMMON_PASSWORDS:
        raise ValueError("Password is too common; pick something less guessable")
    return password


class RegisterRequest(BaseModel):
    email: EmailStr = Field(description="Login email; a verification link is sent here")
    password: str = Field(description="At least 10 characters with letters and digits or symbols")
    full_name: str = Field(min_length=1, max_length=200, description="Displayed name")

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    avatar_url: str | None
    email_verified_at: datetime | None
    created_at: datetime


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, description="Token from the verification email")


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenPairOut(BaseModel):
    access_token: str = Field(description="JWT for the Authorization header; expires quickly")
    refresh_token: str = Field(description="Single-use token for POST /auth/refresh")
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)
