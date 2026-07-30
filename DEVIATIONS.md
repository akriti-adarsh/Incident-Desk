# DEVIATIONS

Format per entry: spec said / reality is / what was done.

- **Frontend commit grouping.** Spec plan lists commits 26-31 as separate frontend slices. Reality:
  the single React Router route table (App.tsx) imports every page, so a commit that added one page
  without the others would not build, violating the "green before every commit" rule. What was done:
  the screens land across a few building-green commits grouped by concern (foundation+auth+list+detail,
  then realtime, then on-call+metrics+settings, then a11y+tests), each with a passing build/lint/type/test.

- **ARQ dead-lettering.** Spec said use a job failure hook for dead-lettering. Reality: the
  pinned arq's `func()`/`Worker` expose no `on_failure`/`on_job_failure` hook. What was done:
  each task is wrapped by `with_dead_letter` (jobs/worker.py), which catches a final-attempt
  exception (`job_try >= max_tries`), records it to the Redis set `incident_desk:dead_letter`,
  then re-raises so earlier attempts still retry normally. Proven by
  `tests/test_jobs.py::test_job_that_fails_three_times_is_dead_lettered`.
