from datetime import timedelta

from app.db.models import (
    AssetObservation,
    ReconTask,
    Target,
    TargetStatus,
    TaskDependency,
    TaskStatus,
)
from app.recon.knowledge import utcnow
from app.recon.modules.base import (
    AssetEmission,
    AssetReference,
    ModuleExecutionError,
    ModuleManifest,
    ModuleMode,
    ModuleResult,
    RelationshipEmission,
)
from app.recon.modules.registry import ModuleRegistry
from app.recon.orchestration import TaskScheduler


class SeedDiscovery:
    manifest = ModuleManifest(
        name="test.seed_discovery",
        version="1",
        description="fixture",
        capability="test.discover",
        consumes=frozenset({"domain"}),
        produces=frozenset({"domain"}),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive"}),
        cache_ttl_seconds=3600,
    )

    @staticmethod
    def accepts(asset):
        return bool(asset.attributes.get("seed"))

    def execute(self, context):
        child = f"api.{context.input_asset.canonical_value}"
        return ModuleResult(
            assets=[AssetEmission("domain", child, {"environment": "api"})],
            relationships=[
                RelationshipEmission(
                    AssetReference("domain", context.input_asset.canonical_value),
                    AssetReference("domain", child),
                    "has_subdomain",
                )
            ],
        )


class ChildAnalysis:
    manifest = ModuleManifest(
        name="test.child_analysis",
        version="1",
        description="fixture",
        capability="test.analyze",
        consumes=frozenset({"domain"}),
        produces=frozenset({"url"}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"passive"}),
        cache_ttl_seconds=3600,
    )

    @staticmethod
    def accepts(asset):
        return not asset.attributes.get("seed")

    def execute(self, context):
        url = f"https://{context.input_asset.canonical_value}/api?version=1"
        return ModuleResult(assets=[AssetEmission("url", url)])


def registry():
    result = ModuleRegistry()
    result.register(SeedDiscovery())
    result.register(ChildAnalysis())
    return result


def new_target(db, domain, *, parent_target_id=None):
    target = Target(
        url=domain,
        profile="passive",
        selected_modules=["test.seed_discovery", "test.child_analysis"],
        authorization_confirmed=True,
        parent_target_id=parent_target_id,
    )
    db.add(target)
    db.flush()
    return target


def drain(db, scheduler, worker="test-worker"):
    executed = 0
    while task := scheduler.claim_next(worker):
        scheduler.execute_claimed(task.id, worker)
        executed += 1
        assert executed < 20
    return executed


def test_results_generate_new_tasks_and_complete_scan(db):
    target = new_target(db, "chain.example.com")
    scheduler = TaskScheduler(db, registry())
    scheduler.bootstrap(target)
    db.commit()
    assert db.query(ReconTask).filter(ReconTask.target_id == target.id).count() == 1

    assert drain(db, scheduler) == 2
    db.refresh(target)
    assert target.status == TargetStatus.completed
    values = {
        observation.asset.canonical_value
        for observation in db.query(AssetObservation).filter_by(target_id=target.id)
    }
    assert "api.chain.example.com" in values
    assert "https://api.chain.example.com/api?version=1" in values


def test_second_scan_reuses_cached_results_and_provenance(db):
    first = new_target(db, "cache.example.com")
    first_scheduler = TaskScheduler(db, registry())
    first_scheduler.bootstrap(first)
    db.commit()
    assert drain(db, first_scheduler) == 2

    second = new_target(db, "cache.example.com", parent_target_id=first.id)
    second_scheduler = TaskScheduler(db, registry())
    second_scheduler.bootstrap(second)
    db.commit()
    assert drain(db, second_scheduler) == 0
    db.refresh(second)
    assert second.status == TargetStatus.completed
    tasks = db.query(ReconTask).filter_by(target_id=second.id).all()
    assert tasks
    assert all(task.status == TaskStatus.skipped.value for task in tasks)
    assert any(task.cache_hit_task_id for task in tasks)
    assert db.query(AssetObservation).filter_by(target_id=second.id).count() >= 3


class FlakyModule:
    manifest = ModuleManifest(
        name="test.flaky",
        version="1",
        description="fixture",
        capability="test.retry",
        consumes=frozenset({"domain"}),
        produces=frozenset({"technology"}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"passive"}),
        max_attempts=2,
        cache_ttl_seconds=0,
    )

    def __init__(self):
        self.calls = 0

    def execute(self, context):
        self.calls += 1
        if self.calls == 1:
            raise ModuleExecutionError("temporary fixture failure", code="temporary")
        return ModuleResult(assets=[AssetEmission("technology", "fixture-server")])


