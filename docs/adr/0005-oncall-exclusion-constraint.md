# ADR-0005: Overlapping on-call shifts prevented by a database exclusion constraint

## Status
Accepted.

## Context
An on-call schedule must not have two shifts covering the same moment, or the
"who is on call now" answer is ambiguous. Overlap prevention could live in
application code or in the database.

## Decision
Prevent overlaps at the database level with a Postgres exclusion constraint:

```sql
EXCLUDE USING gist (
  schedule_id WITH =,
  tstzrange(starts_at, ends_at) WITH &&
)
```

The scalar equality on `schedule_id` requires the `btree_gist` extension, which
is created in the same migration as the constraint.

## Consequences
- **No code path can create an overlap**, not the API, not a bulk import, not
  the seed script, not a future endpoint. The guarantee holds regardless of
  application bugs or race conditions.
- Application-level checking (query for overlaps, then insert) has a
  time-of-check-to-time-of-use race under concurrency: two requests both see no
  overlap and both insert. The database constraint has no such gap.
- `tstzrange` is half-open, so a shift ending at T and one starting at T touch
  but do not overlap, which is the desired behaviour for back-to-back rotations.
- Proven by `tests/test_oncall_exclusion.py`: overlapping and contained inserts
  fail; adjacent inserts and same-window inserts on a different schedule
  succeed.
- The `btree_gist` extension must be created in the migration, or a fresh
  database fails to migrate (recorded in the build spec's failure-recovery
  notes).
