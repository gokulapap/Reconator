import json

import pytest

from app.core.network import PinnedHTTPRequestError, PinnedHTTPResponse
from app.db.models import AssetKind, ReconTask, Target, TaskStatus
from app.recon.modules import builtin
from app.recon.modules.base import (
    ModuleContext,
    ModuleExecutionError,
    ModuleManifest,
    ModuleMode,
    ModuleResult,
)
from app.recon.modules.registry import ModuleRegistry
from app.recon.normalization import normalize_asset
from app.recon.orchestration import TaskScheduler


def _context(kind: str, value: str, config=None) -> ModuleContext:
    return ModuleContext(
        target_id=1,
        task_id=1,
        input_asset=normalize_asset(kind, value),
        config=config or {},
        timeout_seconds=30,
    )


def _payload(data_call: str, version: str, data: dict, *, cached: bool = False) -> dict:
    return {
        "status": "ok",
        "status_code": 200,
        "data_call_name": data_call,
        "data_call_status": "supported",
        "version": version,
        "cached": cached,
        "data": data,
    }


def _response(payload: dict, *, status_code: int = 200) -> PinnedHTTPResponse:
    return PinnedHTTPResponse(
        status_code=status_code,
        reason="OK" if status_code == 200 else "fixture error",
        headers={"content-type": "application/json; charset=utf-8"},
        body=json.dumps(payload).encode(),
        url="https://stat.ripe.net/fixture",
        resolved_addresses=("193.0.0.1",),
    )


def _timeline() -> list[dict[str, str]]:
    return [
        {
            "starttime": "2026-08-10T00:00:00",
            "endtime": "2026-08-24T00:00:00",
        }
    ]


def _network_info_response() -> PinnedHTTPResponse:
    return _response(
        _payload(
            "network-info",
            "1.1",
            {"prefix": "45.33.32.0/24", "asns": [63949]},
        )
    )


def _announced_prefixes_response() -> PinnedHTTPResponse:
    return _response(
        _payload(
            "announced-prefixes",
            "1.2",
            {
                "resource": "AS63949",
                "query_starttime": "2026-08-10T00:00:00",
                "query_endtime": "2026-08-24T00:00:00",
                "prefixes": [
                    {"prefix": "45.33.32.0/24", "timelines": _timeline()},
                    {"prefix": "198.51.100.0/24", "timelines": _timeline()},
                ],
            },
        )
    )