def test_retry_backoff_and_recovery_are_structured(db):
    module_registry = ModuleRegistry()
    flaky = FlakyModule()
    module_registry.register(flaky)
    target = Target(
        url="retry.example.com",
        profile="passive",
        selected_modules=["test.flaky"],
        authorization_confirmed=True,
    )
    db.add(target)
    db.flush()
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)
    db.commit()

    first = scheduler.claim_next("retry-worker")
    scheduler.execute_claimed(first.id, "retry-worker")
    db.refresh(first)
    assert first.status == TaskStatus.retry_wait.value
    assert first.error_code == "temporary"
    first.available_at = utcnow() - timedelta(seconds=1)
    db.commit()

    second = scheduler.claim_next("retry-worker")
    assert second.id == first.id
    scheduler.execute_claimed(second.id, "retry-worker")
    db.refresh(second)
    db.refresh(target)
    assert second.status == TaskStatus.completed.value
    assert second.attempts == 2
    assert target.status == TargetStatus.completed


def test_expired_worker_lease_is_resumable(db):
    module_registry = ModuleRegistry()
    module_registry.register(FlakyModule())
    target = Target(
        url="lease.example.com",
        profile="passive",
        selected_modules=["test.flaky"],
        authorization_confirmed=True,
    )
    db.add(target)
    db.flush()
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)
    db.commit()
    task = scheduler.claim_next("vanished-worker")
    task.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    assert scheduler.recover_expired_leases() == 1
    db.commit()
    db.refresh(task)
    assert task.status == TaskStatus.retry_wait.value
    assert task.lease_owner is None
    assert task.error_code == "lease_expired"


class IPDiscovery:
    manifest = ModuleManifest(
        name="test.ip_discovery",
        version="1",
        description="fixture",
        capability="test.ip_discovery",
        consumes=frozenset({"domain"}),
        produces=frozenset({"ip_address"}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"passive"}),
        cache_ttl_seconds=0,
    )

    def execute(self, context):
        return ModuleResult(assets=[AssetEmission("ip_address", "192.0.2.44")])


class DerivedPassiveAnalysis:
    manifest = ModuleManifest(
        name="test.derived_passive",
        version="1",
        description="fixture",
        capability="test.derived_passive",
        consumes=frozenset({"ip_address"}),
        produces=frozenset({"organization"}),
        mode=ModuleMode.passive,
        default_profiles=frozenset({"passive"}),
        accepts_derived_inputs=True,
        cache_ttl_seconds=0,
    )

    def execute(self, context):
        return ModuleResult(assets=[AssetEmission("organization", "Example Net")])


class DerivedActiveAnalysis:
    manifest = ModuleManifest(
        name="test.derived_active",
        version="1",
        description="fixture",
        capability="test.derived_active",
        consumes=frozenset({"ip_address"}),
        produces=frozenset({"service"}),
        mode=ModuleMode.active,
        default_profiles=frozenset({"passive"}),
        accepts_derived_inputs=True,
        cache_ttl_seconds=0,
    )

    def execute(self, context):
        raise AssertionError("an active module must never receive derived-only scope")


def test_derived_scope_allows_opted_in_passive_work_but_never_active_work(db):
    module_registry = ModuleRegistry()
    module_registry.register(IPDiscovery())
    module_registry.register(DerivedPassiveAnalysis())
    module_registry.register(DerivedActiveAnalysis())
    target = Target(
        url="derived.example.com",
        profile="passive",
        selected_modules=[
            "test.ip_discovery",
            "test.derived_passive",
            "test.derived_active",
        ],
        authorization_confirmed=True,
    )
    db.add(target)
    db.flush()
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)
    db.commit()

    assert drain(db, scheduler) == 2
    tasks = db.query(ReconTask).filter_by(target_id=target.id).all()
    assert {task.module_name for task in tasks} == {
        "test.ip_discovery",
        "test.derived_passive",
    }
    derived = next(task for task in tasks if task.module_name == "test.derived_passive")
    assert derived.scope_basis == "derived"


class CandidateValidator:
    manifest = ModuleManifest(
        name="dns.system.a",
        version="test",
        description="candidate validator fixture",
        capability="dns.resolve",
        consumes=frozenset({"domain"}),
        produces=frozenset({"domain"}),
        mode=ModuleMode.active,
        default_profiles=frozenset({"active"}),
        cache_ttl_seconds=0,
    )

    def execute(self, context):
        return ModuleResult()


class CandidateDownstream:
    manifest = ModuleManifest(
        name="http.probe",
        version="test",
        description="downstream fixture",
        capability="http.probe",
        consumes=frozenset({"domain"}),
        produces=frozenset({"url"}),
        mode=ModuleMode.active,
        default_profiles=frozenset({"active"}),
        cache_ttl_seconds=0,
    )

    def execute(self, context):
        return ModuleResult()


class OriginCrawler:
    manifest = ModuleManifest(
        name="test.origin_crawler",
        version="1",
        description="origin crawler fixture",
        capability="web.crawl",
        consumes=frozenset({"url"}),
        produces=frozenset({"url"}),
        mode=ModuleMode.active,
        default_profiles=frozenset({"active"}),
        cache_ttl_seconds=0,
    )

    def execute(self, context):
        return ModuleResult()


