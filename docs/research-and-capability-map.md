# Recon ecosystem research and capability map

Research snapshot: 2026-08-25. This is a decision record, not a promise that a
tool remains best forever. Provider behavior, licenses, maintenance and output
contracts must be re-evaluated during every pinned dependency update.

## Methodology derived from the research

An effective recon program is a feedback system with cost tiers:

1. Establish authorization, root identities, exclusions, interaction budget and
   private/shared-infrastructure policy.
2. Fan out low-cost passive sources for domains, URLs, certificates, ownership,
   repositories and historical observations.
3. Normalize and correlate before generating work. Multiple sources agreeing on
   one identity should raise confidence, not create duplicate scans.
4. Validate names and infrastructure. DNS answers, wildcards, CNAME chains,
   certificate names, ASN ownership and CDN/cloud classification determine which
   active work is safe and useful.
5. Identify live application surfaces through bounded HTTP/TLS probing, then
   classify redirects, headers, cookies, technologies, certificates and edge
   infrastructure.
6. Expand applications through complementary sources: standard crawling,
   browser/XHR crawling, historical URLs, known files, JavaScript AST analysis,
   source maps, service workers, module manifests and API descriptions.
7. Turn paths into typed endpoints, methods, parameters, forms, authentication
   surfaces and schemas. Prioritize new, changed, administrative, staging,
   upload, integration and API assets.
8. Run higher-cost DNS mutation, port discovery, virtual-host, content and hidden
   parameter discovery only against directly authorized assets and within an
   explicit budget.
9. Compare the graph with earlier scans. New or materially changed entities
   re-enter compatible stages through idempotent task keys; unchanged expensive
   results are cached.

This combines the OWASP WSTG emphasis on application entry points and
architecture mapping with the recursive event models demonstrated by BBOT and
Amass. It also keeps an important distinction: observations may be retained a
hop outside scope, but they must not silently authorize active interaction.

## Consolidated capability map

| Layer | High-value techniques | Result-driven pivots | Current Reconator state |
| --- | --- | --- | --- |
| Authorization | exact/wildcard domains, URLs, IP/CIDR, exclusions, direct vs derived | every task receives a scope decision | implemented centrally |
| Organization intelligence | legal names, brands, acquisitions, ASNs, repositories, package namespaces | organization → domain/ASN/repository | model ready; providers deferred |
| Passive domain discovery | CT, passive DNS, provider APIs, search datasets | domain → subdomain → DNS/HTTP | paginated CertSpotter + all configured Subfinder sources, with merged provider counts |
| Active DNS discovery | wordlists, learned mutations, wildcard and poisoning validation, common SRV records | validated name → address/CNAME/service | wildcard-aware DNSX records + bounded AlterX candidates; wordlist-scale validation remains |
| Certificate intelligence | CT, live TLS SANs, issuer, fingerprint and reuse clusters | certificate ↔ domains ↔ live services | CT + httpx TLS graph |
| Network ownership | RDAP, ASN, BGP prefixes, reverse DNS, internet indexes | IP → ASN/org/CIDR → passive services | RDAP/PTR + httpx ASN; BGP providers remain |
| Edge classification | CDN, cloud, WAF and shared hosting ranges | IP/CNAME → provider → scan-safety decision | CDNCheck + httpx attribution |
| Service discovery | safe connect scans, protocol/TLS handshakes, service fingerprinting | IP → port → service → HTTP/TLS | Python common ports + Naabu connect mode |
| HTTP intelligence | liveness, redirects, status, headers, cookies, title, hashes, technologies, TLS | host/service → URL/technology/certificate | Python pinned probe + httpx enrichment |
| Historical intelligence | Wayback, Common Crawl, URLScan and OTX | domain → old URL/JS/parameter → selective validation | URLFinder with provider provenance; historical hosts become DNS-only hypotheses before promotion |
| Crawling | standard, known files, JS link extraction, authenticated/headless/XHR | URL → URL/JS/form/endpoint | HTML parser + active Katana; browser worker deferred |
| JavaScript | regex, AST, dynamic imports, source maps, workers, bundle manifests | JS → endpoint/method/parameter/domain | Python extraction + safely fetched jsluice AST |
| API discovery | OpenAPI/Swagger, GraphQL, gRPC-Web, WSDL, route datasets, method/content-type discovery | schema → endpoint/method/parameter/auth | entity model ready; schema parser is next priority |
| Content discovery | robots/sitemaps, well-known files, backups, technology-specific paths | URL/technology → candidate path → validation | known files via Katana; contextual brute force deferred |
| Virtual hosts | DNS/certificate candidates, Host/SNI differential responses | IP/service + names → vhost URL | deferred until an isolated differential module exists |
| Cloud exposure | storage naming, tenant IDs, serverless/load-balancer endpoints, authorized cloud APIs | domain/org/JS → cloud resource | model ready; black/white-box modules deferred |
| Repository/source | org/repository search, commit history, IaC, CI artifacts, verified secret candidates | repo → domains/endpoints/cloud resources | model ready; credential vault and redaction required first |
| Change intelligence | additions, removals, content/service/technology deltas | changed entity → selective re-enumeration | assets, comparison and changed-entity scheduling implemented |
| Outputs | API/CLI/UI, notifications, JSON/graph/SARIF | graph/change → integration | API/CLI/UI/metrics/webhooks implemented |

