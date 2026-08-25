from __future__ import annotations

import base64
import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

from app.core.config import settings
from app.core.network import (
    PinnedHTTPRequestError,
    UnsafeDestinationError,
    pinned_http_request,
)
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
from app.recon.normalization import NormalizationError, NormalizedAsset, normalize_asset

_RAW_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _sanitize_raw_output(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            return normalize_asset(AssetKind.url, match.group(0)).canonical_value
        except NormalizationError:
            return match.group(0)

    return _RAW_URL.sub(replace, value)


@dataclass(frozen=True, slots=True)
class ToolboxExecution:
    tool: str
    version: str
    exit_code: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: float
    implementation_digest: str = ""


class ToolboxClient:
    def available(self) -> bool:
        return settings.toolbox_enabled and bool(settings.toolbox_url)

    def execute(
        self,
        *,
        tool: str,
        input_value: str,
        config: dict[str, Any],
        timeout: int,
        payload: bytes | None = None,
    ) -> ToolboxExecution:
        if not self.available() or not settings.toolbox_shared_secret:
            raise ModuleExecutionError(
                "isolated toolbox is not configured",
                retryable=False,
                code="toolbox_unavailable",
            )
        request: dict[str, Any] = {
            "tool": tool,
            "input": input_value,
            "config": {**config, "execution_timeout": min(timeout, 300)},
        }
        if payload is not None:
            request["payload_b64"] = base64.b64encode(payload).decode("ascii")
        body = json.dumps(request, separators=(",", ":")).encode("utf-8")
        if len(body) > 1_000_000:
            raise ModuleExecutionError(
                "toolbox request exceeds the 1 MB transport limit",
                retryable=False,
                code="toolbox_request_too_large",
            )
        try:
            response = pinned_http_request(
                f"{settings.toolbox_url.rstrip('/')}/v1/run",
                method="POST",
                headers={
                    "Authorization": f"Bearer {settings.toolbox_shared_secret}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                content=body,
                timeout=min(timeout + 5, 300),
                max_response_bytes=3_000_000,
                allow_private=True,
                allowed_schemes=frozenset({"http", "https"}),
            )
        except (PinnedHTTPRequestError, UnsafeDestinationError, OSError) as exc:
            raise ModuleExecutionError(
                f"isolated toolbox request failed: {exc}", code="toolbox_transport"
            ) from exc
        try:
            payload_data = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ModuleExecutionError(
                "isolated toolbox returned malformed JSON", code="toolbox_protocol"
            ) from exc
        if not isinstance(payload_data, dict):
            raise ModuleExecutionError(
                "isolated toolbox returned an invalid response", code="toolbox_protocol"
            )
        if response.status_code >= 400:
            detail = str(payload_data.get("error", "toolbox_error"))[:500]
            retryable = response.status_code in {408, 429, 502, 503, 504}
            raise ModuleExecutionError(
                f"isolated toolbox rejected execution: {detail}",
                retryable=retryable,
                code=f"toolbox_http_{response.status_code}",
            )
        try:
            execution = ToolboxExecution(
                tool=str(payload_data["tool"]),
                version=str(payload_data["version"]),
                exit_code=int(payload_data["exit_code"]),
                stdout=str(payload_data.get("stdout", "")),
                stderr=str(payload_data.get("stderr", "")),
                stdout_truncated=bool(payload_data.get("stdout_truncated", False)),
                stderr_truncated=bool(payload_data.get("stderr_truncated", False)),
                duration_ms=float(payload_data.get("duration_ms", 0)),
                implementation_digest=str(payload_data.get("implementation_digest", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModuleExecutionError(
                "isolated toolbox response is missing required fields", code="toolbox_protocol"
            ) from exc
        if execution.tool != tool:
            raise ModuleExecutionError(
                "isolated toolbox returned a mismatched tool identity", code="toolbox_protocol"
            )
        if execution.stdout_truncated:
            raise ModuleExecutionError(
                f"{tool} output exceeded the isolated transport budget",
                retryable=False,
                code="tool_output_truncated",
            )
        if execution.exit_code != 0:
            detail = execution.stderr.strip() or execution.stdout.strip() or "no diagnostic output"
            raise ModuleExecutionError(
                f"{tool} exited with {execution.exit_code}: {detail[:500]}",
                code="tool_exit",
            )
        return execution


toolbox_client = ToolboxClient()


def _json_lines(stdout: str, *, limit: int = 20_000) -> tuple[list[dict[str, Any]], int]:
    lines = stdout.splitlines()
    if len(lines) > limit:
        raise ModuleExecutionError(
            f"tool emitted more than the {limit} structured-record budget",
            retryable=False,
            code="tool_record_budget_exceeded",
        )
    items: list[dict[str, Any]] = []
    rejected = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            rejected += 1
            continue
        if isinstance(item, dict):
            items.append(item)
        else:
            rejected += 1
    return items, rejected


def _source_ref(context: ModuleContext) -> AssetReference:
    return AssetReference(context.input_asset.kind, context.input_asset.canonical_value)


def _execution_metadata(execution: ToolboxExecution, rejected: int = 0) -> dict[str, Any]:
    return {
        "tool": execution.tool,
        "tool_version": execution.version,
        "tool_duration_ms": execution.duration_ms,
        "implementation_digest": execution.implementation_digest,
        "stdout_truncated": execution.stdout_truncated,
        "stderr_truncated": execution.stderr_truncated,
        "rejected_output_records": rejected,
    }


class ToolboxModule:
    tool: str
    manifest: ModuleManifest

    def available(self) -> bool:
        return toolbox_client.available()

    def _execute(self, context: ModuleContext, *, payload: bytes | None = None) -> ToolboxExecution:
        return toolbox_client.execute(
            tool=self.tool,
            input_value=context.input_asset.canonical_value,
            config=context.config,
            timeout=context.timeout_seconds,
            payload=payload,
        )


class SubfinderModule(ToolboxModule):
    tool = "subfinder"
    manifest = ModuleManifest(
        name="toolbox.subfinder",
        version="2.16.0",
        description="Aggregate maintained passive subdomain sources through Subfinder",
        capability="domain.subdomain_discovery",
        consumes=frozenset({AssetKind.domain.value}),
        produces=frozenset({AssetKind.domain.value, AssetKind.ip_address.value}),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=190,
        timeout_seconds=300,
        max_attempts=2,
        cache_ttl_seconds=21_600,
        rate_limit_per_second=0.2,
        implementation="isolated-toolbox:subfinder",
    )

    @staticmethod
    def accepts(asset: NormalizedAsset) -> bool:
        return asset.attributes.get("seed") is True

    def execute(self, context: ModuleContext) -> ModuleResult:
        execution = self._execute(context)
        records, rejected = _json_lines(execution.stdout)
        root = context.input_asset.canonical_value
        source = _source_ref(context)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        discoveries: dict[str, dict[str, set[str]]] = {}
        for record in records:
            candidate = record.get("host") or record.get("domain") or record.get("input")
            try:
                domain = normalize_asset(AssetKind.domain, str(candidate)).canonical_value
            except (NormalizationError, TypeError):
                rejected += 1
                continue
            if domain == root or not domain.endswith(f".{root}"):
                continue
            sources = record.get("sources") or [record.get("source")]
            entry = discoveries.setdefault(domain, {"sources": set(), "addresses": set()})
            entry["sources"].update(str(item)[:128] for item in sources if item)
            address_value = record.get("ip")
            if address_value:
                try:
                    entry["addresses"].add(ipaddress.ip_address(str(address_value)).compressed)
                except ValueError:
                    rejected += 1

        source_counts: dict[str, int] = {}
        for domain, discovery in sorted(discoveries.items()):
            source_names = sorted(discovery["sources"])[:50]
            for source_name in source_names:
                source_counts[source_name] = source_counts.get(source_name, 0) + 1
            evidence = {"sources": source_names}
            assets.append(
                AssetEmission(
                    AssetKind.domain.value,
                    domain,
                    {
                        "passive_sources": source_names,
                        "passive_source_count": len(source_names),
                    },
                    evidence=evidence,
                    source_name="subfinder",
                )
            )
            relationships.append(
                RelationshipEmission(
                    source,
                    AssetReference(AssetKind.domain.value, domain),
                    "has_subdomain",
                    evidence=evidence,
                )
            )
            for address in sorted(discovery["addresses"]):
                assets.append(AssetEmission(AssetKind.ip_address.value, address))
                relationships.append(
                    RelationshipEmission(
                        AssetReference(AssetKind.domain.value, domain),
                        AssetReference(AssetKind.ip_address.value, address),
                        "resolves_to",
                        evidence=evidence,
                    )
                )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={
                **_execution_metadata(execution, rejected),
                "subdomains": len(discoveries),
                "provider_counts": dict(sorted(source_counts.items())),
                "providers_observed": len(source_counts),
            },
        )


def _dnsx_values(value: Any, *, limit: int = 500) -> list[Any]:
    if isinstance(value, list):
        return value[:limit]
    if isinstance(value, (str, int, float, dict)):
        return [value]
    return []


def _dnsx_domain_value(value: Any) -> tuple[str | None, int | None]:
    preference: int | None = None
    candidate: Any = value
    if isinstance(value, dict):
        candidate = (
            value.get("host")
            or value.get("name")
            or value.get("exchange")
            or value.get("target")
            or value.get("value")
        )
        raw_preference = value.get("preference") or value.get("priority")
        if isinstance(raw_preference, int) and 0 <= raw_preference <= 65_535:
            preference = raw_preference
    if not isinstance(candidate, str):
        return None, preference
    fields = candidate.strip().split()
    if len(fields) > 1 and fields[0].isdigit():
        preference = min(int(fields[0]), 65_535)
        candidate = fields[-1]
    try:
        domain = normalize_asset(AssetKind.domain, candidate.rstrip(".")).canonical_value
    except NormalizationError:
        return None, preference
    return domain, preference


def _dnsx_evidence(record: dict[str, Any], record_type: str, answer: str) -> dict[str, Any]:
    resolvers = _dnsx_values(record.get("resolver"), limit=10)
    resolver_names = [str(item)[:128] for item in resolvers if isinstance(item, str)]
    evidence: dict[str, Any] = {
        "record_type": record_type,
        "answer": answer[:4_096],
        "status_code": str(record.get("status_code") or "NOERROR")[:32].upper(),
        "wildcard_filter": "automatic",
    }
    if resolver_names:
        evidence["resolvers"] = resolver_names
    ttl = record.get("ttl")
    if isinstance(ttl, int) and 0 <= ttl <= 4_294_967_295:
        evidence["ttl"] = ttl
    query_time = record.get("query-time") or record.get("query_time")
    if isinstance(query_time, (int, float, str)):
        evidence["query_time"] = str(query_time)[:64]
    return evidence


class DNSXModule(ToolboxModule):
    tool = "dnsx"
    manifest = ModuleManifest(
        name="toolbox.dnsx",
        version="1.3.0",
        description=(
            "Validate DNS names with bounded wildcard-aware A, AAAA, CNAME, NS, MX, "
            "TXT and CAA queries"
        ),
        capability="dns.resolve",
        consumes=frozenset({AssetKind.domain.value}),
        produces=frozenset(
            {
                AssetKind.domain.value,
                AssetKind.ip_address.value,
                AssetKind.dns_record.value,
            }
        ),
        mode=ModuleMode.active,
        default_profiles=frozenset({"balanced", "active"}),
        priority=150,
        timeout_seconds=60,
        max_attempts=2,
        cache_ttl_seconds=3_600,
        rate_limit_per_second=5,
        implementation="isolated-toolbox:dnsx",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        execution = self._execute(context)
        records, rejected = _json_lines(execution.stdout, limit=100)
        input_domain = context.input_asset.canonical_value
        source = _source_ref(context)
        allow_private = context.config.get("allow_private_networks", False) is True
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen_assets: set[tuple[str, str]] = set()
        seen_relationships: set[tuple[str, str, str]] = set()
        counts: dict[str, int] = {}
        accepted_validation_answers = 0
        private_answers_filtered = 0

        def emit_asset(emission: AssetEmission) -> None:
            key = (emission.kind, emission.value)
            if key not in seen_assets:
                seen_assets.add(key)
                assets.append(emission)

        def emit_relationship(emission: RelationshipEmission) -> None:
            key = (
                emission.target.kind,
                emission.target.value,
                emission.relationship_type,
            )
            if key not in seen_relationships:
                seen_relationships.add(key)
                relationships.append(emission)

        for record in records:
            try:
                record_host = normalize_asset(
                    AssetKind.domain, str(record.get("host", ""))
                ).canonical_value
            except NormalizationError:
                rejected += 1
                continue
            if record_host != input_domain:
                rejected += 1
                continue
            status_code = str(record.get("status_code") or "NOERROR").upper()
            if status_code != "NOERROR":
                continue

            for record_type, field in (("A", "a"), ("AAAA", "aaaa")):
                for raw_answer in _dnsx_values(record.get(field)):
                    try:
                        address = ipaddress.ip_address(str(raw_answer).strip()).compressed
                    except ValueError:
                        rejected += 1
                        continue
                    parsed_address = ipaddress.ip_address(address)
                    if not allow_private and not parsed_address.is_global:
                        private_answers_filtered += 1
                        continue
                    evidence = _dnsx_evidence(record, record_type, address)
                    emit_asset(
                        AssetEmission(
                            AssetKind.ip_address.value,
                            address,
                            {"version": parsed_address.version, "record_type": record_type},
                            evidence=evidence,
                            source_name="dnsx",
                        )
                    )
                    emit_relationship(
                        RelationshipEmission(
                            source,
                            AssetReference(AssetKind.ip_address.value, address),
                            "resolves_to",
                            attributes={"record_type": record_type},
                            evidence=evidence,
                        )
                    )
                    counts[record_type] = counts.get(record_type, 0) + 1
                    accepted_validation_answers += 1

            for raw_answer in _dnsx_values(record.get("cname")):
                cname, _preference = _dnsx_domain_value(raw_answer)
                if cname is None:
                    rejected += 1
                    continue
                if cname == input_domain:
                    rejected += 1
                    continue
                evidence = _dnsx_evidence(record, "CNAME", cname)
                emit_asset(
                    AssetEmission(
                        AssetKind.domain.value,
                        cname,
                        {"record_type": "CNAME"},
                        evidence=evidence,
                        source_name="dnsx",
                    )
                )
                emit_relationship(
                    RelationshipEmission(
                        source,
                        AssetReference(AssetKind.domain.value, cname),
                        "aliases_to",
                        attributes={"record_type": "CNAME"},
                        evidence=evidence,
                    )
                )
                counts["CNAME"] = counts.get("CNAME", 0) + 1
                accepted_validation_answers += 1

            for record_type, field, relationship_type in (
                ("NS", "ns", "uses_nameserver"),
                ("MX", "mx", "receives_mail_via"),
            ):
                for raw_answer in _dnsx_values(record.get(field)):
                    domain, preference = _dnsx_domain_value(raw_answer)
                    if domain is None:
                        rejected += 1
                        continue
                    evidence = _dnsx_evidence(record, record_type, str(raw_answer))
                    attributes: dict[str, Any] = {"record_type": record_type}
                    if preference is not None and record_type == "MX":
                        attributes["preference"] = preference
                    if domain != input_domain:
                        emit_asset(
                            AssetEmission(
                                AssetKind.domain.value,
                                domain,
                                attributes,
                                evidence=evidence,
                                source_name="dnsx",
                            )
                        )
                        emit_relationship(
                            RelationshipEmission(
                                source,
                                AssetReference(AssetKind.domain.value, domain),
                                relationship_type,
                                attributes=attributes,
                                evidence=evidence,
                            )
                        )
                    counts[record_type] = counts.get(record_type, 0) + 1

            for record_type, field in (("TXT", "txt"), ("CAA", "caa")):
                for raw_answer in _dnsx_values(record.get(field)):
                    if isinstance(raw_answer, dict):
                        answer = json.dumps(raw_answer, sort_keys=True, separators=(",", ":"))[
                            :4_096
                        ]
                    else:
                        answer = str(raw_answer).strip()[:4_096]
                    if not answer:
                        rejected += 1
                        continue
                    value = f"{record_type} {answer}"
                    evidence = _dnsx_evidence(record, record_type, answer)
                    emit_asset(
                        AssetEmission(
                            AssetKind.dns_record.value,
                            value,
                            {"record_type": record_type},
                            evidence=evidence,
                            source_name="dnsx",
                        )
                    )
                    emit_relationship(
                        RelationshipEmission(
                            source,
                            AssetReference(AssetKind.dns_record.value, value),
                            "publishes_dns_record",
                            attributes={"record_type": record_type},
                            evidence=evidence,
                        )
                    )
                    counts[record_type] = counts.get(record_type, 0) + 1

        if accepted_validation_answers:
            validation_evidence = {
                "validation": "dnsx_wildcard_aware_resolution",
                "accepted_answers": accepted_validation_answers,
                "record_counts": dict(sorted(counts.items())),
            }
            seen_assets.discard((AssetKind.domain.value, input_domain))
            assets = [
                asset
                for asset in assets
                if not (asset.kind == AssetKind.domain.value and asset.value == input_domain)
            ]
            emit_asset(
                AssetEmission(
                    AssetKind.domain.value,
                    input_domain,
                    {"candidate": False, "validated": True, "dns_validated": True},
                    evidence=validation_evidence,
                    source_name="dnsx",
                )
            )

        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={
                **_execution_metadata(execution, rejected),
                "validated": accepted_validation_answers > 0,
                "accepted_validation_answers": accepted_validation_answers,
                "record_counts": dict(sorted(counts.items())),
                "private_answers_filtered": private_answers_filtered,
                "wildcard_filter": "automatic",
            },
        )


class URLFinderModule(ToolboxModule):
    tool = "urlfinder"
    manifest = ModuleManifest(
        name="toolbox.urlfinder",
        version="0.0.3",
        description="Collect historical URLs from curated passive indexes with source provenance",
        capability="url.historical_discovery",
        consumes=frozenset({AssetKind.domain.value}),
        produces=frozenset(
            {AssetKind.domain.value, AssetKind.url.value, AssetKind.javascript.value}
        ),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=175,
        timeout_seconds=300,
        max_attempts=2,
        cache_ttl_seconds=86_400,
        rate_limit_per_second=0.1,
        implementation="isolated-toolbox:urlfinder",
    )

    @staticmethod
    def accepts(asset: NormalizedAsset) -> bool:
        return asset.attributes.get("seed") is True

    def execute(self, context: ModuleContext) -> ModuleResult:
        execution = self._execute(context)
        records, rejected = _json_lines(execution.stdout)
        root = context.input_asset.canonical_value
        source = _source_ref(context)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[tuple[str, str]] = set()
        host_sources: dict[str, set[str]] = {}
        for record in records:
            candidate = record.get("url")
            try:
                normalized = normalize_asset(AssetKind.url, str(candidate))
            except (NormalizationError, TypeError):
                rejected += 1
                continue
            host = str(normalized.attributes.get("host", ""))
            if host != root and not host.endswith(f".{root}"):
                continue
            path = str(normalized.attributes.get("path", "")).lower()
            kind = (
                AssetKind.javascript.value
                if path.endswith((".js", ".mjs", ".cjs"))
                else AssetKind.url.value
            )
            key = (kind, normalized.canonical_value)
            if key in seen:
                continue
            seen.add(key)
            provider = str(record.get("source") or "unknown")[:128]
            evidence = {"historical_source": provider}
            if host != root:
                host_sources.setdefault(host, set()).add(provider)
            assets.append(
                AssetEmission(
                    kind,
                    normalized.canonical_value,
                    {"historical": True},
                    evidence=evidence,
                    source_name=provider,
                )
            )
            relationships.append(
                RelationshipEmission(
                    source,
                    AssetReference(kind, normalized.canonical_value),
                    "historically_exposed",
                    evidence=evidence,
                )
            )
        for host, providers in sorted(host_sources.items()):
            provider_names = sorted(providers)[:50]
            evidence = {"historical_sources": provider_names}
            assets.append(
                AssetEmission(
                    AssetKind.domain.value,
                    host,
                    {
                        "candidate": True,
                        "validated": False,
                        "historical": True,
                        "passive_sources": provider_names,
                    },
                    confidence=0.4,
                    evidence=evidence,
                    source_name="urlfinder",
                )
            )
            relationships.append(
                RelationshipEmission(
                    source,
                    AssetReference(AssetKind.domain.value, host),
                    "historically_referenced",
                    confidence=0.4,
                    evidence=evidence,
                )
            )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={
                **_execution_metadata(execution, rejected),
                "historical_urls": len(seen),
                "historical_hosts": len(host_sources),
            },
        )


def _certificate_fingerprint(tls_data: Any) -> str | None:
    if not isinstance(tls_data, dict):
        return None
    candidates = [tls_data.get("sha256"), tls_data.get("fingerprint")]
    fingerprint_hash = tls_data.get("fingerprint_hash")
    if isinstance(fingerprint_hash, dict):
        candidates.append(fingerprint_hash.get("sha256"))
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        compact = "".join(char for char in candidate.lower() if char in "0123456789abcdef")
        if len(compact) == 64:
            return compact
    return None


class HTTPXModule(ToolboxModule):
    tool = "httpx"
    manifest = ModuleManifest(
        name="toolbox.httpx",
        version="1.10.0",
        description="Enrich web assets with HTTP, TLS, CDN, ASN and technology intelligence",
        capability="http.probe",
        consumes=frozenset({AssetKind.domain.value, AssetKind.url.value}),
        produces=frozenset(
            {
                AssetKind.url.value,
                AssetKind.domain.value,
                AssetKind.ip_address.value,
                AssetKind.technology.value,
                AssetKind.autonomous_system.value,
                AssetKind.organization.value,
                AssetKind.certificate.value,
            }
        ),
        mode=ModuleMode.active,
        default_profiles=frozenset({"balanced", "active"}),
        priority=135,
        timeout_seconds=120,
        max_attempts=2,
        cache_ttl_seconds=3_600,
        rate_limit_per_second=1,
        implementation="isolated-toolbox:httpx",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        execution = self._execute(context)
        records, rejected = _json_lines(execution.stdout, limit=100)
        source = _source_ref(context)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[tuple[str, str]] = set()

        def emit(kind: str, value: str, **kwargs: Any) -> bool:
            try:
                normalized = normalize_asset(kind, value)
            except NormalizationError:
                return False
            key = (kind, normalized.canonical_value)
            if key in seen:
                return False
            seen.add(key)
            assets.append(AssetEmission(kind, normalized.canonical_value, **kwargs))
            return True

        for record in records:
            candidate = record.get("url") or record.get("final_url")
            try:
                normalized_url = normalize_asset(AssetKind.url, str(candidate))
            except (NormalizationError, TypeError):
                rejected += 1
                continue
            url = normalized_url.canonical_value
            attributes = {
                "status_code": record.get("status_code"),
                "title": record.get("title"),
                "content_type": record.get("content_type"),
                "server": record.get("webserver") or record.get("server"),
                "response_time": record.get("time"),
                "content_length": record.get("content_length"),
                "favicon_hash": record.get("favicon"),
            }
            attributes = {key: value for key, value in attributes.items() if value is not None}
            emit(AssetKind.url.value, url, attributes=attributes, source_name="httpx")
            relationships.append(
                RelationshipEmission(
                    source,
                    AssetReference(AssetKind.url.value, url),
                    "serves",
                    evidence={"status_code": record.get("status_code")},
                )
            )
            host = normalized_url.attributes.get("host")
            host_ref = source
            if host:
                try:
                    host_address = ipaddress.ip_address(str(host)).compressed
                except ValueError:
                    normalized_host = normalize_asset(AssetKind.domain, str(host)).canonical_value
                    emit(AssetKind.domain.value, normalized_host, source_name="httpx")
                    host_ref = AssetReference(AssetKind.domain.value, normalized_host)
                else:
                    emit(
                        AssetKind.ip_address.value,
                        host_address,
                        source_name="httpx",
                    )
                    host_ref = AssetReference(AssetKind.ip_address.value, host_address)
            address_value = record.get("host_ip") or record.get("ip")
            infrastructure_ref = host_ref
            if isinstance(address_value, str):
                try:
                    normalized_address = normalize_asset(
                        AssetKind.ip_address, address_value
                    ).canonical_value
                except NormalizationError:
                    normalized_address = None
                if normalized_address:
                    infrastructure_ref = AssetReference(
                        AssetKind.ip_address.value, normalized_address
                    )
                    if emit(
                        AssetKind.ip_address.value,
                        normalized_address,
                        source_name="httpx",
                    ):
                        relationships.append(
                            RelationshipEmission(
                                host_ref,
                                infrastructure_ref,
                                "resolves_to",
                            )
                        )
            cname_values = record.get("cname") or []
            if isinstance(cname_values, str):
                cname_values = [cname_values]
            for cname_value in cname_values[:50] if isinstance(cname_values, list) else []:
                try:
                    cname = normalize_asset(AssetKind.domain, str(cname_value)).canonical_value
                except NormalizationError:
                    continue
                emit(AssetKind.domain.value, cname, source_name="httpx")
                if host_ref.kind == AssetKind.domain.value:
                    relationships.append(
                        RelationshipEmission(
                            host_ref,
                            AssetReference(AssetKind.domain.value, cname),
                            "aliases_to",
                        )
                    )
            technologies = record.get("tech") or record.get("technologies") or []
            if isinstance(technologies, str):
                technologies = [technologies]
            for technology in technologies[:100] if isinstance(technologies, list) else []:
                value = str(technology)[:500]
                if emit(AssetKind.technology.value, value, source_name="httpx"):
                    relationships.append(
                        RelationshipEmission(
                            AssetReference(AssetKind.url.value, url),
                            AssetReference(AssetKind.technology.value, value),
                            "uses_technology",
                            confidence=0.8,
                        )
                    )
            provider = record.get("cdn_name") or record.get("cdn")
            if isinstance(provider, str) and provider:
                provider_value = f"edge:{provider}"
                emit(
                    AssetKind.technology.value,
                    provider_value,
                    attributes={"category": "cdn_waf_cloud"},
                    source_name="httpx",
                )
                relationships.append(
                    RelationshipEmission(
                        AssetReference(AssetKind.url.value, url),
                        AssetReference(AssetKind.technology.value, provider_value),
                        "fronted_by",
                        confidence=0.8,
                    )
                )
            asn_data = record.get("asn")
            if isinstance(asn_data, dict):
                asn_value = asn_data.get("as_number") or asn_data.get("asn")
                organization = asn_data.get("as_name") or asn_data.get("org")
                asn_ref: AssetReference | None = None
                if asn_value:
                    asn = f"AS{str(asn_value).upper().removeprefix('AS')}"
                    asn_ref = AssetReference(AssetKind.autonomous_system.value, asn)
                    if emit(AssetKind.autonomous_system.value, asn, source_name="httpx"):
                        relationships.append(
                            RelationshipEmission(
                                infrastructure_ref,
                                asn_ref,
                                "announced_by",
                                confidence=0.8,
                            )
                        )
                if organization:
                    organization_value = str(organization)
                    if (
                        emit(
                            AssetKind.organization.value,
                            organization_value,
                            source_name="httpx",
                        )
                        and asn_ref
                    ):
                        relationships.append(
                            RelationshipEmission(
                                asn_ref,
                                AssetReference(AssetKind.organization.value, organization_value),
                                "registered_to",
                                confidence=0.8,
                            )
                        )
            tls_data = record.get("tls")
            fingerprint = _certificate_fingerprint(tls_data)
            if fingerprint and emit(
                AssetKind.certificate.value,
                fingerprint,
                attributes={"tls": tls_data if isinstance(tls_data, dict) else {}},
                source_name="httpx",
            ):
                certificate_ref = AssetReference(AssetKind.certificate.value, fingerprint)
                relationships.append(
                    RelationshipEmission(
                        AssetReference(AssetKind.url.value, url),
                        certificate_ref,
                        "presents_certificate",
                    )
                )
                if isinstance(tls_data, dict):
                    names = tls_data.get("subject_an") or tls_data.get("dns_names") or []
                    if isinstance(names, str):
                        names = [names]
                    for name in names[:200] if isinstance(names, list) else []:
                        candidate_name = str(name).removeprefix("*.")
                        try:
                            domain = normalize_asset(
                                AssetKind.domain, candidate_name
                            ).canonical_value
                        except NormalizationError:
                            continue
                        emit(AssetKind.domain.value, domain, source_name="certificate_san")
                        relationships.append(
                            RelationshipEmission(
                                certificate_ref,
                                AssetReference(AssetKind.domain.value, domain),
                                "covers_domain",
                            )
                        )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={**_execution_metadata(execution, rejected), "records": len(records)},
        )


class KatanaModule(ToolboxModule):
    tool = "katana"
    manifest = ModuleManifest(
        name="toolbox.katana",
        version="1.7.0",
        description="Perform bounded same-host crawling with JavaScript and known-file discovery",
        capability="web.crawl",
        consumes=frozenset({AssetKind.url.value}),
        produces=frozenset(
            {
                AssetKind.url.value,
                AssetKind.javascript.value,
                AssetKind.endpoint.value,
                AssetKind.parameter.value,
                AssetKind.technology.value,
            }
        ),
        mode=ModuleMode.active,
        default_profiles=frozenset({"active"}),
        priority=110,
        timeout_seconds=240,
        max_attempts=2,
        cache_ttl_seconds=3_600,
        rate_limit_per_second=0.2,
        implementation="isolated-toolbox:katana",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        execution = self._execute(context)
        records, rejected = _json_lines(execution.stdout)
        source = _source_ref(context)
        input_host = urlsplit(context.input_asset.canonical_value).hostname
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[tuple[str, str]] = set()
        seen_parameters: set[str] = set()
        for record in records:
            if record.get("error"):
                rejected += 1
                continue
            request = record.get("request") if isinstance(record.get("request"), dict) else {}
            response = record.get("response") if isinstance(record.get("response"), dict) else {}
            candidate = request.get("endpoint") or record.get("url") or record.get("endpoint")
            method = str(request.get("method") or record.get("method") or "GET").upper()
            try:
                normalized = normalize_asset(AssetKind.url, str(candidate))
            except (NormalizationError, TypeError):
                rejected += 1
                continue
            if normalized.attributes.get("host") != input_host:
                continue
            path = str(normalized.attributes.get("path", "")).lower()
            kind = (
                AssetKind.javascript.value
                if path.endswith((".js", ".mjs", ".cjs"))
                else AssetKind.url.value
            )
            key = (kind, normalized.canonical_value)
            if key not in seen:
                seen.add(key)
                assets.append(
                    AssetEmission(
                        kind,
                        normalized.canonical_value,
                        {
                            "discovered_via": "katana",
                            **(
                                {"status_code": response.get("status_code")}
                                if response.get("status_code") is not None
                                else {}
                            ),
                        },
                        source_name="katana",
                    )
                )
                relationships.append(
                    RelationshipEmission(
                        source,
                        AssetReference(kind, normalized.canonical_value),
                        "crawled_to",
                    )
                )
            technologies = response.get("technologies") or record.get("technologies") or []
            if isinstance(technologies, str):
                technologies = [technologies]
            for technology in technologies[:100] if isinstance(technologies, list) else []:
                technology_value = str(technology).strip()[:500]
                if not technology_value:
                    continue
                technology_key = (AssetKind.technology.value, technology_value)
                if technology_key not in seen:
                    seen.add(technology_key)
                    assets.append(
                        AssetEmission(
                            AssetKind.technology.value,
                            technology_value,
                            source_name="katana",
                        )
                    )
                relationships.append(
                    RelationshipEmission(
                        AssetReference(kind, normalized.canonical_value),
                        AssetReference(AssetKind.technology.value, technology_value),
                        "uses_technology",
                        confidence=0.75,
                    )
                )
            try:
                endpoint = normalize_asset(
                    AssetKind.endpoint, f"{method} {normalized.canonical_value}"
                ).canonical_value
            except NormalizationError:
                continue
            endpoint_key = (AssetKind.endpoint.value, endpoint)
            if endpoint_key not in seen:
                seen.add(endpoint_key)
                assets.append(
                    AssetEmission(
                        AssetKind.endpoint.value,
                        endpoint,
                        {"method": method, "discovered_via": "katana"},
                        source_name="katana",
                    )
                )
                relationships.append(
                    RelationshipEmission(
                        AssetReference(kind, normalized.canonical_value),
                        AssetReference(AssetKind.endpoint.value, endpoint),
                        "exposes_endpoint",
                    )
                )
            for parameter, _ in parse_qsl(urlsplit(normalized.canonical_value).query)[:100]:
                if parameter not in seen_parameters:
                    seen_parameters.add(parameter)
                    assets.append(AssetEmission(AssetKind.parameter.value, parameter))
                relationships.append(
                    RelationshipEmission(
                        AssetReference(AssetKind.endpoint.value, endpoint),
                        AssetReference(AssetKind.parameter.value, parameter),
                        "accepts_parameter",
                    )
                )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={**_execution_metadata(execution, rejected), "crawl_entities": len(seen)},
        )


class NaabuModule(ToolboxModule):
    tool = "naabu"
    manifest = ModuleManifest(
        name="toolbox.naabu_connect",
        version="2.6.1",
        description="Discover ports using bounded non-privileged TCP connect scans",
        capability="network.port_discovery",
        consumes=frozenset({AssetKind.ip_address.value}),
        produces=frozenset({AssetKind.port.value, AssetKind.service.value}),
        mode=ModuleMode.active,
        default_profiles=frozenset({"active"}),
        priority=105,
        timeout_seconds=180,
        max_attempts=2,
        cache_ttl_seconds=3_600,
        rate_limit_per_second=0.2,
        implementation="isolated-toolbox:naabu",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        execution = self._execute(context)
        records, rejected = _json_lines(execution.stdout, limit=5_000)
        address = context.input_asset.canonical_value
        source = _source_ref(context)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[int] = set()
        address_object = ipaddress.ip_address(address)
        display_host = f"[{address}]" if address_object.version == 6 else address
        for record in records:
            if str(record.get("ip") or record.get("host")) != address:
                continue
            try:
                port = int(record.get("port"))
            except (TypeError, ValueError):
                rejected += 1
                continue
            if not 0 < port <= 65_535 or port in seen:
                continue
            seen.add(port)
            port_value = f"tcp/{port}"
            service_value = f"tcp://{display_host}:{port}"
            assets.extend(
                [
                    AssetEmission(AssetKind.port.value, port_value),
                    AssetEmission(
                        AssetKind.service.value,
                        service_value,
                        {"transport": "tcp", "port": port, "address": address},
                    ),
                ]
            )
            relationships.extend(
                [
                    RelationshipEmission(
                        source,
                        AssetReference(AssetKind.port.value, port_value),
                        "exposes_port",
                    ),
                    RelationshipEmission(
                        source,
                        AssetReference(AssetKind.service.value, service_value),
                        "exposes_service",
                    ),
                ]
            )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={**_execution_metadata(execution, rejected), "open_ports": len(seen)},
        )


class JSLuiceModule(ToolboxModule):
    tool = "jsluice"
    manifest = ModuleManifest(
        name="toolbox.jsluice",
        version="0ddfab153e06",
        description="Analyze safely fetched JavaScript with AST-aware endpoint extraction",
        capability="javascript.endpoint_discovery",
        consumes=frozenset({AssetKind.javascript.value}),
        produces=frozenset(
            {AssetKind.url.value, AssetKind.endpoint.value, AssetKind.parameter.value}
        ),
        mode=ModuleMode.active,
        default_profiles=frozenset({"balanced", "active"}),
        priority=155,
        timeout_seconds=60,
        max_attempts=2,
        cache_ttl_seconds=3_600,
        rate_limit_per_second=1,
        implementation="isolated-toolbox:jsluice",
    )

    @staticmethod
    def accepts(asset: NormalizedAsset) -> bool:
        return asset.attributes.get("historical") is not True

    def execute(self, context: ModuleContext) -> ModuleResult:
        max_body = min(
            max(int(context.config.get("javascript_ast_max_body_bytes", 700_000)), 1_024),
            700_000,
        )
        try:
            response = pinned_http_request(
                context.input_asset.canonical_value,
                timeout=min(context.timeout_seconds, 30),
                max_response_bytes=max_body,
                allow_private=bool(context.config.get("allow_private_networks", False)),
                allowed_schemes=frozenset({"http", "https"}),
                headers={
                    "User-Agent": str(
                        context.config.get("user_agent", "Reconator/3 authorized-recon")
                    )[:256],
                    "Accept": "application/javascript,text/javascript,*/*;q=0.5",
                },
                truncate_response=True,
            )
        except (PinnedHTTPRequestError, UnsafeDestinationError, OSError) as exc:
            raise ModuleExecutionError(
                f"JavaScript fetch failed before isolated analysis: {exc}",
                code="javascript_fetch_error",
            ) from exc
        if response.status_code >= 400:
            raise ModuleExecutionError(
                f"JavaScript fetch returned HTTP {response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
                code="javascript_http_error",
            )
        execution = self._execute(context, payload=response.body)
        records, rejected = _json_lines(execution.stdout)
        source = _source_ref(context)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[str] = set()
        seen_parameters: set[str] = set()
        for record in records:
            candidate = record.get("url")
            method = str(record.get("method") or "GET").upper()
            if isinstance(candidate, str):
                candidate = urljoin(context.input_asset.canonical_value, candidate)
            try:
                endpoint = normalize_asset(AssetKind.endpoint, f"{method} {candidate}")
            except (NormalizationError, TypeError):
                rejected += 1
                continue
            if endpoint.canonical_value in seen:
                continue
            seen.add(endpoint.canonical_value)
            url = endpoint.canonical_value.partition(" ")[2]
            evidence = {"extractor": "jsluice", "type": record.get("type")}
            assets.extend(
                [
                    AssetEmission(
                        AssetKind.url.value,
                        url,
                        {"discovered_via": "javascript_ast"},
                        confidence=0.85,
                        evidence=evidence,
                        source_name="jsluice",
                    ),
                    AssetEmission(
                        AssetKind.endpoint.value,
                        endpoint.canonical_value,
                        {"method": method, "discovered_via": "javascript_ast"},
                        confidence=0.85,
                        evidence=evidence,
                        source_name="jsluice",
                    ),
                ]
            )
            relationships.append(
                RelationshipEmission(
                    source,
                    AssetReference(AssetKind.endpoint.value, endpoint.canonical_value),
                    "references_endpoint",
                    confidence=0.85,
                    evidence=evidence,
                )
            )
            parameters = record.get("queryParams") or []
            body_parameters = record.get("bodyParams") or []
            if isinstance(parameters, list) and isinstance(body_parameters, list):
                for parameter_value in (parameters + body_parameters)[:200]:
                    parameter = str(parameter_value)[:500]
                    if not parameter:
                        continue
                    if parameter not in seen_parameters:
                        seen_parameters.add(parameter)
                        assets.append(AssetEmission(AssetKind.parameter.value, parameter))
                    relationships.append(
                        RelationshipEmission(
                            AssetReference(AssetKind.endpoint.value, endpoint.canonical_value),
                            AssetReference(AssetKind.parameter.value, parameter),
                            "accepts_parameter",
                            confidence=0.85,
                            evidence=evidence,
                        )
                    )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={
                **_execution_metadata(execution, rejected),
                "endpoints": len(seen),
                "source_bytes": len(response.body),
                "source_truncated": response.truncated,
            },
        )


class AlterXModule(ToolboxModule):
    tool = "alterx"
    manifest = ModuleManifest(
        name="toolbox.alterx",
        version="0.1.0",
        description="Generate bounded target-aware DNS mutations from discovered naming patterns",
        capability="domain.mutation",
        consumes=frozenset({AssetKind.domain.value}),
        produces=frozenset({AssetKind.domain.value}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"active"}),
        priority=95,
        timeout_seconds=30,
        max_attempts=1,
        cache_ttl_seconds=31_536_000,
        implementation="isolated-toolbox:alterx",
    )

    @staticmethod
    def accepts(asset: NormalizedAsset) -> bool:
        return asset.attributes.get("seed") is True

    def execute(self, context: ModuleContext) -> ModuleResult:
        execution = self._execute(context)
        source = _source_ref(context)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[str] = set()
        rejected = 0
        max_mutations = min(max(int(context.config.get("max_mutations", 250)), 1), 2_000)
        for line in execution.stdout.splitlines()[:max_mutations]:
            try:
                domain = normalize_asset(AssetKind.domain, line.strip()).canonical_value
            except NormalizationError:
                rejected += 1
                continue
            if domain == context.input_asset.canonical_value or domain in seen:
                continue
            seen.add(domain)
            evidence = {"generator": "alterx", "requires_dns_validation": True}
            assets.append(
                AssetEmission(
                    AssetKind.domain.value,
                    domain,
                    {"candidate": True, "validated": False},
                    confidence=0.2,
                    evidence=evidence,
                    source_name="alterx",
                )
            )
            relationships.append(
                RelationshipEmission(
                    source,
                    AssetReference(AssetKind.domain.value, domain),
                    "suggests_mutation",
                    confidence=0.2,
                    evidence=evidence,
                )
            )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={**_execution_metadata(execution, rejected), "mutations": len(seen)},
        )