def test_unvalidated_domain_hypothesis_only_schedules_dns_validation(db):
    module_registry = ModuleRegistry()
    module_registry.register(CandidateValidator())
    module_registry.register(CandidateDownstream())
    target = Target(
        url="example.com",
        profile="active",
        selected_modules=["dns.system.a", "http.probe"],
        authorization_confirmed=True,
    )
    db.add(target)
    db.flush()
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)

    candidate = scheduler.knowledge.observe_asset(
        target_id=target.id,
        task_id=None,
        module_name="toolbox.alterx",
        emission=AssetEmission(
            "domain",
            "api-dev.example.com",
            {"candidate": True, "validated": False},
            confidence=0.2,
        ),
    )
    scheduler.schedule_for_asset(target, candidate)
    candidate_tasks = (
        db.query(ReconTask).filter(ReconTask.input_asset_id == candidate.asset.id).all()
    )
    assert {task.module_name for task in candidate_tasks} == {"dns.system.a"}

    validated = scheduler.knowledge.observe_asset(
        target_id=target.id,
        task_id=candidate_tasks[0].id,
        module_name="dns.system.a",
        emission=AssetEmission(
            "domain",
            "api-dev.example.com",
            {"candidate": False, "validated": True},
        ),
    )
    assert validated.changed is True
    assert validated.new_to_scan is False
    scheduler.schedule_for_asset(target, validated, parent_task_id=candidate_tasks[0].id)
    promoted_tasks = (
        db.query(ReconTask).filter(ReconTask.input_asset_id == candidate.asset.id).all()
    )
    assert {task.module_name for task in promoted_tasks} == {
        "dns.system.a",
        "http.probe",
    }


def test_web_crawl_is_scheduled_once_per_origin_not_per_path(db):
    module_registry = ModuleRegistry()
    module_registry.register(OriginCrawler())
    target = Target(
        url="example.com",
        profile="active",
        selected_modules=["test.origin_crawler"],
        authorization_confirmed=True,
    )
    db.add(target)
    db.flush()
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)

    for value in [
        "https://app.example.com/",
        "https://app.example.com/api/users",
        "https://app.example.com/settings",
    ]:
        observed = scheduler.knowledge.observe_asset(
            target_id=target.id,
            task_id=None,
            module_name="fixture",
            emission=AssetEmission("url", value),
        )
        scheduler.schedule_for_asset(target, observed)

    tasks = db.query(ReconTask).filter(ReconTask.module_name == "test.origin_crawler").all()
    assert [task.input_asset.canonical_value for task in tasks] == ["https://app.example.com/"]


class DependencyFixture:
    manifest = ModuleManifest(
        name="test.dependency",
        version="1",
        description="dependency fixture",
        capability="test.prerequisite",
        consumes=frozenset({"domain"}),
        produces=frozenset({"technology"}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"passive"}),
        priority=100,
        cache_ttl_seconds=0,
    )

    def execute(self, context):
        return ModuleResult()


class DependentFixture:
    manifest = ModuleManifest(
        name="test.dependent",
        version="1",
        description="dependent fixture",
        capability="test.dependent",
        consumes=frozenset({"domain"}),
        produces=frozenset({"technology"}),
        mode=ModuleMode.local,
        default_profiles=frozenset({"passive"}),
        priority=200,
        cache_ttl_seconds=0,
        depends_on_capabilities=frozenset({"test.prerequisite"}),
    )

    def execute(self, context):
        return ModuleResult()


def test_manifest_dependencies_create_edges_and_gate_execution(db):
    module_registry = ModuleRegistry()
    module_registry.register(DependencyFixture())
    module_registry.register(DependentFixture())
    target = Target(
        url="dependency.example.com",
        profile="passive",
        selected_modules=["test.dependency", "test.dependent"],
        authorization_confirmed=True,
    )
    db.add(target)
    db.flush()
    scheduler = TaskScheduler(db, module_registry)
    scheduler.bootstrap(target)
    db.commit()

    dependent = db.query(ReconTask).filter_by(module_name="test.dependent").one()
    prerequisite = db.query(ReconTask).filter_by(module_name="test.dependency").one()
    assert dependent.status == TaskStatus.blocked.value
    edge = db.query(TaskDependency).one()
    assert (edge.task_id, edge.depends_on_id) == (dependent.id, prerequisite.id)

    first = scheduler.claim_next("dependency-worker")
    assert first.id == prerequisite.id
    scheduler.execute_claimed(first.id, "dependency-worker")
    db.refresh(dependent)
    assert dependent.status == TaskStatus.queued.value
    second = scheduler.claim_next("dependency-worker")
    assert second.id == dependent.id
