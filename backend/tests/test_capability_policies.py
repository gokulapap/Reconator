from datetime import timedelta

import pytest

from app.db.models import ReconTask, Target, TargetStatus, TaskDependency, TaskStatus
from app.recon.knowledge import utcnow
from app.recon.modules.base import (
    CapabilityExecutionPolicy,
    ModuleExecutionError,
    ModuleManifest,
    ModuleMode,
    ModuleResult,
)
from app.recon.modules.registry import ModuleRegistry
from app.recon.orchestration import TaskScheduler


class PolicyModule:
    def __init__(
        self,
        name: str,
        *,
        capability: str = "test.policy",
        policy: CapabilityExecutionPolicy | None = None,
        implementation_priority: int = 100,
        fail: bool = False,
        calls: list[str] | None = None,
        depends_on_capabilities: frozenset[str] = frozenset(),
        cache_ttl_seconds: int = 0,
    ) -> None:
        self.manifest = ModuleManifest(
            name=name,
            version="1",
            description="capability policy fixture",
            capability=capability,
            consumes=frozenset({"domain"}),
            produces=frozenset({"technology"}),
            mode=ModuleMode.local,
            default_profiles=frozenset({"passive"}),
            max_attempts=1,
            cache_ttl_seconds=cache_ttl_seconds,
            capability_policy=policy,
            implementation_priority=implementation_priority,
            depends_on_capabilities=depends_on_capabilities,
        )
        self.fail = fail
        self.calls = calls if calls is not None else []
        self.received_configs: list[dict] = []

    def execute(self, context):
        self.calls.append(self.manifest.name)
        self.received_configs.append(context.config)
        if self.fail:
            raise ModuleExecutionError("fixture failure", retryable=False, code="fixture_failure")
        return ModuleResult()


class PolicyDependent(PolicyModule):
    def __init__(self, calls: list[str]) -> None:
        super().__init__(
            "test.policy_dependent",
            capability="test.dependent",
            calls=calls,
            depends_on_capabilities=frozenset({"test.policy"}),
        )


def policy_target(db, *module_names: str) -> Target:
    target = Target(
        url="policy.example.com",
        profile="passive",
        selected_modules=list(module_names),
        authorization_confirmed=True,
    )
    db.add(target)
    db.flush()
    return target


@pytest.fixture(autouse=True)
def cleanup_policy_targets(db):
    yield
    for target in db.query(Target).filter(Target.url == "policy.example.com"):
        db.delete(target)
    db.commit()


def drain(db, scheduler: TaskScheduler) -> None:
    count = 0
    while task := scheduler.claim_next("policy-worker"):
        scheduler.execute_claimed(task.id, "policy-worker")
        count += 1
        assert count < 10


def test_parallel_is_the_default_and_runs_every_implementation(db):
    calls: list[str] = []
    module_registry = ModuleRegistry()
    module_registry.register(PolicyModule("test.parallel_a", calls=calls))
    module_registry.register(PolicyModule("test.parallel_b", calls=calls))
    target = policy_target(db, "test.parallel_a", "test.parallel_b")
    scheduler = TaskScheduler(db, module_registry)

    scheduler.bootstrap(target)
    tasks = db.query(ReconTask).filter_by(target_id=target.id).all()
    assert {task.status for task in tasks} == {TaskStatus.queued.value}
    assert db.query(TaskDependency).count() == 0

    drain(db, scheduler)
    assert sorted(calls) == ["test.parallel_a", "test.parallel_b"]


