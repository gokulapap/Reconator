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


class RelationshipRead(BaseModel):
    id: int
    source_asset_id: int
    target_asset_id: int
    relationship_type: str
    attributes: dict[str, Any]
    confidence: float
    first_seen_at: datetime
    last_seen_at: datetime


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
