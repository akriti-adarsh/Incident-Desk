# ADR-0004: Gapless per-organisation incident numbers

## Status
Accepted.

## Context
Incidents are referred to as `INC-1`, `INC-2`, ... per organisation. Humans
expect these to be contiguous: a gap ("where did INC-7 go?") reads as data loss.

## Decision
Each organisation has a counter row (`organization_counters`). Allocating a
number takes a `SELECT ... FOR UPDATE` lock on that row, increments it, and the
increment commits (or rolls back) in the same transaction as the incident
insert. A unique constraint on `(org_id, sequence_number)` is the backstop.

## Consequences
- **Contiguity is guaranteed.** Because the counter bump and the insert share a
  transaction, a rolled-back insert also rolls back the number, so no number is
  ever consumed without an incident. Concurrent creators serialise on the row
  lock, each getting a distinct next number.
- **Throughput trade-off.** Concurrent creates in the *same* organisation
  serialise on the lock, so create latency rises under high same-org
  concurrency (measured in [docs/performance.md](../performance.md)). This is
  the deliberate cost of contiguity.
- Proven by `tests/test_sequence_concurrency.py`: 50 simultaneous creates yield
  exactly the numbers 1..50, no duplicates, no gaps.

## Alternatives considered
- **A Postgres SEQUENCE**: faster and lock-free, but sequences skip numbers on
  rollback and are not per-tenant. Rejected because gaps violate the
  requirement.
