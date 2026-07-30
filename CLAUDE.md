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
- Plan position: 33 of 39. Last completed: "feat(seed): deterministic demo data"
- Suite at last commit: backend "304 passed" · Coverage: 96.16% · frontend "25 passed"
- Open deviations: 2 · Next up: commits 34-39 (session E)
- Notes: session D complete (frontend + seed). App verified clickable against seed via browser: login, incident list (21 seeded), detail with timeline spine, org switch changes role (responder->owner) unlocking admin tabs. CORS added (SPA cross-origin). docker compose now builds api+worker+web+seed. Frontend commits consolidated (see DEVIATIONS). Session C complete (websockets+jobs). Full backend suite ~8.5min locally (argon2 + ws timeouts). Session B complete. Boundary checks: 50-way concurrent sequence test green every run; route-registration guard proves detection via a rogue route in-suite. Test plumbing: per-request savepoint sessions on one
  outer connection (conftest); services use begin_nested around risky flushes;
  Base has eager_defaults=True so onupdate timestamps come back via RETURNING.
  Route enumeration via tests/route_table.py (FastAPI defers router inclusion).
- Note: coverage needs concurrency=["thread","greenlet"] or lines after awaited DB calls vanish