def test_network_info_uses_only_the_fixed_bounded_endpoint_and_models_graph(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return _response(
            _payload(
                "network-info",
                "1.1",
                {"prefix": "45.33.32.0/24", "asns": [63949, "AS63949", 64500]},
                cached=True,
            )
        )

    monkeypatch.setattr(builtin, "pinned_http_request", request)
    result = builtin.RIPEstatNetworkInfoModule().execute(
        _context(AssetKind.ip_address.value, "45.33.32.156")
    )

    assert calls[0][0] == (
        "https://stat.ripe.net/data/network-info/data.json"
        "?resource=45.33.32.156&preferred_version=1.1"
    )
    assert calls[0][1]["timeout"] == 15
    assert calls[0][1]["max_response_bytes"] == 256_000
    assert calls[0][1]["max_redirects"] == 0
    assert calls[0][1]["headers"]["Accept"] == "application/json"
    assert {(asset.kind, asset.value) for asset in result.assets} == {
        (AssetKind.cidr.value, "45.33.32.0/24"),
        (AssetKind.autonomous_system.value, "AS63949"),
        (AssetKind.autonomous_system.value, "AS64500"),
    }
    assert all(asset.attributes["intelligence_only"] for asset in result.assets)
    assert all(asset.source_name == "ripestat" for asset in result.assets)
    assert {
        (
            relationship.source.kind,
            relationship.source.value,
            relationship.relationship_type,
            relationship.target.kind,
            relationship.target.value,
        )
        for relationship in result.relationships
    } == {
        (
            AssetKind.ip_address.value,
            "45.33.32.156",
            "member_of_prefix",
            AssetKind.cidr.value,
            "45.33.32.0/24",
        ),
        (
            AssetKind.cidr.value,
            "45.33.32.0/24",
            "announced_by",
            AssetKind.autonomous_system.value,
            "AS63949",
        ),
        (
            AssetKind.cidr.value,
            "45.33.32.0/24",
            "announced_by",
            AssetKind.autonomous_system.value,
            "AS64500",
        ),
    }
    assert result.metadata["api_cached"] is True


def test_announced_prefixes_validates_windows_deduplicates_and_bounds_output(monkeypatch):
    payload = _payload(
        "announced-prefixes",
        "1.2",
        {
            "resource": 64500,
            "query_starttime": "2026-08-10T00:00:00",
            "query_endtime": "2026-08-24T00:00:00",
            "prefixes": [
                {"prefix": "198.51.100.0/24", "timelines": _timeline()},
                {"prefix": "198.51.100.0/24", "timelines": _timeline()},
                {"prefix": "2001:db8::/32", "timelines": _timeline()},
            ],
        },
    )
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return _response(payload)

    monkeypatch.setattr(builtin, "pinned_http_request", request)
    result = builtin.RIPEstatAnnouncedPrefixesModule().execute(
        _context(
            AssetKind.autonomous_system.value,
            "AS64500",
            {"max_prefixes": 1},
        )
    )

    assert calls[0][0] == (
        "https://stat.ripe.net/data/announced-prefixes/data.json"
        "?resource=AS64500&preferred_version=1.2"
    )
    assert calls[0][1]["max_response_bytes"] == 4_000_000
    assert [(asset.kind, asset.value) for asset in result.assets] == [
        (AssetKind.cidr.value, "198.51.100.0/24")
    ]
    assert len(result.relationships) == 1
    assert result.relationships[0].source.value == "198.51.100.0/24"
    assert result.relationships[0].relationship_type == "announced_by"
    assert result.relationships[0].target.value == "AS64500"
    assert result.relationships[0].attributes == {
        "observation_window_start": "2026-08-10T00:00:00",
        "observation_window_end": "2026-08-24T00:00:00",
    }
    assert result.metadata["prefixes_returned"] == 3
    assert result.metadata["prefixes_unique"] == 2
    assert result.metadata["prefixes_emitted"] == 1
    assert result.metadata["prefixes_truncated"] is True


def test_network_info_skips_non_public_addresses_without_an_http_request(monkeypatch):
    def fail_request(*_args, **_kwargs):
        raise AssertionError("non-public input must not cause an HTTP request")

    monkeypatch.setattr(builtin, "pinned_http_request", fail_request)
    result = builtin.RIPEstatNetworkInfoModule().execute(
        _context(AssetKind.ip_address.value, "192.0.2.10")
    )

    assert not result.assets
    assert result.metadata["skipped"] == "non-public address"


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(429, True), (503, True), (404, False)],
)
def test_ripestat_http_errors_have_explicit_retry_classification(
    monkeypatch, status_code, retryable
):
    monkeypatch.setattr(
        builtin,
        "pinned_http_request",
        lambda *_args, **_kwargs: _response({}, status_code=status_code),
    )

    with pytest.raises(ModuleExecutionError) as raised:
        builtin.RIPEstatNetworkInfoModule().execute(
            _context(AssetKind.ip_address.value, "45.33.32.156")
        )

    assert raised.value.code == "ripestat_http_error"
    assert raised.value.retryable is retryable


def test_ripestat_schema_errors_are_non_retryable(monkeypatch):
    response = _response(
        _payload(
            "announced-prefixes",
            "1.2",
            {
                "resource": "AS64501",
                "query_starttime": "2026-08-10T00:00:00",
                "query_endtime": "2026-08-24T00:00:00",
                "prefixes": [],
            },
        )
    )
    monkeypatch.setattr(builtin, "pinned_http_request", lambda *_args, **_kwargs: response)

    with pytest.raises(ModuleExecutionError) as raised:
        builtin.RIPEstatAnnouncedPrefixesModule().execute(
            _context(AssetKind.autonomous_system.value, "AS64500")
        )

    assert raised.value.code == "ripestat_schema_error"
    assert raised.value.retryable is False