## Tool selection: coverage rather than count

The initial isolated toolbox intentionally chooses orthogonal implementations:

| Implementation | Why selected | Interaction | Default use |
| --- | --- | --- | --- |
| Subfinder 2.16.0 | maintained passive-source aggregation, JSONL and per-source quotas/provenance; all configured sources enabled by default | passive | all profiles |
| DNSX 1.3.0 | maintained JSONL DNS validation with automatic wildcard filtering and structured resolver/record evidence | active | balanced/active |
| URLFinder 0.0.3 | curated historical URL sources with source-bearing JSONL | passive | all profiles |
| httpx 1.10.0 | rich HTTP/TLS/ASN/CDN/technology output complementary to the strict built-in probe | active | balanced/active |
| Katana 1.7.0 | bounded standard crawling, JavaScript parsing and known-file discovery | active | active only |
| jsluice pinned commit | AST-aware methods, URLs and parameters that regex extraction misses | local analysis after active safe fetch | balanced/active |
| Naabu 2.6.1 | maintained high-speed discovery; forced into unprivileged TCP connect mode | active | active only, direct IP scope |
| AlterX 0.1.0 | target-aware learned mutations with a hard candidate limit | local generation leading to active DNS | active only |
| CDNCheck 1.2.50 | maintained local CDN/cloud/WAF ownership data | local | all profiles |

Reconator runs these in a separate authenticated container that has internet
egress but no database network membership. Arguments are built by a whitelist;
operators cannot submit shell or arbitrary flags. Output, time, concurrency,
payload and process counts are bounded.

## Evaluated and deliberately deferred

- **Amass and BBOT:** excellent broad frameworks and data models, but embedding a
  framework inside Reconator would duplicate orchestration and obscure
  provenance. Prefer direct providers or narrow adapters where they add unique
  observations.
- **PureDNS/MassDNS:** valuable as the next wordlist-scale validation stage beyond
  single-candidate DNSX. It needs resolver health management, chunk checkpoints,
  and program-wide DNS budgets before safe default integration.
- **Kiterunner:** materially useful for method/header/body-aware API routes, but
  the route dataset is large and high-request. Integrate only with explicit
  per-program budgets and contextual triggering.
- **x8/Arjun:** useful differential hidden-parameter discovery. It should run only
  on prioritized dynamic endpoints after response-baseline storage exists.
- **Feroxbuster/ffuf:** useful forced browsing, but high overlap and request cost.
  Technology-conditioned wordlists and wildcard/soft-404 baselines must precede
  integration.
- **Uncover/internet search APIs:** unique passive service coverage but dependent
  on credentials, quotas and provider query dialects. A vault-backed provider
  abstraction is required.
- **CloudFox:** strong authorized white-box cloud situational awareness, but its
  credential/tenant boundary is different from black-box web recon and deserves
  a dedicated project/secret model.
- **TruffleHog/Gitleaks:** valuable for authorized repository inputs. Findings can
  contain live secrets, so object-store encryption, field redaction and access
  controls must land before ingestion.
- **WAFW00F:** complementary active WAF behavior testing, but httpx/CDNCheck
  provide lower-request first-pass attribution. Trigger deeper behavior only
  when attribution remains unknown.

## Methodology evidence matrix

