from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.db.models import AssetKind, ScopeAction, ScopeRule, ScopeRuleType
from app.recon.normalization import (
    NormalizationError,
    normalize_asset,
    normalize_domain,
    validate_scope_root_domain,
)


class ScopeConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    allowed: bool
    reason: str
    rule_id: int | None = None


def validate_regex(pattern: str) -> str:
    if len(pattern) > 512:
        raise ScopeConfigurationError("scope regex exceeds 512 characters")
    # Python's backtracking regex engine has no execution deadline. Keep this
    # operator-facing syntax intentionally regular: character classes,
    # anchors, alternation, literals, and a small number of repetitions cover
    # useful scope policies without admitting quantified groups or backrefs.
    in_character_class = False
    escaped = False
    unbounded_repetitions = 0
    repetition_operators = 0
    for character in pattern:
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "[":
            in_character_class = True
            continue
        if character == "]" and in_character_class:
            in_character_class = False
            continue
        if in_character_class:
            continue
        if character in "()":
            raise ScopeConfigurationError("scope regex groups are not permitted")
        if character in "*+":
            unbounded_repetitions += 1
        if character in "*+?{":
            repetition_operators += 1
    if repetition_operators > 8:
        raise ScopeConfigurationError("scope regex has too many repetition operators")
    if unbounded_repetitions > 3 or re.search(r"\{\d+,\}", pattern):
        raise ScopeConfigurationError("scope regex has too many unbounded repetitions")
    for match in re.finditer(r"\{(\d+)(?:,(\d+))?\}", pattern):
        upper = int(match.group(2) or match.group(1))
        if upper > 1_024:
            raise ScopeConfigurationError("scope regex repetition bound is too large")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ScopeConfigurationError(f"invalid scope regex: {exc}") from exc
    return pattern


def normalize_rule_pattern(rule_type: str, pattern: str) -> str:
    rule_type = ScopeRuleType(rule_type).value
    if rule_type in {ScopeRuleType.exact.value, ScopeRuleType.subdomain.value}:
        try:
            normalized = normalize_domain(pattern)
            if rule_type == ScopeRuleType.subdomain.value:
                validate_scope_root_domain(normalized)
            return normalized
        except NormalizationError:
            if rule_type == ScopeRuleType.exact.value:
                try:
                    return ipaddress.ip_address(pattern.strip()).compressed
                except ValueError:
                    pass
            raise ScopeConfigurationError("scope pattern must be a domain or IP address") from None
    if rule_type == ScopeRuleType.cidr.value:
        try:
            return ipaddress.ip_network(pattern.strip(), strict=False).with_prefixlen
        except ValueError as exc:
            raise ScopeConfigurationError("scope CIDR is invalid") from exc
    if rule_type == ScopeRuleType.url_prefix.value:
        try:
            return normalize_asset(AssetKind.url, pattern).canonical_value
        except NormalizationError as exc:
            raise ScopeConfigurationError(str(exc)) from exc
    if rule_type == ScopeRuleType.regex.value:
        return validate_regex(pattern)
    raise ScopeConfigurationError(f"unsupported scope rule type: {rule_type}")


