import pytest

from app.db.models import ScopeRule
from app.recon.scope import ScopeConfigurationError, ScopePolicy, normalize_rule_pattern


def rule(action, rule_type, pattern, *, asset_kind=None, priority=100):
    return ScopeRule(
        action=action,
        rule_type=rule_type,
        pattern=pattern,
        normalized_pattern=normalize_rule_pattern(rule_type, pattern),
        asset_kind=asset_kind,
        priority=priority,
    )


def test_scope_is_default_deny_and_applies_domain_rule_to_urls():
    policy = ScopePolicy([rule("include", "subdomain", "example.com")])
    assert policy.decide("domain", "api.example.com").allowed
    assert policy.decide("url", "https://api.example.com/login").allowed
    assert not policy.decide("domain", "example.net").allowed
    assert not policy.decide("ip_address", "93.184.216.34").allowed


def test_recursive_scope_rejects_public_suffix_but_exact_scope_allows_it():
    with pytest.raises(ScopeConfigurationError):
        normalize_rule_pattern("subdomain", "github.io")
    assert normalize_rule_pattern("exact", "github.io") == "github.io"


def test_exclusion_always_wins_over_inclusion():
    policy = ScopePolicy(
        [
            rule("include", "subdomain", "example.com", priority=1),
            rule("exclude", "subdomain", "internal.example.com", priority=999),
        ]
    )
    decision = policy.decide("url", "https://admin.internal.example.com/")
    assert not decision.allowed
    assert "exclusion" in decision.reason


def test_cidr_rules_do_not_expand_network_boundaries():
    policy = ScopePolicy([rule("include", "cidr", "192.0.2.0/28")])
    assert policy.decide("ip_address", "192.0.2.4").allowed
    assert policy.decide("cidr", "192.0.2.0/30").allowed
    assert not policy.decide("ip_address", "192.0.2.20").allowed
    assert not policy.decide("cidr", "192.0.2.0/24").allowed


def test_unsafe_regex_is_rejected():
    with pytest.raises(ScopeConfigurationError):
        normalize_rule_pattern("regex", r"(a+)+$")


def test_scope_regex_rejects_ambiguous_repetition_bombs():
    with pytest.raises(ScopeConfigurationError):
        normalize_rule_pattern("regex", r"a?a?a?a?a?a?a?a?a?b")


def test_scope_regex_allows_bounded_regular_patterns():
    pattern = r"^https?://[a-z0-9.-]+/api/.*$"
    assert normalize_rule_pattern("regex", pattern) == pattern
