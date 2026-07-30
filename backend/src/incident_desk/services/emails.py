"""Outbound email over SMTP.

In development and tests the SMTP sink is Mailpit (compose service), so sent
mail is visible in a UI and assertable through Mailpit's API. Sending is
awaited inline for now; the job-queue milestone moves delivery to a worker.
"""

from email.message import EmailMessage

import aiosmtplib

from incident_desk.config import Settings


class EmailSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        await aiosmtplib.send(
            message,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
        )

    async def send_verification_email(self, *, to: str, token: str) -> None:
        link = f"{self._settings.frontend_base_url}/verify-email?token={token}"
        await self.send(
            to=to,
            subject="Verify your email for incident-desk",
            body=(
                "Confirm this address to finish creating your incident-desk account.\n\n"
                f"Open this link within 24 hours: {link}\n\n"
                "If you did not create an account, ignore this email."
            ),
        )
