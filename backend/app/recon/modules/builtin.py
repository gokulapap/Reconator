from __future__ import annotations

import ipaddress
import json
import re
import shlex
import socket
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from app.core.network import (
    PinnedHTTPRequestError,
    PinnedHTTPResponse,
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
from app.recon.modules.command import CommandModule, CommandSpec
from app.recon.modules.openapi import OpenAPIParseError, parse_openapi_document
from app.recon.modules.registry import ModuleRegistry, registry
from app.recon.normalization import NormalizationError, NormalizedAsset, normalize_asset

_OPENAPI_DOCUMENT_NAMES = frozenset(
    {
        "openapi.json",
        "openapi.yaml",
        "openapi.yml",
        "swagger.json",
        "swagger.yaml",
        "swagger.yml",
        "api-docs",
    }
)
_OPENAPI_STRUCTURED_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/yaml",
        "application/x-yaml",
        "text/json",
        "text/yaml",
        "text/x-yaml",
    }
)
_OPENAPI_JSON_MARKER = re.compile(r'(?:"openapi"\s*:\s*"3\.|"swagger"\s*:\s*"2\.0)')
_OPENAPI_YAML_MARKER = re.compile(
    r"(?m)^\s{0,3}(?:openapi\s*:\s*['\"]?3\.|swagger\s*:\s*['\"]?2\.0)"
)

_RIPESTAT_CALLS = {
    "network-info": (
        "https://stat.ripe.net/data/network-info/data.json",
        "1.1",
        256_000,
    ),
    "announced-prefixes": (
        "https://stat.ripe.net/data/announced-prefixes/data.json",
        "1.2",
        4_000_000,
    ),
}
_RIPESTAT_TIMEOUT_SECONDS = 15
_RIPESTAT_MAX_ANNOUNCERS = 16
_RIPESTAT_DEFAULT_PREFIX_LIMIT = 2_000
_RIPESTAT_HARD_PREFIX_LIMIT = 10_000
_RIPESTAT_MAX_RESPONSE_PREFIXES = 20_000
_RIPESTAT_MAX_RESPONSE_TIMELINES = 100_000


class _SurfaceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.forms: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.links.append(("script", values["src"] or ""))
        elif tag in {"a", "link", "iframe"}:
            candidate = values.get("href") or values.get("src")
            if candidate:
                self.links.append((tag, candidate))
        elif tag == "form" and values.get("action"):
            self.forms.append(((values.get("method") or "GET").upper(), values["action"] or ""))


def _extract_html_surface(
    context: ModuleContext, final_url: str, decoded: str
) -> tuple[list[AssetEmission], list[RelationshipEmission]]:
    parser = _SurfaceHTMLParser()
    try:
        parser.feed(decoded)
    except Exception:
        parser.close()
    max_links = min(int(context.config.get("max_discovered_urls", 500)), 2_000)
    assets: list[AssetEmission] = []
    relationships: list[RelationshipEmission] = []
    seen_links: set[tuple[str, str]] = set()
    canonical_source = normalize_asset(AssetKind.url, final_url).canonical_value
    for source_tag, raw_link in parser.links[:max_links]:
        candidate = urljoin(final_url, raw_link)
        kind = (
            AssetKind.javascript.value
            if source_tag == "script" or urlsplit(candidate).path.lower().endswith(".js")
            else AssetKind.url.value
        )
        try:
            normalized_link = normalize_asset(kind, candidate)
        except NormalizationError:
            continue
        key = (kind, normalized_link.canonical_value)
        if key in seen_links or (
            kind == AssetKind.url.value and normalized_link.canonical_value == canonical_source
        ):
            continue
        seen_links.add(key)
        assets.append(
            AssetEmission(
                kind,
                normalized_link.canonical_value,
                {"discovered_via": source_tag},
            )
        )
        relationships.append(
            RelationshipEmission(
                source=AssetReference(AssetKind.url.value, canonical_source),
                target=AssetReference(kind, normalized_link.canonical_value),
                relationship_type=(
                    "loads_script" if kind == AssetKind.javascript.value else "links_to"
                ),
            )
        )
    for method, action in parser.forms[:max_links]:
        candidate = urljoin(final_url, action)
        try:
            endpoint = normalize_asset(AssetKind.endpoint, f"{method} {candidate}")
        except NormalizationError:
            continue
        assets.append(
            AssetEmission(
                AssetKind.endpoint.value,
                endpoint.canonical_value,
                {"discovered_via": "html_form", "method": method},
            )
        )
        relationships.append(
            RelationshipEmission(
                source=AssetReference(AssetKind.url.value, canonical_source),
                target=AssetReference(AssetKind.endpoint.value, endpoint.canonical_value),
                relationship_type="exposes_form",
            )
        )
    return assets, relationships


def _parse_dns(stdout: str, context: ModuleContext) -> ModuleResult:
    assets: list[AssetEmission] = []
    relationships: list[RelationshipEmission] = []
    source = AssetReference(context.input_asset.kind, context.input_asset.canonical_value)
    seen: set[str] = set()
    for line in stdout.splitlines():
        candidate = line.strip().rstrip(".")
        try:
            address = ipaddress.ip_address(candidate).compressed
        except ValueError:
            continue
        if address in seen:
            continue
        seen.add(address)
        assets.append(
            AssetEmission(
                kind=AssetKind.ip_address.value,
                value=address,
                attributes={"version": ipaddress.ip_address(address).version},
                evidence={"record": candidate},
                source_name="system-dns",
            )
        )
        relationships.append(
            RelationshipEmission(
                source=source,
                target=AssetReference(AssetKind.ip_address.value, address),
                relationship_type="resolves_to",
                evidence={"resolver_output": candidate},
            )
        )
    if seen:
        # Promote mutation hypotheses only after an address lookup succeeds.
        # The scheduler permits unvalidated candidates to reach these bounded
        # resolvers, then changed-asset scheduling unlocks downstream modules.
        assets.append(
            AssetEmission(
                kind=AssetKind.domain.value,
                value=context.input_asset.canonical_value,
                attributes={"candidate": False, "validated": True},
                evidence={"validation": "address_resolution", "answers": len(seen)},
                source_name="system-dns",
            )
        )
    return ModuleResult(assets=assets, relationships=relationships)


def _parse_ptr(stdout: str, context: ModuleContext) -> ModuleResult:
    assets: list[AssetEmission] = []
    relationships: list[RelationshipEmission] = []
    source = AssetReference(AssetKind.ip_address.value, context.input_asset.canonical_value)
    for line in stdout.splitlines():
        candidate = line.strip().rstrip(".")
        if not candidate:
            continue
        try:
            domain = normalize_asset(AssetKind.domain, candidate).canonical_value
        except NormalizationError:
            continue
        assets.append(
            AssetEmission(
                AssetKind.domain.value,
                domain,
                {"record_type": "PTR"},
                source_name="dns",
            )
        )
        relationships.append(
            RelationshipEmission(
                source,
                AssetReference(AssetKind.domain.value, domain),
                "reverse_resolves_to",
                evidence={"record_type": "PTR"},
            )
        )
    return ModuleResult(assets=assets, relationships=relationships)


