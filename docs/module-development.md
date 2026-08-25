# Module development

A Reconator module is a small capability adapter with an honest contract. It does not create database rows, bypass scope, choose scan state, or launch uncontrolled subprocesses.

## Minimal Python module

```python
from app.db.models import AssetKind
from app.recon.modules.base import (
    AssetEmission,
    AssetReference,
    CapabilityExecutionPolicy,
    ModuleContext,
    ModuleManifest,
    ModuleMode,
    ModuleResult,
    RelationshipEmission,
)


class ExampleDiscovery:
    manifest = ModuleManifest(
        name="example.discovery",
        version="1",
        description="Discover an API hostname from a domain",
        capability="domain.related_names",
        consumes=frozenset({AssetKind.domain.value}),
        produces=frozenset({AssetKind.domain.value}),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=100,
        timeout_seconds=30,
        max_attempts=2,
        cache_ttl_seconds=3600,
        rate_limit_per_second=2,
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        discovered = f"api.{context.input_asset.canonical_value}"
        return ModuleResult(
            assets=[
                AssetEmission(
                    kind="domain",
                    value=discovered,
                    evidence={"source_record": "fixture"},
                    source_name="example-source",
                    confidence=0.9,
                )
            ],
            relationships=[
                RelationshipEmission(
                    source=AssetReference("domain", context.input_asset.canonical_value),
                    target=AssetReference("domain", discovered),
                    relationship_type="has_subdomain",
                    evidence={"source_record": "fixture"},
                    confidence=0.9,
                )
            ],
            metadata={"records_considered": 1},
        )
```

Register an independently packaged module with a Python project entry point:

```toml
[project.entry-points."reconator.modules"]
example-discovery = "example_package:ExampleDiscovery"
```

The worker loads entry points at startup. The object may be a module instance or a zero-argument module class.

## Contract rules

- `name` is a stable implementation identity. Increment `version` whenever parsing, semantics, or output identity changes so stale cache entries are not reused.
- `capability` describes the replaceable behavior, not the tool name.
- `consumes` and `produces` must reflect actual outputs; the UI and scheduler use them for introspection and chaining.
- Use `local` only for transformations with no remote interaction, `passive` for third-party/public intelligence, and `active` for direct target interaction.
- Active modules must be narrow, bounded, and safe by default. They never receive derived-only scope.
- Set `accepts_derived_inputs=True` only when passive/local analysis of indirectly observed data is both useful and safe.
- Return evidence sufficient to audit the observation without embedding secrets or unbounded response bodies.
- Attributes, evidence, and metadata must be finite JSON objects. The framework enforces byte and per-task emission ceilings and rejects malformed siblings independently.
- Raise `ModuleExecutionError(code=..., retryable=...)` for expected failures. Unexpected exceptions are isolated and recorded as `module_crash`.
- Never write scan state directly. Emit assets and relationships; the framework handles identity, provenance, prioritization, and new work.

## Predicates

A module may define `accepts(normalized_asset) -> bool` for a cheap deterministic filter. For example, the CT seed module runs only on assets with the `seed` attribute to prevent recursive CT queries for every discovered subdomain.

Do not perform I/O in `accepts`; it runs during scheduling.

## Configuration

The module receives only its effective configuration in `context.config`. Define conservative defaults in code, validate every value, cap list sizes/ranges/timeouts again inside the module, and ignore unknown values only when doing so is safe.

Configuration is included in task/cache identity, so a meaningful configuration change creates new work.

## Multiple implementations of one capability

The default is `parallel_sources`: every selected implementation is independent and
may run concurrently. This is appropriate when sources are complementary and merging
their observations improves coverage.

An implementation may declare a capability-wide policy when running every adapter is
redundant or when ordering is semantically required:

```python
manifest = ModuleManifest(
    # ...
    capability="http.probe",
    capability_policy=CapabilityExecutionPolicy.preferred_then_fallback,
    implementation_priority=200,
)
```

- `preferred_then_fallback` tries implementations from highest
  `implementation_priority` to lowest. The next task is activated only after the
  preceding implementation permanently fails or is unavailable. A successful or
  cache-replayed implementation suppresses the remaining fallbacks.
- `sequential_enrichment` runs every implementation in the same deterministic order.
  A permanent predecessor failure suppresses later enrichment because their ordering
  contract can no longer be satisfied.
- `parallel_sources` preserves the ordinary independent-source behavior.

When priorities tie, task priority and then stable module name determine order. Only
one implementation needs to declare the capability policy; any other explicit
declarations must agree. A conflicting plugin is rejected during registration.

Policy gates are persisted as task dependencies and protected scheduler metadata, so
worker restarts, retry waits, expired leases, cache hits, and horizontal workers cannot
bypass the ordering. Downstream `depends_on_capabilities` tasks wait on the terminal
policy task: a failed preferred implementation followed by a successful fallback
satisfies the capability dependency without treating the expected first failure as a
failed capability.

## Command-backed tools

Use `CommandModule` and `CommandSpec`:

```python
CommandSpec(
    argv=("tool", "--json", "--target", "{input}"),
    parser=parse_json_lines,
)
```

`{input}` is substituted within a single argv element. The adapter never uses `shell=True`, rejects shell interpreters, supplies a minimal environment, closes stdin, bounds retained stdout/stderr, enforces a deadline, and kills the child process group on timeout.

Parsers must treat tool output as untrusted. Limit records, lengths, nesting, and response size before creating emissions. Never trust an output path supplied by a tool.

For maintained external recon binaries, prefer the isolated toolbox pattern used by the
bundled adapters. Add the implementation to the toolbox allowlist with a pinned version,
typed target validator, explicit bounded options, non-shell argv, deadline, output limit,
license notice, and parser fixtures. The worker-facing module should expose a capability
contract and normalize results; it must not expose arbitrary command or flag passthrough.

Classify the real interaction mode, not the apparent operation. A locally installed
binary that queries a passive provider is passive; a crawler or HTTP probe is active; a
pure mutation/range classifier is local. Any tool that contacts the target must require
direct scope even if it calls itself passive.

## Relationship vocabulary

Relationship types use lower snake case, are directional, and should describe a durable fact: `resolves_to`, `has_subdomain`, `serves`, `links_to`, `loads_script`, `exposes_endpoint`, `accepts_parameter`, `exposes_service`, `contains_address`, or `owns_address`.

Prefer one established term over near-duplicates. Evidence belongs on the relationship observation; stable attributes belong on the canonical relationship.

## Testing checklist

- parser fixture for normal, empty, malformed, oversized, and adversarial output;
- normalization and duplicate variants;
- scope behavior, including out-of-scope and derived-only inputs;
- retryable and permanent failure codes;
- timeout and cancellation behavior;
- cache replay after module version/config changes;
- result-driven downstream task generation;
- no external network in unit tests;
- benchmark when the parser may process large result sets.

Add every fixed parser or orchestration bug as a regression test.