| Evidence | Methodological contribution | Reconator consequence |
| --- | --- | --- |
| OWASP WSTG information gathering | inventory entry points and understand architecture, not only hosts | graph entities retain endpoints, technologies, evidence and dependencies |
| OWASP WSTG API reconnaissance | compare current/old schemas, undocumented routes/parameters, repositories, browser traffic and privilege-specific functionality | schema and multi-role browser capture are prioritized capability gaps; endpoint identity separates parameter names from values |
| MITRE ATT&CK Reconnaissance / T1595 | distinguishes direct active probing from non-interactive collection and separates IP, vulnerability and wordlist scanning | module interaction mode, authorization gate and active budgets remain explicit |
| NIST SP 800-115 | plan and conduct assessments while accounting for the benefits and limitations of each technique | profiles, predictable configuration, evidence, failure isolation and auditability are first-class |
| CISA Internet Exposure Reduction | use complementary indexes, assess business necessity/interdependencies, and repeat exposure assessment | continuous comparison, ownership correlation and provider diversity matter more than tool count |
| Amass and BBOT event models | discoveries recursively create typed events while retaining scope-distance semantics | normalized emissions create deduplicated tasks, but observations never silently widen active scope |

Interaction classification is deliberately more precise than “passive versus
active” in future work: local analysis, third-party target disclosure, direct
target requests, credentialed white-box collection and authenticated browser
capture have different privacy and authorization properties.

## Emerging and often-missed discovery surfaces

The following should be represented in the graph even when collection is not yet
automated:

- source maps and original webpack/Vite source trees;
- dynamic imports, import maps, service workers, web manifests and preload tags;
- browser-observed XHR/fetch, WebSocket, SSE and GraphQL operations;
- OpenAPI/AsyncAPI/WSDL/protobuf descriptors and API client collections;
- OAuth/OIDC discovery, SAML metadata, WebAuthn and alternate authentication
  domains;
- `security.txt`, asset links, Apple association files, MTA-STS, BIMI, CAA,
  TLS-RPT and other `.well-known`/policy artifacts;
- mobile application domains and public package/container registry namespaces;
- cloud tenant identifiers, storage endpoints, queue/webhook integrations and
  serverless routes embedded in JavaScript or IaC;
- certificate, favicon, response-similarity and historical-IP clusters that
  reveal renamed or unlinked applications;
- AI/LLM endpoints, model gateways, tool/plugin manifests and machine-facing
  APIs that are absent from normal navigation.

## Primary public references

- [OWASP WSTG information gathering and application architecture](https://wstg.owasp.org/latest/4-Web_Application_Security_Testing/01-Information_Gathering/10-Map_Application_Architecture/)
- [OWASP WSTG application entry-point identification](https://wstg.owasp.org/v4.2/4-Web_Application_Security_Testing/01-Information_Gathering/06-Identify_Application_Entry_Points/)
- [OWASP WSTG API reconnaissance](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/12-API_Testing/01-API_Reconnaissance)
- [MITRE ATT&CK Reconnaissance: active scanning](https://attack.mitre.org/techniques/T1595/)
- [NIST SP 800-115](https://csrc.nist.gov/pubs/sp/800/115/final)
- [CISA Internet Exposure Reduction Guidance](https://www.cisa.gov/resources-tools/resources/exposure-reduction)
- [OWASP Amass](https://github.com/owasp-amass/amass)
- [BBOT events and scope-distance model](https://github.com/blacklanternsecurity/bbot/blob/stable/docs/scanning/events.md)
- [Osmedeus orchestration and community workflows](https://github.com/osmedeus/osmedeus-workflow)
- [reconFTW](https://github.com/six2dez/reconftw)
- [ProjectDiscovery open-source documentation](https://docs.projectdiscovery.io/opensource)
- [Subfinder usage](https://docs.projectdiscovery.io/opensource/subfinder/usage)
- [DNSX usage and wildcard filtering](https://github.com/projectdiscovery/dnsx)
- [httpx usage](https://docs.projectdiscovery.io/opensource/httpx/usage)
- [Katana usage and scope controls](https://docs.projectdiscovery.io/opensource/katana/usage)
- [OWASP PureDNS wildcard and validation methodology](https://github.com/d3mondev/puredns)
- [AlterX pattern-aware DNS mutations](https://github.com/projectdiscovery/alterx)
- [URLFinder](https://github.com/projectdiscovery/urlfinder)
- [jsluice AST extraction](https://github.com/BishopFox/jsluice)
- [Kiterunner contextual API route discovery](https://github.com/assetnote/kiterunner)
- [Assetnote continuously generated wordlists](https://wordlists.assetnote.io/)
- [CDNCheck provider classification](https://github.com/projectdiscovery/cdncheck)
- [Uncover internet search providers](https://github.com/projectdiscovery/uncover)
- [CloudFox](https://github.com/BishopFox/cloudfox)
- [TruffleHog](https://github.com/trufflesecurity/trufflehog)
