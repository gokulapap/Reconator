from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode

from app.db.models import AssetKind
from app.recon.modules.base import (
    AssetEmission,
    AssetReference,
    ModuleContext,
    ModuleExecutionError,
    ModuleManifest,
    ModuleMode,
    ModuleResult,
    RelationshipEmission,
)
from app.recon.normalization import NormalizationError, normalize_asset

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
_SENSITIVE_NAME = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|auth|authorization|client[_-]?secret|credential|jwt|"
    r"password|private[_-]?key|secret|session|signature|token)(?:$|[_-])",
    re.IGNORECASE,
)
_SERVER_VARIABLE = re.compile(r"\{([^{}]{1,128})\}")
_PATH_VARIABLE = re.compile(r"\{([^{}]{1,128})\}")
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class OpenAPIParseError(ValueError):
    """A bounded, non-retryable OpenAPI document parsing failure."""


@dataclass(frozen=True, slots=True)
class OpenAPILimits:
    max_document_bytes: int = 2_000_000
    max_nesting_depth: int = 40
    max_nodes: int = 100_000
    max_yaml_aliases: int = 16
    max_paths: int = 10_000
    max_operations: int = 50_000
    max_parameters: int = 100_000
    max_servers: int = 256
    max_server_variants_per_operation: int = 8
    max_callbacks: int = 1_000
    max_webhooks: int = 1_000
    max_schema_depth: int = 8
    max_assets: int = 100_000
    max_relationships: int = 200_000

    def __post_init__(self) -> None:
        hard_limits = _hard_limits()
        for item in fields(self):
            value = getattr(self, item.name)
            if not isinstance(value, int) or value < 1 or value > hard_limits[item.name]:
                raise ValueError(f"{item.name} must be between 1 and {hard_limits[item.name]}")

    @classmethod
    def from_config(cls, value: object) -> OpenAPILimits:
        if not isinstance(value, dict):
            return cls()
        defaults = cls()
        configured: dict[str, int] = {}
        for item in fields(defaults):
            candidate = value.get(item.name)
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                # Scan configuration may make a parser stricter, never less bounded.
                configured[item.name] = min(candidate, getattr(defaults, item.name))
        return cls(**configured)


def _hard_limits() -> dict[str, int]:
    return {
        "max_document_bytes": 4_000_000,
        "max_nesting_depth": 64,
        "max_nodes": 200_000,
        "max_yaml_aliases": 32,
        "max_paths": 20_000,
        "max_operations": 100_000,
        "max_parameters": 200_000,
        "max_servers": 512,
        "max_server_variants_per_operation": 16,
        "max_callbacks": 2_000,
        "max_webhooks": 2_000,
        "max_schema_depth": 16,
        "max_assets": 200_000,
        "max_relationships": 400_000,
    }