class ScopePolicy:
    """Default-deny scope evaluator shared by every module and execution adapter."""

    def __init__(self, rules: list[ScopeRule]) -> None:
        self.rules = sorted(
            rules,
            key=lambda rule: (
                0 if rule.action == ScopeAction.exclude.value else 1,
                rule.priority,
                rule.id or 0,
            ),
        )

    @staticmethod
    def _subject(kind: str, canonical_value: str) -> tuple[str, str | None]:
        if kind in {
            AssetKind.url.value,
            AssetKind.endpoint.value,
            AssetKind.repository.value,
            AssetKind.javascript.value,
            AssetKind.service.value,
        }:
            raw_url = canonical_value.split(" ", 1)[-1]
            parsed = urlsplit(raw_url)
            subject = raw_url if kind == AssetKind.endpoint.value else canonical_value
            return subject, parsed.hostname
        if kind in {AssetKind.domain.value, AssetKind.ip_address.value, AssetKind.cidr.value}:
            return canonical_value, canonical_value
        return canonical_value, None

    @classmethod
    def _matches(cls, rule: ScopeRule, kind: str, canonical_value: str) -> bool:
        if rule.asset_kind and rule.asset_kind != kind:
            return False
        subject, host = cls._subject(kind, canonical_value)
        pattern = rule.normalized_pattern

        if rule.rule_type == ScopeRuleType.exact.value:
            return subject == pattern or host == pattern
        if rule.rule_type == ScopeRuleType.subdomain.value:
            return bool(host and (host == pattern or host.endswith(f".{pattern}")))
        if rule.rule_type == ScopeRuleType.url_prefix.value:
            return subject == pattern or subject.startswith(pattern.rstrip("/") + "/")
        if rule.rule_type == ScopeRuleType.regex.value:
            return re.fullmatch(pattern, subject) is not None
        if rule.rule_type == ScopeRuleType.cidr.value:
            try:
                allowed_network = ipaddress.ip_network(pattern)
                if kind == AssetKind.ip_address.value:
                    return ipaddress.ip_address(canonical_value) in allowed_network
                if kind == AssetKind.cidr.value:
                    return ipaddress.ip_network(canonical_value).subnet_of(allowed_network)
                if host:
                    return ipaddress.ip_address(host) in allowed_network
            except ValueError:
                return False
        return False

    def decide(self, kind: str | AssetKind, value: str) -> ScopeDecision:
        try:
            normalized = normalize_asset(kind, value)
        except NormalizationError as exc:
            return ScopeDecision(False, f"invalid asset: {exc}")

        includes: list[ScopeRule] = []
        for rule in self.rules:
            if not self._matches(rule, normalized.kind, normalized.canonical_value):
                continue
            if rule.action == ScopeAction.exclude.value:
                return ScopeDecision(False, rule.reason or "matched exclusion", rule.id)
            includes.append(rule)
        if includes:
            rule = includes[0]
            return ScopeDecision(True, rule.reason or "matched inclusion", rule.id)
        return ScopeDecision(False, "no inclusion rule matched")


def create_root_scope_rules(
    target_id: int, value: str, kind: str = AssetKind.domain.value
) -> list[ScopeRule]:
    """Create the narrowest useful default scope for an authorized seed."""
    normalized = normalize_asset(kind, value)
    base = {
        "target_id": target_id,
        "action": ScopeAction.include.value,
        "priority": 100,
    }
    if normalized.kind == AssetKind.domain.value:
        try:
            validate_scope_root_domain(normalized.canonical_value)
        except NormalizationError as exc:
            raise ScopeConfigurationError(str(exc)) from exc
        return [
            ScopeRule(
                **base,
                rule_type=ScopeRuleType.subdomain.value,
                asset_kind=None,
                pattern=value,
                normalized_pattern=normalized.canonical_value,
                reason="authorized root domain and its subdomains",
            )
        ]
    if normalized.kind == AssetKind.url.value:
        host = normalized.attributes["host"]
        host_kind = AssetKind.ip_address.value if _is_ip_address(host) else AssetKind.domain.value
        if host_kind == AssetKind.domain.value:
            try:
                validate_scope_root_domain(host)
            except NormalizationError as exc:
                raise ScopeConfigurationError(str(exc)) from exc
        return [
            ScopeRule(
                **base,
                rule_type=ScopeRuleType.url_prefix.value,
                asset_kind=None,
                pattern=value,
                normalized_pattern=normalized.canonical_value,
                reason="authorized URL prefix",
            ),
            ScopeRule(
                **base,
                rule_type=ScopeRuleType.exact.value,
                asset_kind=host_kind,
                pattern=host,
                normalized_pattern=host,
                reason="host required to investigate the authorized URL",
            ),
        ]
    if normalized.kind == AssetKind.ip_address.value:
        return [
            ScopeRule(
                **base,
                rule_type=ScopeRuleType.exact.value,
                asset_kind=None,
                pattern=value,
                normalized_pattern=normalized.canonical_value,
                reason="authorized IP address",
            )
        ]
    if normalized.kind == AssetKind.cidr.value:
        return [
            ScopeRule(
                **base,
                rule_type=ScopeRuleType.cidr.value,
                asset_kind=None,
                pattern=value,
                normalized_pattern=normalized.canonical_value,
                reason="authorized network range",
            )
        ]
    raise ScopeConfigurationError(f"unsupported root target kind: {normalized.kind}")


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
