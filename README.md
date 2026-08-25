# Reconator

Reconator helps you find and track the public parts of a web target during an approved security test. It can find names, addresses, web pages, ports, services, JavaScript files, API paths, and links between them.

Reconator runs each check as a separate task. A new result can start more useful tasks. Results are cleaned, joined, saved, and reused instead of being left as separate tool output files.

> **Use Reconator only on targets you own or have clear permission to test.** You must confirm permission when you create a scan. Reconator checks the allowed target list before it runs a task. You are still responsible for setting the correct allowed target list and safe scan limits.

## What works today

Reconator can:

- Find subdomains with Subfinder and the public certificate log service Cert Spotter.
- Check names with DNSX. It removes false results caused by catch-all DNS and reads A, AAAA, CNAME, NS, MX, TXT, CAA, and PTR records.
- Find old URLs with URLFinder.
- Check web servers with HTTPX and Reconator's built-in HTTP check.
- Record status codes, page titles, redirects, website certificate details, technologies, hosting network details, and network owner details when a tool returns them.
- Crawl allowed web pages with Katana and read links, forms, scripts, paths, and input names.
- Read JavaScript with JSLuice and Reconator's built-in parser to find likely API paths and input names.
- Find open TCP ports with Naabu connect scans and a small built-in TCP check.
- Create likely subdomain names with AlterX, then pass them to DNS checks before other work uses them.
- Match IP addresses to known content delivery, cloud, and web firewall ranges with CDNCheck.
- Look up public IP ownership records with RDAP.
- Expand small, allowed network ranges written in CIDR form. The scan setting limits how many addresses it may create.
- Save where each result came from, the supporting output, when it was found, and which scan found it.
- Show added, changed, and removed results between scans.

These tools do not run by themselves. Reconator decides when a tool may run, checks scope, limits parallel work, and changes tool output into the same result format.

## How a scan works

1. You add a target, confirm permission, and choose a scan profile.
2. Reconator creates the first tasks and puts them in the task queue.
3. Workers take ready tasks. Independent tasks can run at the same time.
4. Reconator cleans each result and removes duplicates.
5. It saves results and links. For example, a domain can link to an IP, an IP to a port, and a web page to a JavaScript file.
6. Useful new results create follow-up tasks when the profile and scope allow them.
7. Failed tasks can retry without stopping the whole scan.

The database keeps the task state. If a worker stops, another worker can take unfinished work after its task lock expires. Finished tasks are not repeated unless their saved result is too old or the input changed.

## Start with Docker Compose

You need Docker Engine with Docker Compose v2.

```bash
cp .env.example .env
```

Open `.env` and replace these three required values with different long random values:

- `ADMIN_API_KEY`
- `POSTGRES_PASSWORD`
- `TOOLBOX_SHARED_SECRET`

Do not commit your `.env` file.

Build and start Reconator:

```bash
docker compose up --build -d
docker compose ps
```