class CDNCheckModule(ToolboxModule):
    tool = "cdncheck"
    manifest = ModuleManifest(
        name="toolbox.cdncheck",
        version="1.2.50",
        description="Classify discovered addresses against maintained CDN, cloud and WAF ranges",
        capability="infrastructure.classification",
        consumes=frozenset({AssetKind.ip_address.value}),
        produces=frozenset({AssetKind.technology.value}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=150,
        timeout_seconds=20,
        max_attempts=1,
        cache_ttl_seconds=604_800,
        accepts_derived_inputs=True,
        implementation="isolated-toolbox:cdncheck",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        execution = self._execute(context)
        records, rejected = _json_lines(execution.stdout, limit=100)
        source = _source_ref(context)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[str] = set()
        for record in records:
            for category in ("cdn", "cloud", "waf"):
                raw = record.get(f"{category}_name") or record.get(category)
                if not isinstance(raw, str) or not raw:
                    continue
                value = f"{category}:{raw}"
                if value in seen:
                    continue
                seen.add(value)
                assets.append(
                    AssetEmission(
                        AssetKind.technology.value,
                        value,
                        {"category": category},
                        source_name="cdncheck",
                    )
                )
                relationships.append(
                    RelationshipEmission(
                        source,
                        AssetReference(AssetKind.technology.value, value),
                        f"classified_as_{category}",
                        confidence=0.9,
                    )
                )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=_sanitize_raw_output(execution.stdout),
            metadata={**_execution_metadata(execution, rejected), "classifications": len(seen)},
        )


def toolbox_modules() -> list[ToolboxModule]:
    return [
        SubfinderModule(),
        DNSXModule(),
        URLFinderModule(),
        HTTPXModule(),
        KatanaModule(),
        NaabuModule(),
        JSLuiceModule(),
        AlterXModule(),
        CDNCheckModule(),
    ]
