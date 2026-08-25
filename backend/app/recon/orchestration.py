from __future__ import annotations

import logging
import time
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.core.metrics import (
    active_tasks,
    assets_observed_total,
    relationships_observed_total,
    task_cache_hits_total,
    task_duration_seconds,
    task_queue_depth,
    tasks_total,
)
from app.db.models import (
    Asset,
    AssetObservation,
    AssetRelationship,
    ReconTask,
    ScopeRule,
    Target,
    TargetStatus,
    TaskDependency,
    TaskStatus,
)
from app.recon.knowledge import KnowledgeStore, ObservedAsset, utcnow
from app.recon.modules.base import (
    AssetEmission,
    AssetReference,
    CapabilityExecutionPolicy,
    ModuleContext,
    ModuleExecutionError,
    ModuleMode,
    RelationshipEmission,
)
from app.recon.modules.builtin import register_builtin_modules
from app.recon.modules.registry import ModuleRegistry, registry
from app.recon.normalization import NormalizedAsset, normalize_asset, stable_digest
from app.recon.scope import ScopePolicy, create_root_scope_rules

log = logging.getLogger(__name__)

_SUCCESS_TERMINAL = {
    TaskStatus.completed.value,
    TaskStatus.skipped.value,
}
_ALL_TERMINAL = _SUCCESS_TERMINAL | {
    TaskStatus.failed.value,
    TaskStatus.cancelled.value,
}
_CANDIDATE_VALIDATORS = {"dns.system.a", "dns.system.aaaa", "toolbox.dnsx"}
_POLICY_CONFIG_KEY = "_reconator_capability_policy"
_CACHE_REPLAYED_KEY = "_reconator_cache_replayed"


