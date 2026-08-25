# RIPEstat BGP intelligence

Reconator has two native passive modules for bounded routing intelligence from the RIPE NCC RIPEstat Data API. They enrich an authorized scan's graph; they do not probe the input IP, any announced prefix, or any address inside a prefix.

## Modules and graph model

| Module | Input | Output | Relationship |
| --- | --- | --- | --- |
| `infrastructure.ripestat_network_info` | public `ip_address` | containing routed `cidr` and one or more `autonomous_system` assets | `IP --member_of_prefix--> CIDR`; `CIDR --announced_by--> ASN` |
| `infrastructure.ripestat_announced_prefixes` | `autonomous_system` | announced `cidr` assets | `CIDR --announced_by--> ASN` |

Only the following version-selected HTTPS requests can be constructed:

- `https://stat.ripe.net/data/network-info/data.json?resource=<canonical-IP>&preferred_version=1.1`
- `https://stat.ripe.net/data/announced-prefixes/data.json?resource=<canonical-ASN>&preferred_version=1.2`

The endpoint and query keys are code constants. Resource values pass through Reconator's IP or ASN normalizer before URL encoding. Redirects are disabled. The pinned HTTP client resolves and validates the RIPEstat service destination, connects to that validated address, and rejects non-HTTPS or unsafe destinations. Neither module accepts an operator-supplied endpoint, path, callback, time range, organization name, or related-resource pivot.

The upstream contracts are documented by RIPE NCC in [Network Info](https://stat.ripe.net/docs/data-api/api-endpoints/network-info.html), [Announced Prefixes](https://stat.ripe.net/docs/data-api/api-endpoints/announced-prefixes), and the [RIPEstat Data API overview](https://stat.ripe.net/docs/data-api/ripestat-data-api).

## Authorization and derived intelligence

Both modules are `passive` and set `accepts_derived_inputs=true`. This permits useful passive chaining such as:

```text
authorized domain -> resolved IP -> routed prefix + ASN -> announced prefixes
```

An emitted prefix carries `intelligence_only=true` and `routing_source="RIPE RIS"`. Those attributes describe provenance; authorization enforcement remains centralized in the scheduler. The scheduler retains out-of-scope derived assets in the knowledge graph, but schedules one only when all of these conditions hold:

1. it has a successful parent task;
2. the consuming module explicitly accepts derived inputs; and
3. the consuming module is not active.

The same checks run when work is scheduled and again immediately before execution. `network.cidr_expand` does not accept derived inputs, so a RIPEstat prefix cannot be expanded into address tasks merely because it appeared in routing data. An active module cannot use derived-only scope even if its own manifest mistakenly opts into derived inputs. A prefix becomes active scope only when it independently matches the scan's explicit include rules. Active authorization confirmation remains a separate requirement.

This implementation deliberately does not emit organization assets or pivot from fuzzy holder names. An ASN is obtained only as the structured origin value of a routed prefix, and announced prefixes are queried only from that canonical ASN.

## Bounds and service controls

| Control | Network Info | Announced Prefixes |
| --- | ---: | ---: |
| Per-request timeout | 15 seconds | 15 seconds |
| Manifest timeout | 20 seconds | 20 seconds |
| Maximum response body | 256,000 bytes | 4,000,000 bytes |
| Redirects | 0 | 0 |
| Maximum response items | 16 origin ASNs | 20,000 prefix records and 100,000 timeline records |
| Default emitted prefixes | not applicable | 2,000 |
| Hard emitted-prefix cap | not applicable | 10,000 |
| Cache TTL | 8 hours | 6 hours |
| Rate limit | 0.5 requests/second | 0.5 requests/second |
| Attempts | 3 | 3 |

`infrastructure.ripestat_announced_prefixes.max_prefixes` may be set to a positive JSON integer. Values above 10,000 are clamped to the hard cap. Invalid values fail without retry. Every returned prefix and timeline is still schema-checked within the response-item safety ceilings; the output is deduplicated and then capped. Result metadata records returned, unique, emitted, and truncated counts.

Private, loopback, link-local, reserved, and otherwise non-global IP inputs are skipped without an HTTP request. The announced-prefix module can represent IPv4 and IPv6 prefixes. It does not assume that routing visibility proves ownership or scan authorization.

## Response validation and failures

A response is accepted only when all relevant checks pass:

- HTTP status is exactly 200 and the media type is `application/json`;
- the body is valid JSON with an object at the top level;
- common RIPEstat fields report `status="ok"`, `status_code=200`, the requested `data_call_name`, a `supported` data-call status, and a compatible major response version;
- `data` is an object and an optional `cached` field is boolean;
- Network Info supplies a prefix containing the queried IP and one or more valid ASNs, or a coherent unrouted result with `prefix=null` and an empty ASN list;
- Announced Prefixes echoes the queried ASN, supplies bounded prefix and timeline lists, supplies bounded query/timeline timestamps, and contains valid canonicalizable IP networks.

Failure classification is explicit:

| Error code | Retryable | Meaning |
| --- | --- | --- |
| `ripestat_transport_error` | yes | transient pinned-client, DNS, TLS, socket, or HTTP transport failure |
| `ripestat_http_error` | only for 408, 425, 429, and 5xx | unsuccessful HTTP response |
| `ripestat_api_error` | only for maintenance or retryable embedded status | RIPEstat returned an unsuccessful API status |
| `ripestat_destination_error` | no | fixed service destination failed SSRF policy |
| `ripestat_response_too_large` | no | response exceeded its byte ceiling |
| `ripestat_schema_error` | no | content type, JSON, common envelope, or endpoint data violated the contract |
| `ripestat_item_limit` | no | a response exceeded a hard item ceiling |
| `ripestat_invalid_config` | no | `max_prefixes` was not a positive integer |

Assets and relationships include compact evidence naming `RIPE NCC RIPEstat`, `RIPE RIS`, the data call, query resource, and response version. Announced-prefix relationships also record the observation window. Full upstream payloads and individual timeline arrays are not retained as raw output, limiting database growth while preserving useful provenance.

## Test isolation

The focused tests in `backend/tests/test_ripestat_modules.py` replace the pinned HTTP request function with local in-memory responses. They assert exact URL construction and request bounds, graph direction, deduplication and truncation, status/schema rejection, retry classification, registration and manifest controls, non-public-IP short-circuiting, and the scheduler's passive-derived versus active-scope behavior. No test contacts RIPEstat or any scan target.
