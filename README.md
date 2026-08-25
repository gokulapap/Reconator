# Reconator 3

Reconator is a result-driven reconnaissance framework for authorized security testing. It treats reconnaissance as a growing knowledge graph—not a sequence of disposable shell commands.

Every module consumes normalized assets, emits structured assets and relationships, records evidence and provenance, and can create deduplicated follow-up work. The core engine owns scope, scheduling, retries, leases, caching, safety, persistence, and observability; individual tools are replaceable capability implementations.

> Use Reconator only against assets you own or are explicitly authorized to assess. Creating a scan requires an authorization confirmation. Active modules are additionally blocked unless that confirmation is present.

## What it provides

- Canonical asset graph for domains, DNS records, URLs, IPs, CIDRs, ports, services, endpoints, parameters, JavaScript, technologies, certificates, cloud resources, repositories, organizations, ASNs, and namespaced plugin types.
- Persistent observations, evidence, source/module provenance, typed relationships, timestamps, change snapshots, and scan-to-scan comparisons.
- Dynamic task generation from discoveries, with priorities, dependencies, branching, retries, exponential backoff, cache replay, cancellation, leases, crash recovery, and per-target concurrency limits.
- Central default-deny scope engine with exact, subdomain, CIDR, URL-prefix, regex, and exclusion rules. Exclusions always win.
- Explicit direct-vs-derived scope semantics: a passive module may opt into derived infrastructure enrichment, but derived data never silently authorizes active scanning.
- Capability-oriented module registry and Python entry-point discovery (`reconator.modules`) so new implementations do not modify the scheduler.
- Passive, balanced, and active profiles plus per-scan/per-module configuration.
- FastAPI API, automation CLI, React operations UI, Prometheus metrics, structured logs, request IDs, notifications, and Sentry integration.
- Horizontally safe PostgreSQL workers using leased tasks and `FOR UPDATE SKIP LOCKED`.
- Docker Compose production topology with a migration gate, PostgreSQL, API, multiple workers, and an Nginx UI; services run non-root with dropped capabilities and read-only filesystems.

The bundled v3 modules establish the framework loop with DNS A/AAAA/CNAME/NS/MX/TXT/PTR intelligence, certificate-transparency discovery, HTTP probing and HTML surface extraction, bounded JavaScript endpoint/parameter analysis, URL modeling, bounded CIDR expansion, TCP connect discovery, and RDAP ownership enrichment. Additional tools belong behind module contracts rather than in the core.

## Architecture

```text
authorized seed + scope
         │
         ▼
  normalize / identify ───────► persistent asset graph
         │                              │
         ▼                              ▼
 capability consumers ◄──── observations + relationships
         │                              │
         ▼                              │
 priority task queue ──lease──► module execution
         ▲                              │
         └──── new normalized results ◄─┘
```

The API never executes reconnaissance itself. It creates scan state and tasks. Independent workers claim bounded work; the UI and CLI are clients of the same API. See [architecture](docs/architecture.md), [module development](docs/module-development.md), and [security model](docs/security.md).

## Quick start with Docker Compose

Requirements: Docker Engine with Compose v2.

```bash
cp .env.example .env
# Replace ADMIN_API_KEY and POSTGRES_PASSWORD in .env with long random values.
docker compose up --build -d
docker compose ps
```

Open `http://localhost:3000`, then enter `ADMIN_API_KEY` on the Settings page. API documentation is at `http://localhost:8000/docs`.

The API and UI bind to loopback by default. Put them behind an authenticated TLS reverse proxy before exposing them to a network.

Create a scan through the API:

```bash
curl --request POST http://127.0.0.1:8000/api/v1/targets \
  --header "X-API-Key: $RECONATOR_API_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "target_kind": "domain",
    "url": "authorized.example",
    "profile": "passive",
    "authorization_confirmed": true
  }'
```

`target_kind` accepts `domain`, `url`, `ip_address`, or `cidr`. The root seed creates the narrowest useful default scope. Add exclusions or explicit infrastructure inclusions through the Scope tab/API before using active modules.

Stop the stack without deleting PostgreSQL data:

```bash
docker compose down
```

## CLI

Run the client from the backend environment or container:

```bash
export RECONATOR_API_KEY='your-api-key'
python -m app.cli scan authorized.example --kind domain --profile passive --authorized --wait
python -m app.cli status 1
python -m app.cli assets 1 --kind url
python -m app.cli events 1
python -m app.cli modules
```

`--authorized` is deliberately required for `scan`. Use `--json` for automation.

## Profiles and module selection

- `passive`: public data sources and local transformations.
- `balanced`: passive work plus low-impact active discovery such as DNS and HTTP probing.
- `active`: explicitly authorized active capabilities, including bounded service discovery.

If `selected_modules` is absent, profile defaults apply. If supplied, it is an allowlist of module names or capability names. Configuration precedence is global environment → scan `defaults` → scan `modules.<module-name>`.

Example bounded module configuration:

```json
{
  "scan_config": {
    "defaults": {"user_agent": "Authorized-Research/1.0"},
    "modules": {
      "network.cidr_expand": {"max_cidr_addresses": 64},
      "network.tcp_connect": {"ports": [80, 443, 8443], "connect_timeout": 1}
    }
  }
}
```

## Important API surfaces

- `POST /api/v1/targets` and `/targets/bulk` — create authorized scans.
- `GET /api/v1/targets/{id}/assets` — canonical scan assets.
- `GET /api/v1/targets/{id}/graph` — graph nodes and typed edges.
- `GET /api/v1/targets/{id}/tasks` — task state, attempts, parents, cache hits, and errors.
- `GET /api/v1/targets/{id}/events` — execution timeline.
- `GET|POST|DELETE /api/v1/targets/{id}/scope` — inspect and reconcile policy.
- `GET /api/v1/targets/{id}/compare/{baseline}` — incremental changes.
- `GET /api/v1/knowledge/stats` and `/metrics` — operational visibility.

Production Compose protects reconnaissance reads and writes with `X-API-Key`. Health endpoints remain available for orchestration.

## Development and verification

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r backend/requirements-dev.txt
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/python -m pytest
../.venv/bin/python -m benchmarks.benchmark_core

cd ../frontend
npm ci
npm audit --audit-level=high
npm run build
```

Database changes are migration-owned:

```bash
cd backend
DATABASE_URL='postgresql+psycopg://…' alembic upgrade head
```

CI verifies lint, tests, a real PostgreSQL migration, Python/npm vulnerability audits, both service images, the Compose topology, health endpoints, reverse proxying, and protected reads.

## Extending Reconator

Implement `ReconModule`, declare a truthful `ModuleManifest`, return normalized emissions, and register an entry point in the `reconator.modules` group. Command-backed integrations receive argv elements directly; shell interpreters are rejected, process groups are timed out, and retained stdout/stderr is bounded.

Read [module-development.md](docs/module-development.md) before adding a capability. Coverage decisions and remaining high-value work are tracked in [coverage-and-roadmap.md](docs/coverage-and-roadmap.md), while [competitive-analysis.md](docs/competitive-analysis.md) explains Reconator’s architectural positioning.

## Legacy directory

The historical `modules/` scripts remain in the repository for migration reference, but the default v3 engine and production images do not execute or package them. Their raw, sequential outputs do not satisfy the framework’s scope, normalization, provenance, or isolation contracts. Port useful behavior into v3 modules and add regression fixtures before enabling it.

## License

GPL-3.0; see [LICENSE](LICENSE).
