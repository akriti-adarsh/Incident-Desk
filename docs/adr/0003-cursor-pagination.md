# ADR-0003: Cursor (keyset) pagination, not offset

## Status
Accepted.

## Context
List endpoints (incidents, comments, events, audit log) need pagination. The
data changes continuously (incidents are created while someone is paging).

## Decision
All list endpoints use **cursor (keyset) pagination**. The cursor is an opaque
base64 encoding of `(sort_value, id)`. Every `ORDER BY` includes the unique row
`id` as a tiebreaker, and the next page is fetched with a row-value comparison
against the cursor.

## Consequences
- **Stability under writes.** An offset scan (`OFFSET 40 LIMIT 20`) shifts when
  rows are inserted or deleted between requests, so a client walking pages
  skips and duplicates rows. A cursor pins the position to the last row seen,
  so concurrent writes cannot corrupt the walk.
- **Performance.** Offset re-reads and discards every skipped row on each page
  (O(n) per page, O(n^2) to walk a table). A cursor is an index range scan from
  the last position. See [docs/performance.md](../performance.md) for the
  measured plan (a scan-and-sort becomes an index range scan, ~109x faster on
  50k rows).
- **The tiebreaker is not optional.** Without `id` in the ORDER BY, rows sharing
  a sort value (e.g. timestamps written in one transaction) are skipped and
  duplicated across pages. `tests/test_search_pagination.py` proves the walk is
  clean even when every row shares one `created_at`.
- The cursor is opaque; clients must treat it as a token, not parse it.