def test_preferred_fallback_suppresses_lower_rank_after_success(db):
    calls: list[str] = []
    module_registry = ModuleRegistry()
    module_registry.register(
        PolicyModule(
            "test.preferred",
            policy=CapabilityExecutionPolicy.preferred_then_fallback,
            implementation_priority=200,
            calls=calls,
        )
    )
    module_registry.register(
        PolicyModule("test.fallback", implementation_priority=100, calls=calls)
    )
    module_registry.register(
        PolicyModule("test.last_fallback", implementation_priority=50, calls=calls)
    )
    module_registry.register(PolicyDependent(calls))
    target = policy_target(
        db,
        "test.preferred",
        "test.fallback",
        "test.last_fallback",
        "test.policy_dependent",
    )
    scheduler = TaskScheduler(db, module_registry)

    scheduler.bootstrap(target)
    drain(db, scheduler)

    fallback = db.query(ReconTask).filter_by(module_name="test.fallback").one()
    last_fallback = db.query(ReconTask).filter_by(module_name="test.last_fallback").one()
    dependent = db.query(ReconTask).filter_by(module_name="test.policy_dependent").one()
    assert calls == ["test.preferred", "test.policy_dependent"]
    assert fallback.status == TaskStatus.skipped.value
    assert fallback.error_code == "fallback_not_required"
    assert last_fallback.status == TaskStatus.skipped.value
    assert last_fallback.error_code == "fallback_not_required"
    assert dependent.status == TaskStatus.completed.value
    dependency_ids = {
        edge.depends_on_id for edge in db.query(TaskDependency).filter_by(task_id=dependent.id)
    }
    assert dependency_ids == {last_fallback.id}


def test_preferred_fallback_activates_next_implementation_after_failure(db):
    calls: list[str] = []
    module_registry = ModuleRegistry()
    module_registry.register(
        PolicyModule(
            "test.preferred",
            policy=CapabilityExecutionPolicy.preferred_then_fallback,
            implementation_priority=200,
            fail=True,
            calls=calls,
        )
    )
    module_registry.register(
        PolicyModule("test.fallback", implementation_priority=100, calls=calls)
    )
    module_registry.register(PolicyDependent(calls))
    target = policy_target(db, "test.preferred", "test.fallback", "test.policy_dependent")
    scheduler = TaskScheduler(db, module_registry)

    scheduler.bootstrap(target)
    drain(db, scheduler)

    statuses = {
        task.module_name: task.status for task in db.query(ReconTask).filter_by(target_id=target.id)
    }
    assert calls == ["test.preferred", "test.fallback", "test.policy_dependent"]
    assert statuses == {
        "test.preferred": TaskStatus.failed.value,
        "test.fallback": TaskStatus.completed.value,
        "test.policy_dependent": TaskStatus.completed.value,
    }


def test_sequential_enrichment_runs_in_declared_order(db):
    calls: list[str] = []
    module_registry = ModuleRegistry()
    module_registry.register(
        PolicyModule(
            "test.enrich_first",
            policy=CapabilityExecutionPolicy.sequential_enrichment,
            implementation_priority=300,
            calls=calls,
        )
    )
    module_registry.register(
        PolicyModule("test.enrich_second", implementation_priority=200, calls=calls)
    )
    module_registry.register(
        PolicyModule("test.enrich_third", implementation_priority=100, calls=calls)
    )
    target = policy_target(db, "test.enrich_first", "test.enrich_second", "test.enrich_third")
    scheduler = TaskScheduler(db, module_registry)

    scheduler.bootstrap(target)
    drain(db, scheduler)

    assert calls == ["test.enrich_first", "test.enrich_second", "test.enrich_third"]


def test_engine_policy_metadata_is_not_passed_to_modules(db):
    module_registry = ModuleRegistry()
    first = PolicyModule(
        "test.enrich_first",
        policy=CapabilityExecutionPolicy.sequential_enrichment,
        implementation_priority=200,
    )
    second = PolicyModule("test.enrich_second", implementation_priority=100)
    module_registry.register(first)
    module_registry.register(second)
    target = policy_target(db, "test.enrich_first", "test.enrich_second")
    scheduler = TaskScheduler(db, module_registry)

    scheduler.bootstrap(target)
    drain(db, scheduler)

    assert first.received_configs and second.received_configs
    assert all(
        not key.startswith("_reconator_")
        for config in first.received_configs + second.received_configs
        for key in config
    )


