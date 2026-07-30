"""Outbound email: message builders, SMTP transport, and the queued sender.

Message *content* is built here in one place. Delivery happens in the ARQ
worker (the ``send_email`` task) over SMTP; the API process only enqueues.
In development and CI the SMTP sink is Mailpit, so sent mail is visible in a
web UI and assertable through Mailpit's API.
"""

from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib
from arq.connections import ArqRedis

from incident_desk.config import Settings


@dataclass(frozen=True)
class EmailSpec:
    to: str
    subject: str
    body: str


def verification_email(settings: Settings, *, to: str, token: str) -> EmailSpec:
    link = f"{settings.frontend_base_url}/verify-email?token={token}"
    return EmailSpec(
        to=to,
        subject="Verify your email for incident-desk",
        body=(
            "Confirm this address to finish creating your incident-desk account.\n\n"
            f"Open this link within 24 hours: {link}\n\n"
            "If you did not create an account, ignore this email."
        ),
    )


def invitation_email(settings: Settings, *, to: str, org_name: str, token: str) -> EmailSpec:
    link = f"{settings.frontend_base_url}/accept-invite?token={token}"
    return EmailSpec(
        to=to,
        subject=f"You are invited to {org_name} on incident-desk",
        body=(
            f"You have been invited to join {org_name} on incident-desk.\n\n"
            f"Open this link within 7 days to accept: {link}\n\n"
            "If you do not have an account yet, register with this email "
            "address first, then open the link."
        ),
    )


def password_reset_email(settings: Settings, *, to: str, token: str) -> EmailSpec:
    link = f"{settings.frontend_base_url}/reset-password?token={token}"
    return EmailSpec(
        to=to,
        subject="Reset your incident-desk password",
        body=(
            "A password reset was requested for this account.\n\n"
            f"Open this link within 30 minutes to set a new password: {link}\n\n"
            "If you did not request a reset, ignore this email; your password "
            "is unchanged."
        ),
    )


def escalation_email(
    settings: Settings, *, to: str, org_name: str, incident_number: str, title: str, level: int
) -> EmailSpec:
    return EmailSpec(
        to=to,
        subject=f"[{org_name}] {incident_number} is sev1 and unacknowledged",
        body=(
            f"{incident_number} ({title}) is still unacknowledged.\n\n"
            f"You are being notified at escalation level {level}. Open "
            f"{settings.frontend_base_url} and acknowledge it, or hand it off."
        ),
    )


async def deliver(settings: Settings, spec: EmailSpec) -> None:
    """SMTP delivery; runs inside the worker."""
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = spec.to
    message["Subject"] = spec.subject
    message.set_content(spec.body)
    await aiosmtplib.send(message, hostname=settings.smtp_host, port=settings.smtp_port)


class EmailQueue:
    """What request handlers see: fire-and-forget enqueue of prepared messages."""

    def __init__(self, arq: ArqRedis, settings: Settings) -> None:
        self._arq = arq
        self._settings = settings

    async def _enqueue(self, spec: EmailSpec) -> None:
        await self._arq.enqueue_job("send_email", spec.to, spec.subject, spec.body)

    async def send_verification_email(self, *, to: str, token: str) -> None:
        await self._enqueue(verification_email(self._settings, to=to, token=token))

    async def send_invitation_email(self, *, to: str, org_name: str, token: str) -> None:
        await self._enqueue(invitation_email(self._settings, to=to, org_name=org_name, token=token))

    async def send_password_reset_email(self, *, to: str, token: str) -> None:
        await self._enqueue(password_reset_email(self._settings, to=to, token=token))
