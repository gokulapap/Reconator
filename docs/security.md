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

## SSRF and outbound requests

HTTP target probing resolves all candidate addresses and blocks non-global networks unless the deployment and scan configuration both allow private targets. Its socket is pinned to an address that passed policy while TLS still verifies the requested hostname, closing the usual DNS-rebinding check/connect gap. Redirects are observed but never automatically followed.

RDAP uses a fixed bootstrap host, pins and validates every HTTPS redirect destination, caps redirects, and caps the body. Webhook endpoints must be HTTPS, cannot contain credentials, are connected through the same pinned transport, are blocked when they point to non-public addresses unless an explicit deployment override is enabled, and do not follow redirects. The pinned transport ignores environment proxies and rejects request-header injection.

Deploy egress firewall rules as the final defense: deny metadata/link-local/RFC1918 destinations from workers unless an authorized internal-testing deployment explicitly requires them. Treat application validation as one layer, not a network boundary.

## Untrusted result handling

Normalization rejects control characters, oversized values, credentials in URLs, invalid ports/methods/fingerprints, and unsafe custom kind names. Module output has bounded record/body counts. An invalid asset or relationship is rejected individually, reported in the task summary/event stream, and does not discard valid sibling output.

Raw output is retained only up to `MAX_RAW_OUTPUT_BYTES`. Avoid placing credentials, session cookies, private source, or full sensitive response bodies in module evidence. Secrets must come from environment/secret management and must never be emitted into task config or logs.

## Filesystem and containers

Compose services use non-root users, read-only root filesystems, `no-new-privileges`, dropped Linux capabilities, private backend networking, loopback port publication, and bounded tmpfs/volumes. PostgreSQL is not published. CPU and memory limits provide a final resource-exhaustion boundary.

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
- Pin released images by digest in controlled deployments and sign/attest builds.
- Establish data retention because recon evidence can itself be sensitive.

## Known trust boundaries

Module code and installed entry-point packages execute with the worker’s privileges and are trusted extensions. Reconator isolates failures and validates outputs, but it is not a sandbox for malicious Python plugins. Review and pin every module package.

The current administrative API key has no per-user attribution. Multi-tenant authorization, secrets vault integration, cryptographic audit-log sealing, and process/container isolation per untrusted third-party tool remain deliberate future hardening areas.