def test_sequential_cache_hits_settle_without_claiming_work(db):
    calls: list[str] = []
    module_registry = ModuleRegistry()
    module_registry.register(
        PolicyModule(
            "test.cached_first",
            policy=CapabilityExecutionPolicy.sequential_enrichment,
            implementation_priority=200,
            calls=calls,
            cache_ttl_seconds=3600,
        )
    )
    module_registry.register(
        PolicyModule(
            "test.cached_second",
            implementation_priority=100,
            calls=calls,
            cache_ttl_seconds=3600,
        )
    )
    selected = ("test.cached_first", "test.cached_second")
    first = policy_target(db, *selected)
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(first)
    drain(db, scheduler)
    assert calls == ["test.cached_first", "test.cached_second"]

    calls.clear()
    second = policy_target(db, *selected)
    scheduler.bootstrap(second)

    tasks = db.query(ReconTask).filter_by(target_id=second.id).all()
    assert calls == []
    assert all(task.status == TaskStatus.skipped.value for task in tasks)
    assert all(task.cache_hit_task_id is not None for task in tasks)
    assert all(task.config["_reconator_cache_replayed"] is True for task in tasks)
    assert scheduler.claim_next("policy-worker") is None


def test_cached_fallback_is_not_reported_as_reused_when_preferred_succeeds(db):
    calls: list[str] = []
    module_registry = ModuleRegistry()
    preferred = PolicyModule(
        "test.preferred",
        policy=CapabilityExecutionPolicy.preferred_then_fallback,
        implementation_priority=200,
        fail=True,
        calls=calls,
    )
    module_registry.register(preferred)
    module_registry.register(
        PolicyModule(
            "test.fallback",
            implementation_priority=100,
            calls=calls,
            cache_ttl_seconds=3600,
        )
    )
    selected = ("test.preferred", "test.fallback")
    first = policy_target(db, *selected)
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(first)
    drain(db, scheduler)
    assert calls == ["test.preferred", "test.fallback"]

    calls.clear()
    preferred.fail = False
    second = policy_target(db, *selected)
    scheduler.bootstrap(second)
    drain(db, scheduler)

    fallback = db.query(ReconTask).filter_by(target_id=second.id, module_name="test.fallback").one()
    assert calls == ["test.preferred"]
    assert fallback.error_code == "fallback_not_required"
    assert fallback.cache_hit_task_id is None
    assert "_reconator_cache_replayed" not in fallback.config


def test_expired_preferred_lease_resumes_at_fallback(db):
    calls: list[str] = []
    module_registry = ModuleRegistry()
    module_registry.register(
        PolicyModule(
            "test.preferred",
            policy=CapabilityExecutionPolicy.preferred_then_fallback,
            implementation_priority=200,
            calls=calls,
        )
    )
    module_registry.register(
        PolicyModule("test.fallback", implementation_priority=100, calls=calls)
    )
    target = policy_target(db, "test.preferred", "test.fallback")
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)

    preferred = scheduler.claim_next("vanished-policy-worker")
    preferred.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert scheduler.recover_expired_leases() == 1

    fallback = db.query(ReconTask).filter_by(module_name="test.fallback").one()
    assert preferred.status == TaskStatus.failed.value
    assert fallback.status == TaskStatus.queued.value


def test_expired_sequential_lease_suppresses_chain_and_finalizes(db):
    calls: list[str] = []
    module_registry = ModuleRegistry()
    module_registry.register(
        PolicyModule(
            "test.enrich_first",
            policy=CapabilityExecutionPolicy.sequential_enrichment,
            implementation_priority=200,
            calls=calls,
        )
    )
    module_registry.register(
        PolicyModule("test.enrich_second", implementation_priority=100, calls=calls)
    )
    target = policy_target(db, "test.enrich_first", "test.enrich_second")
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)

    first = scheduler.claim_next("vanished-policy-worker")
    first.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert scheduler.recover_expired_leases() == 1

    second = db.query(ReconTask).filter_by(module_name="test.enrich_second").one()
    db.refresh(target)
    assert first.status == TaskStatus.failed.value
    assert second.status == TaskStatus.skipped.value
    assert second.error_code == "dependency_failed"
    assert target.status == TargetStatus.failed


def test_registry_rejects_conflicting_explicit_capability_policies():
    module_registry = ModuleRegistry()
    module_registry.register(
        PolicyModule(
            "test.policy_a",
            policy=CapabilityExecutionPolicy.preferred_then_fallback,
        )
    )
    with pytest.raises(ValueError, match="conflicting execution policies"):
        module_registry.register(
            PolicyModule(
                "test.policy_b",
                policy=CapabilityExecutionPolicy.sequential_enrichment,
            )
        )
