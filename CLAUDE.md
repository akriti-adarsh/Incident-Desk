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
- Plan position: 10 of 39. Last completed: "test: exhaustive permission matrix and tenant isolation"
- Suite at last commit: backend "146 passed" · Coverage: 98.47% · frontend "1 passed"
- Open deviations: 0 · Next up: commits 11–20 (session B)
- Notes for next session: session A complete. Boundary checks done: permission matrix
  exhaustive (4 roles x 17 permissions), tenant isolation parametrised over the route
  table asserts 404 (not 403), refresh-reuse kills the family (tests/test_refresh_reuse.py).
  Route-registration guard already proves it catches missing deps
  (test_the_checker_catches_a_route_missing_auth). FastAPI defers router inclusion;
  use tests/route_table.py to enumerate routes, not app.routes directly.
- Note: coverage needs concurrency=["thread","greenlet"] or lines after awaited DB calls vanish
- Notes for next session: session A in progress
