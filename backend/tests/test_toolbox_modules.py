import json
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.network import PinnedHTTPResponse
from app.db.models import AssetKind
from app.recon.modules.base import ModuleContext, ModuleExecutionError
from app.recon.modules.toolbox import (
    AlterXModule,
    CDNCheckModule,
    DNSXModule,
    HTTPXModule,
    JSLuiceModule,
    KatanaModule,
    NaabuModule,
    SubfinderModule,
    ToolboxClient,
    ToolboxExecution,
    URLFinderModule,
)
from app.recon.normalization import normalize_asset


def context(kind: str, value: str, config: dict | None = None) -> ModuleContext:
    return ModuleContext(
        target_id=1,
        task_id=2,
        input_asset=normalize_asset(kind, value),
        config=config or {},
        timeout_seconds=120,
    )


def execution(tool: str, records: list[dict] | None = None, stdout: str | None = None):
    output = stdout if stdout is not None else "\n".join(json.dumps(item) for item in records or [])
    return ToolboxExecution(
        tool=tool,
        version="test",
        exit_code=0,
        stdout=output,
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=1.5,
    )


def test_toolbox_catalog_availability_does_not_require_execution_secret(monkeypatch):
    client = ToolboxClient()
    monkeypatch.setattr(settings, "toolbox_enabled", True)
    monkeypatch.setattr(settings, "toolbox_url", "http://toolbox:7777")
    monkeypatch.setattr(settings, "toolbox_shared_secret", None)

    assert client.available() is True
    with pytest.raises(ModuleExecutionError, match="not configured"):
        client.execute(tool="subfinder", input_value="example.com", config={}, timeout=1)


def test_subfinder_preserves_sources_and_filters_unrelated_domains():
    module = SubfinderModule()
    result_data = execution(
        "subfinder",
        [
            {"host": "api.example.com", "sources": ["crtsh", "alienvault"]},
            {"host": "api.example.com", "source": "duplicate"},
            {"host": "unrelated.test", "source": "poisoned"},
        ],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.domain.value, "example.com"))

    assert [(asset.kind, asset.value) for asset in result.assets] == [("domain", "api.example.com")]
    assert result.assets[0].attributes["passive_sources"] == [
        "alienvault",
        "crtsh",
        "duplicate",
    ]
    assert result.metadata["provider_counts"] == {
        "alienvault": 1,
        "crtsh": 1,
        "duplicate": 1,
    }
    assert result.relationships[0].relationship_type == "has_subdomain"


def test_dnsx_promotes_only_answered_names_and_preserves_record_evidence():
    module = DNSXModule()
    result_data = execution(
        "dnsx",
        [
            {
                "host": "candidate.authorized.invalid",
                "status_code": "NOERROR",
                "ttl": 300,
                "resolver": ["1.1.1.1:53"],
                "query-time": "12ms",
                "a": ["8.8.8.8", "10.0.0.5", "not-an-address"],
                "aaaa": ["2606:4700:4700::1111"],
                "cname": ["edge.authorized.invalid."],
                "ns": ["ns1.authorized.invalid."],
                "mx": ["10 mail.authorized.invalid."],
                "txt": ["v=spf1 -all"],
                "caa": [{"flag": 0, "tag": "issue", "value": "ca.invalid"}],
            },
            {
                "host": "poisoned.invalid",
                "status_code": "NOERROR",
                "a": ["9.9.9.9"],
            },
        ],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.domain.value, "candidate.authorized.invalid"))

    identities = {(asset.kind, asset.value) for asset in result.assets}
    assert ("ip_address", "8.8.8.8") in identities
    assert ("ip_address", "2606:4700:4700::1111") in identities
    assert ("ip_address", "10.0.0.5") not in identities
    assert ("domain", "edge.authorized.invalid") in identities
    assert ("dns_record", "TXT v=spf1 -all") in identities
    promoted = next(
        asset
        for asset in result.assets
        if asset.kind == "domain" and asset.value == "candidate.authorized.invalid"
    )
    assert promoted.attributes["validated"] is True
    assert promoted.source_name == "dnsx"
    address = next(asset for asset in result.assets if asset.value == "8.8.8.8")
    assert address.evidence["resolvers"] == ["1.1.1.1:53"]
    assert address.evidence["wildcard_filter"] == "automatic"
    assert result.metadata["private_answers_filtered"] == 1
    assert result.metadata["rejected_output_records"] == 2
    assert {relationship.relationship_type for relationship in result.relationships} >= {
        "resolves_to",
        "aliases_to",
        "uses_nameserver",
        "receives_mail_via",
        "publishes_dns_record",
    }


