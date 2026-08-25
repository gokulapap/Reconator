import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.db.models import AssetKind, ModuleStatus, TargetStatus
from app.recon.normalization import NormalizationError, normalize_asset

DOMAIN_REGEX = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})+$")
TargetValue = Annotated[str, Field(min_length=3, max_length=2048)]


def _normalise_domain(v: str) -> str:
    v = v.strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = v.rstrip("/")
    if not DOMAIN_REGEX.match(v):
        raise ValueError(f"invalid domain: {v!r} — provide a bare domain like example.com")
    return v


def _normalise_target(value: str, kind: str) -> str:
    if kind == AssetKind.domain.value:
        # Preserve the friendly legacy input that accepts https://example.com/.
        value = _normalise_domain(value)
    try:
        normalized = normalize_asset(kind, value)
    except NormalizationError as exc:
        raise ValueError(str(exc)) from exc
    if kind == AssetKind.url.value and normalized.attributes.get("scheme") not in {
        "http",
        "https",
    }:
        raise ValueError("root URL targets must use http or https")
    if len(normalized.canonical_value) > 2048:
        raise ValueError("normalized target exceeds 2048 characters")
    return normalized.canonical_value


def _normalise_tags(v: list[str]) -> list[str]:
    cleaned = sorted({t.strip().lower() for t in v if t.strip()})
    for tag in cleaned:
        if not re.match(r"^[a-z0-9._:-]{1,32}$", tag):
            raise ValueError(f"invalid tag: {tag!r}")
    return cleaned


def _validate_scan_config(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) - {"defaults", "modules"}:
        raise ValueError("scan_config supports only 'defaults' and 'modules'")
    if any(not isinstance(item, dict) for item in value.values()):
        raise ValueError("scan_config sections must be objects")
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("scan_config must contain finite JSON values") from exc
    if len(encoded.encode("utf-8")) > 65_536:
        raise ValueError("scan_config exceeds 64 KiB")
    return value


class TargetCreate(BaseModel):
    target_kind: Literal["domain", "url", "ip_address", "cidr"] = "domain"
    url: TargetValue
    tags: list[str] = Field(default_factory=list, max_length=20)
    selected_modules: list[str] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    profile: Literal["passive", "balanced", "active"] = "balanced"
    scan_config: dict[str, Any] = Field(default_factory=dict)
    authorization_confirmed: bool = False

    @field_validator("url")
    @classmethod
    def validate_target(cls, value: str, info: ValidationInfo) -> str:
        return _normalise_target(value, info.data.get("target_kind", "domain"))

    @field_validator("tags")
    @classmethod
    def normalise_tags(cls, v: list[str]) -> list[str]:
        return _normalise_tags(v)

    @field_validator("selected_modules")
    @classmethod
    def normalise_modules(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = sorted(set(value))
        if len(cleaned) > 100:
            raise ValueError("at most 100 modules may be selected")
        if any(not re.fullmatch(r"[a-z][a-z0-9_.-]{1,127}", item) for item in cleaned):
            raise ValueError("module names must use lowercase letters, digits, dots, or dashes")
        return cleaned

    @field_validator("scan_config")
    @classmethod
    def validate_scan_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_scan_config(value)


class TargetBulkCreate(BaseModel):
    target_kind: Literal["domain", "url", "ip_address", "cidr"] = "domain"
    urls: list[TargetValue] = Field(..., min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=20)
    selected_modules: list[str] | None = None
    profile: Literal["passive", "balanced", "active"] = "balanced"
    scan_config: dict[str, Any] = Field(default_factory=dict)
    authorization_confirmed: bool = False

    @field_validator("tags")
    @classmethod
    def normalise_tags(cls, value: list[str]) -> list[str]:
        return _normalise_tags(value)

    @field_validator("selected_modules")
    @classmethod
    def normalise_modules(cls, value: list[str] | None) -> list[str] | None:
        return TargetCreate.normalise_modules(value)

    @field_validator("scan_config")
    @classmethod
    def validate_scan_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_scan_config(value)


class TargetBulkResult(BaseModel):
    created: list[int]
    conflicts: list[str]
    errors: dict[str, str]


class ScanResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    module: str
    status: ModuleStatus
    output: str | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


class ScanResultSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    module: str
    status: ModuleStatus
    completed_at: datetime | None
    has_output: bool = False


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    target_kind: str
    status: TargetStatus
    error: str | None
    tags: list[str] = Field(default_factory=list)
    selected_modules: list[str] | None = None
    profile: str
    authorization_confirmed: bool
    parent_target_id: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TargetDetail(TargetRead):
    notes: str | None = None
    results: list[ScanResultSummary] = Field(default_factory=list)


class TargetList(BaseModel):
    items: list[TargetRead]
    total: int
    page: int
    page_size: int


class StatsResponse(BaseModel):
    queued: int
    running: int
    completed: int
    failed: int
    cancelled: int
    total: int
    avg_duration_seconds: float | None = None
