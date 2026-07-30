# CLAUDE.md — standing rules and state
The spec is docs/BUILD_SPEC.md. This file is rules and state; the spec defines the work.

## Rules — non-negotiable
1. No TODO, FIXME, NotImplementedError, or stub bodies anywhere in src/. Ever.
2. Dependency versions come from the resolver (`uv add` / `npm install`); commit the lockfile.
   Never hand-type a version number the resolver has not produced.
3. Nothing is "done" until its command has run in THIS session with the real output shown —
   the actual pytest summary line, the actual exit status. "Should pass" is not a status.
4. Every number in a README or doc must exist in a committed artifact (eval_results/,
   benchmarks/results/, a CI log). An estimated or remembered number is a defect.
5. When a library, API, or dataset differs from the spec — renamed function, changed endpoint,
   auth now required — adapt to reality and add one line to DEVIATIONS.md
   (spec said / reality is / what was done). Never mock a real path to fake compliance.
6. Never weaken, skip, or delete a test to make it pass. Fix the code or flag the conflict.
7. One commit per plan milestone; the full test suite runs green before every commit.
8. If the next milestone will not fit in the session's remaining capacity, stop at the last
   green commit and update State. Do not start work you cannot finish.

## State (update at every commit)
- Plan position: 17 of 39. Last completed: "feat(api): optimistic concurrency and idempotency keys"
- Suite at last commit: backend "260 passed" · Coverage: 96.81% · frontend "1 passed"
- Open deviations: 0 · Next up: commits 18–20
- Notes: session B in progress. Test plumbing: per-request savepoint sessions on one
  outer connection (conftest); services use begin_nested around risky flushes;
  Base has eager_defaults=True so onupdate timestamps come back via RETURNING.
  Route enumeration via tests/route_table.py (FastAPI defers router inclusion).
- Note: coverage needs concurrency=["thread","greenlet"] or lines after awaited DB calls vanish