class TaskScheduler:
    def __init__(self, db: Session, module_registry: ModuleRegistry = registry) -> None:
        register_builtin_modules(module_registry)
        self.db = db
        self.registry = module_registry
        self.knowledge = KnowledgeStore(db)

    def _module_config(self, target: Target, module_name: str) -> dict[str, Any]:
        scan_config = target.scan_config or {}
        defaults = scan_config.get("defaults", {})
        module_configs = scan_config.get("modules", {})
        config = {**defaults, **module_configs.get(module_name, {})}
        config = {key: value for key, value in config.items() if not key.startswith("_reconator_")}
        config["allow_private_networks"] = bool(
            settings.allow_private_targets and config.get("allow_private_networks", False)
        )
        if target.target_kind == "url":
            # Protected, engine-derived scope context. Tool adapters may narrow
            # outbound requests with it, while users cannot widen it through
            # module configuration.
            config["_authorized_url_prefix"] = normalize_asset("url", target.url).canonical_value
            config["_excluded_url_prefixes"] = list(
                self.db.scalars(
                    select(ScopeRule.normalized_pattern).where(
                        ScopeRule.target_id == target.id,
                        ScopeRule.action == "exclude",
                        ScopeRule.rule_type == "url_prefix",
                    )
                )
            )
        return config

    def _scope(self, target_id: int) -> ScopePolicy:
        rules = list(
            self.db.scalars(
                select(ScopeRule)
                .where(ScopeRule.target_id == target_id)
                .order_by(ScopeRule.priority, ScopeRule.id)
            )
        )
        return ScopePolicy(rules)

    def bootstrap(self, target: Target) -> Asset:
        self.db.flush()
        if not self.db.scalar(
            select(ScopeRule.id).where(ScopeRule.target_id == target.id).limit(1)
        ):
            self.db.add_all(create_root_scope_rules(target.id, target.url, target.target_kind))
            self.db.flush()

        observed = self.knowledge.observe_asset(
            target_id=target.id,
            task_id=None,
            module_name="core.seed",
            emission=AssetEmission(
                kind=target.target_kind,
                value=target.url,
                attributes={"seed": True},
                evidence={"source": "user_authorized_target"},
                source_name="user",
            ),
        )
        self.knowledge.record_event(
            target_id=target.id,
            event_type="scan.created",
            message=f"Recon scan created for {target.url}",
            data={"profile": target.profile, "root_asset_id": observed.asset.id},
        )
        self.schedule_for_asset(target, observed)
        self._finalize_if_idle(target)
        return observed.asset

    def _selected_modules(self, target: Target) -> set[str] | None:
        return set(target.selected_modules) if target.selected_modules else None

    def _task_count(self, target_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.count()).select_from(ReconTask).where(ReconTask.target_id == target_id)
            )
            or 0
        )

    def schedule_for_asset(
        self,
        target: Target,
        observed: ObservedAsset,
        *,
        parent_task_id: int | None = None,
    ) -> list[ReconTask]:
        # Serialize expansion for one scan. This makes MAX_TASKS_PER_SCAN a
        # hard fleet-wide ceiling instead of a best-effort worker-local check.
        locked_target = self.db.scalar(
            select(Target).where(Target.id == target.id).with_for_update()
        )
        if locked_target is None:
            return []
        target = locked_target
        scope_decision = self._scope(target.id).decide(
            observed.normalized.kind, observed.normalized.canonical_value
        )
        if not scope_decision.allowed:
            self.knowledge.record_event(
                target_id=target.id,
                task_id=parent_task_id,
                event_type="asset.out_of_scope",
                message=f"Asset retained but not scheduled: {observed.normalized.canonical_value}",
                data={
                    "asset_id": observed.asset.id,
                    "kind": observed.asset.kind,
                    "reason": scope_decision.reason,
                },
            )

        scheduled: list[ReconTask] = []
        remaining_capacity = settings.max_tasks_per_scan - self._task_count(target.id)
        consumers = self.registry.consumers_for(
            observed.asset.kind,
            profile=target.profile,
            selected_modules=self._selected_modules(target),
        )
        for module in consumers:
            accepts = getattr(module, "accepts", None)
            if accepts is not None and not accepts(observed.normalized):
                continue
            if remaining_capacity <= 0:
                self.knowledge.record_event(
                    target_id=target.id,
                    event_type="scan.task_limit",
                    level="warning",
                    message="Maximum tasks per scan reached; new work was suppressed",
                    data={"limit": settings.max_tasks_per_scan},
                )
                break
            manifest = module.manifest
            attributes = observed.normalized.attributes
            is_unvalidated_candidate = bool(
                observed.asset.kind == "domain"
                and attributes.get("candidate") is True
                and attributes.get("validated") is False
            )
            if is_unvalidated_candidate and manifest.name not in _CANDIDATE_VALIDATORS:
                continue
            if observed.asset.kind == "url":
                is_seed = attributes.get("seed") is True
                is_origin = bool(
                    attributes.get("path") == "/" and not attributes.get("query_parameters")
                )
                # Probers run once for a user seed or host asset. Crawlers run
                # once per canonical origin, never once per discovered path.
                if manifest.capability == "http.probe" and not is_seed:
                    continue
                if manifest.capability == "web.crawl" and not (
                    (is_seed and not attributes.get("query_parameters")) or is_origin
                ):
                    continue
            if (
                manifest.mode == ModuleMode.active
                and target.target_kind == "url"
                and observed.asset.kind == "domain"
            ):
                # The host entity is useful for correlation/passive work, but a
                # URL-prefix authorization does not authorize probing host root.
                continue
            derived_scope = bool(
                not scope_decision.allowed
                and parent_task_id is not None
                and manifest.accepts_derived_inputs
                and manifest.mode != ModuleMode.active
            )
            if not scope_decision.allowed and not derived_scope:
                continue
            if manifest.mode == ModuleMode.active and not target.authorization_confirmed:
                self.knowledge.record_event(
                    target_id=target.id,
                    event_type="task.authorization_blocked",
                    level="warning",
                    message=f"Active module {manifest.name} requires authorization confirmation",
                    data={"module": manifest.name, "asset_id": observed.asset.id},
                )
                continue
            config = self._module_config(target, manifest.name)
            idempotency_key = stable_digest(
                manifest.name,
                manifest.version,
                observed.asset.id,
                config,
            )
            existing = self.db.scalar(
                select(ReconTask).where(
                    ReconTask.target_id == target.id,
                    ReconTask.idempotency_key == idempotency_key,
                )
            )
            if existing:
                continue
            cache_key = stable_digest(
                manifest.name,
                manifest.version,
                observed.normalized.identity_hash,
                config,
            )
            cached = None
            if manifest.cache_ttl_seconds > 0:
                cutoff = utcnow() - timedelta(seconds=manifest.cache_ttl_seconds)
                cached = self.db.scalar(
                    select(ReconTask)
                    .where(
                        ReconTask.cache_key == cache_key,
                        ReconTask.status == TaskStatus.completed.value,
                        ReconTask.completed_at >= cutoff,
                    )
                    .order_by(ReconTask.completed_at.desc())
                    .limit(1)
                )
            now = utcnow()
            task = ReconTask(
                target_id=target.id,
                input_asset_id=observed.asset.id,
                parent_task_id=parent_task_id,
                cache_hit_task_id=cached.id if cached else None,
                module_name=manifest.name,
                module_version=manifest.version,
                capability=manifest.capability,
                scope_basis="derived" if derived_scope else "direct",
                status=TaskStatus.skipped.value if cached else TaskStatus.queued.value,
                priority=manifest.priority + int(observed.asset.priority_score),
                idempotency_key=idempotency_key,
                cache_key=cache_key,
                config=config,
                attempts=0,
                max_attempts=manifest.max_attempts,
                timeout_seconds=manifest.timeout_seconds,
                available_at=now,
                completed_at=now if cached else None,
                output_summary=(
                    {**(cached.output_summary or {}), "cache_hit": True} if cached else {}
                ),
            )
            try:
                with self.db.begin_nested():
                    self.db.add(task)
                    self.db.flush()
            except IntegrityError:
                # Concurrent result processing can discover the same work. The
                # database uniqueness constraint is the final deduplication gate.
                continue
            remaining_capacity -= 1
            scheduled.append(task)
        self._attach_dependencies(target, observed.asset.id, scheduled)
        self._apply_capability_policies(scheduled)
        for task in scheduled:
            self._record_scheduled_task(target, observed.asset, task)
        for task in scheduled:
            if self._replay_ready_cache_hit(target, task):
                self._unblock_dependents(task.id)
        return scheduled

    def _record_scheduled_task(self, target: Target, asset: Asset, task: ReconTask) -> None:
        policy = self._policy_metadata(task)
        if task.cache_hit_task_id and task.status == TaskStatus.skipped.value:
            event_type = "task.cache_hit"
            message = f"Reused cached result for {task.module_name}"
            task_cache_hits_total.labels(module=task.module_name).inc()
        elif policy and task.status == TaskStatus.blocked.value:
            event_type = "task.policy_wait"
            message = f"Deferred {task.module_name} by capability execution policy"
        elif task.status == TaskStatus.skipped.value:
            event_type = "task.dependency_wait"
            message = task.error_detail or f"Skipped {task.module_name}"
        else:
            event_type = "task.queued"
            message = f"Queued {task.module_name} for {asset.canonical_value}"
        self.knowledge.record_event(
            target_id=target.id,
            task_id=task.id,
            event_type=event_type,
            level="warning" if task.error_code else "info",
            message=message,
            data={
                "module": task.module_name,
                "capability": task.capability,
                "asset_id": asset.id,
                "cache_hit_task_id": task.cache_hit_task_id,
                "capability_policy": (policy.get("policy") if policy else "parallel_sources"),
                "implementation_position": policy.get("position") if policy else None,
            },
        )

    @staticmethod
    def _policy_metadata(task: ReconTask) -> dict[str, Any]:
        metadata = (task.config or {}).get(_POLICY_CONFIG_KEY)
        return metadata if isinstance(metadata, dict) else {}

    def _apply_capability_policies(self, tasks: list[ReconTask]) -> None:
        modules = [
            module for task in tasks if (module := self.registry.get(task.module_name)) is not None
        ]
        task_by_module = {task.module_name: task for task in tasks}
        for group in self.registry.execution_groups(modules):
            if group.policy == CapabilityExecutionPolicy.parallel_sources or len(group.modules) < 2:
                continue
            ordered_tasks = [task_by_module[module.manifest.name] for module in group.modules]
            for position, task in enumerate(ordered_tasks):
                predecessor_id = ordered_tasks[position - 1].id if position else None
                config = dict(task.config or {})
                config[_POLICY_CONFIG_KEY] = {
                    "policy": group.policy.value,
                    "position": position,
                    "size": len(ordered_tasks),
                    "predecessor_task_id": predecessor_id,
                    "base_status": task.status,
                    "base_error_code": task.error_code,
                    "base_error_detail": task.error_detail,
                }
                task.config = config
                if predecessor_id is None:
                    continue
                self.db.add(TaskDependency(task_id=task.id, depends_on_id=predecessor_id))
                task.status = TaskStatus.blocked.value
                task.completed_at = None
                task.error_code = None
                task.error_detail = None

    def _replay_ready_cache_hit(self, target: Target, task: ReconTask) -> bool:
        if (
            task.cache_hit_task_id is None
            or task.status != TaskStatus.skipped.value
            or task.error_code is not None
            or (task.config or {}).get(_CACHE_REPLAYED_KEY) is True
        ):
            return False
        cached = self.db.get(ReconTask, task.cache_hit_task_id)
        if cached is None:
            task.cache_hit_task_id = None
            task.status = TaskStatus.queued.value
            task.completed_at = None
            return False
        config = dict(task.config or {})
        config[_CACHE_REPLAYED_KEY] = True
        task.config = config
        self._replay_cached_assets(target, task, cached)
        policy = self._policy_metadata(task)
        if policy.get("position", 0) > 0:
            task_cache_hits_total.labels(module=task.module_name).inc()
            self.knowledge.record_event(
                target_id=target.id,
                task_id=task.id,
                event_type="task.cache_hit",
                message=f"Activated cached result for {task.module_name}",
                data={
                    "module": task.module_name,
                    "capability": task.capability,
                    "cache_hit_task_id": cached.id,
                    "capability_policy": policy.get("policy"),
                    "implementation_position": policy.get("position"),
                },
            )
        return True

    @staticmethod
    def _discard_unused_cache_hit(task: ReconTask) -> None:
        if task.cache_hit_task_id is None or (task.config or {}).get(_CACHE_REPLAYED_KEY) is True:
            return
        task.cache_hit_task_id = None
        task.output_summary = {}

    def _attach_dependencies(
        self, target: Target, input_asset_id: int, tasks: list[ReconTask]
    ) -> None:
        for task in tasks:
            if task.status != TaskStatus.queued.value:
                continue
            module = self.registry.get(task.module_name)
            required = module.manifest.depends_on_capabilities if module else frozenset()
            if not required:
                continue
            predecessors = list(
                self.db.scalars(
                    select(ReconTask).where(
                        ReconTask.target_id == target.id,
                        ReconTask.input_asset_id == input_asset_id,
                        ReconTask.id != task.id,
                        ReconTask.capability.in_(required),
                    )
                )
            )
            found = {predecessor.capability for predecessor in predecessors}
            missing = sorted(required - found)
            if missing:
                task.status = TaskStatus.skipped.value
                task.completed_at = utcnow()
                task.error_code = "dependency_unavailable"
                task.error_detail = (
                    f"required capabilities were not scheduled: {', '.join(missing)}"
                )
            else:
                selected_predecessors: list[ReconTask] = []
                for capability in sorted(required):
                    capability_tasks = [
                        predecessor
                        for predecessor in predecessors
                        if predecessor.capability == capability
                    ]
                    capability_modules = [
                        module
                        for predecessor in capability_tasks
                        if (module := self.registry.get(predecessor.module_name)) is not None
                    ]
                    policy = self.registry.execution_policy_for(capability_modules)
                    if (
                        policy == CapabilityExecutionPolicy.parallel_sources
                        or len(capability_tasks) < 2
                    ):
                        selected_predecessors.extend(capability_tasks)
                        continue
                    ordered_names = [
                        module.manifest.name
                        for group in self.registry.execution_groups(capability_modules)
                        for module in group.modules
                    ]
                    by_name = {
                        predecessor.module_name: predecessor for predecessor in capability_tasks
                    }
                    selected_predecessors.append(by_name[ordered_names[-1]])
                for predecessor in selected_predecessors:
                    self.db.add(TaskDependency(task_id=task.id, depends_on_id=predecessor.id))
                if any(
                    predecessor.status in _ALL_TERMINAL
                    and not self._is_successful_terminal(predecessor)
                    for predecessor in selected_predecessors
                ):
                    task.status = TaskStatus.skipped.value
                    task.completed_at = utcnow()
                    task.error_code = "dependency_failed"
                    task.error_detail = "a required predecessor did not complete successfully"
                elif any(
                    predecessor.status not in _SUCCESS_TERMINAL
                    for predecessor in selected_predecessors
                ):
                    task.status = TaskStatus.blocked.value
            if task.status != TaskStatus.queued.value:
                self.knowledge.record_event(
                    target_id=target.id,
                    task_id=task.id,
                    event_type="task.dependency_wait",
                    level="warning" if task.status == TaskStatus.skipped.value else "info",
                    message=task.error_detail or "Task is waiting for required capabilities",
                    data={"required_capabilities": sorted(required)},
                )

    def _replay_cached_assets(self, target: Target, task: ReconTask, cached: ReconTask) -> None:
        asset_ids = (cached.output_summary or {}).get("asset_ids", [])
        for asset_id in asset_ids[: settings.max_tasks_per_scan]:
            asset = self.db.get(Asset, asset_id)
            if asset is None:
                continue
            observed = self.knowledge.observe_asset(
                target_id=target.id,
                task_id=task.id,
                module_name=task.module_name,
                emission=AssetEmission(
                    kind=asset.kind,
                    value=asset.canonical_value,
                    attributes=asset.attributes or {},
                    evidence={"cache_hit_task_id": cached.id},
                    source_name="task_cache",
                ),
            )
            if observed.new_to_scan:
                self.schedule_for_asset(target, observed, parent_task_id=task.id)
        relationship_ids = (cached.output_summary or {}).get("relationship_ids", [])
        for relationship_id in relationship_ids[: settings.max_tasks_per_scan]:
            relationship = self.db.get(AssetRelationship, relationship_id)
            if relationship is None:
                continue
            self.knowledge.observe_relationship(
                target_id=target.id,
                task_id=task.id,
                module_name=task.module_name,
                emission=RelationshipEmission(
                    source=AssetReference(
                        relationship.source_asset.kind,
                        relationship.source_asset.canonical_value,
                    ),
                    target=AssetReference(
                        relationship.target_asset.kind,
                        relationship.target_asset.canonical_value,
                    ),
                    relationship_type=relationship.relationship_type,
                    attributes=relationship.attributes or {},
                    confidence=relationship.confidence,
                    evidence={"cache_hit_task_id": cached.id},
                ),
            )

    @staticmethod
    def _is_successful_terminal(task: ReconTask) -> bool:
        return bool(
            task.status == TaskStatus.completed.value
            or (
                task.status == TaskStatus.skipped.value
                and (
                    (task.cache_hit_task_id is not None and task.error_code is None)
                    or task.error_code == "fallback_not_required"
                )
            )
        )

    def _dependency_tasks(self, task_id: int) -> list[ReconTask]:
        dependency = aliased(ReconTask)
        return list(
            self.db.scalars(
                select(dependency)
                .select_from(TaskDependency)
                .join(dependency, dependency.id == TaskDependency.depends_on_id)
                .where(TaskDependency.task_id == task_id)
            )
        )

    def _restore_policy_base_state(self, task: ReconTask) -> None:
        metadata = self._policy_metadata(task)
        base_status = metadata.get("base_status")
        base_error_code = metadata.get("base_error_code")
        if base_status == TaskStatus.skipped.value:
            task.status = TaskStatus.skipped.value
            task.completed_at = utcnow()
            task.error_code = base_error_code
            task.error_detail = metadata.get("base_error_detail")
        else:
            task.status = TaskStatus.queued.value
            task.available_at = utcnow()
            task.completed_at = None
            task.error_code = None
            task.error_detail = None

    def _settle_task_dependencies(self, task: ReconTask) -> bool:
        """Resolve dependency and capability gates; return true when terminal."""
        dependencies = self._dependency_tasks(task.id)
        metadata = self._policy_metadata(task)
        predecessor_id = metadata.get("predecessor_task_id")
        policy_predecessor = next(
            (dependency for dependency in dependencies if dependency.id == predecessor_id),
            None,
        )
        functional = [dependency for dependency in dependencies if dependency.id != predecessor_id]
        if any(
            dependency.status in _ALL_TERMINAL and not self._is_successful_terminal(dependency)
            for dependency in functional
        ):
            task.status = TaskStatus.skipped.value
            task.error_code = "dependency_failed"
            task.error_detail = "a required predecessor did not complete successfully"
            task.completed_at = utcnow()
            self._discard_unused_cache_hit(task)
            return True
        if any(dependency.status not in _SUCCESS_TERMINAL for dependency in functional):
            task.status = TaskStatus.blocked.value
            return False
        if predecessor_id is None:
            if task.status == TaskStatus.blocked.value:
                task.status = TaskStatus.queued.value
                task.available_at = utcnow()
            return task.status in _ALL_TERMINAL
        if policy_predecessor is None:
            task.status = TaskStatus.skipped.value
            task.error_code = "policy_predecessor_missing"
            task.error_detail = "capability policy predecessor is unavailable"
            task.completed_at = utcnow()
            self._discard_unused_cache_hit(task)
            return True
        if policy_predecessor.status not in _ALL_TERMINAL:
            task.status = TaskStatus.blocked.value
            return False

        policy = CapabilityExecutionPolicy(metadata["policy"])
        predecessor_succeeded = self._is_successful_terminal(policy_predecessor)
        if policy == CapabilityExecutionPolicy.preferred_then_fallback and predecessor_succeeded:
            task.status = TaskStatus.skipped.value
            task.error_code = "fallback_not_required"
            task.error_detail = (
                f"preferred implementation {policy_predecessor.module_name} succeeded"
            )
            task.completed_at = utcnow()
            self._discard_unused_cache_hit(task)
            return True
        if policy == CapabilityExecutionPolicy.sequential_enrichment and not predecessor_succeeded:
            task.status = TaskStatus.skipped.value
            task.error_code = "dependency_failed"
            task.error_detail = (
                f"sequential predecessor {policy_predecessor.module_name} did not succeed"
            )
            task.completed_at = utcnow()
            self._discard_unused_cache_hit(task)
            return True
        self._restore_policy_base_state(task)
        return task.status in _ALL_TERMINAL

    def _settle_and_continue(self, task: ReconTask) -> None:
        was_status = task.status
        terminal = self._settle_task_dependencies(task)
        target = self.db.get(Target, task.target_id)
        if task.status != was_status:
            if task.error_code == "fallback_not_required":
                event_type = "task.fallback_suppressed"
            elif task.status == TaskStatus.queued.value:
                event_type = "task.policy_activated"
            elif task.status == TaskStatus.skipped.value:
                event_type = "task.dependency_failed"
            else:
                event_type = "task.dependency_wait"
            self.knowledge.record_event(
                target_id=task.target_id,
                task_id=task.id,
                event_type=event_type,
                level="warning" if task.error_code == "dependency_failed" else "info",
                message=task.error_detail or f"Capability policy activated {task.module_name}",
                data=self._policy_metadata(task),
            )
        if target is not None and self._replay_ready_cache_hit(target, task):
            terminal = True
        if terminal:
            self._unblock_dependents(task.id)

    def recover_expired_leases(self) -> int:
        now = utcnow()
        expired = list(
            self.db.scalars(
                select(ReconTask)
                .where(
                    ReconTask.status == TaskStatus.running.value,
                    ReconTask.lease_expires_at < now,
                )
                .order_by(ReconTask.lease_expires_at, ReconTask.id)
                .limit(100)
                .with_for_update(skip_locked=True, of=ReconTask)
            )
        )
        affected_target_ids: set[int] = set()
        for task in expired:
            affected_target_ids.add(task.target_id)
            task.lease_owner = None
            task.lease_expires_at = None
            task.heartbeat_at = None
            if task.attempts >= task.max_attempts:
                task.status = TaskStatus.failed.value
                task.error_code = "lease_expired"
                task.error_detail = "worker lease expired after final attempt"
                task.completed_at = now
            else:
                task.status = TaskStatus.retry_wait.value
                task.available_at = now + timedelta(
                    seconds=settings.task_retry_base_seconds * (2 ** max(task.attempts - 1, 0))
                )
                task.error_code = "lease_expired"
                task.error_detail = "worker lease expired; task will be retried"
            self.knowledge.record_event(
                target_id=task.target_id,
                task_id=task.id,
                event_type="task.lease_expired",
                level="warning",
                message=task.error_detail,
            )
        for task in expired:
            if task.status == TaskStatus.failed.value:
                self._unblock_dependents(task.id)
        for target_id in affected_target_ids:
            target = self.db.get(Target, target_id)
            if target is not None:
                self._finalize_if_idle(target)
        return len(expired)

    def claim_next(self, worker_id: str) -> ReconTask | None:
        self.recover_expired_leases()
        # Claim one row at a time. Locking a large candidate batch makes other
        # workers skip high-priority work and limits horizontal throughput.
        for _ in range(25):
            now = utcnow()
            task = self.db.scalar(
                select(ReconTask)
                .join(Target, Target.id == ReconTask.target_id)
                .where(
                    ReconTask.status.in_([TaskStatus.queued.value, TaskStatus.retry_wait.value]),
                    ReconTask.available_at <= now,
                    Target.cancel_requested.is_(False),
                    Target.status.in_([TargetStatus.queued, TargetStatus.running]),
                )
                .order_by(ReconTask.priority.desc(), ReconTask.created_at, ReconTask.id)
                .limit(1)
                .with_for_update(skip_locked=True, of=ReconTask)
            )
            if task is None:
                break
            target_lock = self.db.get(Target, task.target_id, with_for_update=True)
            if target_lock is None:
                self.db.commit()
                continue
            running_for_target = int(
                self.db.scalar(
                    select(func.count())
                    .select_from(ReconTask)
                    .where(
                        ReconTask.target_id == task.target_id,
                        ReconTask.status == TaskStatus.running.value,
                    )
                )
                or 0
            )
            if running_for_target >= settings.max_concurrent_tasks_per_target:
                # Briefly defer this busy target so another target can be
                # considered without retaining a batch of row locks.
                task.available_at = now + timedelta(milliseconds=250)
                self.db.commit()
                continue
            if self._dependency_tasks(task.id):
                self._settle_and_continue(task)
                if task.status != TaskStatus.queued.value:
                    self._finalize_if_idle(target_lock)
                    self.db.commit()
                    continue
            module = self.registry.get(task.module_name)
            rate = module.manifest.rate_limit_per_second if module else None
            if rate:
                last_started = self.db.scalar(
                    select(ReconTask.started_at)
                    .where(
                        ReconTask.target_id == task.target_id,
                        ReconTask.module_name == task.module_name,
                        ReconTask.started_at.isnot(None),
                    )
                    .order_by(ReconTask.started_at.desc())
                    .limit(1)
                )
                if last_started:
                    if last_started.tzinfo is None:
                        last_started = last_started.replace(tzinfo=UTC)
                    earliest = last_started + timedelta(seconds=1 / rate)
                    if earliest > now:
                        task.available_at = earliest
                        self.db.commit()
                        continue
            task.status = TaskStatus.running.value
            task.attempts += 1
            task.lease_owner = worker_id
            task.started_at = task.started_at or now
            task.heartbeat_at = now
            task.lease_expires_at = now + timedelta(
                seconds=max(settings.task_lease_seconds, task.timeout_seconds + 30)
            )
            target = self.db.get(Target, task.target_id)
            if target:
                target.status = TargetStatus.running
                target.started_at = target.started_at or now
            self.knowledge.record_event(
                target_id=task.target_id,
                task_id=task.id,
                event_type="task.started",
                message=f"Started {task.module_name} (attempt {task.attempts})",
                data={"worker_id": worker_id, "attempt": task.attempts},
            )
            self.db.commit()
            self.db.refresh(task)
            active_tasks.inc()
            return task
        queued_count = self.db.scalar(
            select(func.count())
            .select_from(ReconTask)
            .where(ReconTask.status.in_([TaskStatus.queued.value, TaskStatus.retry_wait.value]))
        )
        task_queue_depth.set(int(queued_count or 0))
        self.db.commit()
        return None

    def execute_claimed(self, task_id: int, worker_id: str) -> None:
        claimed = self.db.get(ReconTask, task_id)
        owns_active_task = bool(
            claimed
            and claimed.status == TaskStatus.running.value
            and claimed.lease_owner == worker_id
        )
        try:
            self._execute_claimed_inner(task_id, worker_id)
        finally:
            if owns_active_task:
                active_tasks.dec()

    def _execute_claimed_inner(self, task_id: int, worker_id: str) -> None:
        execution_started = time.perf_counter()
        task = self.db.get(ReconTask, task_id)
        if task is None or task.status != TaskStatus.running.value:
            return
        if task.lease_owner != worker_id:
            log.warning("worker=%s does not own task=%s", worker_id, task_id)
            return
        target = self.db.get(Target, task.target_id)
        if target is None:
            return
        if target.cancel_requested:
            self._cancel_task(task, "scan cancellation requested")
            self._finalize_if_idle(target)
            self.db.commit()
            return
        module = self.registry.get(task.module_name)
        if module is None:
            self._fail_task(
                task,
                ModuleExecutionError(
                    f"module is not registered: {task.module_name}",
                    retryable=False,
                    code="module_unavailable",
                ),
            )
            self._finalize_if_idle(target)
            self.db.commit()
            return
        asset = task.input_asset or self.db.get(Asset, task.input_asset_id)
        if asset is None:
            self._fail_task(
                task,
                ModuleExecutionError(
                    "input asset no longer exists",
                    retryable=False,
                    code="input_missing",
                ),
            )
            self._finalize_if_idle(target)
            self.db.commit()
            return
        decision = self._scope(target.id).decide(asset.kind, asset.canonical_value)
        derived_allowed = False
        if task.scope_basis == "derived" and module.manifest.accepts_derived_inputs:
            parent = self.db.get(ReconTask, task.parent_task_id) if task.parent_task_id else None
            derived_allowed = bool(
                module.manifest.mode != ModuleMode.active
                and parent is not None
                and parent.status in _SUCCESS_TERMINAL
            )
        if not decision.allowed and not derived_allowed:
            task.status = TaskStatus.skipped.value
            task.error_code = "out_of_scope"
            task.error_detail = decision.reason
            task.completed_at = utcnow()
            self.knowledge.record_event(
                target_id=target.id,
                task_id=task.id,
                event_type="task.scope_blocked",
                level="warning",
                message=f"Scope blocked {task.module_name}: {decision.reason}",
            )
            self._clear_lease(task)
            self._finalize_if_idle(target)
            self.db.commit()
            return

        normalized_input = NormalizedAsset(
            kind=asset.kind,
            value=asset.value,
            canonical_value=asset.canonical_value,
            identity_hash=asset.identity_hash,
            attributes=asset.attributes or {},
        )
        context = ModuleContext(
            target_id=target.id,
            task_id=task.id,
            input_asset=normalized_input,
            config={
                key: value
                for key, value in (task.config or {}).items()
                if not key.startswith("_reconator_")
            },
            timeout_seconds=task.timeout_seconds,
        )
        try:
            result = module.execute(context)
            # Cancellation may arrive while a blocking module is executing.
            # Re-read the flag before accepting any output.
            self.db.refresh(target, attribute_names=["cancel_requested"])
            if target.cancel_requested:
                self._cancel_task(task, "scan cancellation requested during execution")
                self.knowledge.record_event(
                    target_id=target.id,
                    task_id=task.id,
                    event_type="task.cancelled",
                    message="Task output discarded because the scan was cancelled",
                )
                self._finalize_if_idle(target)
                self.db.commit()
                return
            persisted = self.knowledge.persist_result(
                target_id=target.id,
                task_id=task.id,
                module_name=task.module_name,
                result=result,
            )
            for item in persisted.assets:
                assets_observed_total.labels(new_globally=str(item.new_globally).lower()).inc()
            relationships_observed_total.inc(len(persisted.relationship_ids))
        except ModuleExecutionError as exc:
            self._fail_task(task, exc)
        except Exception as exc:
            log.exception("module crashed task_id=%s module=%s", task.id, task.module_name)
            self._fail_task(
                task,
                ModuleExecutionError(f"{type(exc).__name__}: {exc}", code="module_crash"),
            )
        else:
            task.status = TaskStatus.completed.value
            task.completed_at = utcnow()
            raw_output = result.raw_output or ""
            retained_for_scan = int(
                self.db.scalar(
                    select(func.coalesce(func.sum(func.length(ReconTask.raw_output)), 0)).where(
                        ReconTask.target_id == target.id,
                        ReconTask.raw_output.isnot(None),
                    )
                )
                or 0
            )
            remaining_scan_budget = max(
                settings.max_raw_output_bytes_per_scan - retained_for_scan, 0
            )
            raw_limit = min(settings.max_raw_output_bytes, remaining_scan_budget)
            task.raw_output = raw_output[:raw_limit] or None
            task.output_summary = {
                **result.metadata,
                "asset_ids": [item.asset.id for item in persisted.assets],
                "asset_count": len(persisted.assets),
                "relationship_ids": persisted.relationship_ids,
                "relationship_count": len(persisted.relationship_ids),
                "validation_error_count": len(persisted.validation_errors),
                "validation_errors": persisted.validation_errors[:20],
                "raw_output_truncated": len(raw_output) > raw_limit,
                "raw_output_scan_budget_exhausted": bool(raw_output and remaining_scan_budget == 0),
            }
            self._clear_lease(task)
            self.knowledge.record_event(
                target_id=target.id,
                task_id=task.id,
                event_type="task.completed",
                message=f"Completed {task.module_name}",
                data=task.output_summary,
            )
            if persisted.validation_errors:
                self.knowledge.record_event(
                    target_id=target.id,
                    task_id=task.id,
                    event_type="task.output_rejected",
                    level="warning",
                    message=(
                        f"Rejected {len(persisted.validation_errors)} malformed module emission(s)"
                    ),
                    data={"errors": persisted.validation_errors[:20]},
                )
            for item in persisted.assets:
                if item.new_to_scan or item.changed:
                    self.schedule_for_asset(target, item, parent_task_id=task.id)
        self._unblock_dependents(task.id)
        self._finalize_if_idle(target)
        self.db.commit()
        tasks_total.labels(module=task.module_name, status=task.status).inc()
        task_duration_seconds.labels(module=task.module_name).observe(
            time.perf_counter() - execution_started
        )

    def _fail_task(self, task: ReconTask, exc: ModuleExecutionError) -> None:
        task.error_code = exc.code
        task.error_detail = str(exc)[:4_000]
        self._clear_lease(task)
        now = utcnow()
        if exc.code == "toolbox_http_429":
            # Capacity pressure is queueing, not an execution failure. Do not
            # burn the module's finite retry budget while the isolated tool
            # plane is busy with other authorized work.
            task.attempts = max(task.attempts - 1, 0)
        if exc.retryable and task.attempts < task.max_attempts:
            task.status = TaskStatus.retry_wait.value
            task.available_at = now + timedelta(
                seconds=settings.task_retry_base_seconds * (2 ** max(task.attempts - 1, 0))
            )
            event_type = "task.retry_scheduled"
            message = f"{task.module_name} failed; retry scheduled"
        else:
            task.status = TaskStatus.failed.value
            task.completed_at = now
            event_type = "task.failed"
            message = f"{task.module_name} failed permanently"
        self.knowledge.record_event(
            target_id=task.target_id,
            task_id=task.id,
            event_type=event_type,
            level="error",
            message=message,
            data={"code": exc.code, "detail": str(exc)[:1000]},
        )

    @staticmethod
    def _clear_lease(task: ReconTask) -> None:
        task.lease_owner = None
        task.lease_expires_at = None
        task.heartbeat_at = None

    def _cancel_task(self, task: ReconTask, reason: str) -> None:
        task.status = TaskStatus.cancelled.value
        task.error_code = "cancelled"
        task.error_detail = reason
        task.completed_at = utcnow()
        self._clear_lease(task)

    def cancel_pending(self, target: Target) -> int:
        tasks = list(
            self.db.scalars(
                select(ReconTask).where(
                    ReconTask.target_id == target.id,
                    ReconTask.status.in_(
                        [
                            TaskStatus.queued.value,
                            TaskStatus.retry_wait.value,
                            TaskStatus.blocked.value,
                        ]
                    ),
                )
            )
        )
        for task in tasks:
            self._cancel_task(task, "scan cancellation requested")
        target.cancel_requested = True
        running = int(
            self.db.scalar(
                select(func.count())
                .select_from(ReconTask)
                .where(
                    ReconTask.target_id == target.id,
                    ReconTask.status == TaskStatus.running.value,
                )
            )
            or 0
        )
        if running:
            target.status = TargetStatus.running
        else:
            target.status = TargetStatus.cancelled
            target.completed_at = utcnow()
        self.knowledge.record_event(
            target_id=target.id,
            event_type="scan.cancel_requested" if running else "scan.cancelled",
            message=(
                "Cancellation requested; waiting for running tasks"
                if running
                else "Scan and unfinished tasks were cancelled"
            ),
            data={"cancelled_tasks": len(tasks), "running_tasks": running},
        )
        return len(tasks)

    def reconcile_scope(self, target: Target) -> dict[str, int]:
        """Apply changed scope to queued work and previously observed assets."""
        policy = self._scope(target.id)
        suppressed = 0
        pending = list(
            self.db.scalars(
                select(ReconTask).where(
                    ReconTask.target_id == target.id,
                    ReconTask.status.in_(
                        [
                            TaskStatus.queued.value,
                            TaskStatus.retry_wait.value,
                            TaskStatus.blocked.value,
                        ]
                    ),
                )
            )
        )
        for task in pending:
            asset = task.input_asset or self.db.get(Asset, task.input_asset_id)
            if asset and not policy.decide(asset.kind, asset.canonical_value).allowed:
                task.status = TaskStatus.skipped.value
                task.error_code = "scope_changed"
                task.error_detail = "task suppressed after scope policy changed"
                task.completed_at = utcnow()
                suppressed += 1

        asset_ids = list(
            self.db.scalars(
                select(AssetObservation.asset_id)
                .where(AssetObservation.target_id == target.id)
                .distinct()
                .limit(settings.max_tasks_per_scan)
            )
        )
        scheduled = 0
        for asset in self.db.scalars(select(Asset).where(Asset.id.in_(asset_ids))):
            normalized = NormalizedAsset(
                asset.kind,
                asset.value,
                asset.canonical_value,
                asset.identity_hash,
                asset.attributes or {},
            )
            if not policy.decide(asset.kind, asset.canonical_value).allowed:
                continue
            scheduled += len(
                self.schedule_for_asset(
                    target,
                    ObservedAsset(asset, normalized, False, False, False),
                )
            )
        self.knowledge.record_event(
            target_id=target.id,
            event_type="scope.reconciled",
            message="Scope policy was applied to assets and unfinished tasks",
            data={"scheduled": scheduled, "suppressed": suppressed},
        )
        if scheduled and target.status in {
            TargetStatus.completed,
            TargetStatus.failed,
            TargetStatus.cancelled,
        }:
            target.status = TargetStatus.queued
            target.cancel_requested = False
            target.completed_at = None
            target.error = None
        self._finalize_if_idle(target)
        return {"scheduled": scheduled, "suppressed": suppressed}

    def _unblock_dependents(self, completed_task_id: int) -> None:
        dependent_ids = list(
            self.db.scalars(
                select(TaskDependency.task_id).where(
                    TaskDependency.depends_on_id == completed_task_id
                )
            )
        )
        for task_id in dependent_ids:
            task = self.db.scalar(
                select(ReconTask).where(ReconTask.id == task_id).with_for_update()
            )
            if task is None or task.status != TaskStatus.blocked.value:
                continue
            self._settle_and_continue(task)

    def _finalize_if_idle(self, target: Target) -> None:
        # Concurrent terminal tasks must serialize here. The last waiter sees
        # every earlier commit and is responsible for finalizing the scan.
        locked_target = self.db.scalar(
            select(Target).where(Target.id == target.id).with_for_update()
        )
        if locked_target is None:
            return
        target = locked_target
        counts = dict(
            self.db.execute(
                select(ReconTask.status, func.count())
                .where(ReconTask.target_id == target.id)
                .group_by(ReconTask.status)
            ).all()
        )
        active = sum(count for status, count in counts.items() if status not in _ALL_TERMINAL)
        if active:
            return
        if target.completed_at is not None and target.status in {
            TargetStatus.completed,
            TargetStatus.failed,
            TargetStatus.cancelled,
        }:
            return
        now = utcnow()
        target.completed_at = now
        if target.cancel_requested:
            target.status = TargetStatus.cancelled
            target.error = "cancelled by user"
        elif counts.get(TaskStatus.failed.value, 0) and not counts.get(
            TaskStatus.completed.value, 0
        ):
            target.status = TargetStatus.failed
            target.error = "all executable recon tasks failed"
        else:
            target.status = TargetStatus.completed
            failures = counts.get(TaskStatus.failed.value, 0)
            target.error = f"partial failure: {failures} task(s)" if failures else None
        self.knowledge.record_event(
            target_id=target.id,
            event_type="scan.completed",
            message=f"Scan finished with status {target.status.value}",
            data={"task_status_counts": counts},
        )
        if target.parent_target_id:
            current_ids = set(
                self.db.scalars(
                    select(AssetObservation.asset_id).where(AssetObservation.target_id == target.id)
                )
            )
            baseline_ids = set(
                self.db.scalars(
                    select(AssetObservation.asset_id).where(
                        AssetObservation.target_id == target.parent_target_id
                    )
                )
            )
            self.knowledge.record_event(
                target_id=target.id,
                event_type="scan.change_summary",
                message="Incremental scan comparison completed",
                data={
                    "baseline_target_id": target.parent_target_id,
                    "added": len(current_ids - baseline_ids),
                    "removed": len(baseline_ids - current_ids),
                    "unchanged": len(current_ids & baseline_ids),
                },
            )