class _BoundedYAMLLoader(yaml.BaseLoader):
    def __init__(self, stream: str, limits: OpenAPILimits) -> None:
        super().__init__(stream)
        self._limits = limits
        self._alias_count = 0
        self._compose_depth = 0
        self._node_count = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            self._alias_count += 1
            if self._alias_count > self._limits.max_yaml_aliases:
                raise OpenAPIParseError("OpenAPI YAML alias limit exceeded")
        self._compose_depth += 1
        if self._compose_depth > self._limits.max_nesting_depth:
            raise OpenAPIParseError("OpenAPI document nesting limit exceeded")
        try:
            node = super().compose_node(parent, index)
        finally:
            self._compose_depth -= 1
        self._node_count += 1
        if self._node_count > self._limits.max_nodes:
            raise OpenAPIParseError("OpenAPI document node limit exceeded")
        return node

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[str, Any]:
        if not isinstance(node, MappingNode):
            raise OpenAPIParseError("OpenAPI YAML contains an invalid mapping")
        mapping: dict[str, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise OpenAPIParseError("OpenAPI YAML mapping keys must be strings")
            if key in mapping:
                raise OpenAPIParseError(f"OpenAPI YAML contains duplicate key: {key[:100]}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


@dataclass(slots=True)
class _ParseState:
    limits: OpenAPILimits
    source_url: str
    version: str
    document: dict[str, Any]
    assets: dict[tuple[str, str], AssetEmission]
    relationships: dict[tuple[str, str, str, str, str], RelationshipEmission]
    local_refs: int = 0
    remote_refs: int = 0
    unresolved_refs: int = 0
    paths: int = 0
    operations: int = 0
    parameters: int = 0
    servers: int = 0
    callbacks: int = 0
    webhooks: int = 0
    truncated: bool = False

    def evidence(self, pointer: str) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "document_version": self.version,
            "pointer": pointer[:1_024],
        }

    def add_asset(
        self,
        kind: str,
        value: str,
        attributes: dict[str, Any],
        pointer: str,
        *,
        confidence: float = 1.0,
    ) -> AssetReference | None:
        if len(self.assets) >= self.limits.max_assets:
            self.truncated = True
            return None
        try:
            normalized = normalize_asset(kind, value, attributes)
        except NormalizationError:
            return None
        key = (kind, normalized.canonical_value)
        self.assets.setdefault(
            key,
            AssetEmission(
                kind=kind,
                value=normalized.canonical_value,
                attributes=normalized.attributes,
                confidence=confidence,
                evidence=self.evidence(pointer),
                source_name="openapi",
            ),
        )
        return AssetReference(kind, normalized.canonical_value)

    def relate(
        self,
        source: AssetReference,
        target: AssetReference | None,
        relationship_type: str,
        pointer: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if target is None:
            return
        if len(self.relationships) >= self.limits.max_relationships:
            self.truncated = True
            return
        key = (
            source.kind,
            source.value,
            target.kind,
            target.value,
            relationship_type,
        )
        self.relationships.setdefault(
            key,
            RelationshipEmission(
                source=source,
                target=target,
                relationship_type=relationship_type,
                attributes=attributes or {},
                evidence=self.evidence(pointer),
            ),
        )


def _bounded_json_load(text: str, limits: OpenAPILimits) -> Any:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > limits.max_nesting_depth:
                raise OpenAPIParseError("OpenAPI document nesting limit exceeded")
        elif character in "]}":
            depth -= 1

    def unique_mapping(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        for key, value in pairs:
            if key in mapping:
                raise OpenAPIParseError(f"OpenAPI JSON contains duplicate key: {key[:100]}")
            mapping[key] = value
        return mapping

    try:
        return json.loads(text, object_pairs_hook=unique_mapping)
    except OpenAPIParseError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise OpenAPIParseError("OpenAPI JSON is invalid") from exc


def _bounded_yaml_load(text: str, limits: OpenAPILimits) -> Any:
    loader = _BoundedYAMLLoader(text, limits)
    try:
        return loader.get_single_data()
    except OpenAPIParseError:
        raise
    except yaml.YAMLError as exc:
        raise OpenAPIParseError("OpenAPI YAML is invalid") from exc
    finally:
        loader.dispose()


def _validate_tree(root: Any, limits: OpenAPILimits) -> None:
    stack: list[tuple[Any, int]] = [(root, 1)]
    seen_containers: set[int] = set()
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > limits.max_nodes:
            raise OpenAPIParseError("OpenAPI document node limit exceeded")
        if depth > limits.max_nesting_depth:
            raise OpenAPIParseError("OpenAPI document nesting limit exceeded")
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen_containers:
                continue
            seen_containers.add(identity)
            if any(not isinstance(key, str) for key in value):
                raise OpenAPIParseError("OpenAPI mapping keys must be strings")
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            identity = id(value)
            if identity in seen_containers:
                continue
            seen_containers.add(identity)
            stack.extend((child, depth + 1) for child in value)
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise OpenAPIParseError("OpenAPI document contains an unsupported value")


def _load_document(body: bytes | str, limits: OpenAPILimits) -> tuple[dict[str, Any], str]:
    if isinstance(body, str):
        encoded = body.encode("utf-8")
    elif isinstance(body, bytes):
        encoded = body
    else:
        raise OpenAPIParseError("OpenAPI body must be bytes or text")
    if len(encoded) > limits.max_document_bytes:
        raise OpenAPIParseError("OpenAPI document byte limit exceeded")
    try:
        text = encoded.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OpenAPIParseError("OpenAPI document must be UTF-8") from exc
    stripped = text.lstrip()
    if not stripped:
        raise OpenAPIParseError("OpenAPI document is empty")
    document_format = "json" if stripped.startswith(("{", "[")) else "yaml"
    loaded = (
        _bounded_json_load(text, limits)
        if document_format == "json"
        else _bounded_yaml_load(text, limits)
    )
    _validate_tree(loaded, limits)
    if not isinstance(loaded, dict):
        raise OpenAPIParseError("OpenAPI document root must be an object")
    return loaded, document_format


def _string(value: object, *, max_length: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:max_length] if cleaned else None


def _bool(value: object) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _resolve_ref(value: object, state: _ParseState) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    current = value
    seen_refs: set[str] = set()
    for _ in range(state.limits.max_nesting_depth):
        reference = current.get("$ref")
        if reference is None:
            return current
        if not isinstance(reference, str) or not reference.startswith("#/"):
            state.remote_refs += 1
            return None
        if reference in seen_refs:
            state.unresolved_refs += 1
            return None
        seen_refs.add(reference)
        state.local_refs += 1
        resolved: Any = state.document
        tokens = reference[2:].split("/")
        if len(tokens) > state.limits.max_nesting_depth:
            state.unresolved_refs += 1
            return None
        for raw_token in tokens:
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if not isinstance(resolved, dict) or token not in resolved:
                state.unresolved_refs += 1
                return None
            resolved = resolved[token]
        if not isinstance(resolved, dict):
            state.unresolved_refs += 1
            return None
        current = resolved
    if "$ref" in current:
        state.unresolved_refs += 1
        return None
    return current


def _normal_url(value: str, source_url: str) -> str | None:
    absolute = urljoin(source_url, value)
    try:
        normalized = normalize_asset(AssetKind.url, absolute)
    except NormalizationError:
        return None
    if normalized.attributes.get("scheme") not in _ALLOWED_SCHEMES:
        return None
    return normalized.canonical_value


def _expand_server(server: object, source_url: str) -> str | None:
    if not isinstance(server, dict):
        return None
    raw_url = _string(server.get("url"), max_length=2_048)
    if raw_url is None:
        return None
    variables = server.get("variables") if isinstance(server.get("variables"), dict) else {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        definition = variables.get(name)
        if _SENSITIVE_NAME.search(name) or not isinstance(definition, dict):
            return ""
        default = _string(definition.get("default"), max_length=256)
        if default is None or _SENSITIVE_NAME.search(default):
            return ""
        return default

    expanded = _SERVER_VARIABLE.sub(replace, raw_url)
    if _SERVER_VARIABLE.search(expanded) or not expanded:
        return None
    return _normal_url(expanded, source_url)


def _swagger_server(document: dict[str, Any], source_url: str) -> str | None:
    parsed_source = urlsplit(source_url)
    schemes = document.get("schemes")
    scheme = parsed_source.scheme
    if isinstance(schemes, list):
        scheme = next(
            (
                item.lower()
                for item in schemes
                if isinstance(item, str) and item.lower() in _ALLOWED_SCHEMES
            ),
            scheme,
        )
    host = _string(document.get("host"), max_length=512) or parsed_source.netloc
    if not host or "@" in host:
        return None
    base_path = _string(document.get("basePath"), max_length=2_048) or "/"
    return _normal_url(urlunsplit((scheme, host, base_path, "", "")), source_url)


def _server_urls(
    declarations: object,
    state: _ParseState,
    fallback: list[str],
) -> list[str]:
    if not isinstance(declarations, list):
        return fallback
    output: list[str] = []
    for declaration in declarations:
        if state.servers >= state.limits.max_servers:
            state.truncated = True
            break
        state.servers += 1
        candidate = _expand_server(declaration, state.source_url)
        if candidate and candidate not in output:
            output.append(candidate)
    return output or fallback


def _join_endpoint(server: str, path: str) -> str | None:
    parsed = urlsplit(server)
    base = parsed.path.rstrip("/")
    combined_path = f"{base}/{path.lstrip('/')}"
    return _normal_url(urlunsplit((parsed.scheme, parsed.netloc, combined_path, "", "")), server)


def _schema_metadata(schema: object, state: _ParseState) -> dict[str, Any]:
    resolved = _resolve_ref(schema, state)
    if not resolved:
        return {}
    metadata: dict[str, Any] = {}
    for key in ("type", "format"):
        value = _string(resolved.get(key), max_length=64)
        if value:
            metadata[key] = value
    if isinstance(resolved.get("enum"), list):
        # Values can contain credentials; only retain the size as useful shape metadata.
        metadata["enum_size"] = min(len(resolved["enum"]), 10_000)
    return metadata


def _parameter_items(items: object, state: _ParseState) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    output: list[dict[str, Any]] = []
    for item in items:
        resolved = _resolve_ref(item, state)
        if resolved is not None:
            output.append(resolved)
    return output


def _emit_parameter(
    parameter: dict[str, Any],
    endpoint: AssetReference,
    pointer: str,
    state: _ParseState,
) -> None:
    if state.parameters >= state.limits.max_parameters:
        state.truncated = True
        return
    name = _string(parameter.get("name"), max_length=256)
    location = _string(parameter.get("in"), max_length=32)
    if not name or location not in {"path", "query", "header", "cookie", "body", "formData"}:
        return
    state.parameters += 1
    schema = parameter.get("schema")
    attributes = {
        "name": name,
        "location": location.lower(),
        "required": location == "path" or _bool(parameter.get("required")),
        "deprecated": _bool(parameter.get("deprecated")),
        **_schema_metadata(schema, state),
    }
    if "type" not in attributes:
        parameter_type = _string(parameter.get("type"), max_length=64)
        if parameter_type:
            attributes["type"] = parameter_type
    reference = state.add_asset(
        AssetKind.parameter.value,
        f"{location.lower()}:{name}",
        attributes,
        pointer,
    )
    state.relate(endpoint, reference, "accepts_parameter", pointer, attributes)


def _request_body_parameters(
    operation: dict[str, Any],
    endpoint: AssetReference,
    pointer: str,
    state: _ParseState,
) -> None:
    request_body = _resolve_ref(operation.get("requestBody"), state)
    if not request_body:
        return
    content = request_body.get("content")
    if not isinstance(content, dict):
        return
    seen_fields: set[str] = set()
    for media_type, media in list(content.items())[:16]:
        if not isinstance(media, dict):
            continue
        schema = _resolve_ref(media.get("schema"), state)
        if schema is None:
            continue
        stack: list[tuple[str, dict[str, Any], bool, int, frozenset[int]]] = [
            ("", schema, False, 0, frozenset())
        ]
        while stack:
            prefix, current_schema, inherited_required, depth, ancestors = stack.pop()
            resolved_schema = _resolve_ref(current_schema, state)
            if resolved_schema is None or id(resolved_schema) in ancestors:
                continue
            child_ancestors = ancestors | {id(resolved_schema)}
            properties = resolved_schema.get("properties")
            if not isinstance(properties, dict):
                continue
            required_names = (
                set(resolved_schema.get("required", []))
                if isinstance(resolved_schema.get("required"), list)
                else set()
            )
            for name, property_schema in properties.items():
                if not isinstance(name, str) or not isinstance(property_schema, dict):
                    continue
                field_name = f"{prefix}.{name}" if prefix else name
                if len(field_name) > 512:
                    continue
                required = inherited_required or name in required_names
                if field_name not in seen_fields:
                    seen_fields.add(field_name)
                    _emit_parameter(
                        {
                            "name": field_name,
                            "in": "body",
                            "required": required,
                            "schema": property_schema,
                        },
                        endpoint,
                        f"{pointer}/requestBody/content/{media_type}/schema/properties/{field_name}",
                        state,
                    )
                if depth + 1 < state.limits.max_schema_depth:
                    child_schema = _resolve_ref(property_schema, state)
                    if child_schema:
                        if child_schema.get("type") == "array":
                            child_schema = _resolve_ref(child_schema.get("items"), state)
                        if child_schema:
                            stack.append(
                                (
                                    field_name,
                                    child_schema,
                                    required,
                                    depth + 1,
                                    child_ancestors,
                                )
                            )


def _security_schemes(state: _ParseState) -> dict[str, AssetReference]:
    components = state.document.get("components")
    definitions: object = None
    if isinstance(components, dict):
        definitions = components.get("securitySchemes")
    if not isinstance(definitions, dict):
        definitions = state.document.get("securityDefinitions")
    if not isinstance(definitions, dict):
        return {}
    source = AssetReference(AssetKind.url.value, state.source_url)
    output: dict[str, AssetReference] = {}
    for name, raw_definition in list(definitions.items())[:1_000]:
        definition = _resolve_ref(raw_definition, state)
        if not isinstance(name, str) or definition is None:
            continue
        attributes: dict[str, Any] = {"name": name}
        for key, output_key in (
            ("type", "type"),
            ("scheme", "scheme"),
            ("bearerFormat", "bearer_format"),
            ("in", "location"),
            ("name", "parameter_name"),
        ):
            value = _string(definition.get(key), max_length=128)
            if value:
                attributes[output_key] = value
        flows = definition.get("flows")
        if isinstance(flows, dict):
            safe_flows: list[dict[str, Any]] = []
            for flow_name, flow in list(flows.items())[:16]:
                if not isinstance(flow_name, str) or not isinstance(flow, dict):
                    continue
                safe_flow: dict[str, Any] = {"name": flow_name[:64]}
                for key, output_key in (
                    ("authorizationUrl", "authorization_url"),
                    ("tokenUrl", "token_url"),
                    ("refreshUrl", "refresh_url"),
                ):
                    raw_url = _string(flow.get(key), max_length=2_048)
                    normalized_url = _normal_url(raw_url, state.source_url) if raw_url else None
                    if normalized_url:
                        safe_flow[output_key] = normalized_url
                scopes = flow.get("scopes")
                if isinstance(scopes, dict):
                    safe_flow["scopes"] = sorted(str(scope)[:128] for scope in scopes)[:64]
                safe_flows.append(safe_flow)
            attributes["oauth_flows"] = safe_flows
        openid_url = _string(definition.get("openIdConnectUrl"), max_length=2_048)
        if openid_url and (normalized_openid := _normal_url(openid_url, state.source_url)):
            attributes["openid_connect_url"] = normalized_openid
        pointer = f"#/components/securitySchemes/{name}"
        reference = state.add_asset(
            "auth_scheme",
            f"{state.source_url}#security:{name}",
            attributes,
            pointer,
        )
        if reference:
            output[name] = reference
            state.relate(source, reference, "declares_auth_scheme", pointer)
    return output


def _apply_security(
    operation: dict[str, Any],
    document_security: object,
    endpoint: AssetReference,
    schemes: dict[str, AssetReference],
    pointer: str,
    state: _ParseState,
) -> tuple[bool, int]:
    security = operation.get("security", document_security)
    if not isinstance(security, list) or not security:
        return False, 0
    alternatives = 0
    auth_required = True
    for alternative in security[:64]:
        if not isinstance(alternative, dict):
            continue
        alternatives += 1
        if not alternative:
            auth_required = False
        for name, scopes in alternative.items():
            if not isinstance(name, str):
                continue
            reference = schemes.get(name)
            if reference is None:
                reference = state.add_asset(
                    "auth_scheme",
                    f"{state.source_url}#security:{name}",
                    {"name": name, "type": "undeclared"},
                    pointer,
                    confidence=0.7,
                )
            scope_names = (
                sorted(str(scope)[:128] for scope in scopes)[:64]
                if isinstance(scopes, list)
                else []
            )
            state.relate(
                endpoint,
                reference,
                "requires_auth",
                pointer,
                {"scopes": scope_names},
            )
    return auth_required, alternatives


def _callback_assets(
    callbacks: object,
    endpoint: AssetReference,
    pointer: str,
    state: _ParseState,
) -> None:
    if not isinstance(callbacks, dict):
        return
    for name, raw_callback in callbacks.items():
        callback = _resolve_ref(raw_callback, state)
        if not isinstance(name, str) or callback is None:
            continue
        for expression, path_item in callback.items():
            if state.callbacks >= state.limits.max_callbacks:
                state.truncated = True
                return
            state.callbacks += 1
            methods = (
                sorted(key.upper() for key in path_item if key.lower() in _HTTP_METHODS)
                if isinstance(path_item, dict)
                else []
            )
            state.operations += len(methods)
            if state.operations > state.limits.max_operations:
                raise OpenAPIParseError("OpenAPI operation limit exceeded")
            expression_type = "runtime_expression"
            normalized_expression = None
            if isinstance(expression, str) and expression.startswith(("http://", "https://")):
                normalized_expression = _normal_url(expression, state.source_url)
                expression_type = "url"
            attributes: dict[str, Any] = {
                "name": name[:256],
                "expression_type": expression_type,
                "methods": methods,
            }
            if normalized_expression:
                attributes["url"] = normalized_expression
            callback_ref = state.add_asset(
                "callback",
                f"{endpoint.value}#callback:{name}:{state.callbacks}",
                attributes,
                f"{pointer}/callbacks/{name}",
            )
            state.relate(endpoint, callback_ref, "declares_callback", pointer)


def _operation_attributes(operation: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "method": method,
        "path_template": path[:2_048],
        "deprecated": _bool(operation.get("deprecated")),
    }
    operation_id = _string(operation.get("operationId"), max_length=256)
    if operation_id:
        attributes["operation_id"] = operation_id
    if isinstance(operation.get("tags"), list):
        attributes["tags"] = sorted(
            {value for item in operation["tags"][:64] if (value := _string(item, max_length=128))}
        )
    return attributes


def _parse_paths(
    state: _ParseState,
    root_servers: list[str],
    schemes: dict[str, AssetReference],
) -> None:
    paths = state.document.get("paths")
    if not isinstance(paths, dict):
        return
    source = AssetReference(AssetKind.url.value, state.source_url)
    document_security = state.document.get("security")
    for path, unresolved_path_item in paths.items():
        if state.paths >= state.limits.max_paths:
            state.truncated = True
            break
        if not isinstance(path, str) or not path.startswith("/") or len(path) > 2_048:
            continue
        path_item = _resolve_ref(unresolved_path_item, state)
        if path_item is None:
            continue
        state.paths += 1
        path_servers = _server_urls(path_item.get("servers"), state, root_servers)
        path_parameters = _parameter_items(path_item.get("parameters"), state)
        for method_name, unresolved_operation in path_item.items():
            method = method_name.lower()
            if method not in _HTTP_METHODS:
                continue
            if state.operations >= state.limits.max_operations:
                raise OpenAPIParseError("OpenAPI operation limit exceeded")
            operation = _resolve_ref(unresolved_operation, state)
            if operation is None:
                continue
            state.operations += 1
            pointer = f"#/paths/{path}/{method}"
            operation_servers = _server_urls(operation.get("servers"), state, path_servers)
            for server in operation_servers[: state.limits.max_server_variants_per_operation]:
                endpoint_url = _join_endpoint(server, path)
                if not endpoint_url:
                    continue
                attributes = _operation_attributes(operation, path, method.upper())
                endpoint = state.add_asset(
                    AssetKind.endpoint.value,
                    f"{method.upper()} {endpoint_url}",
                    attributes,
                    pointer,
                )
                if endpoint is None:
                    continue
                auth_required, alternatives = _apply_security(
                    operation,
                    document_security,
                    endpoint,
                    schemes,
                    pointer,
                    state,
                )
                state.assets[(endpoint.kind, endpoint.value)].attributes.update(
                    {"auth_required": auth_required, "auth_alternatives": alternatives}
                )
                state.relate(source, endpoint, "describes_endpoint", pointer)
                combined_parameters: dict[tuple[str, str], dict[str, Any]] = {}
                for parameter in path_parameters + _parameter_items(
                    operation.get("parameters"), state
                ):
                    name = _string(parameter.get("name"), max_length=256)
                    location = _string(parameter.get("in"), max_length=32)
                    if name and location:
                        combined_parameters[(location, name)] = parameter
                for variable in _PATH_VARIABLE.findall(path):
                    combined_parameters.setdefault(
                        ("path", variable),
                        {"name": variable, "in": "path", "required": True},
                    )
                for parameter in combined_parameters.values():
                    _emit_parameter(parameter, endpoint, pointer, state)
                _request_body_parameters(operation, endpoint, pointer, state)
                _callback_assets(operation.get("callbacks"), endpoint, pointer, state)


def _parse_webhooks(state: _ParseState) -> None:
    webhooks = state.document.get("webhooks")
    if not isinstance(webhooks, dict):
        return
    source = AssetReference(AssetKind.url.value, state.source_url)
    for name, raw_path_item in webhooks.items():
        if state.webhooks >= state.limits.max_webhooks:
            state.truncated = True
            break
        path_item = _resolve_ref(raw_path_item, state)
        if not isinstance(name, str) or path_item is None:
            continue
        state.webhooks += 1
        methods = sorted(key.upper() for key in path_item if key.lower() in _HTTP_METHODS)
        state.operations += len(methods)
        if state.operations > state.limits.max_operations:
            raise OpenAPIParseError("OpenAPI operation limit exceeded")
        pointer = f"#/webhooks/{name}"
        reference = state.add_asset(
            "webhook",
            f"{state.source_url}#webhook:{name}",
            {"name": name[:256], "methods": methods},
            pointer,
        )
        state.relate(source, reference, "describes_webhook", pointer)


def _reference_counts(document: dict[str, Any], state: _ParseState) -> tuple[int, int]:
    local = 0
    remote = 0
    stack: list[Any] = [document]
    seen: set[int] = set()
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if id(value) in seen:
                continue
            seen.add(id(value))
            reference = value.get("$ref")
            if isinstance(reference, str):
                if reference.startswith("#/"):
                    local += 1
                else:
                    remote += 1
            stack.extend(value.values())
        elif isinstance(value, list):
            if id(value) in seen:
                continue
            seen.add(id(value))
            stack.extend(value)
    return local, remote


def parse_openapi_document(
    source_url: str,
    body: bytes | str,
    *,
    limits: OpenAPILimits | None = None,
) -> ModuleResult:
    """Parse an already-fetched OpenAPI document without performing network I/O."""

    limits = limits or OpenAPILimits()
    try:
        source = normalize_asset(AssetKind.url, source_url)
    except NormalizationError as exc:
        raise OpenAPIParseError("OpenAPI source URL is invalid") from exc
    if source.attributes.get("scheme") not in _ALLOWED_SCHEMES:
        raise OpenAPIParseError("OpenAPI source URL must use HTTP or HTTPS")
    document, document_format = _load_document(body, limits)
    openapi_version = _string(document.get("openapi"), max_length=32)
    swagger_version = _string(document.get("swagger"), max_length=32)
    if openapi_version and openapi_version.startswith("3."):
        version = openapi_version
    elif swagger_version == "2.0":
        version = swagger_version
    else:
        raise OpenAPIParseError("document is not OpenAPI 3.x or Swagger 2.0")

    state = _ParseState(limits, source.canonical_value, version, document, {}, {})
    document_ref = AssetReference(AssetKind.url.value, source.canonical_value)
    if openapi_version:
        declared_servers = document.get("servers")
        root_servers = _server_urls(declared_servers, state, [])
        if not root_servers:
            default_server = _normal_url("/", source.canonical_value)
            root_servers = [default_server] if default_server else []
    else:
        swagger_server = _swagger_server(document, source.canonical_value)
        root_servers = [swagger_server] if swagger_server else []
    for index, server in enumerate(root_servers):
        server_ref = state.add_asset(
            AssetKind.url.value,
            server,
            {"role": "api_server", "openapi_version": version},
            f"#/servers/{index}",
        )
        state.relate(document_ref, server_ref, "declares_api_server", f"#/servers/{index}")

    schemes = _security_schemes(state)
    _parse_paths(state, root_servers, schemes)
    _parse_webhooks(state)
    local_refs, remote_refs = _reference_counts(document, state)
    metadata = {
        "document_format": document_format,
        "document_version": version,
        "source_url": source.canonical_value,
        "paths_processed": state.paths,
        "operations_processed": state.operations,
        "parameters_emitted": state.parameters,
        "servers_processed": state.servers,
        "callbacks_processed": state.callbacks,
        "webhooks_processed": state.webhooks,
        "local_refs_seen": local_refs,
        "remote_refs_ignored": remote_refs,
        "unresolved_local_refs": state.unresolved_refs,
        "truncated": state.truncated,
        "network_requests": 0,
    }
    return ModuleResult(
        assets=list(state.assets.values()),
        relationships=list(state.relationships.values()),
        metadata=metadata,
    )


class OpenAPIIntelligenceModule:
    """Adapter for a prior, scope-checked document fetch stage."""

    manifest = ModuleManifest(
        name="web.openapi.intelligence",
        version="1",
        description="Extract endpoints, parameters, servers, callbacks, webhooks, and auth from OpenAPI documents",
        capability="web.openapi.intelligence",
        consumes=frozenset({AssetKind.url.value}),
        produces=frozenset(
            {
                AssetKind.url.value,
                AssetKind.endpoint.value,
                AssetKind.parameter.value,
                "auth_scheme",
                "callback",
                "webhook",
            }
        ),
        mode=ModuleMode.local,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=75,
        timeout_seconds=30,
        max_attempts=1,
        cache_ttl_seconds=86_400,
        accepts_derived_inputs=True,
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        body = context.config.get("document_body")
        try:
            limits = OpenAPILimits.from_config(context.config.get("openapi_limits"))
            return parse_openapi_document(
                context.input_asset.canonical_value,
                body,
                limits=limits,
            )
        except (OpenAPIParseError, ValueError) as exc:
            raise ModuleExecutionError(
                str(exc), retryable=False, code="invalid_openapi_document"
            ) from exc
