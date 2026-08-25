import json

from app.core.network import PinnedHTTPResponse
from app.db.models import AssetKind
from app.recon.modules import builtin
from app.recon.modules.base import ModuleContext
from app.recon.normalization import normalize_asset


def _context(kind: str, value: str, config=None) -> ModuleContext:
    return ModuleContext(
        target_id=1,
        task_id=1,
        input_asset=normalize_asset(kind, value),
        config=config or {},
        timeout_seconds=30,
    )


def test_mx_parser_models_mail_infrastructure_and_preference():
    result = builtin._parse_domain_dns_record(
        "10 mail.example.net.\n20 backup.example.net.\n",
        _context("domain", "example.com"),
        record_type="MX",
        relationship_type="receives_mail_via",
    )

    assert [asset.value for asset in result.assets] == [
        "mail.example.net",
        "backup.example.net",
    ]
    assert result.assets[0].attributes["preference"] == 10
    assert all(
        relationship.relationship_type == "receives_mail_via"
        for relationship in result.relationships
    )


def test_txt_record_identity_preserves_case():
    lower = normalize_asset(AssetKind.dns_record, "verification=AbCd")
    upper = normalize_asset(AssetKind.dns_record, "verification=ABCD")
    assert lower.canonical_value == "verification=AbCd"
    assert lower.identity_hash != upper.identity_hash


def test_javascript_analysis_extracts_endpoints_without_retaining_source(monkeypatch):
    body = b"""fetch("/api/v1/users?role=admin");
    const graph = "https://api.example.com/graphql?operation=viewer";
    const client_secret = "do-not-retain-this-value";"""
    response = PinnedHTTPResponse(
        status_code=200,
        reason="OK",
        headers={"content-type": "application/javascript; charset=utf-8"},
        body=body,
        url="https://app.example.com/static/app.js",
        resolved_addresses=("93.184.216.34",),
    )
    monkeypatch.setattr(builtin, "pinned_http_request", lambda *_args, **_kwargs: response)

    result = builtin.JavaScriptEndpointModule().execute(
        _context("javascript", "https://app.example.com/static/app.js")
    )

    endpoint_values = {
        asset.canonical_value
        if hasattr(asset, "canonical_value")
        else normalize_asset(asset.kind, asset.value).canonical_value
        for asset in result.assets
        if asset.kind == AssetKind.endpoint.value
    }
    assert endpoint_values == {
        "GET https://api.example.com/graphql",
        "GET https://app.example.com/api/v1/users",
    }
    assert {asset.value for asset in result.assets if asset.kind == "parameter"} == {
        "operation",
        "role",
    }
    assert result.metadata["potential_secret_patterns"] == 1
    assert result.raw_output is None


