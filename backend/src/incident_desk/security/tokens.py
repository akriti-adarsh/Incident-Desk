"""Opaque token primitives.

Tokens handed to users (email verification, password reset, refresh tokens,
API key secrets) are random values; the database stores only a SHA-256 digest,
so a database leak does not leak usable credentials. SHA-256 without a work
factor is appropriate here because the inputs are 256-bit random values, not
human-chosen passwords.
"""

import hashlib
import hmac
import secrets


def generate_token(num_bytes: int = 32) -> str:
    return secrets.token_urlsafe(num_bytes)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tokens_match(stored_hash: str, candidate_raw: str) -> bool:
    return hmac.compare_digest(stored_hash, hash_token(candidate_raw))
