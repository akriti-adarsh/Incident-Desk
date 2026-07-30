"""TOTP (RFC 6238) helpers around pyotp.

``match_code`` returns the matched timestep counter rather than a boolean so
callers can persist it and reject replays of the same code within its window.
The window is ±1 step (30 seconds either way) to tolerate clock skew.
"""

import hmac
from datetime import datetime

import pyotp

STEP_SECONDS = 30
SKEW_STEPS = 1


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, account_name: str, issuer: str) -> str:
    """The otpauth:// URI an authenticator app enrols from (rendered as a QR code)."""
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def code_at(secret: str, at: datetime) -> str:
    return pyotp.TOTP(secret).at(at)


def match_code(secret: str, code: str, at: datetime) -> int | None:
    """Return the timestep counter the code matches, or None if it matches none.

    Checks the current step and ±SKEW_STEPS neighbours in constant-time
    comparisons.
    """
    totp = pyotp.TOTP(secret)
    counter = int(at.timestamp()) // STEP_SECONDS
    matched: int | None = None
    for offset in range(-SKEW_STEPS, SKEW_STEPS + 1):
        candidate = totp.at((counter + offset) * STEP_SECONDS)
        if hmac.compare_digest(candidate, code.strip()):
            matched = counter + offset
    return matched
