# Architecture

## Design boundary

Reconator’s core is deliberately tool-agnostic. It owns identity, policy, work state, and history. A module owns one implementation of one capability and cannot decide global scope or lifecycle state.

```text
API / CLI / UI / automation
            │
            ▼
      scan + scope state
            │
            ▼
 module registry ── capability selection
            │
            ▼
 PostgreSQL priority task queue ◄── retries / leases / dependencies
            │
            ▼
 bounded worker pools ── module isolation ── authenticated tool plane
            │
            ▼
 parser → normalizer → validator → deduplicator → prioritizer
            │
            ▼
 assets + observations + relationships + evidence + events
            │
            └──────── result-driven task generation ───────┘
```

The API process never launches tools. Worker processes can scale independently, and every interface uses the same database-backed engine.

The web application is an operational projection of that engine rather than a second
source of truth. It uses the same paginated APIs to expose per-scan distributions,
interactive graph exploration, asset-level evidence/provenance, task ancestry and raw
bounded output, change sets, events, and centrally reconciled scope policy.

## Knowledge model

`assets` contains scan-independent canonical identities. A domain or URL is stored once even if ten sources and twenty scans observe it. `asset_observations` connects that identity to a scan, task, module, source, confidence, evidence, first/last timestamps, count, and latest source snapshot.

`asset_relationships` stores a canonical typed edge such as `resolves_to`, `has_subdomain`, `loads_script`, `exposes_endpoint`, or `owns_address`. `relationship_observations` preserves scan/task provenance for each assertion.

This separation provides:

- global deduplication without discarding source evidence;
- incremental scan comparison;
- cache replay into a new scan with explicit provenance;
- many sources agreeing on one asset or edge;
- future temporal queries without rewriting raw tool files.

Asset kinds are strings with validated built-ins and namespaced custom values. This lets plugins introduce a kind without changing a database enum or the scheduler.

## Identity and normalization

Normalization happens before persistence or scheduling. Identity is SHA-256 over `(kind, canonical_value)`, not raw text.

- Domains are lowercased, IDNA encoded, trailing-dot free, and label validated.
- URLs reject credentials and control characters, normalize host/default ports/path/query order, and drop fragments.
- IPs and CIDRs use canonical `ipaddress` forms.
- Endpoints combine a validated HTTP method with a canonical URL.
- Ports normalize to `tcp/N` or `udp/N`.
- Certificates use validated SHA fingerprints.
- Custom kinds must use a constrained lowercase namespace and receive conservative whitespace/case normalization.

Database uniqueness constraints remain the final concurrency-safe deduplication gate.

## Scheduling lifecycle

1. The API validates the target and explicit authorization confirmation.
2. The scheduler creates root scope and a `core.seed` observation.
3. The registry finds modules whose contracts consume the new asset and match the profile/allowlist.
4. The scheduler calculates a stable idempotency key and a cross-scan cache key.
5. A unique task is queued, cache-replayed, or suppressed by policy/capacity.
6. A worker claims work by priority with `FOR UPDATE SKIP LOCKED`, records a lease owner/expiry, and enforces per-target concurrency.
7. Scope and authorization are checked again immediately before execution.
8. Valid outputs are persisted; malformed individual emissions are rejected and recorded without losing valid siblings.
9. New-to-scan or materially changed assets return to step 3. Stable idempotency keys prevent duplicate work on the same entity/configuration.
10. When no unfinished task remains, the scan becomes completed, partially failed, failed, or cancelled and records its final counts/change summary.

Retries use exponential backoff and structured error codes. Expired leases become retryable work or final failures, allowing another worker to resume after a crash. Cancellation stops new claims; a module already running finishes within its timeout, refreshes cancellation state, and discards its output when cancellation was requested.

Dependencies are declared by capability in module manifests and materialized in
`task_dependencies` for the same input entity. A task remains blocked until every
predecessor succeeds or is skipped; a failed or unavailable required predecessor
suppresses the dependent task.

## Scope semantics

Scope is default-deny and evaluated by the core both when scheduling and before execution. Rules support `exact`, `subdomain`, `cidr`, `url_prefix`, and bounded safe regex matching. Exclusion matches take precedence over every inclusion.