def test_dnsx_does_not_promote_nodata_or_unsafe_private_only_answers():
    module = DNSXModule()
    result_data = execution(
        "dnsx",
        [
            {
                "host": "candidate.authorized.invalid",
                "status_code": "NOERROR",
                "a": ["10.0.0.5"],
            },
            {
                "host": "candidate.authorized.invalid",
                "status_code": "NXDOMAIN",
                "a": ["8.8.8.8"],
            },
        ],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.domain.value, "candidate.authorized.invalid"))

    assert result.metadata["validated"] is False
    assert result.metadata["private_answers_filtered"] == 1
    assert not result.assets


def test_dnsx_private_answers_require_explicit_module_authorization():
    module = DNSXModule()
    result_data = execution(
        "dnsx",
        [
            {
                "host": "internal.authorized.invalid",
                "status_code": "NOERROR",
                "a": ["10.0.0.5"],
            }
        ],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(
            context(
                AssetKind.domain.value,
                "internal.authorized.invalid",
                {"allow_private_networks": True},
            )
        )

    assert result.metadata["validated"] is True
    assert any(asset.value == "10.0.0.5" for asset in result.assets)


def test_urlfinder_distinguishes_javascript_and_keeps_source_provenance():
    module = URLFinderModule()
    result_data = execution(
        "urlfinder",
        [
            {"url": "https://app.example.com/app.js?v=1", "source": "waybackarchive"},
            {"url": "https://app.example.com/login", "source": "commoncrawl"},
            {"url": "https://third-party.test/tracker.js", "source": "waybackarchive"},
        ],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.domain.value, "example.com"))

    assert {asset.kind for asset in result.assets} == {"domain", "javascript", "url"}
    assert {asset.source_name for asset in result.assets} == {
        "urlfinder",
        "waybackarchive",
        "commoncrawl",
    }
    host = next(asset for asset in result.assets if asset.kind == "domain")
    assert host.value == "app.example.com"
    assert host.attributes["candidate"] is True
    assert host.attributes["validated"] is False
    assert result.metadata["historical_hosts"] == 1
    assert {item.relationship_type for item in result.relationships} == {
        "historically_exposed",
        "historically_referenced",
    }


def test_httpx_maps_tls_infrastructure_and_technology_to_graph_entities():
    module = HTTPXModule()
    fingerprint = "a" * 64
    result_data = execution(
        "httpx",
        [
            {
                "url": "https://www.example.com/",
                "status_code": 200,
                "title": "Example",
                "content_type": "text/html",
                "webserver": "nginx",
                "host_ip": "93.184.216.34",
                "cname": ["edge.example.net"],
                "tech": ["Nginx", "React"],
                "cdn_name": "cloudflare",
                "asn": {"as_number": "AS64500", "as_name": "Example Network"},
                "tls": {
                    "fingerprint_hash": {"sha256": fingerprint},
                    "subject_an": ["www.example.com", "api.example.com"],
                },
            }
        ],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.domain.value, "www.example.com"))

    identities = {(asset.kind, asset.value) for asset in result.assets}
    assert ("url", "https://www.example.com/") in identities
    assert ("ip_address", "93.184.216.34") in identities
    assert ("autonomous_system", "AS64500") in identities
    assert ("certificate", fingerprint) in identities
    assert ("domain", "api.example.com") in identities
    relationship_types = {item.relationship_type for item in result.relationships}
    assert {
        "uses_technology",
        "fronted_by",
        "announced_by",
        "registered_to",
        "presents_certificate",
    } <= (relationship_types)


def test_httpx_models_ip_literal_hosts_without_creating_domain_references():
    module = HTTPXModule()
    result_data = execution(
        "httpx",
        [{"url": "http://93.184.216.34/", "host_ip": "93.184.216.34"}],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.url.value, "http://93.184.216.34/"))

    assert not any(asset.kind == "domain" for asset in result.assets)
    assert not any(relationship.source.kind == "domain" for relationship in result.relationships)


