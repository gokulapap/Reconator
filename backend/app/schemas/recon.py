from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    value: str
    canonical_value: str
    attributes: dict[str, Any]
    priority_score: float
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime
    active: bool


class AssetList(BaseModel):
    items: list[AssetRead]
    total: int
    page: int
    page_size: int


class AssetObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    asset_id: int
    task_id: int | None
    source_module: str
    source_name: str | None
    confidence: float
    evidence: dict[str, Any]
    snapshot: dict[str, Any]
    first_observed_at: datetime
    last_observed_at: datetime
    observation_count: int


class RelationshipRead(BaseModel):
    id: int
    source_asset_id: int
    target_asset_id: int
    relationship_type: str
    attributes: dict[str, Any]
    confidence: float
    first_seen_at: datetime
    last_seen_at: datetime


class AssetRelationshipContext(BaseModel):
    relationship: RelationshipRead
    direction: Literal["incoming", "outgoing"]
    related_asset: AssetRead


class AssetIntelligence(BaseModel):
    asset: AssetRead
    observations: list[AssetObservationRead]
    relationships: list[AssetRelationshipContext]
    observations_truncated: bool = False
    relationships_truncated: bool = False


class GraphResponse(BaseModel):
    nodes: list[AssetRead]
    edges: list[RelationshipRead]
    truncated: bool = False


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    input_asset_id: int | None
    parent_task_id: int | None
    cache_hit_task_id: int | None
    module_name: str
    module_version: str
    capability: str
    scope_basis: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    timeout_seconds: int
    available_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_detail: str | None
    output_summary: dict[str, Any]


class TaskList(BaseModel):
    items: list[TaskRead]
    total: int
    page: int
    page_size: int


class TaskDetail(TaskRead):
    raw_output: str | None
    config: dict[str, Any]


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    task_id: int | None
    event_type: str
    level: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class ScopeRuleCreate(BaseModel):
    action: Literal["include", "exclude"]
    rule_type: Literal["exact", "subdomain", "cidr", "url_prefix", "regex"]
    asset_kind: str | None = Field(default=None, max_length=48)
    pattern: str = Field(min_length=1, max_length=2048)
    priority: int = Field(default=100, ge=0, le=10_000)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("asset_kind")
    @classmethod
    def validate_asset_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower().strip()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,47}", normalized):
            raise ValueError("asset_kind must be a valid built-in or namespaced kind")
        return normalized


class ScopeRuleRead(ScopeRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    normalized_pattern: str
    created_at: datetime


class ScanComparison(BaseModel):
    baseline_target_id: int
    comparison_target_id: int
    added: list[AssetRead]
    removed: list[AssetRead]
    changed: list[AssetRead]
    unchanged_count: int
    truncated: bool = False


class KnowledgeStats(BaseModel):
    assets_total: int
    relationships_total: int
    observations_total: int
    tasks_by_status: dict[str, int]
    assets_by_kind: dict[str, int]


class SourceYield(BaseModel):
    source_module: str
    source_name: str | None
    observations: int
    distinct_assets: int
    exclusive_assets: int
    average_confidence: float
    last_observed_at: datetime | None


class ScanCompleteness(BaseModel):
    tasks_inspected: int
    tasks_total: int
    truncated_tasks: int
    discovery_truncated_tasks: int
    evidence_truncated_tasks: int
    validation_rejections: int


class ModuleHealth(BaseModel):
    module_name: str
    capability: str
    tasks_total: int
    tasks_by_status: dict[str, int]
    failure_rate: float
    error_codes: dict[str, int] = Field(default_factory=dict)
    duration_sample_size: int = 0
    duration_total: int = 0
    average_duration_seconds: float | None = None
    p95_duration_seconds: float | None = None


class ScanKnowledgeSummary(BaseModel):
    assets_total: int
    relationships_total: int
    observations_total: int
    tasks_total: int
    assets_by_kind: dict[str, int]
    relationships_by_type: dict[str, int]
    tasks_by_status: dict[str, int]
    observations_by_module: dict[str, int]
    source_yield: list[SourceYield] = Field(default_factory=list)
    module_health: list[ModuleHealth] = Field(default_factory=list)
    completeness: ScanCompleteness | None = None
