# Coverage and remaining roadmap

Reconator 3 establishes the framework substrate and a safe end-to-end discovery loop. It is not reasonable to claim that any recon system is “perfect”; providers, technologies, defenses, and research continuously change. This document makes current coverage and the next highest-value gaps explicit.

## Implemented foundation

- Domain, URL, IP, and CIDR roots.
- Canonical graph assets and arbitrary typed relationships.
- Evidence/provenance, global identity, per-scan observations, snapshots, and comparisons.
- DNS A/AAAA/CNAME/NS/MX/TXT/PTR, CT subdomains, HTTP/HTML links/scripts/forms, bounded JavaScript endpoint/parameter extraction, TCP services, bounded network expansion, and RDAP ownership.
- Dynamic capability consumers and plugin discovery.
- Central scope, passive/balanced/active modes, direct/derived semantics, exclusions, and reconciliation.
- Priorities, dependencies, bounded concurrency, rate spacing, retries/backoff, leases, cache reuse, cancellation, resumability, and task ceilings.
- API, CLI, UI, metrics, events/logs, notification adapters, Docker Compose, migrations, and CI security audits.

## Highest-value capability additions

1. Passive sources with credential-aware quotas: additional CT/DNS datasets, ASN/BGP, historical DNS, archive URLs, and organization-to-domain pivots.
2. Deeper JavaScript analysis: source maps, AST-based extraction, API schemas, dynamic imports, redacted secret-candidate verification, and framework routes.
3. HTTP intelligence: TLS/certificate entities, redirect chains with scope-aware validation, headers/cookies, favicon/body hashes, virtual hosts, CDN/WAF/cloud attribution, and screenshot artifacts.
4. Service discovery implementations behind `network.port_discovery` and service fingerprinting with per-program safety profiles.
5. API discovery: OpenAPI/GraphQL/gRPC artifacts, parameters, methods, auth surfaces, and relationship-aware schema expansion.
6. Repository/source intelligence: authorized organization/repository providers, commit/history artifacts, IaC routes/domains/cloud resources, and token-safe evidence.
7. Cloud discovery: buckets, storage endpoints, load balancers, serverless endpoints, tenant IDs, and provider-resource relationships.
8. Historical/change intelligence: first-class removal confirmation, DNS/service/technology diffs, notification rules, and scheduled scan policies.

## Platform improvements

- Distributed global/provider rate-limit buckets rather than database-visible per-target start spacing.
- Scheduler fairness by tenant/program and queue-age SLOs.
- Heartbeats for modules whose safe execution can exceed their declared timeout.
- Process/container isolation profiles for third-party tools.
- Object storage for large evidence with hashes, retention, and redaction.
- PostgreSQL-native search/materialized graph summaries for million-node programs.
- WebSocket/SSE event streaming and visual graph exploration.
- RBAC, per-user audit attribution, projects/programs, secrets-vault integration, and tenant isolation.
- Scheduled continuous recon service with jitter, budgets, maintenance windows, and change-trigger policies.
- Signed plugin manifests, compatibility ranges, and module health/canary execution.

## Acceptance rule for new coverage

A new tool is not coverage until it has:

- a capability contract and truthful interaction mode;
- bounded input/output/resource behavior;
- normalization and relationship mapping;
- provenance/evidence decisions;
- centralized scope behavior;
- retry/failure semantics;
- cache/version behavior;
- parser and pipeline regression fixtures;
- documentation and observable metrics.

This rule preserves the difference between a framework and a tool launcher.
