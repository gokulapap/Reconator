# Security model

Reconator processes hostile network data and invokes security tooling, so the framework itself is part of the attack surface.

## Authorization and scope

Every scan creation requires explicit authorization confirmation by default. Active modules check that confirmation when scheduled. The centralized scope engine checks each task twice and uses default-deny matching with exclusion precedence.

An observed IP behind a scoped domain is not automatically authorized for active scanning. Derived infrastructure can be passed only to modules that explicitly opt in, and never to active modules. Add a direct exact/CIDR inclusion only when the assessment authorization covers that infrastructure.

## API protection

Production Compose requires `ADMIN_API_KEY` and sets `PROTECT_READ_ENDPOINTS=true`. This protects assets, evidence, task raw output, history, exports, and mutations. Health/readiness remain public for container orchestration. The UI stores the key in browser local storage, so use a dedicated workstation profile and do not run untrusted scripts in the same origin.

The API is loopback-bound by default. Deploy TLS and stronger identity-aware access at a reverse proxy for shared/multi-user environments; the built-in key is an administrative deployment gate, not tenant isolation or RBAC.

Trusted Host validation, explicit CORS origins, request IDs, write rate limits, a body-size limit (including chunked bodies), security headers, and bounded pagination reduce common web abuse. Do not set wildcard hosts in production.

## Process execution

The v3 command adapter:

- uses an argv array with no shell;
- rejects shell interpreters;
- passes normalized input as one argument;
- supplies a minimal environment rather than inherited credentials;
- closes stdin;
- drains stdout/stderr while retaining a fixed byte limit;
- applies a timeout and kills the whole process group.

The production images do not package the historical shell module directory. Port legacy behavior into typed modules before use.

Pinned third-party binaries execute in the separate toolbox container. Its API is
authenticated with an independent secret and accepts only enumerated tools, normalized
inputs, and bounded typed options. It never accepts a command string, arbitrary flag,
environment variable, output path, or caller-provided file path. Child processes use
temporary directories, a minimal environment, bounded output, a process-group timeout,
and a global capacity semaphore. JavaScript is fetched by the worker's pinned SSRF-safe
transport; JSLuice receives only bounded bytes and cannot choose a remote destination.
The broker erases its initial shared-secret environment entry before any tool starts,
verifies every executable and reports an aggregate implementation digest, bounds
connections before creating handler threads, applies socket/body deadlines, and waits
briefly for execution capacity. A capacity response is requeued without consuming a
module attempt.

The toolbox has no PostgreSQL/backend-network access and no published host port. Compose
runs it non-root, read-only, capability-free, with `no-new-privileges`, PID/resource
limits, and a bounded tmpfs. Only worker and toolbox containers receive
`TOOLBOX_SHARED_SECRET`; API and migration containers receive only the non-secret module
enablement flag and endpoint. Rotate the toolbox secret independently from the API key.
This limits blast radius but cannot make a compromised upstream binary trustworthy;
review pinned sources/licenses and scan/attest the built image before production use.

## SSRF and outbound requests

HTTP target probing resolves all candidate addresses and blocks non-global networks unless the deployment and scan configuration both allow private targets. Its socket is pinned to an address that passed policy while TLS still verifies the requested hostname, closing the usual DNS-rebinding check/connect gap. Redirects are observed but never automatically followed.

RDAP uses a fixed bootstrap host, pins and validates every HTTPS redirect destination, caps redirects, and caps the body. Webhook endpoints must be HTTPS, cannot contain credentials, are connected through the same pinned transport, are blocked when they point to non-public addresses unless an explicit deployment override is enabled, and do not follow redirects. The pinned transport ignores environment proxies and rejects request-header injection.

Deploy egress firewall rules as the final defense: deny metadata/link-local/RFC1918 destinations from workers and the toolbox unless an authorized internal-testing deployment explicitly requires them. HTTPX receives an explicit private/reserved deny list by default, and Naabu rejects non-global addresses unless both deployment and scan policy authorize private targets. Treat application validation as one layer, not a network boundary.

For URL-prefix targets, the engine passes a protected effective prefix/exclusion
contract to Katana, disables host-root known-file expansion for narrow prefixes, and
prevents derived host entities from authorizing active root probing. HTTPX favicon
fetching is disabled because it would add an implicit root request.

## Untrusted result handling

Normalization rejects control characters, oversized values, credentials in URLs, invalid ports/methods/fingerprints, and unsafe custom kind names. Module output has bounded record/body counts. An invalid asset or relationship is rejected individually, reported in the task summary/event stream, and does not discard valid sibling output.

Raw output is retained only up to `MAX_RAW_OUTPUT_BYTES` per task and
`MAX_RAW_OUTPUT_BYTES_PER_SCAN` in aggregate. Sensitive URL query values are redacted
from canonical/storage identities and isolated-tool JSONL evidence. Avoid placing
credentials, session cookies, private source, or full sensitive response bodies in
module evidence. Secrets must come from environment/secret management and must never
be emitted into task config or logs.

## Filesystem and containers

Compose services use non-root users, read-only root filesystems, `no-new-privileges`, dropped Linux capabilities, separated backend/recon-egress networking, loopback port publication, and bounded tmpfs/volumes. PostgreSQL is neither published nor connected to recon egress. CPU, memory, PID, process-output, and tool-capacity limits provide layered resource-exhaustion boundaries.

Alembic—not application startup—owns schema changes. Back up the PostgreSQL volume before production migrations and test restore procedures.

## Webhooks and notifications

Notification failures are isolated and do not affect scan state. Telegram/webhook credentials are never returned by the system-info API. The generic webhook payload contains scan messages; configure a trusted destination because those messages may contain target identifiers.

## Operational recommendations

- Generate unique API/database secrets and rotate them after exposure.
- Terminate TLS and add SSO/RBAC at the edge for teams.
- Restrict worker egress to required DNS/HTTP destinations and authorized target ranges.
- Keep `ALLOW_PRIVATE_TARGETS=false` unless the deployment exists specifically for internal authorized testing.
- Export `/metrics` and logs only to trusted observability systems.
- Run `pip-audit`, `npm audit`, tests, and container scanning in every release pipeline.
- Pin base images by digest in controlled deployments, verify tool module sums, preserve
  third-party notices, generate an SBOM, and sign/attest builds.
- Establish data retention because recon evidence can itself be sensitive.

## Known trust boundaries

Module code and installed entry-point packages execute with the worker’s privileges and are trusted extensions. Reconator isolates failures and validates outputs, but it is not a sandbox for malicious Python plugins. Review and pin every module package. The toolbox improves fault and credential isolation for external executables, but its container is likewise not a sandbox for intentionally malicious code without an appropriately configured runtime and host policy.

The current administrative API key has no per-user attribution. Multi-tenant authorization, secrets vault integration, cryptographic audit-log sealing, and process/container isolation per untrusted third-party tool remain deliberate future hardening areas.
