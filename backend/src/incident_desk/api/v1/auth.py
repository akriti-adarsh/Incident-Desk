"""Authentication endpoints: registration and email verification."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.deps import CurrentUser
from incident_desk.config import get_settings
from incident_desk.db import models
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResult,
    LogoutRequest,
    MfaChallengeRequest,
    MfaCodeRequest,
    MfaEnrollConfirmOut,
    MfaEnrollOut,
    MfaRequiredOut,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenPairOut,
    UserOut,
    VerifyEmailRequest,
)
from incident_desk.schemas.common import Data
from incident_desk.security.jwt import create_mfa_token
from incident_desk.services import auth_service, mfa, sessions
from incident_desk.services.emails import EmailQueue

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_email_sender(request: Request) -> EmailQueue:
    return EmailQueue(request.app.state.arq, get_settings())


SenderDep = Annotated[EmailQueue, Depends(get_email_sender)]


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


def _token_pair(tokens: sessions.SessionTokens) -> TokenPairOut:
    return TokenPairOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/login",
    summary="Log in",
    description=(
        "Returns a 15-minute access JWT and a single-use rotating refresh token. "
        "Accounts with MFA enabled instead receive a short-lived mfa_token to "
        "present to /auth/mfa/challenge."
    ),
)
async def login(payload: LoginRequest, session: SessionDep) -> Data[LoginResult]:
    user = await sessions.authenticate(session, email=payload.email, password=payload.password)
    if user.mfa_enabled_at is not None:
        token = create_mfa_token(get_settings(), user_id=user.id, token_version=user.token_version)
        return Data[LoginResult](data=MfaRequiredOut(mfa_token=token))
    tokens = await sessions.issue_session(session, get_settings(), user)
    await session.commit()
    return Data[LoginResult](data=_token_pair(tokens))


@router.post(
    "/mfa/enroll",
    status_code=201,
    summary="Start MFA enrolment",
    description=(
        "Creates a pending TOTP secret. MFA is not enforced until a code from "
        "the authenticator is confirmed via /auth/mfa/verify."
    ),
)
async def mfa_enroll(user: CurrentUser, session: SessionDep) -> Data[MfaEnrollOut]:
    secret, uri = await mfa.start_enrollment(session, get_settings(), user)
    await session.commit()
    return Data(data=MfaEnrollOut(secret=secret, otpauth_uri=uri))


@router.post(
    "/mfa/verify",
    summary="Confirm MFA enrolment",
    description=(
        "Verifies the first authenticator code, enables MFA, and returns the "
        "recovery codes. They are shown exactly once."
    ),
)
async def mfa_verify(
    payload: MfaCodeRequest, user: CurrentUser, session: SessionDep
) -> Data[MfaEnrollConfirmOut]:
    codes = await mfa.confirm_enrollment(session, user, payload.code)
    await session.commit()
    return Data(data=MfaEnrollConfirmOut(recovery_codes=codes))


@router.post(
    "/mfa/challenge",
    summary="Complete an MFA login",
    description="Exchanges the mfa_token from login plus a valid code for a session.",
)
async def mfa_challenge(payload: MfaChallengeRequest, session: SessionDep) -> Data[TokenPairOut]:
    tokens = await mfa.complete_challenge(
        session, get_settings(), mfa_token=payload.mfa_token, code=payload.code
    )
    await session.commit()
    return Data(data=_token_pair(tokens))


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


@router.get(
    "/me",
    summary="The authenticated user",
    description="Returns the account behind the presented access token.",
)
async def me(user: CurrentUser) -> Data[UserOut]:
    return Data(data=UserOut.model_validate(user))


@router.post(
    "/forgot-password",
    status_code=202,
    summary="Request a password reset",
    description=(
        "Always responds 202. If the address belongs to an active account, a "
        "reset link valid for 30 minutes is emailed; the response never reveals "
        "whether an account exists."
    ),
)
async def forgot_password(
    payload: ForgotPasswordRequest, session: SessionDep, sender: SenderDep
) -> Data[dict[str, str]]:
    email = auth_service.normalize_email(payload.email)
    user = await session.scalar(select(models.User).where(models.User.email == email))
    if user is not None and user.is_active:
        token = await auth_service.issue_password_reset_token(session, user)
        await session.commit()
        await sender.send_password_reset_email(to=user.email, token=token)
    return Data(data={"status": "accepted"})


@router.post(
    "/reset-password",
    summary="Set a new password",
    description=(
        "Consumes a reset token, sets the new password, and logs the account "
        "out everywhere: refresh tokens are revoked and outstanding access "
        "tokens stop validating."
    ),
)
async def reset_password(payload: ResetPasswordRequest, session: SessionDep) -> Data[UserOut]:
    user = await auth_service.reset_password(session, payload.token, payload.password)
    await session.commit()
    return Data(data=UserOut.model_validate(user))


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
