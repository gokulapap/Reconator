from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db.models import AssetKind
from app.recon.modules.base import ModuleContext, ModuleExecutionError
from app.recon.modules.openapi import (
    OpenAPIIntelligenceModule,
    OpenAPILimits,
    OpenAPIParseError,
    parse_openapi_document,
)
from app.recon.normalization import normalize_asset

FIXTURES = Path(__file__).parent / "fixtures" / "openapi"


def _values(result: object, kind: str) -> set[str]:
    return {asset.value for asset in result.assets if asset.kind == kind}


def _safe_serialization(result: object) -> str:
    return json.dumps(
        {
            "assets": [
                {
                    "kind": asset.kind,
                    "value": asset.value,
                    "attributes": asset.attributes,
                    "evidence": asset.evidence,
                }
                for asset in result.assets
            ],
            "relationships": [
                {
                    "source": relationship.source.value,
                    "target": relationship.target.value,
                    "attributes": relationship.attributes,
                    "evidence": relationship.evidence,
                }
                for relationship in result.relationships
            ],
            "metadata": result.metadata,
        },
        sort_keys=True,
    )


def test_openapi_yaml_extracts_normalized_graph_without_secret_values() -> None:
    result = parse_openapi_document(
        "https://docs.example.invalid/openapi.yaml?token=source-secret",
        (FIXTURES / "api.yaml").read_bytes(),
    )

    endpoints = _values(result, AssetKind.endpoint.value)
    assert "GET https://eu.api.example.invalid/v1/users/%7Bid%7D" in endpoints
    assert "POST https://eu.api.example.invalid/v1/users/%7Bid%7D" in endpoints
    assert "GET https://eu.api.example.invalid/v1/external" in endpoints
    assert {
        "path:id",
        "query:cursor",
        "body:email",
        "body:token",
        "body:profile",
        "body:profile.displayName",
    } <= _values(result, AssetKind.parameter.value)
    assert len(_values(result, "auth_scheme")) == 2
    assert len(_values(result, "callback")) == 1
    assert len(_values(result, "webhook")) == 1
    relationship_types = {item.relationship_type for item in result.relationships}
    assert {
        "declares_api_server",
        "describes_endpoint",
        "accepts_parameter",
        "requires_auth",
        "declares_callback",
        "describes_webhook",
    } <= relationship_types
    assert result.metadata == {
        "document_format": "yaml",
        "document_version": "3.1.0",
        "source_url": "https://docs.example.invalid/openapi.yaml?token=%5BREDACTED%5D",
        "paths_processed": 2,
        "operations_processed": 5,
        "parameters_emitted": 7,
        "servers_processed": 1,
        "callbacks_processed": 1,
        "webhooks_processed": 1,
        "local_refs_seen": 1,
        "remote_refs_ignored": 1,
        "unresolved_local_refs": 0,
        "truncated": False,
        "network_requests": 0,
    }
    serialized = _safe_serialization(result)
    assert "source-secret" not in serialized
    assert "do-not-store-this" not in serialized
    assert "private@example.invalid" not in serialized
    assert "token=%5BREDACTED%5D" in serialized


def test_swagger_json_extracts_server_parameter_and_api_key_auth() -> None:
    result = parse_openapi_document(
        "https://docs.example.invalid/swagger.json",
        (FIXTURES / "swagger.json").read_text(),
    )

    assert "GET https://legacy.api.example.invalid/v2/pets" in _values(
        result, AssetKind.endpoint.value
    )
    assert "query:limit" in _values(result, AssetKind.parameter.value)
    auth = next(asset for asset in result.assets if asset.kind == "auth_scheme")
    assert auth.attributes == {
        "name": "apiKey",
        "type": "apiKey",
        "location": "header",
        "parameter_name": "X-API-Key",
    }
    assert result.metadata["document_format"] == "json"
    assert result.metadata["document_version"] == "2.0"
    assert "do-not-store-this-key" not in _safe_serialization(result)


def test_remote_references_are_counted_and_never_resolved() -> None:
    body = """
openapi: 3.0.3
info: {title: fixture, version: '1'}
paths:
  /items:
    get:
      parameters:
        - $ref: https://remote.example.invalid/parameter.yaml
"""
    result = parse_openapi_document("https://api.example.invalid/openapi.yaml", body)

    assert result.metadata["remote_refs_ignored"] == 1
    assert not _values(result, AssetKind.parameter.value)
    assert result.metadata["network_requests"] == 0


def test_yaml_alias_and_document_limits_fail_closed() -> None:
    aliases = """
openapi: 3.0.3
info: &shared {title: fixture, version: '1'}
x-copy-one: *shared
x-copy-two: *shared
paths: {}
"""
    with pytest.raises(OpenAPIParseError, match="alias limit"):
        parse_openapi_document(
            "https://api.example.invalid/openapi.yaml",
            aliases,
            limits=OpenAPILimits(max_yaml_aliases=1),
        )
    with pytest.raises(OpenAPIParseError, match="byte limit"):
        parse_openapi_document(
            "https://api.example.invalid/openapi.json",
            '{"openapi":"3.0.0"}',
            limits=OpenAPILimits(max_document_bytes=10),
        )
    with pytest.raises(OpenAPIParseError, match="nesting limit"):
        parse_openapi_document(
            "https://api.example.invalid/openapi.json",
            '{"openapi":"3.0.0","info":{"x":{"y":1}},"paths":{}}',
            limits=OpenAPILimits(max_nesting_depth=3),
        )


def test_path_budget_truncates_and_operation_budget_rejects() -> None:
    body = json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "fixture", "version": "1"},
            "paths": {
                "/one": {"get": {"responses": {}}},
                "/two": {"post": {"responses": {}}},
            },
        }
    )
    result = parse_openapi_document(
        "https://api.example.invalid/openapi.json",
        body,
        limits=OpenAPILimits(max_paths=1),
    )
    assert result.metadata["paths_processed"] == 1
    assert result.metadata["truncated"] is True
    with pytest.raises(OpenAPIParseError, match="operation limit"):
        parse_openapi_document(
            "https://api.example.invalid/openapi.json",
            body,
            limits=OpenAPILimits(max_operations=1),
        )


def test_module_adapter_requires_an_already_fetched_document() -> None:
    module = OpenAPIIntelligenceModule()
    context = ModuleContext(
        target_id=1,
        task_id=2,
        input_asset=normalize_asset(AssetKind.url, "https://api.example.invalid/openapi.json"),
        config={},
        timeout_seconds=30,
    )

    with pytest.raises(ModuleExecutionError) as exc_info:
        module.execute(context)
    assert exc_info.value.retryable is False
    assert exc_info.value.code == "invalid_openapi_document"