def _dns_module(record_type: str, priority: int) -> CommandModule:
    return CommandModule(
        ModuleManifest(
            name=f"dns.system.{record_type.lower()}",
            version="1",
            description=f"Resolve {record_type} records with the system DNS client",
            capability="dns.resolve",
            consumes=frozenset({AssetKind.domain.value}),
            produces=frozenset({AssetKind.ip_address.value}),
            mode=ModuleMode.active,
            default_profiles=frozenset({"balanced", "active"}),
            priority=priority,
            timeout_seconds=30,
            max_attempts=2,
            cache_ttl_seconds=3_600,
            implementation="dig",
        ),
        CommandSpec(
            argv=("dig", "+time=5", "+tries=2", "+short", "{input}", record_type),
            parser=_parse_dns,
        ),
        max_output_bytes=256_000,
    )


def _reverse_dns_module() -> CommandModule:
    return CommandModule(
        ModuleManifest(
            name="dns.reverse",
            version="1",
            description="Resolve PTR records for discovered IP addresses",
            capability="dns.reverse",
            consumes=frozenset({AssetKind.ip_address.value}),
            produces=frozenset({AssetKind.domain.value}),
            mode=ModuleMode.passive,
            default_profiles=frozenset({"passive", "balanced", "active"}),
            priority=115,
            timeout_seconds=20,
            max_attempts=2,
            cache_ttl_seconds=86_400,
            rate_limit_per_second=5,
            accepts_derived_inputs=True,
            implementation="dig",
        ),
        CommandSpec(argv=("dig", "+short", "-x", "{input}"), parser=_parse_ptr),
    )


def _parse_domain_dns_record(
    stdout: str,
    context: ModuleContext,
    *,
    record_type: str,
    relationship_type: str,
) -> ModuleResult:
    assets: list[AssetEmission] = []
    relationships: list[RelationshipEmission] = []
    source = AssetReference(AssetKind.domain.value, context.input_asset.canonical_value)
    seen: set[str] = set()
    for line in stdout.splitlines()[:10_000]:
        fields = line.strip().split()
        if not fields:
            continue
        candidate = fields[-1].rstrip(".")
        try:
            domain = normalize_asset(AssetKind.domain, candidate).canonical_value
        except NormalizationError:
            continue
        if domain in seen:
            continue
        seen.add(domain)
        attributes = {"record_type": record_type}
        if record_type == "MX" and fields[0].isdigit():
            attributes["preference"] = int(fields[0])
        evidence = {"record_type": record_type, "answer": line[:1_000]}
        assets.append(
            AssetEmission(
                AssetKind.domain.value,
                domain,
                attributes,
                evidence=evidence,
                source_name="dns",
            )
        )
        relationships.append(
            RelationshipEmission(
                source,
                AssetReference(AssetKind.domain.value, domain),
                relationship_type,
                attributes=attributes,
                evidence=evidence,
            )
        )
    return ModuleResult(assets=assets, relationships=relationships)


def _domain_dns_module(
    record_type: str,
    *,
    capability: str,
    relationship_type: str,
    priority: int,
) -> CommandModule:
    def parser(stdout: str, context: ModuleContext) -> ModuleResult:
        return _parse_domain_dns_record(
            stdout,
            context,
            record_type=record_type,
            relationship_type=relationship_type,
        )

    return CommandModule(
        ModuleManifest(
            name=f"dns.system.{record_type.lower()}",
            version="1",
            description=f"Discover {record_type} DNS infrastructure records",
            capability=capability,
            consumes=frozenset({AssetKind.domain.value}),
            produces=frozenset({AssetKind.domain.value}),
            mode=ModuleMode.active,
            default_profiles=frozenset({"balanced", "active"}),
            priority=priority,
            timeout_seconds=30,
            max_attempts=2,
            cache_ttl_seconds=3_600,
            rate_limit_per_second=5,
            implementation="dig",
        ),
        CommandSpec(
            argv=("dig", "+time=5", "+tries=2", "+short", "{input}", record_type),
            parser=parser,
        ),
        max_output_bytes=512_000,
    )


def _parse_txt_records(stdout: str, context: ModuleContext) -> ModuleResult:
    source = AssetReference(AssetKind.domain.value, context.input_asset.canonical_value)
    assets: list[AssetEmission] = []
    relationships: list[RelationshipEmission] = []
    seen: set[str] = set()
    for line in stdout.splitlines()[:5_000]:
        try:
            chunks = shlex.split(line, posix=True)
        except ValueError:
            continue
        value = "".join(chunks)[:4_096]
        if not value or value in seen:
            continue
        seen.add(value)
        record = AssetReference(AssetKind.dns_record.value, value)
        assets.append(
            AssetEmission(
                AssetKind.dns_record.value,
                value,
                {"record_type": "TXT"},
                source_name="dns",
            )
        )
        relationships.append(RelationshipEmission(source, record, "publishes_dns_record"))
    return ModuleResult(
        assets=assets,
        relationships=relationships,
        metadata={"txt_records": len(assets)},
    )


def _txt_dns_module() -> CommandModule:
    return CommandModule(
        ModuleManifest(
            name="dns.system.txt",
            version="1",
            description="Collect public TXT policy and verification records",
            capability="dns.txt_records",
            consumes=frozenset({AssetKind.domain.value}),
            produces=frozenset({AssetKind.dns_record.value}),
            mode=ModuleMode.active,
            default_profiles=frozenset({"balanced", "active"}),
            priority=105,
            timeout_seconds=30,
            max_attempts=2,
            cache_ttl_seconds=3_600,
            rate_limit_per_second=5,
            implementation="dig",
        ),
        CommandSpec(
            argv=("dig", "+time=5", "+tries=2", "+short", "{input}", "TXT"),
            parser=_parse_txt_records,
        ),
        max_output_bytes=512_000,
    )


