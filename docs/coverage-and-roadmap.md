# Coverage and remaining roadmap

Reconator 3 establishes the framework substrate and a safe end-to-end discovery loop. It is not reasonable to claim that any recon system is “perfect”; providers, technologies, defenses, and research continuously change. This document makes current coverage and the next highest-value gaps explicit.

## Implemented foundation

- Domain, URL, IP, and CIDR roots.
- Canonical graph assets and arbitrary typed relationships.
- Evidence/provenance, global identity, per-scan observations, snapshots, and comparisons.
- DNS A/AAAA/CNAME/NS/MX/TXT/PTR, paginated CT subdomains, historical URL-host hypotheses, HTTP/HTML links/scripts/forms, bounded JavaScript endpoint/parameter extraction, TCP services, bounded network expansion, and RDAP ownership.
- Pinned isolated implementations for multi-source passive subdomains (Subfinder), historical URLs (URLFinder), HTTP/TLS/ASN/CDN/technology enrichment (HTTPX), same-host crawling (Katana), TCP-connect port discovery (Naabu), AST-aware JavaScript analysis (JSLuice), bounded name mutations (AlterX), and local CDN/cloud/WAF range classification (CDNCheck).
- Dynamic capability consumers and plugin discovery.
- Central scope, passive/balanced/active modes, direct/derived semantics, exclusions, and reconciliation.
- Priorities, manifest capability dependencies, bounded concurrency, rate spacing, retries/backoff, leases, cache reuse, cancellation, resumability, and task ceilings.
- API, CLI, UI, metrics, events/logs, notification adapters, Docker Compose, migrations, CI security audits, and a non-root authenticated tool execution plane separated from PostgreSQL.

The evidence, overlap analysis, implementation/fallback choices, and broader methodology
are maintained in [Research and capability map](research-and-capability-map.md).

## Highest-value capability additions

1. Passive sources with credential-aware distributed quotas: historical DNS, ASN/BGP and reverse-WHOIS organization pivots, code-host search, provider attribution, and source-health scoring.
2. API intelligence: OpenAPI/Swagger/Postman discovery and parsing, GraphQL/gRPC/GraphQL-over-WebSocket artifacts, parameters, methods, auth surfaces, schema relationships, and Kiterunner-style route dictionaries.
3. Repository/source intelligence: authorized organization/repository providers, history-aware secret-candidate verification, IaC-derived domains/routes/cloud resources, CI artifacts, package metadata, and token-safe evidence.
4. Cloud/SaaS discovery: storage endpoints, load balancers, serverless endpoints, tenant IDs, dangling provider bindings, mobile-app associations, and provider-resource relationships.
5. Deeper web analysis: source maps, dynamic imports and chunks, framework manifests/routes, WebAssembly imports/strings, WebSocket/SSE channels, service workers, browser extension surfaces, and screenshot artifacts.
6. Validation implementations: wildcard-aware high-throughput DNS resolution, virtual-host comparison, bounded content discovery, service fingerprinting, and response-similarity suppression with per-program safety profiles.
7. Historical/change intelligence: first-class multi-observation removal confirmation, DNS/service/technology/content diffs, notification rules, and scheduled scan policies.
8. Quality intelligence: source precision/recall tracking, result confidence fusion, false-positive feedback, stale-observation policy, and cost-aware capability selection.
9. Maximum-yield DNS: wildcard/poisoning-aware batched validation, a checksum-pinned maintained wordlist, bounded recursive zone discovery, corpus-driven mutations, and chunked checkpointed ingestion for source results above one task's in-memory budget.

## Platform improvements

- Distributed global/provider rate-limit buckets rather than database-visible per-target start spacing.
- Explicit capability policies (`parallel_consensus`, `preferred_then_fallback`, and enrichment chains) rather than always running every matching implementation.
- Scheduler fairness by tenant/program and queue-age SLOs.
- Heartbeats for modules whose safe execution can exceed their declared timeout.
- Stronger per-task sandboxing for third-party tools (seccomp/AppArmor, rootless runtime,
  per-capability egress policy, signed binaries, and image attestations).
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
