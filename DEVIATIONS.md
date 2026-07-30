# DEVIATIONS

Format per entry: spec said / reality is / what was done.

- **ARQ dead-lettering.** Spec said use a job failure hook for dead-lettering. Reality: the
  pinned arq's `func()`/`Worker` expose no `on_failure`/`on_job_failure` hook. What was done:
  each task is wrapped by `with_dead_letter` (jobs/worker.py), which catches a final-attempt
  exception (`job_try >= max_tries`), records it to the Redis set `incident_desk:dead_letter`,
  then re-raises so earlier attempts still retry normally. Proven by
  `tests/test_jobs.py::test_job_that_fails_three_times_is_dead_lettered`.