class CIDRExpansionModule:
    manifest = ModuleManifest(
        name="network.cidr_expand",
        version="1",
        description="Expand a bounded authorized CIDR into address assets",
        capability="network.cidr_expand",
        consumes=frozenset({AssetKind.cidr.value}),
        produces=frozenset({AssetKind.ip_address.value}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"balanced", "active"}),
        priority=95,
        timeout_seconds=30,
        max_attempts=1,
        cache_ttl_seconds=0,
        implementation="python-ipaddress",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        network = ipaddress.ip_network(context.input_asset.canonical_value)
        configured_limit = int(context.config.get("max_cidr_addresses", 256))
        # Large ranges must be chunked by a future range scheduler instead of
        # materializing unbounded assets and relationships in one worker.
        limit = min(max(configured_limit, 1), 4_096)
        if network.num_addresses > limit:
            raise ModuleExecutionError(
                f"CIDR contains {network.num_addresses} addresses; configured limit is {limit}",
                retryable=False,
                code="cidr_too_large",
            )
        source = AssetReference(AssetKind.cidr.value, network.with_prefixlen)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        for address in network.hosts():
            value = address.compressed
            assets.append(AssetEmission(AssetKind.ip_address.value, value))
            relationships.append(
                RelationshipEmission(
                    source,
                    AssetReference(AssetKind.ip_address.value, value),
                    "contains_address",
                )
            )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            metadata={"addresses_emitted": len(assets), "configured_limit": limit},
        )


class RDAPIPModule:
    manifest = ModuleManifest(
        name="infrastructure.rdap_ip",
        version="1",
        description="Enrich public IP addresses with RDAP network ownership data",
        capability="infrastructure.rdap",
        consumes=frozenset({AssetKind.ip_address.value}),
        produces=frozenset({AssetKind.cidr.value, AssetKind.organization.value}),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=80,
        timeout_seconds=30,
        max_attempts=2,
        cache_ttl_seconds=86_400,
        rate_limit_per_second=2,
        accepts_derived_inputs=True,
        implementation="rdap.org",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        address = ipaddress.ip_address(context.input_asset.canonical_value)
        if not address.is_global:
            return ModuleResult(metadata={"skipped": "non-public address"})
        endpoint = f"https://rdap.org/ip/{address.compressed}"
        try:
            response = pinned_http_request(
                endpoint,
                timeout=min(context.timeout_seconds, 30),
                max_response_bytes=2_000_000,
                headers={"Accept": "application/rdap+json"},
                max_redirects=5,
            )
            if response.status_code >= 400:
                raise ModuleExecutionError(
                    f"RDAP returned HTTP {response.status_code}",
                    retryable=response.status_code == 429 or response.status_code >= 500,
                    code="rdap_http_error",
                )
            payload = json.loads(response.body)
        except (PinnedHTTPRequestError, UnsafeDestinationError, ValueError) as exc:
            raise ModuleExecutionError(f"RDAP lookup failed: {exc}", code="rdap_error") from exc

        source = AssetReference(AssetKind.ip_address.value, address.compressed)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        start = payload.get("startAddress")
        end = payload.get("endAddress")
        if isinstance(start, str) and isinstance(end, str):
            try:
                networks = list(
                    ipaddress.summarize_address_range(
                        ipaddress.ip_address(start), ipaddress.ip_address(end)
                    )
                )
            except (TypeError, ValueError):
                networks = []
            for network in networks[:32]:
                cidr = network.with_prefixlen
                assets.append(
                    AssetEmission(
                        AssetKind.cidr.value,
                        cidr,
                        {"country": payload.get("country"), "rdap_handle": payload.get("handle")},
                    )
                )
                relationships.append(
                    RelationshipEmission(
                        AssetReference(AssetKind.cidr.value, cidr),
                        source,
                        "contains_address",
                    )
                )
        organization = payload.get("name") or payload.get("handle")
        if isinstance(organization, str) and organization.strip():
            assets.append(
                AssetEmission(
                    AssetKind.organization.value,
                    organization,
                    {"country": payload.get("country"), "source": "rdap"},
                )
            )
            relationships.append(
                RelationshipEmission(
                    AssetReference(AssetKind.organization.value, organization),
                    source,
                    "owns_address",
                )
            )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=json.dumps(payload, sort_keys=True),
            metadata={"rdap_handle": payload.get("handle")},
        )


def _ripestat_url(data_call: str, resource: str) -> str:
    """Build one of the two allowed RIPEstat URLs from a canonical resource."""

    try:
        endpoint, version, _max_response_bytes = _RIPESTAT_CALLS[data_call]
    except KeyError as exc:  # The data call is a module constant, never operator input.
        raise ValueError("unsupported RIPEstat data call") from exc
    try:
        if data_call == "network-info":
            canonical = ipaddress.ip_address(resource).compressed
        else:
            canonical = normalize_asset(
                AssetKind.autonomous_system, resource
            ).canonical_value
    except (NormalizationError, ValueError) as exc:
        raise ValueError("invalid RIPEstat resource") from exc
    if canonical != resource:
        raise ValueError("RIPEstat resource must be canonical")
    query = urlencode(
        (("resource", canonical), ("preferred_version", version)),
        encoding="ascii",
        errors="strict",
    )
    return f"{endpoint}?{query}"


def _ripestat_retryable_status(status_code: int) -> bool:
    return status_code in {408, 425, 429} or status_code >= 500


def _ripestat_error(
    detail: str,
    *,
    code: str = "ripestat_schema_error",
    retryable: bool = False,
) -> ModuleExecutionError:
    return ModuleExecutionError(
        f"RIPEstat response rejected: {detail}",
        code=code,
        retryable=retryable,
    )


