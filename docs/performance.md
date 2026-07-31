# Performance

Real measurements, not estimates. Every number here was produced by a command
in this repository and can be reproduced.

- Load test: `backend/loadtest/locustfile.py`
- Index benchmark: `backend/loadtest/explain_index.py`

Measured on the development machine (single API container, single Postgres 16
container, local Docker). These are relative figures for one replica; the
architecture scales horizontally (stateless API, Redis-backed WebSocket
fan-out), so absolute throughput rises with replicas.

## Load test

`locust` drove the hot read path (incident list and search) with occasional
creates, at 10, 50, and 200 concurrent users for 25 seconds each, against the
compose stack. Rate limits were raised for the run (via
`docker-compose.perf.yml`) so the numbers measure request latency, not the
throttle. Zero failures at every level.

Command:

```bash
docker compose -f docker-compose.yml -f docker-compose.perf.yml up -d api
cd backend
uv run locust -f loadtest/locustfile.py --host http://localhost:8000 \
  --users 50 --spawn-rate 50 --run-time 25s --headless --only-summary
```

### GET /incidents (list), latency in ms

| Concurrent users | p50 | p95 | p99 | req/s | failures |
|---|---|---|---|---|---|
| 10 | 11 | 19 | 28 | 20 | 0 |
| 50 | 31 | 220 | 330 | 82 | 0 |
| 200 | 630 | 2600 | 5400 | 83 | 0 |

### POST /incidents (create), latency in ms

| Concurrent users | p50 | p95 | p99 | req/s | failures |
|---|---|---|---|---|---|
| 10 | 63 | 86 | 330 | 2 | 0 |
| 50 | 100 | 360 | 440 | 9 | 0 |
| 200 | 730 | 3300 | 4300 | 9 | 0 |

Reading the results:

- **The read path stays fast and flat** through 50 users (p95 220 ms), then
  the single API/Postgres pair saturates at 200 users. That is one replica's
  ceiling, not an architectural one.
- **Create is slower than read by design.** Gapless per-org numbering takes a
  `SELECT ... FOR UPDATE` lock on the org's counter row, so concurrent creates
  in the same organisation serialise. That is the deliberate trade for
  guaranteed contiguous `INC-n` numbers; the alternative (a sequence with
  gaps) would be faster but violate the requirement.

## Index optimisation

The incident-list query is keyset-paginated:

```sql
SELECT ... FROM incidents
WHERE org_id = ?
ORDER BY created_at DESC, id DESC
LIMIT 25;
```

Benchmarked on 50,000 incidents (a third in the target organisation), before
and after adding `ix_incidents_org_created_id (org_id, created_at, id)`.
`backend/loadtest/explain_index.py` produced the plans below.

### Before the index

```
Limit  (cost=3207.24..3207.30 rows=25 width=48) (actual time=7.406..7.410 rows=25 loops=1)
  Buffers: shared hit=1640
  ->  Sort  (cost=3207.24..3290.72 rows=33390 width=48) (actual time=7.404..7.406 rows=25 loops=1)
        Sort Key: created_at DESC, id DESC
        Sort Method: top-N heapsort  Memory: 29kB
        Buffers: shared hit=1640
        ->  Seq Scan on incidents  (cost=0.00..2265.00 rows=33390 width=48) (actual time=1.156..4.357 rows=33333 loops=1)
              Filter: (org_id = '...'::uuid)
              Rows Removed by Filter: 16667
              Buffers: shared hit=1640
Execution Time: 7.430 ms
```

A sequential scan of the whole table filtered by `org_id`, then a top-N sort:
1,640 buffers touched, **7.430 ms**.

### After the index

```
Limit  (cost=0.41..6.78 rows=25 width=48) (actual time=0.033..0.060 rows=25 loops=1)
  Buffers: shared hit=25 read=3
  ->  Index Scan Backward using ix_incidents_org_created_id on incidents  (cost=0.41..8463.81 rows=33238 width=48) (actual time=0.032..0.058 rows=25 loops=1)
        Index Cond: (org_id = '...'::uuid)
        Buffers: shared hit=25 read=3
Execution Time: 0.068 ms
```

An index range scan, walked backwards for the `DESC` order: 28 buffers, no
sort at all, **0.068 ms**.

### The improvement

| | Plan | Buffers | Execution time |
|---|---|---|---|
| Before | Seq Scan + top-N heapsort | 1640 | 7.430 ms |
| After | Index Scan Backward | 28 | 0.068 ms |

**About a 109x reduction** in execution time (7.430 ms to 0.068 ms) and a 58x
reduction in buffers read, by replacing a scan-and-sort with an index range
scan. The index (`org_id, created_at, id`) matches the query's filter and sort
exactly, including the `id` tiebreaker that keyset pagination relies on.