Direct scope means the asset itself matches an inclusion. Derived scope means a directly scoped task observed related infrastructure that does not itself match an inclusion—for example an IP behind an authorized domain.

A module must explicitly declare `accepts_derived_inputs`; only non-active modules can receive derived scope. This allows passive ownership enrichment without turning a DNS answer into implicit authorization to port-scan shared infrastructure. Active work always needs a direct matching scope rule.

Scope changes call reconciliation: newly permitted observed assets generate missing tasks, while unfinished work that is no longer permitted becomes skipped. At least one inclusion must remain.

## Capability and implementation model

A manifest declares:

- stable module name and version;
- capability;
- consumed and produced asset kinds;
- local/passive/active mode;
- default profiles;
- priority, timeout, retry count, cache TTL, and rate limit;
- whether derived input is acceptable;
- implementation identity.

Users may select a concrete module or a capability. Multiple implementations may
therefore coexist, be compared, or replace one another without changing the scheduler.
Current capability selection runs matching implementations as complementary sources;
ordered preferred/fallback policy is intentionally listed as remaining work rather
than being simulated with hidden tool-specific behavior.

Python package entry points under `reconator.modules` are discovered at worker startup. A broken plugin is logged and isolated from other registrations.

## Concurrency and backpressure

Compose starts multiple worker containers; each uses a bounded thread pool. Concurrency is limited globally per worker and again per target. Module start spacing provides a database-visible per-target rate limit. Target-row serialization makes the task ceiling fleet-wide, while emission-count and JSON-size ceilings bound every structured module result.

Task claims and idempotency constraints are database-coordinated, so workers need no shared in-process state. PostgreSQL is the queue and source of truth. This keeps deployment simple while supporting horizontal workers; a future dedicated broker can be introduced behind the scheduler contract if measured database contention justifies it.

## Incremental state

Rescans link to a parent scan. Cacheable module results are replayed only within their manifest TTL and create fresh observations identifying the cache source. Scan comparisons report added, removed, changed, and unchanged canonical assets. Expensive work is avoided when module version, normalized input, and effective configuration have not changed.

## Failure domains

- A module exception fails/retries one task.
- A malformed emission is rejected individually.
- A process timeout kills its whole process group.
- Worker loss expires a lease; another worker resumes it.
- One failed plugin does not block registry startup.
- One failed task does not stop independent branches.
- API and UI failure do not stop workers already operating from PostgreSQL.
- A toolbox crash or saturated execution slot fails/retries only the requesting task.

## Isolated tool execution plane

Maintained third-party implementations run in a separate `toolbox` service instead of
inside the worker. The worker sends one typed request over an authenticated internal
HTTP interface. The service accepts only an enumerated tool name, a normalized target,
and bounded configuration fields; callers cannot submit commands, arbitrary flags, file
paths, or environment variables.

Each execution uses an argv array, minimal environment, temporary working directory,
closed stdin, bounded stdout/stderr, process-group deadline, and global semaphore. The
container is non-root and read-only with dropped capabilities, a small tmpfs, PID/CPU/
memory limits, and no database-network attachment. It has only the egress network needed
by recon implementations. Version-pinned capability adapters normalize results back into
the same graph and provenance model as native modules.

This boundary contains ordinary tool defects and hostile parser input; it is not a
security boundary against a deliberately malicious upstream binary. Every added binary
still requires version, license, supply-chain, parser, and resource review.

## Deployment topology

`docker-compose.yaml` defines PostgreSQL on an internal network, a one-shot migration gate, API, replicated workers, an isolated reconnaissance toolbox, and Nginx UI. Only API/UI loopback ports are published by default. Runtime containers are non-root, read-only, capability-free, `no-new-privileges`, bounded by memory/CPU reservations, and use named volumes only where writes are required. The toolbox is attached only to the egress network; PostgreSQL and migration services never are. Workers bridge the private control plane to the egress plane, while API and UI remain off the recon egress network.

Schema creation is never performed implicitly by API/worker startup; Alembic owns production migrations.