def _request_ripestat(
    context: ModuleContext,
    *,
    data_call: str,
    resource: str,
) -> dict[str, Any]:
    endpoint = _ripestat_url(data_call, resource)
    _base_url, expected_version, max_response_bytes = _RIPESTAT_CALLS[data_call]
    try:
        response = pinned_http_request(
            endpoint,
            timeout=min(context.timeout_seconds, _RIPESTAT_TIMEOUT_SECONDS),
            max_response_bytes=max_response_bytes,
            headers={
                "Accept": "application/json",
                "User-Agent": "Reconator/2 RIPEstat-passive-BGP",
            },
            max_redirects=0,
        )
    except UnsafeDestinationError as exc:
        raise ModuleExecutionError(
            f"RIPEstat destination rejected: {exc}",
            code="ripestat_destination_error",
            retryable=False,
        ) from exc
    except PinnedHTTPRequestError as exc:
        response_too_large = "response exceeded" in str(exc).lower()
        raise ModuleExecutionError(
            f"RIPEstat request failed: {exc}",
            code=(
                "ripestat_response_too_large"
                if response_too_large
                else "ripestat_transport_error"
            ),
            retryable=not response_too_large,
        ) from exc

    if response.status_code != 200:
        raise ModuleExecutionError(
            f"RIPEstat returned HTTP {response.status_code}",
            code="ripestat_http_error",
            retryable=_ripestat_retryable_status(response.status_code),
        )
    media_type = response.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type != "application/json":
        raise _ripestat_error("content type is not application/json")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ripestat_error("body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise _ripestat_error("top-level value is not an object")

    status = payload.get("status")
    status_code = payload.get("status_code")
    if status != "ok" or status_code != 200:
        embedded_status = status_code if isinstance(status_code, int) else 0
        raise _ripestat_error(
            "API status is not successful",
            code="ripestat_api_error",
            retryable=status == "maintenance"
            or _ripestat_retryable_status(embedded_status),
        )
    if payload.get("data_call_name") != data_call:
        raise _ripestat_error("data_call_name does not match the requested endpoint")
    if payload.get("data_call_status") != "supported":
        raise _ripestat_error("data call is not marked supported")
    version = payload.get("version")
    expected_major = expected_version.partition(".")[0]
    if not isinstance(version, str) or version.partition(".")[0] != expected_major:
        raise _ripestat_error("response version is incompatible")
    if not isinstance(payload.get("data"), dict):
        raise _ripestat_error("data is not an object")
    if "cached" in payload and not isinstance(payload["cached"], bool):
        raise _ripestat_error("cached flag is not a boolean")
    return payload


def _ripestat_provenance(
    payload: dict[str, Any], *, data_call: str, resource: str
) -> dict[str, Any]:
    return {
        "provider": "RIPE NCC RIPEstat",
        "routing_dataset": "RIPE RIS",
        "data_call": data_call,
        "query_resource": resource,
        "response_version": payload["version"],
    }


def _ripestat_prefix_limit(context: ModuleContext) -> int:
    configured = context.config.get("max_prefixes", _RIPESTAT_DEFAULT_PREFIX_LIMIT)
    if isinstance(configured, bool) or not isinstance(configured, int) or configured < 1:
        raise ModuleExecutionError(
            "RIPEstat max_prefixes must be a positive integer",
            code="ripestat_invalid_config",
            retryable=False,
        )
    return min(configured, _RIPESTAT_HARD_PREFIX_LIMIT)


class RIPEstatNetworkInfoModule:
    manifest = ModuleManifest(
        name="infrastructure.ripestat_network_info",
        version="1",
        description="Map a public IP to its RIPE RIS routed prefix and announcing ASNs",
        capability="infrastructure.bgp_network_info",
        consumes=frozenset({AssetKind.ip_address.value}),
        produces=frozenset(
            {AssetKind.cidr.value, AssetKind.autonomous_system.value}
        ),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=85,
        timeout_seconds=20,
        max_attempts=3,
        cache_ttl_seconds=28_800,
        rate_limit_per_second=0.5,
        accepts_derived_inputs=True,
        implementation="ripestat-network-info",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        address = ipaddress.ip_address(context.input_asset.canonical_value)
        if not address.is_global:
            return ModuleResult(
                metadata={
                    "provider": "RIPE NCC RIPEstat",
                    "data_call": "network-info",
                    "skipped": "non-public address",
                }
            )

        resource = address.compressed
        payload = _request_ripestat(
            context,
            data_call="network-info",
            resource=resource,
        )
        data = payload["data"]
        prefix_value = data.get("prefix")
        asn_values = data.get("asns")
        if not isinstance(asn_values, list):
            raise _ripestat_error("network-info asns is not a list")
        if len(asn_values) > _RIPESTAT_MAX_ANNOUNCERS:
            raise _ripestat_error(
                "network-info announcer count exceeds the safety limit",
                code="ripestat_item_limit",
            )
        if prefix_value is None:
            if asn_values:
                raise _ripestat_error("an unrouted response contains announcing ASNs")
            return ModuleResult(
                metadata={
                    "provider": "RIPE NCC RIPEstat",
                    "data_call": "network-info",
                    "response_version": payload["version"],
                    "api_cached": payload.get("cached"),
                    "routed": False,
                    "announcers": 0,
                }
            )
        if not isinstance(prefix_value, str):
            raise _ripestat_error("network-info prefix is not a string or null")
        try:
            network = ipaddress.ip_network(prefix_value, strict=False)
        except ValueError as exc:
            raise _ripestat_error("network-info prefix is invalid") from exc
        if address not in network:
            raise _ripestat_error("network-info prefix does not contain the query address")
        if not asn_values:
            raise _ripestat_error("a routed prefix has no announcing ASN")

        asns: list[str] = []
        seen_asns: set[str] = set()
        for asn_value in asn_values:
            if isinstance(asn_value, bool) or not isinstance(asn_value, (int, str)):
                raise _ripestat_error("network-info contains an invalid ASN value")
            try:
                asn = normalize_asset(
                    AssetKind.autonomous_system, str(asn_value)
                ).canonical_value
            except NormalizationError as exc:
                raise _ripestat_error("network-info contains an invalid ASN") from exc
            if asn not in seen_asns:
                seen_asns.add(asn)
                asns.append(asn)

        cidr = network.with_prefixlen
        provenance = _ripestat_provenance(
            payload,
            data_call="network-info",
            resource=resource,
        )
        intelligence_attributes = {
            "intelligence_only": True,
            "routing_source": "RIPE RIS",
        }
        assets = [
            AssetEmission(
                AssetKind.cidr.value,
                cidr,
                intelligence_attributes,
                evidence=provenance,
                source_name="ripestat",
            )
        ]
        assets.extend(
            AssetEmission(
                AssetKind.autonomous_system.value,
                asn,
                intelligence_attributes,
                evidence=provenance,
                source_name="ripestat",
            )
            for asn in asns
        )
        relationships = [
            RelationshipEmission(
                AssetReference(AssetKind.ip_address.value, resource),
                AssetReference(AssetKind.cidr.value, cidr),
                "member_of_prefix",
                evidence=provenance,
            )
        ]
        relationships.extend(
            RelationshipEmission(
                AssetReference(AssetKind.cidr.value, cidr),
                AssetReference(AssetKind.autonomous_system.value, asn),
                "announced_by",
                evidence=provenance,
            )
            for asn in asns
        )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            metadata={
                "provider": "RIPE NCC RIPEstat",
                "data_call": "network-info",
                "response_version": payload["version"],
                "api_cached": payload.get("cached"),
                "routed": True,
                "announcers": len(asns),
            },
        )


class RIPEstatAnnouncedPrefixesModule:
    manifest = ModuleManifest(
        name="infrastructure.ripestat_announced_prefixes",
        version="1",
        description="Collect bounded RIPE RIS announced-prefix intelligence for an ASN",
        capability="infrastructure.bgp_announced_prefixes",
        consumes=frozenset({AssetKind.autonomous_system.value}),
        produces=frozenset({AssetKind.cidr.value}),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=82,
        timeout_seconds=20,
        max_attempts=3,
        cache_ttl_seconds=21_600,
        rate_limit_per_second=0.5,
        accepts_derived_inputs=True,
        implementation="ripestat-announced-prefixes",
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        resource = normalize_asset(
            AssetKind.autonomous_system,
            context.input_asset.canonical_value,
        ).canonical_value
        prefix_limit = _ripestat_prefix_limit(context)
        payload = _request_ripestat(
            context,
            data_call="announced-prefixes",
            resource=resource,
        )
        data = payload["data"]
        response_resource = data.get("resource")
        if isinstance(response_resource, bool) or not isinstance(
            response_resource, (int, str)
        ):
            raise _ripestat_error("announced-prefixes resource is invalid")
        try:
            canonical_response_resource = normalize_asset(
                AssetKind.autonomous_system, str(response_resource)
            ).canonical_value
        except NormalizationError as exc:
            raise _ripestat_error("announced-prefixes resource is invalid") from exc
        if canonical_response_resource != resource:
            raise _ripestat_error("announced-prefixes resource does not match the query")

        prefix_items = data.get("prefixes")
        if not isinstance(prefix_items, list):
            raise _ripestat_error("announced-prefixes prefixes is not a list")
        if len(prefix_items) > _RIPESTAT_MAX_RESPONSE_PREFIXES:
            raise _ripestat_error(
                "announced-prefixes response exceeds the item safety limit",
                code="ripestat_item_limit",
            )
        query_start = data.get("query_starttime")
        query_end = data.get("query_endtime")
        if (
            not isinstance(query_start, str)
            or not isinstance(query_end, str)
            or not 1 <= len(query_start) <= 128
            or not 1 <= len(query_end) <= 128
        ):
            raise _ripestat_error("announced-prefixes query window is invalid")

        prefixes: list[str] = []
        seen_prefixes: set[str] = set()
        timeline_count = 0
        for item in prefix_items:
            if not isinstance(item, dict) or not isinstance(item.get("prefix"), str):
                raise _ripestat_error("announced-prefixes contains an invalid prefix entry")
            timelines = item.get("timelines")
            if not isinstance(timelines, list):
                raise _ripestat_error("announced-prefixes timelines is not a list")
            timeline_count += len(timelines)
            if timeline_count > _RIPESTAT_MAX_RESPONSE_TIMELINES:
                raise _ripestat_error(
                    "announced-prefixes timeline count exceeds the safety limit",
                    code="ripestat_item_limit",
                )
            for timeline in timelines:
                if not isinstance(timeline, dict):
                    raise _ripestat_error("announced-prefixes contains an invalid timeline")
                start = timeline.get("starttime")
                end = timeline.get("endtime")
                if (
                    not isinstance(start, str)
                    or not isinstance(end, str)
                    or not 1 <= len(start) <= 128
                    or not 1 <= len(end) <= 128
                ):
                    raise _ripestat_error("announced-prefixes timeline window is invalid")
            try:
                prefix = ipaddress.ip_network(
                    item["prefix"], strict=False
                ).with_prefixlen
            except ValueError as exc:
                raise _ripestat_error(
                    "announced-prefixes contains an invalid prefix"
                ) from exc
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            if len(prefixes) < prefix_limit:
                prefixes.append(prefix)

        provenance = _ripestat_provenance(
            payload,
            data_call="announced-prefixes",
            resource=resource,
        )
        relationship_attributes = {
            "observation_window_start": query_start,
            "observation_window_end": query_end,
        }
        intelligence_attributes = {
            "intelligence_only": True,
            "routing_source": "RIPE RIS",
        }
        assets = [
            AssetEmission(
                AssetKind.cidr.value,
                prefix,
                intelligence_attributes,
                evidence=provenance,
                source_name="ripestat",
            )
            for prefix in prefixes
        ]
        relationships = [
            RelationshipEmission(
                AssetReference(AssetKind.cidr.value, prefix),
                AssetReference(AssetKind.autonomous_system.value, resource),
                "announced_by",
                attributes=relationship_attributes,
                evidence=provenance,
            )
            for prefix in prefixes
        ]
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            metadata={
                "provider": "RIPE NCC RIPEstat",
                "data_call": "announced-prefixes",
                "response_version": payload["version"],
                "api_cached": payload.get("cached"),
                "query_starttime": query_start,
                "query_endtime": query_end,
                "prefixes_returned": len(prefix_items),
                "prefixes_unique": len(seen_prefixes),
                "prefixes_emitted": len(prefixes),
                "prefixes_truncated": len(seen_prefixes) > len(prefixes),
                "prefix_limit": prefix_limit,
            },
        )


class URLStructureModule:
    manifest = ModuleManifest(
        name="url.structure",
        version="1",
        description="Extract endpoint and parameter entities from normalized URLs",
        capability="url.structure",
        consumes=frozenset({AssetKind.url.value, AssetKind.javascript.value}),
        produces=frozenset({AssetKind.endpoint.value, AssetKind.parameter.value}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=160,
        timeout_seconds=10,
        max_attempts=1,
        cache_ttl_seconds=31_536_000,
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        parsed = urlsplit(context.input_asset.canonical_value)
        endpoint_url = parsed._replace(query="", fragment="").geturl()
        endpoint_value = f"GET {endpoint_url}"
        assets = [
            AssetEmission(
                AssetKind.endpoint.value,
                endpoint_value,
                {"method": "GET", "path": parsed.path or "/"},
            )
        ]
        relationships = [
            RelationshipEmission(
                source=AssetReference(
                    context.input_asset.kind, context.input_asset.canonical_value
                ),
                target=AssetReference(AssetKind.endpoint.value, endpoint_value),
                relationship_type="exposes_endpoint",
            )
        ]

        parameter_names = context.input_asset.attributes.get("query_parameters", [])
        for name in parameter_names:
            assets.append(AssetEmission(AssetKind.parameter.value, name))
            relationships.append(
                RelationshipEmission(
                    source=AssetReference(AssetKind.endpoint.value, endpoint_value),
                    target=AssetReference(AssetKind.parameter.value, name),
                    relationship_type="accepts_parameter",
                )
            )
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            metadata={"parameter_count": len(parameter_names)},
        )


class JavaScriptEndpointModule:
    manifest = ModuleManifest(
        name="javascript.endpoint_extract",
        version="1",
        description="Fetch in-scope JavaScript and extract likely API endpoints and parameters",
        capability="javascript.endpoint_discovery",
        consumes=frozenset({AssetKind.javascript.value}),
        produces=frozenset({AssetKind.endpoint.value, AssetKind.parameter.value}),
        mode=ModuleMode.active,
        default_profiles=frozenset({"balanced", "active"}),
        priority=145,
        timeout_seconds=30,
        max_attempts=2,
        cache_ttl_seconds=3_600,
        rate_limit_per_second=2,
        implementation="python-parser",
    )
    _absolute_url = re.compile(r"https?://[^\s\"'`<>\\]{1,2048}", re.I)
    _quoted_path = re.compile(r"[\"']((?:/|\./|\.\./)[A-Za-z0-9_~!$&()*+,;=:@%?./-]{1,1024})[\"']")
    _interesting_path = re.compile(
        r"(?:^|/)(?:api|graphql|rest|oauth|auth|admin|internal|v\d+)(?:/|$)", re.I
    )
    _secret_signal = re.compile(
        r"(?:api[_-]?key|client[_-]?secret|access[_-]?token|authorization)\s*[:=]",
        re.I,
    )

    @staticmethod
    def accepts(asset: NormalizedAsset) -> bool:
        return asset.attributes.get("historical") is not True

    def execute(self, context: ModuleContext) -> ModuleResult:
        allow_private = bool(context.config.get("allow_private_networks", False))
        try:
            max_body = min(
                max(int(context.config.get("javascript_max_body_bytes", 1_000_000)), 1_024),
                2_000_000,
            )
            max_endpoints = min(
                max(int(context.config.get("max_javascript_endpoints", 500)), 1), 2_000
            )
        except (TypeError, ValueError) as exc:
            raise ModuleExecutionError(
                "JavaScript limits must be integers",
                retryable=False,
                code="invalid_config",
            ) from exc
        try:
            response = pinned_http_request(
                context.input_asset.canonical_value,
                timeout=min(context.timeout_seconds, 30),
                max_response_bytes=max_body,
                allow_private=allow_private,
                allowed_schemes=frozenset({"http", "https"}),
                headers={
                    "User-Agent": str(
                        context.config.get("user_agent", "Reconator/3 authorized-recon")
                    )[:256],
                    "Accept": "application/javascript,text/javascript,*/*;q=0.5",
                },
                truncate_response=True,
            )
            if response.status_code >= 400:
                raise ModuleExecutionError(
                    f"JavaScript fetch returned HTTP {response.status_code}",
                    retryable=response.status_code == 429 or response.status_code >= 500,
                    code="javascript_http_error",
                )
        except (PinnedHTTPRequestError, UnsafeDestinationError, OSError) as exc:
            raise ModuleExecutionError(
                f"JavaScript fetch failed: {exc}", code="javascript_fetch_error"
            ) from exc

        decoded = response.decoded_body().replace(r"\/", "/")
        candidates = set(self._absolute_url.findall(decoded))
        candidates.update(self._quoted_path.findall(decoded))
        source = AssetReference(AssetKind.javascript.value, context.input_asset.canonical_value)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[str] = set()
        seen_parameters: set[str] = set()
        parameter_relationships = 0
        for candidate in sorted(candidates):
            resolved = urljoin(context.input_asset.canonical_value, candidate)
            parsed = urlsplit(resolved)
            if not self._interesting_path.search(parsed.path):
                continue
            try:
                endpoint = normalize_asset(AssetKind.endpoint, f"GET {resolved}")
            except NormalizationError:
                continue
            if endpoint.canonical_value in seen:
                continue
            seen.add(endpoint.canonical_value)
            evidence = {"source": "javascript_static_analysis"}
            assets.append(
                AssetEmission(
                    AssetKind.endpoint.value,
                    endpoint.canonical_value,
                    {"discovered_via": "javascript"},
                    confidence=0.7,
                    evidence=evidence,
                )
            )
            endpoint_ref = AssetReference(AssetKind.endpoint.value, endpoint.canonical_value)
            relationships.append(
                RelationshipEmission(
                    source,
                    endpoint_ref,
                    "references_endpoint",
                    confidence=0.7,
                    evidence=evidence,
                )
            )
            for parameter in endpoint.attributes.get("query_parameters", [])[:100]:
                if parameter not in seen_parameters:
                    if len(seen_parameters) >= 2_000:
                        continue
                    seen_parameters.add(parameter)
                    assets.append(AssetEmission(AssetKind.parameter.value, parameter))
                if parameter_relationships < 5_000:
                    relationships.append(
                        RelationshipEmission(
                            endpoint_ref,
                            AssetReference(AssetKind.parameter.value, parameter),
                            "accepts_parameter",
                            confidence=0.7,
                            evidence=evidence,
                        )
                    )
                    parameter_relationships += 1
            if len(seen) >= max_endpoints:
                break
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            metadata={
                "endpoints_discovered": len(seen),
                "potential_secret_patterns": len(self._secret_signal.findall(decoded)),
                "body_bytes_captured": len(response.body),
                "body_truncated": response.truncated,
            },
        )


class CertificateTransparencyModule:
    manifest = ModuleManifest(
        name="ct.certspotter",
        version="1",
        description="Discover certificate names from Cert Spotter's public CT API",
        capability="certificate.transparency",
        consumes=frozenset({AssetKind.domain.value}),
        produces=frozenset({AssetKind.domain.value}),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive", "balanced", "active"}),
        priority=150,
        timeout_seconds=120,
        max_attempts=3,
        cache_ttl_seconds=21_600,
        rate_limit_per_second=0.2,
        implementation="certspotter-api",
    )

    @staticmethod
    def accepts(asset) -> bool:
        return bool(asset.attributes.get("seed"))

    def execute(self, context: ModuleContext) -> ModuleResult:
        root = context.input_asset.canonical_value
        endpoint = "https://api.certspotter.com/v1/issuances"
        max_pages = min(max(int(context.config.get("max_pages", 25)), 1), 100)
        max_issuances = min(max(int(context.config.get("max_issuances", 50_000)), 1), 200_000)
        deadline = time.monotonic() + max(float(context.timeout_seconds), 1.0)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        seen: set[str] = set()
        pages = 0
        issuances = 0
        after: str | None = None
        cursors: set[str] = set()
        truncated = False
        try:
            with httpx.Client(
                follow_redirects=False,
                trust_env=False,
                headers={"User-Agent": "Reconator/3 authorized-recon"},
            ) as client:
                while pages < max_pages and issuances < max_issuances:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ModuleExecutionError(
                            "certificate pagination exceeded the module deadline",
                            code="source_timeout",
                        )
                    params = {
                        "domain": root,
                        "include_subdomains": "true",
                        "expand": "dns_names",
                    }
                    if after is not None:
                        params["after"] = after
                    with client.stream(
                        "GET",
                        endpoint,
                        params=params,
                        timeout=min(remaining, 30.0),
                    ) as response:
                        response.raise_for_status()
                        payload = bytearray()
                        for chunk in response.iter_bytes():
                            payload.extend(chunk)
                            if len(payload) > 5_000_000:
                                raise ModuleExecutionError(
                                    "certificate response page exceeded 5 MB",
                                    retryable=False,
                                    code="response_too_large",
                                )
                    try:
                        records = json.loads(payload)
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        raise ModuleExecutionError(
                            "certificate source returned malformed JSON",
                            code="source_malformed",
                        ) from exc
                    if not isinstance(records, list):
                        raise ModuleExecutionError(
                            "certificate source returned a non-list page",
                            code="source_malformed",
                        )
                    pages += 1
                    if not records:
                        break
                    remaining_issuances = max_issuances - issuances
                    page_records = records[:remaining_issuances]
                    if len(page_records) < len(records):
                        truncated = True
                    for record in page_records:
                        if not isinstance(record, dict):
                            continue
                        issuances += 1
                        names = record.get("dns_names", [])
                        if not isinstance(names, list):
                            continue
                        for raw_name in names:
                            candidate = str(raw_name).removeprefix("*.").rstrip(".").lower()
                            try:
                                normalized = normalize_asset(AssetKind.domain, candidate)
                            except NormalizationError:
                                continue
                            if (
                                normalized.canonical_value == root
                                or not normalized.canonical_value.endswith(f".{root}")
                            ):
                                continue
                            if normalized.canonical_value in seen:
                                continue
                            seen.add(normalized.canonical_value)
                            evidence = {"source": "certspotter", "root": root}
                            assets.append(
                                AssetEmission(
                                    AssetKind.domain.value,
                                    normalized.canonical_value,
                                    {"discovered_via": "certificate_transparency"},
                                    confidence=0.9,
                                    evidence=evidence,
                                    source_name="certspotter",
                                )
                            )
                            relationships.append(
                                RelationshipEmission(
                                    source=AssetReference(AssetKind.domain.value, root),
                                    target=AssetReference(
                                        AssetKind.domain.value, normalized.canonical_value
                                    ),
                                    relationship_type="has_subdomain",
                                    confidence=0.9,
                                    evidence=evidence,
                                )
                            )
                    if truncated:
                        break
                    last = records[-1]
                    next_cursor = str(last.get("id", "")) if isinstance(last, dict) else ""
                    if not next_cursor:
                        truncated = True
                        break
                    if next_cursor in cursors:
                        raise ModuleExecutionError(
                            "certificate source repeated a pagination cursor",
                            retryable=False,
                            code="source_cursor_loop",
                        )
                    cursors.add(next_cursor)
                    after = next_cursor
                else:
                    truncated = True
        except httpx.HTTPError as exc:
            raise ModuleExecutionError(
                f"certificate transparency request failed: {exc}", code="source_error"
            ) from exc
        return ModuleResult(
            assets=assets,
            relationships=relationships,
            metadata={
                "certificate_names": len(assets),
                "issuances_processed": issuances,
                "pages_fetched": pages,
                "pagination_truncated": truncated,
                "last_cursor": after,
            },
        )


class TCPConnectModule:
    manifest = ModuleManifest(
        name="network.tcp_connect",
        version="1",
        description="Scope-gated TCP discovery with a small configurable port set",
        capability="network.port_discovery",
        consumes=frozenset({AssetKind.ip_address.value}),
        produces=frozenset({AssetKind.port.value, AssetKind.service.value}),
        mode=ModuleMode.active,
        default_profiles=frozenset({"active"}),
        priority=90,
        timeout_seconds=120,
        max_attempts=2,
        cache_ttl_seconds=3_600,
        rate_limit_per_second=1.0,
        implementation="python-socket",
    )
    default_ports = (21, 22, 25, 53, 80, 110, 143, 443, 445, 587, 993, 995, 3000, 8000, 8080, 8443)

    def execute(self, context: ModuleContext) -> ModuleResult:
        address = ipaddress.ip_address(context.input_asset.canonical_value)
        if not address.is_global and not context.config.get("allow_private_networks", False):
            raise ModuleExecutionError(
                "non-public IP scanning is disabled by the deployment safety policy",
                retryable=False,
                code="private_network_blocked",
            )
        raw_ports = context.config.get("ports", self.default_ports)
        if not isinstance(raw_ports, list | tuple) or len(raw_ports) > 100:
            raise ModuleExecutionError(
                "ports must be a list containing at most 100 entries",
                retryable=False,
                code="invalid_config",
            )
        try:
            ports = sorted({int(port) for port in raw_ports if 0 < int(port) <= 65535})
        except (TypeError, ValueError) as exc:
            raise ModuleExecutionError(
                "ports contain an invalid value", retryable=False, code="invalid_config"
            ) from exc
        connect_timeout = min(float(context.config.get("connect_timeout", 1.0)), 5.0)
        assets: list[AssetEmission] = []
        relationships: list[RelationshipEmission] = []
        source = AssetReference(AssetKind.ip_address.value, address.compressed)
        for port in ports:
            try:
                with socket.create_connection((address.compressed, port), timeout=connect_timeout):
                    pass
            except OSError:
                continue
            port_value = f"tcp/{port}"
            service_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
            service_value = f"tcp://{service_host}:{port}"
            assets.extend(
                [
                    AssetEmission(AssetKind.port.value, port_value),
                    AssetEmission(
                        AssetKind.service.value,
                        service_value,
                        {"transport": "tcp", "port": port, "address": address.compressed},
                    ),
                ]
            )
            relationships.extend(
                [
                    RelationshipEmission(
                        source, AssetReference(AssetKind.port.value, port_value), "exposes_port"
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
            metadata={"ports_checked": len(ports), "open_services": len(assets) // 2},
        )


def _detect_openapi_document(
    url: str,
    content_type: str,
    decoded_body: str,
) -> tuple[bool, tuple[str, ...]]:
    """Identify strong OpenAPI signals without parsing or making another request."""

    media_type = content_type.partition(";")[0].strip().lower()
    path = urlsplit(url).path.lower().rstrip("/")
    filename = path.rsplit("/", 1)[-1]
    path_hint = filename in _OPENAPI_DOCUMENT_NAMES or path.endswith(
        ("/v2/api-docs", "/v3/api-docs")
    )
    vendor_content_type = "openapi" in media_type or "swagger" in media_type
    structured_content_type = (
        media_type in _OPENAPI_STRUCTURED_MEDIA_TYPES
        or media_type.endswith("+json")
        or media_type.endswith("+yaml")
    )
    snippet = decoded_body[:65_536].lstrip("\ufeff \t\r\n")
    body_marker = bool(
        (snippet.startswith("{") and _OPENAPI_JSON_MARKER.search(snippet))
        or _OPENAPI_YAML_MARKER.search(snippet)
    )
    signals: list[str] = []
    if vendor_content_type:
        signals.append("vendor_content_type")
    if path_hint:
        signals.append("document_path")
    if structured_content_type:
        signals.append("structured_content_type")
    if body_marker:
        signals.append("document_body_marker")
    detected = vendor_content_type or body_marker or (path_hint and structured_content_type)
    return detected, tuple(signals)


class HTTPProbeModule:
    manifest = ModuleManifest(
        name="http.probe",
        version="1",
        description="Safely probe HTTP services without following out-of-scope redirects",
        capability="http.probe",
        consumes=frozenset({AssetKind.domain.value, AssetKind.url.value}),
        produces=frozenset(
            {
                AssetKind.url.value,
                AssetKind.domain.value,
                AssetKind.technology.value,
                AssetKind.endpoint.value,
                AssetKind.parameter.value,
                AssetKind.javascript.value,
                "auth_scheme",
                "callback",
                "webhook",
            }
        ),
        mode=ModuleMode.active,
        default_profiles=frozenset({"balanced", "active"}),
        priority=120,
        timeout_seconds=30,
        max_attempts=2,
        cache_ttl_seconds=3_600,
        rate_limit_per_second=2.0,
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        if context.input_asset.kind == AssetKind.url.value:
            candidate_urls = [context.input_asset.canonical_value]
        else:
            host = context.input_asset.canonical_value
            candidate_urls = [f"https://{host}/", f"http://{host}/"]
        allow_private = bool(context.config.get("allow_private_networks", False))
        timeout = min(float(context.timeout_seconds), 30.0)
        max_body = min(
            max(int(context.config.get("http_max_body_bytes", 65_536)), 1_024), 1_000_000
        )
        user_agent = str(context.config.get("user_agent", "Reconator/3 authorized-recon"))[:256]
        failures: list[str] = []

        for url in candidate_urls:
            try:
                response = pinned_http_request(
                    url,
                    timeout=timeout,
                    max_response_bytes=max_body,
                    allow_private=allow_private,
                    allowed_schemes=frozenset({"http", "https"}),
                    truncate_response=True,
                    headers={
                        "User-Agent": user_agent,
                        "Accept": "text/html,*/*;q=0.8",
                    },
                )
                return self._result(context, response)
            except (PinnedHTTPRequestError, UnsafeDestinationError, OSError) as exc:
                failures.append(f"{url}: {type(exc).__name__}: {exc}")
        raise ModuleExecutionError("; ".join(failures), code="http_unreachable")

    @staticmethod
    def _result(
        context: ModuleContext,
        response: PinnedHTTPResponse,
    ) -> ModuleResult:
        final_url = response.url
        content_type = response.headers.get("content-type", "")[:256]
        server = response.headers.get("server", "")[:256]
        decoded = response.decoded_body()
        title_match = re.search(r"<title[^>]*>(.*?)</title>", decoded, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:512] if title_match else None
        url_attributes = {
            "status_code": response.status_code,
            "content_type": content_type,
            "server": server or None,
            "title": title,
            "resolved_addresses": list(response.resolved_addresses),
        }
        assets = [
            AssetEmission(
                AssetKind.url.value,
                final_url,
                url_attributes,
                evidence={"status_code": response.status_code},
            )
        ]
        source = AssetReference(context.input_asset.kind, context.input_asset.canonical_value)
        relationships = []
        if not (
            source.kind == AssetKind.url.value
            and source.value == normalize_asset(AssetKind.url, final_url).canonical_value
        ):
            relationships.append(
                RelationshipEmission(
                    source=source,
                    target=AssetReference(AssetKind.url.value, final_url),
                    relationship_type="serves",
                    evidence={"status_code": response.status_code},
                )
            )

        if "html" in content_type.lower():
            discovered_assets, discovered_relationships = _extract_html_surface(
                context, final_url, decoded
            )
            assets.extend(discovered_assets)
            relationships.extend(discovered_relationships)

        if server:
            assets.append(
                AssetEmission(
                    AssetKind.technology.value,
                    server,
                    {"source": "server_header"},
                    confidence=0.7,
                )
            )
            relationships.append(
                RelationshipEmission(
                    source=AssetReference(AssetKind.url.value, final_url),
                    target=AssetReference(AssetKind.technology.value, server),
                    relationship_type="uses_technology",
                    confidence=0.7,
                )
            )

        location = response.headers.get("location")
        if location:
            redirect_url = urljoin(final_url, location)
            try:
                normalize_asset(AssetKind.url, redirect_url)
            except NormalizationError:
                pass
            else:
                assets.append(
                    AssetEmission(
                        AssetKind.url.value,
                        redirect_url,
                        {"discovered_via": "redirect"},
                    )
                )
                relationships.append(
                    RelationshipEmission(
                        source=AssetReference(AssetKind.url.value, final_url),
                        target=AssetReference(AssetKind.url.value, redirect_url),
                        relationship_type="redirects_to",
                        evidence={"status_code": response.status_code},
                    )
                )

        metadata: dict[str, Any] = {
            "status_code": response.status_code,
            "body_bytes_captured": len(response.body),
            "body_truncated": response.truncated,
            "openapi_parse_status": "not_detected",
            "openapi_parse_error_code": None,
        }
        detected, detection_signals = _detect_openapi_document(final_url, content_type, decoded)
        metadata["openapi_detection_signals"] = list(detection_signals)
        if detected and response.truncated:
            metadata["openapi_parse_status"] = "skipped_truncated"
            metadata["openapi_parse_error_code"] = "response_truncated"
        elif detected:
            try:
                openapi_result = parse_openapi_document(final_url, decoded)
            except OpenAPIParseError:
                metadata["openapi_parse_status"] = "rejected"
                metadata["openapi_parse_error_code"] = "invalid_openapi_document"
            except Exception:  # Parser isolation: untrusted documents cannot fail HTTP probing.
                metadata["openapi_parse_status"] = "error"
                metadata["openapi_parse_error_code"] = "openapi_parser_error"
            else:
                assets.extend(openapi_result.assets)
                relationships.extend(openapi_result.relationships)
                metadata["openapi_parse_status"] = "parsed"
                metadata["openapi"] = openapi_result.metadata

        return ModuleResult(
            assets=assets,
            relationships=relationships,
            raw_output=decoded,
            metadata=metadata,
        )


def register_builtin_modules(module_registry: ModuleRegistry = registry) -> None:
    from app.recon.modules.toolbox import toolbox_modules

    builtins = [
        _dns_module("A", 140),
        _dns_module("AAAA", 135),
        _domain_dns_module(
            "CNAME",
            capability="dns.aliases",
            relationship_type="aliases_to",
            priority=130,
        ),
        _domain_dns_module(
            "NS",
            capability="dns.nameservers",
            relationship_type="uses_nameserver",
            priority=125,
        ),
        _domain_dns_module(
            "MX",
            capability="dns.mail_infrastructure",
            relationship_type="receives_mail_via",
            priority=120,
        ),
        _txt_dns_module(),
        _reverse_dns_module(),
        CertificateTransparencyModule(),
        HTTPProbeModule(),
        JavaScriptEndpointModule(),
        TCPConnectModule(),
        CIDRExpansionModule(),
        RDAPIPModule(),
        RIPEstatNetworkInfoModule(),
        RIPEstatAnnouncedPrefixesModule(),
        URLStructureModule(),
        *toolbox_modules(),
    ]
    for module in builtins:
        if module_registry.get(module.manifest.name) is None:
            module_registry.register(module)
