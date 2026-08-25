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
