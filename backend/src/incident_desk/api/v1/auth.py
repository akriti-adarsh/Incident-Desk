"""Authentication endpoints: registration and email verification."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    TokenPairOut,
    UserOut,
    VerifyEmailRequest,
)
from incident_desk.schemas.common import Data
from incident_desk.services import auth_service, sessions
from incident_desk.services.emails import EmailSender

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_email_sender() -> EmailSender:
    return EmailSender(get_settings())


SenderDep = Annotated[EmailSender, Depends(get_email_sender)]


@router.post(
    "/register",
    status_code=201,
    summary="Create an account",
    description="Creates an unverified account and emails a verification link valid for 24 hours.",
)
async def register(
    payload: RegisterRequest, session: SessionDep, sender: SenderDep
) -> Data[UserOut]:
    user, token = await auth_service.register_user(
        session, email=payload.email, password=payload.password, full_name=payload.full_name
    )
    await session.commit()
    await sender.send_verification_email(to=user.email, token=token)
    return Data(data=UserOut.model_validate(user))


@router.post(
    "/verify-email",
    summary="Verify an email address",
    description="Consumes a verification token. Tokens are single use and expire after 24 hours.",
)
async def verify_email(payload: VerifyEmailRequest, session: SessionDep) -> Data[UserOut]:
    user = await auth_service.verify_email(session, payload.token)
    await session.commit()
    return Data(data=UserOut.model_validate(user))


@router.post(
    "/login",
    summary="Log in",
    description="Returns a 15-minute access JWT and a single-use rotating refresh token.",
)
async def login(payload: LoginRequest, session: SessionDep) -> Data[TokenPairOut]:
    user = await sessions.authenticate(session, email=payload.email, password=payload.password)
    tokens = await sessions.issue_session(session, get_settings(), user)
    await session.commit()
    return Data(
        data=TokenPairOut(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )
    )


@router.post(
    "/refresh",
    summary="Rotate the refresh token",
    description=(
        "Consumes the presented refresh token and returns a new token pair in the "
        "same family. Reusing an already-consumed token revokes the entire family."
    ),
)
async def refresh(payload: RefreshRequest, session: SessionDep) -> Data[TokenPairOut]:
    try:
        tokens = await sessions.rotate_refresh(session, get_settings(), payload.refresh_token)
    except sessions.RefreshReusedError:
        # The theft response (revoking the family) must survive the 401.
        await session.commit()
        raise
    await session.commit()
    return Data(
        data=TokenPairOut(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )
    )


@router.post(
    "/logout",
    status_code=204,
    summary="Log out",
    description="Revokes the refresh-token family of the presented token. Idempotent.",
)
async def logout(payload: LogoutRequest, session: SessionDep) -> None:
    await sessions.revoke_session(session, payload.refresh_token)
    await session.commit()


@router.post(
    "/resend-verification",
    status_code=202,
    summary="Resend the verification email",
    description=(
        "Always responds 202. If the address belongs to an unverified account, "
        "a fresh verification email is sent; the response never reveals whether "
        "an account exists."
    ),
)
async def resend_verification(
    payload: ResendVerificationRequest, session: SessionDep, sender: SenderDep
) -> Data[dict[str, str]]:
    email = auth_service.normalize_email(payload.email)
    user = await session.scalar(select(models.User).where(models.User.email == email))
    if user is not None and user.email_verified_at is None:
        token = await auth_service.issue_verification_token(session, user)
        await session.commit()
        await sender.send_verification_email(to=user.email, token=token)
    return Data(data={"status": "accepted"})
