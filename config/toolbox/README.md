# Toolbox provider configuration

This directory is mounted read-only at `/config` in the isolated toolbox.
Provider credential files are intentionally ignored by Git.

To enable credential-backed Subfinder sources, create:

```text
config/toolbox/subfinder-provider.yaml
```

Use the provider schema documented by Subfinder. Keep the file readable only by
the local operator and never commit it. Public, credential-free sources remain
available when the file is absent. Reconator enables Subfinder's `-all` source
mode by default to maximize coverage. Set
`scan_config.modules["toolbox.subfinder"].all_sources` to `false` only when a
lower-cost/faster pass is intentional.

DNSX does not accept arbitrary command-line flags or per-scan resolver endpoints.
The `toolbox.dnsx` module always enables automatic wildcard filtering and queries
A, AAAA, CNAME, NS, MX, TXT, and CAA records. Its supported per-module settings
are clamped by the execution broker:

| Setting | Default | Allowed range |
| --- | ---: | ---: |
| `concurrency` | 25 | 1–100 |
| `rate_limit` | 100 requests/second | 1–500 |
| `request_timeout_seconds` | 3 | 1–15 |
| `retries` | 2 | 1–4 |
| `wildcard_threshold` | 5 | 2–20 |

Private and reserved A/AAAA answers are discarded unless both deployment policy
and the scan's module configuration explicitly authorize private networks. The
tool still uses the centrally enforced scope decision for its input; CNAME, NS,
and MX targets may be retained as graph evidence, but out-of-scope targets are
not scheduled for active follow-up.

The image is built from the signed DNSX `v1.3.0` source tag. That upstream tag
still prints `1.2.3` for `dnsx -version`; ProjectDiscovery tracks this release
banner bug in <https://github.com/projectdiscovery/dnsx/issues/1002>.