def test_http_probe_reuses_fetched_openapi_body_for_graph_intelligence():
    body = json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "fixture", "version": "1"},
            "paths": {
                "/users/{id}": {
                    "get": {
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    ).encode()
    response = PinnedHTTPResponse(
        status_code=200,
        reason="OK",
        headers={"content-type": "application/json; charset=utf-8"},
        body=body,
        url="https://api.example.invalid/openapi.json",
        resolved_addresses=("192.0.2.10",),
    )

    result = builtin.HTTPProbeModule._result(
        _context("url", "https://api.example.invalid/openapi.json"), response
    )

    assert "GET https://api.example.invalid/users/%7Bid%7D" in {
        asset.value for asset in result.assets if asset.kind == AssetKind.endpoint.value
    }
    assert "path:id" in {
        asset.value for asset in result.assets if asset.kind == AssetKind.parameter.value
    }
    assert result.metadata["openapi_parse_status"] == "parsed"
    assert result.metadata["openapi_parse_error_code"] is None
    assert result.metadata["openapi"]["network_requests"] == 0
    assert result.metadata["openapi"]["operations_processed"] == 1
    assert set(result.metadata["openapi_detection_signals"]) == {
        "document_path",
        "structured_content_type",
        "document_body_marker",
    }
    assert {"auth_scheme", "callback", "webhook"} <= builtin.HTTPProbeModule.manifest.produces


def test_http_probe_does_not_parse_unmarked_json():
    response = PinnedHTTPResponse(
        status_code=200,
        reason="OK",
        headers={"content-type": "application/json"},
        body=b'{"items": [1, 2, 3]}',
        url="https://api.example.invalid/data.json",
        resolved_addresses=("192.0.2.10",),
    )

    result = builtin.HTTPProbeModule._result(
        _context("url", "https://api.example.invalid/data.json"), response
    )

    assert result.metadata["openapi_parse_status"] == "not_detected"
    assert result.metadata["openapi_parse_error_code"] is None
    assert not [asset for asset in result.assets if asset.kind == AssetKind.endpoint.value]


def test_http_probe_keeps_invalid_openapi_parse_failure_non_fatal():
    response = PinnedHTTPResponse(
        status_code=200,
        reason="OK",
        headers={"content-type": "application/json"},
        body=b'{"openapi": "3.0.3", "paths": ',
        url="https://api.example.invalid/openapi.json",
        resolved_addresses=("192.0.2.10",),
    )

    result = builtin.HTTPProbeModule._result(
        _context("url", "https://api.example.invalid/openapi.json"), response
    )

    assert result.metadata["openapi_parse_status"] == "rejected"
    assert result.metadata["openapi_parse_error_code"] == "invalid_openapi_document"
    assert [asset.kind for asset in result.assets] == [AssetKind.url.value]


def test_http_probe_does_not_ingest_a_truncated_openapi_document():
    response = PinnedHTTPResponse(
        status_code=200,
        reason="OK",
        headers={"content-type": "application/vnd.oai.openapi+json"},
        body=b'{"openapi": "3.0.3"',
        url="https://api.example.invalid/spec",
        resolved_addresses=("192.0.2.10",),
        truncated=True,
    )

    result = builtin.HTTPProbeModule._result(
        _context("url", "https://api.example.invalid/spec"), response
    )

    assert result.metadata["openapi_parse_status"] == "skipped_truncated"
    assert result.metadata["openapi_parse_error_code"] == "response_truncated"
    assert [asset.kind for asset in result.assets] == [AssetKind.url.value]


def test_http_probe_isolates_unexpected_openapi_parser_failures(monkeypatch):
    response = PinnedHTTPResponse(
        status_code=200,
        reason="OK",
        headers={"content-type": "application/vnd.oai.openapi+yaml"},
        body=b"openapi: 3.0.3\npaths: {}\n",
        url="https://api.example.invalid/spec",
        resolved_addresses=("192.0.2.10",),
    )

    def fail_parser(*_args, **_kwargs):
        raise RuntimeError("isolated parser failure")

    monkeypatch.setattr(builtin, "parse_openapi_document", fail_parser)
    result = builtin.HTTPProbeModule._result(
        _context("url", "https://api.example.invalid/spec"), response
    )

    assert result.metadata["openapi_parse_status"] == "error"
    assert result.metadata["openapi_parse_error_code"] == "openapi_parser_error"
    assert [asset.kind for asset in result.assets] == [AssetKind.url.value]


def test_http_probe_detects_root_yaml_marker_without_relying_on_a_filename():
    detected, signals = builtin._detect_openapi_document(
        "https://api.example.invalid/specification",
        "text/plain",
        "openapi: 3.1.0\ninfo: {title: fixture, version: '1'}\npaths: {}\n",
    )

    assert detected is True
    assert signals == ("document_body_marker",)


def test_certificate_transparency_paginates_until_empty(monkeypatch):
    calls: list[str | None] = []
    pages = {
        None: [{"id": 10, "dns_names": ["api.example.com", "*.wild.example.com"]}],
        "10": [{"id": 20, "dns_names": ["api.example.com", "admin.example.com"]}],
        "20": [],
    }

    class FakeResponse:
        def __init__(self, records):
            self.payload = json.dumps(records).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def raise_for_status():
            return None

        def iter_bytes(self):
            yield self.payload

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, _method, _endpoint, *, params, timeout):
            assert timeout > 0
            cursor = params.get("after")
            calls.append(cursor)
            return FakeResponse(pages[cursor])

    monkeypatch.setattr(builtin.httpx, "Client", FakeClient)

    result = builtin.CertificateTransparencyModule().execute(
        _context("domain", "example.com", {"max_pages": 5})
    )

    assert calls == [None, "10", "20"]
    assert {asset.value for asset in result.assets} == {
        "admin.example.com",
        "api.example.com",
        "wild.example.com",
    }
    assert result.metadata == {
        "certificate_names": 3,
        "issuances_processed": 2,
        "pages_fetched": 3,
        "pagination_truncated": False,
        "last_cursor": "20",
    }