Open the web dashboard at [http://localhost:3000](http://localhost:3000). Open **Settings** and enter the value you used for `ADMIN_API_KEY`.

The API help page is at [http://localhost:8000/docs](http://localhost:8000/docs).

Stop Reconator without deleting saved database data:

```bash
docker compose down
```

The API and web dashboard listen only on your computer by default. Read [Security](docs/security.md) before making either service available on a network.

## Create a scan in the web dashboard

1. Open **Targets**.
2. Enter a domain, URL, IP address, or CIDR range.
3. Choose `passive`, `balanced`, or `active`.
4. Confirm that you have permission to test the target.
5. Start the scan.

You can also add several targets from the bulk form. Review the **Scope** tab before using active checks. Exclusion rules always win.

## Create a scan with the API

Use the same value as `ADMIN_API_KEY` in the `X-API-Key` header:

```bash
curl --request POST http://127.0.0.1:8000/api/v1/targets \
  --header 'X-API-Key: your-admin-api-key' \
  --header 'Content-Type: application/json' \
  --data '{
    "target_kind": "domain",
    "url": "authorized.example",
    "profile": "passive",
    "authorization_confirmed": true
  }'
```

`target_kind` can be `domain`, `url`, `ip_address`, or `cidr`.

Useful API paths include:

- `GET /api/v1/targets/{id}` for scan status.
- `GET /api/v1/targets/{id}/assets` for results.
- `GET /api/v1/targets/{id}/graph` for result links.
- `GET /api/v1/targets/{id}/tasks` for task status and errors.
- `GET /api/v1/targets/{id}/events` for the scan timeline.
- `GET /api/v1/targets/{id}/compare/{older_id}` for changes between scans.
- `GET /api/v1/targets/{id}/scope` for scope rules.
- `GET /api/v1/metrics` for service measurements.

## Create a scan with the CLI

The CLI talks to the same API as the web dashboard. You can run it inside the API container:

```bash
docker compose exec api python -m app.cli \
  --api-url http://127.0.0.1:8000 \
  --api-key 'your-admin-api-key' \
  scan authorized.example \
  --kind domain \
  --profile passive \
  --authorized \
  --wait
```

Other CLI commands:

```bash
docker compose exec api python -m app.cli --api-key 'your-admin-api-key' status 1
docker compose exec api python -m app.cli --api-key 'your-admin-api-key' assets 1 --kind url
docker compose exec api python -m app.cli --api-key 'your-admin-api-key' events 1
docker compose exec api python -m app.cli --api-key 'your-admin-api-key' summary 1
docker compose exec api python -m app.cli --api-key 'your-admin-api-key' modules
```

The `scan` command will not start without `--authorized`. Add `--json` before the command name when another program needs to read the output.

## Scan profiles

- `passive` uses public data services and saved data. It does not run direct web or port checks against the target by default.
- `balanced` adds lower-impact DNS, web, and JavaScript checks.
- `active` also allows crawling, port checks, and name guessing. Use it only when your permission covers that work.

You can choose named modules instead of using all modules in a profile. Scan settings can also set timeouts, port lists, page limits, and other module limits. See [Module development](docs/module-development.md) for the module rules and setting format.

## Results and history

The scan page has these views:

- **Overview** shows totals and current progress.
- **Assets** shows each found item, its source, supporting details, and score.
- **Graph** shows how found items are linked.
- **Changes** compares the scan with an older scan of the same target.
- **Tasks** shows queued, running, finished, retried, skipped, and failed work.
- **Timeline** shows scan events in time order.
- **Scope** shows what Reconator may and may not test.

Reconator keeps old results in PostgreSQL. A later scan can use saved results, avoid some repeated work, and show what changed.

## Workers and the toolbox

The Docker setup runs these services:

- `db` stores targets, tasks, results, links, and history.
- `migrate` updates the database format before the other services start.
- `api` serves the web dashboard, CLI, and other programs.
- `worker` runs scan tasks. The default setup starts two workers.
- `toolbox` contains the outside recon tools. Only workers can ask it to run a tool.
- `web` serves the dashboard and sends API requests to `api`.

Add workers when the database and machine have enough CPU, memory, and network room:

```bash
docker compose up -d --scale worker=4
```

More workers do not remove the scan limits. `MAX_CONCURRENT_TASKS`, `MAX_CONCURRENT_TASKS_PER_TARGET`, and tool limits still control load. Start with small values and raise them only after watching the target and your machine.

The toolbox image includes fixed versions of Subfinder, DNSX, URLFinder, HTTPX, Katana, Naabu, JSLuice, AlterX, and CDNCheck. The toolbox runs without root access, has a read-only file system, has no host port, and cannot reach the database network. Tool output is treated as unsafe input and is checked by the worker.

## Common settings

Edit `.env`, then restart the affected services after a change.

| Setting | What it changes |
| --- | --- |
| `API_PORT`, `WEB_PORT` | Ports used on your computer. |
| `API_BIND_ADDRESS`, `WEB_BIND_ADDRESS` | Addresses used on your computer. Keep `127.0.0.1` unless you have a safe proxy. |
| `WORKER_REPLICAS` | Number of workers started by Compose. |
| `MAX_CONCURRENT_TASKS` | Tasks one worker may run at the same time. |
| `MAX_CONCURRENT_TASKS_PER_TARGET` | Tasks one worker may run at the same time for one target. |
| `TOOLBOX_MAX_CONCURRENT` | Outside tools the toolbox may run at the same time. |
| `MAX_TASKS_PER_SCAN` | Total task limit for one scan. |
| `ALLOW_PRIVATE_TARGETS` | Allows private or local addresses when set to `true`. Leave it `false` unless your approved test needs them. |
| `PROTECT_READ_ENDPOINTS` | Requires the API key when reading results. Keep it `true` for normal use. |
| `LOG_LEVEL` | Log detail, such as `INFO` or `DEBUG`. |
| `TELEGRAM_API_KEY`, `TELEGRAM_CHAT_ID` | Optional Telegram messages. |
| `WEBHOOK_URL`, `WEBHOOK_KIND` | Optional generic, Slack, or Discord messages. |
| `SENTRY_DSN` | Optional error reports to Sentry. |

See [.env.example](.env.example) for every Docker setting and its default value.

## Run tests

Backend tests use Python 3.11 and `uv`:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r backend/requirements-dev.txt
cd backend
../.venv/bin/ruff check . ../toolbox
../.venv/bin/ruff format --check . ../toolbox
../.venv/bin/python -m pytest
../.venv/bin/python -m benchmarks.benchmark_core
```

Frontend tests use Node.js 22:

```bash
cd frontend
npm ci --no-audit --no-fund
node scripts/validate-lock-registry.mjs
npm audit --audit-level=high
npm run lint
npm test
npm run build
```

Check the Docker file without starting services:

```bash
docker compose config --quiet
```

## Common problems

### A page or API request says `401`

Enter the correct `ADMIN_API_KEY` on the dashboard **Settings** page. API and CLI requests must send the same value.

### A scan has no running tasks

Check the workers and toolbox:

```bash
docker compose ps
docker compose logs worker
docker compose logs toolbox
```

Also check the scan's **Scope** and **Tasks** tabs. A task may be outside scope, blocked by the chosen profile, waiting for another task, or already completed from saved data.

### A service does not become ready

Read its logs:

```bash
docker compose logs db
docker compose logs migrate
docker compose logs api
docker compose logs web
```

Make sure all three required values in `.env` were changed from the example values.

### Port 3000 or 8000 is already in use

Change `WEB_PORT` or `API_PORT` in `.env`, then run:

```bash
docker compose up -d
```

### The machine is running out of CPU or memory

Lower `WORKER_REPLICAS`, `MAX_CONCURRENT_TASKS`, or `TOOLBOX_MAX_CONCURRENT` in `.env`. The default container limits are in [docker-compose.yaml](docker-compose.yaml).

### A tool needs a provider key or different setting

Read [Toolbox configuration](config/toolbox/README.md). Keep provider keys outside Git and rebuild or restart the toolbox after changing its files.

## More documents

- [Architecture](docs/architecture.md): how the engine, database, tasks, and result links work.
- [Operations](docs/operations.md): running, updating, backing up, and watching Reconator.
- [Security](docs/security.md): scope checks, login rules, network safety, and tool safety.
- [Module development](docs/module-development.md): adding a new recon module.
- [Current coverage and roadmap](docs/coverage-and-roadmap.md): what is present and what is still planned.
- [Research and capability map](docs/research-and-capability-map.md): why the current methods and tools were chosen.
- [Performance](docs/performance.md): speed tests, limits, and tuning notes.
- [Tool comparison](docs/competitive-analysis.md): differences between Reconator and other open tools.

The old `modules/` folder is kept only as a reference. The current Docker images do not run those scripts.

## License

Reconator is licensed under GPL-3.0. See [LICENSE](LICENSE).
