import pytest

from app.recon.normalization import NormalizationError, normalize_asset


def test_domain_and_idna_normalization():
    assert normalize_asset("domain", "ExAmPlE.COM.").canonical_value == "example.com"
    assert normalize_asset("domain", "bücher.example").canonical_value == "xn--bcher-kva.example"


def test_url_identity_normalizes_defaults_and_query_order():
    first = normalize_asset("url", "HTTPS://Example.COM:443/a/../login?b=2&a=1#fragment")
    second = normalize_asset("url", "https://example.com/login?a=1&b=2")
    assert first.canonical_value == "https://example.com/login?a=1&b=2"
    assert first.identity_hash == second.identity_hash
    assert first.attributes["query_parameters"] == ["a", "b"]


def test_scheme_is_preserved_but_domain_relationship_can_correlate_it():
    http = normalize_asset("url", "HTTP://Example.com")
    https = normalize_asset("url", "https://example.com/")
    domain = normalize_asset("domain", "example.com")
    assert http.canonical_value == "http://example.com/"
    assert http.identity_hash != https.identity_hash
    assert http.attributes["host"] == domain.canonical_value


def test_network_endpoint_and_extensible_kinds():
    assert normalize_asset("ip_address", "2001:0db8::1").canonical_value == "2001:db8::1"
    assert normalize_asset("cidr", "192.0.2.7/24").canonical_value == "192.0.2.0/24"
    assert (
        normalize_asset("endpoint", "post HTTPS://API.Example.com:443/v1").canonical_value
        == "POST https://api.example.com/v1"
    )
    assert normalize_asset("mobile.application", "  Example App  ").canonical_value == "example app"


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("url", "https://user:secret@example.com"),
        ("domain", "not a domain"),
        ("port", "tcp/70000"),
        ("bad kind!", "value"),
        ("domain", "example.com\nmalicious"),
    ],
)
def test_rejects_unsafe_or_invalid_values(kind, value):
    with pytest.raises(NormalizationError):
        normalize_asset(kind, value)
