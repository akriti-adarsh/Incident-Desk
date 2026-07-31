# ADR-0002: Rotating refresh-token families with theft detection

## Status
Accepted.

## Context
Login issues a short-lived access token (15 min) and a longer-lived refresh
token. Refresh tokens are the higher-value credential: if one is stolen (from a
log, a backup, an XSS payload), the thief can mint access tokens indefinitely.

## Decision
Refresh tokens rotate on every use and are grouped into a **family** (a lineage
id created at login). On refresh, the presented token is consumed and a new one
is issued in the same family. Presenting an already-consumed token is treated
as evidence of theft: the entire family is revoked and the user must log in
again. Only the SHA-256 hash of each token is stored.

## Consequences
- After a theft, the attacker and the legitimate user both hold tokens in the
  same family. Rotation means whoever presents a stale (consumed) token second
  reveals the theft; revoking the whole family kills the attacker's copy at the
  cost of one forced re-login for the victim.
- Other concurrent sessions (other families, e.g. a phone and a laptop) are
  independent and unaffected.
- Access tokens carry a `token_version`; a password reset or forced logout
  bumps it, invalidating outstanding access tokens without a database lookup on
  every request.
- The full scenario is proven in `tests/test_refresh_reuse.py`.

## Alternatives considered
- **Static refresh tokens**: simpler, but a stolen token is usable until it
  expires with no way to detect the theft. Rejected.
