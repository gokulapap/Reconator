# Operations

## Startup

1. Copy `.env.example` to `.env` and replace all three required secrets: database password, administrative API key, and independent toolbox shared secret.
2. Run `docker compose config --quiet`.
3. Run `docker compose up --build -d`.
4. Confirm `migrate` exited zero and `db`, `api`, `worker`, `toolbox`, and `web` are healthy/running.
5. Verify `/api/v1/ready`, then enter the API key in the UI.

The migration service gates API/worker startup. Never work around a failed migration by enabling `create_all` in application startup.

The toolbox is intentionally not published on the host. Its health endpoint is checked
inside Compose. Optional Subfinder credentials belong in
`config/toolbox/subfinder-provider.yaml`, which is ignored by Git and mounted read-only.
Do not place provider keys in scan configuration, task data, or images. Subfinder runs
all configured providers by default and records per-host and per-task provider evidence;
disable `all_sources` per module only for an intentionally lower-cost pass.

DNSX active validation is bounded in the toolbox and uses automatic wildcard
filtering. Tune its module-level concurrency/QPS conservatively for the authorized
program; the broker clamps all values even when scan configuration is malformed.
The toolbox health response includes the pinned DNSX version and binary digest.

## Scaling workers

Set `WORKER_REPLICAS` or run:

```bash
docker compose up -d --scale worker=4
```

Each worker also has `MAX_CONCURRENT_TASKS`. Scale gradually while watching PostgreSQL connections, target rate limits, memory, and egress. The per-target limit applies per claim transaction across the fleet.

`TOOLBOX_MAX_CONCURRENT` is a separate fleet-local guard for heavyweight subprocesses.
Scale the toolbox only after measuring tool memory and upstream quotas. If more than one
toolbox replica is used, the shared worker URL needs an internal load balancer and rate
limits must be coordinated across replicas.

## Observability

- `/metrics`: scan/task counters, task duration, active tasks, queue depth, cache hits, assets, relationships, and HTTP metrics. When protected reads are enabled, Prometheus must send `X-API-Key`.
- JSON logs: request ID, task/worker identifiers, module failures, lease recovery, and plugin load errors.
- `/targets/{id}/events`: user-facing execution/audit timeline.
- `/knowledge/stats`: graph/observation/task cardinality.
- optional Sentry: unhandled API/worker errors.
- toolbox JSON logs and health: execution availability without exposing targets, output,
  arguments, credentials, or the shared secret.

Alert on repeated worker/toolbox restarts, readiness failures, old queued tasks, lease-expiry growth, retry/failure spikes, toolbox capacity exhaustion/timeouts, PostgreSQL saturation, output truncation, rejected emissions, and task-limit events.

## Backups and upgrades

Back up PostgreSQL before an upgrade. Test the backup restore and migration in a staging project using the same image digest. Run `alembic current` and `alembic upgrade head` through the release/migration service; deploy workers/API only after it succeeds.

Assets are global knowledge. Deleting a scan removes its task/observation history but canonical assets may remain because another scan can reference them. A future retention/garbage-collection job should delete only unreferenced nodes under explicit policy.

## Graceful shutdown and recovery

Workers stop claiming after SIGTERM and wait for in-flight thread work. Compose grants a two-minute grace period. A hard loss leaves running tasks leased; after expiry they enter retry wait or final failure based on attempts. Increasing lease duration should accompany a justified module timeout increase.

## Private targets

`ALLOW_PRIVATE_TARGETS=false` is the safe default. Internal authorized testing requires both the deployment flag and module scan configuration `allow_private_networks=true`. Isolate such a deployment from cloud metadata endpoints and unrelated internal networks with egress policy.

## Troubleshooting

- API ready fails: inspect PostgreSQL health and migration logs.
- Worker has no work: inspect target status, task `available_at`, scope events, selected capabilities, and authorization confirmation.
- Task repeatedly retries: inspect structured `error_code`, attempts, module timeout, and source quota/rate.
- Asset exists but no active work: it may be derived-only scope; add a direct rule only when authorization covers it.
- UI returns 401: set the same `ADMIN_API_KEY` in Settings or send `X-API-Key` from automation.
- Tool unavailable: the standard image intentionally includes only built-in dependencies; build a reviewed module image for additional tools.
- Toolbox unavailable: verify its health, the independent secret on both services, the
  `recon-egress` attachment, resource pressure, and pinned binary startup. The modules API
  reports toolbox-backed implementations as unavailable when it is not configured.
- Passive source is empty: many providers require credentials or apply quotas; inspect
  source metadata and install provider keys in the read-only provider file rather than
  assuming the tool failed.
