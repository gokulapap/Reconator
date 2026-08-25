# Competitive analysis

This analysis uses public project documentation and focuses on architectural lessons, not proprietary implementation details.

## OWASP Amass

[OWASP Amass](https://owasp-amass.github.io/docs/) is mature at attack-surface mapping and formalizes a broad [Open Asset Model](https://owasp-amass.github.io/docs/open_asset_model/assets/index.html). Its strength is deep domain/infrastructure enumeration and a well-considered asset vocabulary.

Reconator adopts the durable lesson—recon data should be modeled as assets and relationships—while targeting a more general capability/task runtime. Reconator’s differentiator is that any normalized result can select new module consumers with explicit task state, retry/lease/cache semantics, per-scan provenance, and API/UI operations.

## BBOT

[BBOT’s scanning model](https://github.com/blacklanternsecurity/bbot/blob/stable/docs/scanning/index.md) demonstrates the power of event-driven modules, central scope concepts, and reusable [presets](https://github.com/blacklanternsecurity/bbot/blob/stable/docs/scanning/presets.md). It offers broad module coverage and practical operator ergonomics.

Reconator follows the event/result-driven insight but persists each unit of follow-up work as a leased task and each assertion as graph provenance. Its direct-vs-derived scope basis is intended to make the authorization boundary inspectable at task level. Reconator profiles are intentionally small; module/capability allowlists and layered configuration provide the extensibility point.

## Osmedeus

[Osmedeus workflows](https://docs.osmedeus.org/workflows/overview) provide powerful workflow composition and reusable steps. Its documentation also addresses [distributed execution](https://docs.osmedeus.org/others/faq), which is important for large recon programs.

Reconator avoids making a static workflow file the sole source of future work. Manifests describe capability contracts, while normalized discoveries select consumers dynamically. PostgreSQL leases let multiple workers share work without repeating completed tasks. Explicit dependencies remain available when strict ordering is necessary.

## Common recon stacks

Shell pipelines built around subdomain, probing, URL, crawling, and template tools are fast to assemble and often excellent for a focused run. Their recurring weaknesses are inconsistent identity, repeated work, lost provenance, output-file coupling, coarse recovery, unsafe interpolation, and manual correlation.

Reconator does not compete by hiding those tools behind buttons. It supplies the control plane and knowledge layer in which a tool can be one replaceable implementation. Coverage should grow through typed adapters and fixtures, not by restoring an opaque sequential script.

## Where Reconator is stronger

- Durable global asset identity plus per-scan/source evidence.
- Result-driven scheduling with persisted task ancestry.
- Horizontal leases, idempotency, cache replay, cancellation, and recovery.
- Central scope enforcement at scheduling and execution.
- Inspectable direct/derived authorization basis.
- Capability abstraction independent of tool brand.
- Same engine behind API, CLI, UI, and automation.
- Production container/migration/security posture.

## Where mature projects remain stronger

- Significantly larger maintained module/tool ecosystems.
- Years of edge-case parsers and provider integrations.
- Richer wordlist/content-discovery and cloud/repository intelligence coverage.
- More operator presets and community knowledge.
- In some cases, mature distributed runners and graph analysis.

Reconator should not imitate breadth by adding fragile wrappers. The priority is to port high-value capabilities through the contract, retain structured evidence, and prove that each new result creates useful bounded follow-up work.