def test_katana_enforces_same_host_and_models_methods_and_parameters():
    module = KatanaModule()
    result_data = execution(
        "katana",
        [
            {
                "request": {
                    "endpoint": "https://app.example.com/api/users?id=7",
                    "method": "POST",
                },
                "response": {"status_code": 200, "technologies": ["FastAPI"]},
            },
            {"request": {"endpoint": "https://outside.test/ignored", "method": "GET"}},
            {
                "request": {
                    "endpoint": "https://app.example.com/unreachable",
                    "method": "GET",
                },
                "error": "no address found for host",
            },
        ],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.url.value, "https://app.example.com/"))

    assert any(
        asset.kind == "endpoint" and asset.value.startswith("POST ") for asset in result.assets
    )
    assert any(asset.kind == "parameter" and asset.value == "id" for asset in result.assets)
    assert any(asset.kind == "technology" and asset.value == "FastAPI" for asset in result.assets)
    assert all("outside.test" not in asset.value for asset in result.assets)
    assert all("unreachable" not in asset.value for asset in result.assets)


def test_naabu_only_accepts_results_for_requested_address():
    module = NaabuModule()
    result_data = execution(
        "naabu",
        [
            {"ip": "93.184.216.34", "port": 443},
            {"ip": "93.184.216.34", "port": 443},
            {"ip": "198.51.100.4", "port": 22},
        ],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.ip_address.value, "93.184.216.34"))

    assert {(asset.kind, asset.value) for asset in result.assets} == {
        ("port", "tcp/443"),
        ("service", "tcp://93.184.216.34:443"),
    }


def test_jsluice_uses_core_safe_fetch_then_maps_ast_results():
    module = JSLuiceModule()
    response = PinnedHTTPResponse(
        status_code=200,
        reason="OK",
        headers={"content-type": "application/javascript"},
        body=b"fetch('/api/users?id=' + userId)",
        url="https://app.example.com/app.js",
        resolved_addresses=("93.184.216.34",),
    )
    result_data = execution(
        "jsluice",
        [
            {
                "url": "https://app.example.com/api/users?id=EXPR",
                "method": "GET",
                "queryParams": ["id"],
                "bodyParams": [],
                "type": "fetch",
            }
        ],
    )
    with (
        patch("app.recon.modules.toolbox.pinned_http_request", return_value=response),
        patch.object(module, "_execute", return_value=result_data) as remote_execute,
    ):
        result = module.execute(
            context(AssetKind.javascript.value, "https://app.example.com/app.js")
        )

    assert remote_execute.call_args.kwargs["payload"] == response.body
    assert any(asset.kind == "endpoint" for asset in result.assets)
    assert any(asset.kind == "parameter" and asset.value == "id" for asset in result.assets)


def test_jsluice_resolves_relative_ast_endpoints_against_script_url():
    module = JSLuiceModule()
    response = PinnedHTTPResponse(
        status_code=200,
        reason="OK",
        headers={"content-type": "application/javascript"},
        body=b"fetch('/v2/me')",
        url="https://app.example.com/static/app.js",
        resolved_addresses=("93.184.216.34",),
    )
    with (
        patch("app.recon.modules.toolbox.pinned_http_request", return_value=response),
        patch.object(
            module,
            "_execute",
            return_value=execution(
                "jsluice", [{"url": "/v2/me", "method": "GET", "type": "fetch"}]
            ),
        ),
    ):
        result = module.execute(
            context(AssetKind.javascript.value, "https://app.example.com/static/app.js")
        )

    assert any(
        asset.kind == "endpoint" and asset.value == "GET https://app.example.com/v2/me"
        for asset in result.assets
    )


def test_alterx_candidates_are_low_confidence_and_bounded():
    module = AlterXModule()
    result_data = execution(
        "alterx",
        stdout="api-dev.example.com\napi-stage.example.com\nnot a domain\n",
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(
            context(AssetKind.domain.value, "api.example.com", {"max_mutations": 2})
        )

    assert len(result.assets) == 2
    assert all(asset.confidence == 0.2 for asset in result.assets)
    assert all(asset.attributes["validated"] is False for asset in result.assets)


def test_cdncheck_normalizes_classification_categories():
    module = CDNCheckModule()
    result_data = execution(
        "cdncheck",
        [{"ip": "93.184.216.34", "cdn_name": "cloudflare", "cloud_name": "aws"}],
    )
    with patch.object(module, "_execute", return_value=result_data):
        result = module.execute(context(AssetKind.ip_address.value, "93.184.216.34"))

    assert {(asset.kind, asset.value) for asset in result.assets} == {
        ("technology", "cdn:cloudflare"),
        ("technology", "cloud:aws"),
    }
