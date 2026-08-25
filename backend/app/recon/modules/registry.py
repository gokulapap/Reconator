from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from importlib.metadata import entry_points
from threading import RLock

from app.recon.modules.base import CapabilityExecutionPolicy, ReconModule

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CapabilityExecutionGroup:
    capability: str
    policy: CapabilityExecutionPolicy
    modules: tuple[ReconModule, ...]


class ModuleRegistry:
    """Thread-safe capability registry; modules are replaceable implementations."""

    def __init__(self) -> None:
        self._modules: dict[str, ReconModule] = {}
        self._lock = RLock()

    def register(self, module: ReconModule, *, replace: bool = False) -> None:
        manifest = module.manifest
        with self._lock:
            if manifest.name in self._modules and not replace:
                raise ValueError(f"module already registered: {manifest.name}")
            declared = {
                candidate.manifest.capability_policy
                for candidate in self._modules.values()
                if candidate.manifest.capability == manifest.capability
                and candidate.manifest.name != manifest.name
                and candidate.manifest.capability_policy is not None
            }
            if (
                manifest.capability_policy is not None
                and declared
                and manifest.capability_policy not in declared
            ):
                other = sorted(policy.value for policy in declared)
                raise ValueError(
                    f"capability {manifest.capability} declares conflicting execution "
                    f"policies: {', '.join(other)}, {manifest.capability_policy.value}"
                )
            self._modules[manifest.name] = module

    def get(self, name: str) -> ReconModule | None:
        with self._lock:
            return self._modules.get(name)

    def all(self) -> list[ReconModule]:
        with self._lock:
            return sorted(self._modules.values(), key=lambda item: item.manifest.name)

    @staticmethod
    def is_available(module: ReconModule) -> bool:
        availability = getattr(module, "available", None)
        if availability is None:
            return True
        try:
            return bool(availability())
        except Exception:
            log.exception("module availability check failed module=%s", module.manifest.name)
            return False

    def consumers_for(
        self,
        asset_kind: str,
        *,
        profile: str,
        selected_modules: set[str] | None = None,
    ) -> list[ReconModule]:
        candidates = []
        for module in self.all():
            manifest = module.manifest
            if not manifest.enabled or asset_kind not in manifest.consumes:
                continue
            if not self.is_available(module):
                continue
            if selected_modules is not None and not {
                manifest.name,
                manifest.capability,
            }.intersection(selected_modules):
                continue
            if selected_modules is None and profile not in manifest.default_profiles:
                continue
            candidates.append(module)
        return sorted(candidates, key=lambda item: (-item.manifest.priority, item.manifest.name))

    @staticmethod
    def execution_policy_for(
        modules: list[ReconModule] | tuple[ReconModule, ...],
    ) -> CapabilityExecutionPolicy:
        declared = {
            module.manifest.capability_policy
            for module in modules
            if module.manifest.capability_policy is not None
        }
        if not declared:
            return CapabilityExecutionPolicy.parallel_sources
        if len(declared) > 1:
            policies = ", ".join(sorted(policy.value for policy in declared))
            raise ValueError(f"conflicting capability execution policies: {policies}")
        return declared.pop()

    def policy_for_capability(self, capability: str) -> CapabilityExecutionPolicy:
        with self._lock:
            modules = tuple(
                module
                for module in self._modules.values()
                if module.manifest.capability == capability
            )
        return self.execution_policy_for(modules)

    def execution_groups(self, modules: list[ReconModule]) -> list[CapabilityExecutionGroup]:
        grouped: dict[str, list[ReconModule]] = defaultdict(list)
        for module in modules:
            grouped[module.manifest.capability].append(module)
        groups = []
        for capability, implementations in grouped.items():
            ordered = tuple(
                sorted(
                    implementations,
                    key=lambda item: (
                        -item.manifest.implementation_priority,
                        -item.manifest.priority,
                        item.manifest.name,
                    ),
                )
            )
            groups.append(
                CapabilityExecutionGroup(
                    capability=capability,
                    policy=self.execution_policy_for(ordered),
                    modules=ordered,
                )
            )
        return sorted(
            groups,
            key=lambda group: (
                -max(module.manifest.priority for module in group.modules),
                group.capability,
            ),
        )

    def load_entry_points(self) -> None:
        for entry_point in entry_points(group="reconator.modules"):
            try:
                loaded = entry_point.load()
                module = loaded() if isinstance(loaded, type) else loaded
                self.register(module)
            except Exception:
                log.exception("failed to load recon module entry point=%s", entry_point.name)


registry = ModuleRegistry()