def test_ripestat_response_byte_limit_failures_are_not_retried(monkeypatch):
    def fail_request(*_args, **_kwargs):
        raise PinnedHTTPRequestError("response exceeded 256000 bytes")

    monkeypatch.setattr(builtin, "pinned_http_request", fail_request)

    with pytest.raises(ModuleExecutionError) as raised:
        builtin.RIPEstatNetworkInfoModule().execute(
            _context(AssetKind.ip_address.value, "45.33.32.156")
        )

    assert raised.value.code == "ripestat_response_too_large"
    assert raised.value.retryable is False


def test_announced_prefix_response_item_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(builtin, "_RIPESTAT_MAX_RESPONSE_PREFIXES", 1)
    monkeypatch.setattr(
        builtin,
        "pinned_http_request",
        lambda *_args, **_kwargs: _announced_prefixes_response(),
    )

    with pytest.raises(ModuleExecutionError) as raised:
        builtin.RIPEstatAnnouncedPrefixesModule().execute(
            _context(AssetKind.autonomous_system.value, "AS63949")
        )

    assert raised.value.code == "ripestat_item_limit"
    assert raised.value.retryable is False


class _ForbiddenActiveCIDRModule:
    manifest = ModuleManifest(
        name="test.forbidden_active_cidr",
        version="1",
        description="must never receive a passively derived CIDR",
        capability="test.forbidden_active_cidr",
        consumes=frozenset({AssetKind.cidr.value}),
        produces=frozenset({AssetKind.service.value}),
        mode=ModuleMode.active,
        default_profiles=frozenset({"active"}),
        accepts_derived_inputs=True,
        cache_ttl_seconds=0,
    )

    def execute(self, context: ModuleContext) -> ModuleResult:
        raise AssertionError("derived routing intelligence must not imply active scope")


def test_central_scope_allows_passive_asn_chaining_but_no_cidr_activation(db, monkeypatch):
    def request(url, **_kwargs):
        if "/network-info/" in url:
            return _network_info_response()
        if "/announced-prefixes/" in url:
            return _announced_prefixes_response()
        raise AssertionError(f"unexpected network request: {url}")

    monkeypatch.setattr(builtin, "pinned_http_request", request)
    module_registry = ModuleRegistry()
    module_registry.register(_ForbiddenActiveCIDRModule())
    target = Target(
        url="45.33.32.156",
        target_kind=AssetKind.ip_address.value,
        profile="active",
        selected_modules=[
            "infrastructure.ripestat_network_info",
            "infrastructure.ripestat_announced_prefixes",
            "network.cidr_expand",
            "test.forbidden_active_cidr",
        ],
        authorization_confirmed=False,
    )
    db.add(target)
    db.flush()
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)
    db.commit()

    executed = 0
    while task := (
        db.query(ReconTask)
        .filter_by(target_id=target.id, status=TaskStatus.queued.value)
        .order_by(ReconTask.id)
        .first()
    ):
        task.status = TaskStatus.running.value
        task.lease_owner = "ripestat-test-worker"
        task.attempts += 1
        db.commit()
        scheduler.execute_claimed(task.id, "ripestat-test-worker")
        executed += 1
        assert executed < 5

    tasks = db.query(ReconTask).filter_by(target_id=target.id).all()
    assert executed == 2
    assert {task.module_name for task in tasks} == {
        "infrastructure.ripestat_network_info",
        "infrastructure.ripestat_announced_prefixes",
    }
    scope_basis = {task.module_name: task.scope_basis for task in tasks}
    assert scope_basis["infrastructure.ripestat_network_info"] == "direct"
    assert scope_basis["infrastructure.ripestat_announced_prefixes"] == "derived"
    assert all(task.module_name != "network.cidr_expand" for task in tasks)
    assert all(task.module_name != "test.forbidden_active_cidr" for task in tasks)


def test_ripestat_manifests_are_passive_cached_rate_limited_and_registered():
    module_registry = ModuleRegistry()
    builtin.register_builtin_modules(module_registry)

    for name in (
        "infrastructure.ripestat_network_info",
        "infrastructure.ripestat_announced_prefixes",
    ):
        module = module_registry.get(name)
        assert module is not None
        assert module.manifest.mode == ModuleMode.passive
        assert module.manifest.accepts_derived_inputs is True
        assert module.manifest.cache_ttl_seconds > 0
        assert module.manifest.rate_limit_per_second == 0.5
