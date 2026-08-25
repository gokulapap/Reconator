# Performance and capacity

Reconator favors bounded, measurable behavior over uncontrolled concurrency.

## Local baseline

The deterministic benchmark in `backend/benchmarks/benchmark_core.py` measures the two hot paths that do not require external tools or network conditions. On the development machine on 2026-08-24:

| Path | Work | Result |
|---|---:|---:|
| URL normalization/dedup identity | 100,000 inputs | 9.314 s, ~10,736/s, 0.24 MiB measured peak |
| SQLite observation persistence | 10,000 observations / 5,000 unique | 5.342 s, ~1,872 observations/s |

These are development baselines, not production SLOs. PostgreSQL latency, index cache, evidence size, module mix, network rates, and container CPU limits materially change throughput.

Run the benchmark:

```bash
cd backend
../.venv/bin/python -m benchmarks.benchmark_core
```

`tests/test_performance.py` supplies generous regression ceilings for normalization and scope evaluation. It is designed to detect accidental algorithmic degradation, not compare machines.

## Backpressure controls

- `MAX_CONCURRENT_TASKS`: worker-local pool bound.
- `MAX_CONCURRENT_TASKS_PER_TARGET`: prevents one scan monopolizing a worker fleet.
- `MAX_TASKS_PER_SCAN`: hard work-expansion ceiling.
- `MAX_ASSET_EMISSIONS_PER_TASK` / `MAX_RELATIONSHIP_EMISSIONS_PER_TASK`: structured-result ceilings.
- `MAX_EMISSION_METADATA_BYTES`: per-emission evidence/attribute JSON ceiling.
- manifest `rate_limit_per_second`: per-target/module start spacing.
- manifest timeout/retries/cache TTL: bounds slow/failing/repeated work.
- module record/body caps: bound parsing and persistence volume.
- `MAX_RAW_OUTPUT_BYTES`: retained raw evidence cap.
- container CPU/memory limits: deployment-level final boundary.

Task priority combines module priority and extensible asset-interest scoring. New/auth/API/admin/staging/change signals can therefore move useful work ahead of low-value expansion without hard-coding decisions in every module.

## Storage/index choices

Canonical uniqueness uses `(kind, identity_hash)`. Task deduplication uses `(target_id, idempotency_key)`. Claiming uses a composite status/availability/priority/creation index. Scan observations, relationship provenance, event timelines, cache keys, and lease expiry have dedicated indexes.

Assets are global and evidence is per scan/source, which prevents duplicate large nodes without losing provenance. Target relationships are lazy-loaded; list APIs use explicit paginated queries rather than loading every task with each target.

## Scaling model

Add worker replicas before increasing thread-pool size when modules are subprocess/network heavy. PostgreSQL coordinates claims, deduplication, and leases. API replicas are stateless.

Watch:

- queue depth and oldest available task age;
- running tasks vs worker capacity;
- task latency/failure/retry by module;
- PostgreSQL lock waits, connection saturation, write latency, and table/index growth;
- cache-hit ratio;
- assets/relationships/observations created per task;
- process/container CPU, RSS, disk, and egress;
- raw-output truncation and rejected-emission counts.

Only introduce a separate broker after measurements show PostgreSQL claim contention. A broker does not replace durable idempotency, graph persistence, or leases; it adds another consistency boundary.

## Next measurements

High-value production benchmarks still needed are multi-worker PostgreSQL claim contention, million-node graph pagination, cache replay fan-out, cancellation during long subprocesses, and sustained large-parser fixtures. The module contract makes tool-specific benchmarks independently addable.
