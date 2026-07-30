"""Argon2id password hashing.

Uses argon2-cffi's current recommended profile (time_cost=3, memory_cost=64 MiB,
parallelism=4), per the spec's instruction not to hand-tune from stale advice.
Measured on the dev machine (2026-07-30): hash 135 ms, verify 173 ms.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, candidate: str) -> bool:
    try:
        _hasher.verify(password_hash, candidate)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
