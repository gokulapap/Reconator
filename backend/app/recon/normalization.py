from __future__ import annotations

import hashlib
import ipaddress
import json
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from app.db.models import AssetKind

_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_SUPPORTED_URL_SCHEMES = {"http", "https", "ws", "wss", "ftp"}
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}
_MAX_VALUE_LENGTH = 16_384
_CUSTOM_KIND = re.compile(r"^[a-z][a-z0-9_.-]{1,47}$")


class NormalizationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NormalizedAsset:
    kind: str
    value: str
    canonical_value: str
    identity_hash: str
    attributes: dict[str, Any] = field(default_factory=dict)


def stable_digest(*parts: Any) -> str:
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _clean_value(value: str) -> str:
    if not isinstance(value, str):
        raise NormalizationError("asset value must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise NormalizationError("asset value cannot be empty")
    if len(cleaned) > _MAX_VALUE_LENGTH:
        raise NormalizationError(f"asset value exceeds {_MAX_VALUE_LENGTH} characters")
    if _CONTROL_CHARACTERS.search(cleaned):
        raise NormalizationError("asset value contains control characters")
    return cleaned


def normalize_domain(value: str) -> str:
    value = _clean_value(value)
    if "://" in value:
        parsed = urlsplit(value)
        value = parsed.hostname or ""
    value = value.rstrip(".").lower()
    try:
        ascii_domain = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise NormalizationError("domain is not valid IDNA") from exc
    if len(ascii_domain) > 253 or "." not in ascii_domain:
        raise NormalizationError("domain must be a fully qualified domain name")
    if any(not _DOMAIN_LABEL.fullmatch(label) for label in ascii_domain.split(".")):
        raise NormalizationError("domain contains an invalid label")
    return ascii_domain


def normalize_url(value: str) -> tuple[str, dict[str, Any]]:
    value = _clean_value(value)
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in _SUPPORTED_URL_SCHEMES:
        raise NormalizationError(f"unsupported URL scheme: {scheme or '(missing)'}")
    if parsed.username or parsed.password:
        raise NormalizationError("URLs containing credentials are not accepted")
    if not parsed.hostname:
        raise NormalizationError("URL must contain a hostname")

    host = parsed.hostname.rstrip(".").lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        host = normalize_domain(host)
        is_ip = False
    else:
        host = ip.compressed
        is_ip = True

    try:
        port = parsed.port
    except ValueError as exc:
        raise NormalizationError("URL contains an invalid port") from exc
    display_host = f"[{host}]" if is_ip and ":" in host else host
    netloc = display_host
    if port and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{display_host}:{port}"

    raw_path = parsed.path or "/"
    normalized_path = posixpath.normpath(raw_path)
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    if raw_path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"
    normalized_path = quote(normalized_path, safe="/%:@!$&'()*+,;=-._~")

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    canonical_query = urlencode(sorted(query_pairs), doseq=True, safe="/:@")
    canonical = urlunsplit((scheme, netloc, normalized_path, canonical_query, ""))
    return canonical, {
        "scheme": scheme,
        "host": host,
        "port": port or _DEFAULT_PORTS.get(scheme),
        "path": normalized_path,
        "query_parameters": sorted({name for name, _ in query_pairs}),
    }


def _normalize_email(value: str) -> tuple[str, dict[str, Any]]:
    value = _clean_value(value)
    local, separator, domain = value.rpartition("@")
    if not separator or not local:
        raise NormalizationError("email address is invalid")
    canonical_domain = normalize_domain(domain)
    return f"{local}@{canonical_domain}", {"domain": canonical_domain}


def _normalize_asn(value: str) -> str:
    value = _clean_value(value).upper()
    if value.startswith("AS"):
        value = value[2:]
    if not value.isdigit() or not 0 < int(value) <= 4_294_967_295:
        raise NormalizationError("autonomous system number is invalid")
    return f"AS{int(value)}"


def normalize_asset(
    kind: str | AssetKind,
    value: str,
    attributes: dict[str, Any] | None = None,
) -> NormalizedAsset:
    kind_value = kind.value if isinstance(kind, AssetKind) else str(kind).lower().strip()
    try:
        AssetKind(kind_value)
    except ValueError as exc:
        if not _CUSTOM_KIND.fullmatch(kind_value):
            raise NormalizationError(f"invalid custom asset kind: {kind_value}") from exc

    original = _clean_value(value)
    derived: dict[str, Any] = {}

    if kind_value == AssetKind.domain.value:
        canonical = normalize_domain(original)
    elif kind_value in {
        AssetKind.url.value,
        AssetKind.repository.value,
        AssetKind.javascript.value,
    }:
        canonical, derived = normalize_url(original)
    elif kind_value == AssetKind.ip_address.value:
        try:
            canonical = ipaddress.ip_address(original).compressed
        except ValueError as exc:
            raise NormalizationError("IP address is invalid") from exc
        derived = {"version": ipaddress.ip_address(canonical).version}
    elif kind_value == AssetKind.cidr.value:
        try:
            network = ipaddress.ip_network(original, strict=False)
        except ValueError as exc:
            raise NormalizationError("CIDR is invalid") from exc
        canonical = network.with_prefixlen
        derived = {"version": network.version, "size": network.num_addresses}
    elif kind_value == AssetKind.email.value:
        canonical, derived = _normalize_email(original)
    elif kind_value == AssetKind.autonomous_system.value:
        canonical = _normalize_asn(original)
    elif kind_value == AssetKind.certificate.value:
        canonical = re.sub(r"[^a-fA-F0-9]", "", original).lower()
        if len(canonical) not in {40, 64, 128}:
            raise NormalizationError("certificate identity must be a SHA fingerprint")
    elif kind_value == AssetKind.endpoint.value:
        method, separator, endpoint_url = original.partition(" ")
        if not separator:
            method, endpoint_url = "GET", original
        canonical_url, derived = normalize_url(endpoint_url)
        method = method.upper()
        if not re.fullmatch(r"[A-Z]{3,16}", method):
            raise NormalizationError("endpoint HTTP method is invalid")
        canonical = f"{method} {canonical_url}"
        derived["method"] = method
    elif kind_value == AssetKind.port.value:
        match = re.fullmatch(r"(?:(tcp|udp)/)?(\d{1,5})", original.lower())
        if not match or not 0 < int(match.group(2)) <= 65535:
            raise NormalizationError("port must be formatted as [tcp|udp]/1-65535")
        protocol = match.group(1) or "tcp"
        canonical = f"{protocol}/{int(match.group(2))}"
        derived = {"protocol": protocol, "port": int(match.group(2))}
    elif kind_value in {AssetKind.parameter.value, AssetKind.dns_record.value}:
        canonical = original
    else:
        canonical = " ".join(original.split()).lower()

    merged_attributes = {**derived, **(attributes or {})}
    return NormalizedAsset(
        kind=kind_value,
        value=original,
        canonical_value=canonical,
        identity_hash=stable_digest(kind_value, canonical),
        attributes=merged_attributes,
    )
