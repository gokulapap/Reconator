from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from app.recon.normalization import NormalizedAsset

_MODULE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_CAPABILITY_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,95}$")
_ASSET_KIND = re.compile(r"^[a-z][a-z0-9_.-]{1,47}$")


class ModuleMode(StrEnum):
    local = "local"
    passive = "passive"
    active = "active"


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    name: str
    version: str
    description: str
    capability: str
    consumes: frozenset[str]
    produces: frozenset[str]
    mode: ModuleMode
    default_profiles: frozenset[str] = frozenset({"balanced", "active"})
    priority: int = 100
    timeout_seconds: int = 300
    max_attempts: int = 3
    cache_ttl_seconds: int = 86_400
    rate_limit_per_second: float | None = None
    accepts_derived_inputs: bool = False
    enabled: bool = True
    implementation: str = "python"

    def __post_init__(self) -> None:
        if not _MODULE_NAME.fullmatch(self.name):
            raise ValueError("module name must be a lowercase namespaced identifier")
        if not _CAPABILITY_NAME.fullmatch(self.capability):
            raise ValueError("module capability must be a lowercase namespaced identifier")
        if not self.version or len(self.version) > 32:
            raise ValueError(f"module {self.name} has an invalid version")
        if not self.description or len(self.description) > 500:
            raise ValueError(f"module {self.name} has an invalid description")
        if not self.consumes:
            raise ValueError(f"module {self.name} must declare at least one input kind")
        if any(not _ASSET_KIND.fullmatch(kind) for kind in self.consumes | self.produces):
            raise ValueError(f"module {self.name} declares an invalid asset kind")
        if not self.default_profiles <= {"passive", "balanced", "active"}:
            raise ValueError(f"module {self.name} declares an invalid profile")
        if not -10_000 <= self.priority <= 10_000:
            raise ValueError(f"module {self.name} has an invalid priority")
        if not 1 <= self.timeout_seconds <= 86_400 or not 1 <= self.max_attempts <= 20:
            raise ValueError(f"module {self.name} has invalid execution limits")
        if self.cache_ttl_seconds < 0:
            raise ValueError(f"module {self.name} has an invalid cache TTL")
        if self.rate_limit_per_second is not None and not 0 < self.rate_limit_per_second <= 10_000:
            raise ValueError(f"module {self.name} has an invalid rate limit")


@dataclass(frozen=True, slots=True)
class AssetReference:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class AssetEmission:
    kind: str
    value: str
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)
    source_name: str | None = None


@dataclass(frozen=True, slots=True)
class RelationshipEmission:
    source: AssetReference
    target: AssetReference
    relationship_type: str
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModuleResult:
    assets: list[AssetEmission] = field(default_factory=list)
    relationships: list[RelationshipEmission] = field(default_factory=list)
    raw_output: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModuleContext:
    target_id: int
    task_id: int
    input_asset: NormalizedAsset
    config: dict[str, Any]
    timeout_seconds: int


class ReconModule(Protocol):
    manifest: ModuleManifest

    def execute(self, context: ModuleContext) -> ModuleResult: ...


class ModuleExecutionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True, code: str = "execution_error"):
        super().__init__(message)
        self.retryable = retryable
        self.code = code
