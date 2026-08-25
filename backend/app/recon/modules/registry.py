from __future__ import annotations

import logging
from importlib.metadata import entry_points
from threading import RLock

from app.recon.modules.base import ReconModule

log = logging.getLogger(__name__)


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

    def load_entry_points(self) -> None:
        for entry_point in entry_points(group="reconator.modules"):
            try:
                loaded = entry_point.load()
                module = loaded() if isinstance(loaded, type) else loaded
                self.register(module)
            except Exception:
                log.exception("failed to load recon module entry point=%s", entry_point.name)


registry = ModuleRegistry()
