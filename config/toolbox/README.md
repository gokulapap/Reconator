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
