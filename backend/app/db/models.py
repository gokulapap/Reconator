from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class TargetStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ModuleStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class TaskStatus(StrEnum):
    queued = "queued"
    running = "running"
    retry_wait = "retry_wait"
    blocked = "blocked"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class AssetKind(StrEnum):
    domain = "domain"
    url = "url"
    ip_address = "ip_address"
    cidr = "cidr"
    port = "port"
    service = "service"
    endpoint = "endpoint"
    parameter = "parameter"
    certificate = "certificate"
    autonomous_system = "autonomous_system"
    technology = "technology"
    cloud_resource = "cloud_resource"
    repository = "repository"
    javascript = "javascript"
    email = "email"
    organization = "organization"
    dns_record = "dns_record"


class ScopeAction(StrEnum):
    include = "include"
    exclude = "exclude"


class ScopeRuleType(StrEnum):
    exact = "exact"
    subdomain = "subdomain"
    cidr = "cidr"
    url_prefix = "url_prefix"
    regex = "regex"


class Target(Base, TimestampMixin):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Target roots may be full URLs. Avoid a large btree over arbitrary URL text;
    # target_kind/status narrows active-target conflict checks efficiently.
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_kind: Mapped[str] = mapped_column(
        String(24), default=AssetKind.domain.value, nullable=False
    )
    status: Mapped[TargetStatus] = mapped_column(
        Enum(TargetStatus, name="target_status"),
        default=TargetStatus.queued,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # New: tags + selected modules. JSON for cross-dialect support (sqlite tests).
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    selected_modules: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    profile: Mapped[str] = mapped_column(String(32), default="balanced", nullable=False)
    scan_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    authorization_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parent_target_id: Mapped[int | None] = mapped_column(
        ForeignKey("targets.id", ondelete="SET NULL"), nullable=True, index=True
    )

    results: Mapped[list["ScanResult"]] = relationship(
        "ScanResult",
        back_populates="target",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    tasks: Mapped[list["ReconTask"]] = relationship(
        "ReconTask",
        back_populates="target",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    scope_rules: Mapped[list["ScopeRule"]] = relationship(
        "ScopeRule",
        back_populates="target",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    __table_args__ = (
        Index("ix_targets_status_created", "status", "created_at"),
        Index("ix_targets_kind_status", "target_kind", "status"),
    )


class ScanResult(Base, TimestampMixin):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ModuleStatus] = mapped_column(
        Enum(ModuleStatus, name="module_status"),
        default=ModuleStatus.pending,
        nullable=False,
    )
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    target: Mapped[Target] = relationship("Target", back_populates="results")

    __table_args__ = (Index("ix_scan_results_target_module", "target_id", "module", unique=True),)


class Asset(Base, TimestampMixin):
    """A canonical, scan-independent node in Reconator's knowledge graph."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_value: Mapped[str] = mapped_column(Text, nullable=False)
    identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("kind", "identity_hash", name="uq_assets_kind_identity"),
        Index("ix_assets_kind_last_seen", "kind", "last_seen_at"),
        Index("ix_assets_priority", "priority_score", "last_seen_at"),
    )


class ReconTask(Base, TimestampMixin):
    """A resumable, leased unit of work generated from an asset observation."""

    __tablename__ = "recon_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    input_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("recon_tasks.id", ondelete="SET NULL"), nullable=True
    )
    cache_hit_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("recon_tasks.id", ondelete="SET NULL"), nullable=True
    )
    module_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    module_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    capability: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    scope_basis: Mapped[str] = mapped_column(String(16), default="direct", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=TaskStatus.queued.value, nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    target: Mapped[Target] = relationship("Target", back_populates="tasks")
    input_asset: Mapped[Asset | None] = relationship(
        "Asset", foreign_keys=[input_asset_id], lazy="joined"
    )

    __table_args__ = (
        UniqueConstraint("target_id", "idempotency_key", name="uq_task_idempotency"),
        CheckConstraint("attempts >= 0", name="ck_task_attempts_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="ck_task_max_attempts_positive"),
        CheckConstraint("timeout_seconds >= 1", name="ck_task_timeout_positive"),
        Index(
            "ix_recon_tasks_claim",
            "status",
            "available_at",
            "priority",
            "created_at",
        ),
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("recon_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_id: Mapped[int] = mapped_column(
        ForeignKey("recon_tasks.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        CheckConstraint("task_id != depends_on_id", name="ck_task_dependency_not_self"),
    )


class AssetObservation(Base, TimestampMixin):
    __tablename__ = "asset_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("recon_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_module: Mapped[str] = mapped_column(String(128), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provenance_key: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    asset: Mapped[Asset] = relationship("Asset", lazy="joined")

    __table_args__ = (
        UniqueConstraint("target_id", "provenance_key", name="uq_asset_observation_provenance"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_observation_confidence"),
        Index("ix_asset_observation_scan_asset", "target_id", "asset_id"),
    )


class AssetRelationship(Base, TimestampMixin):
    __tablename__ = "asset_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source_asset: Mapped[Asset] = relationship(
        "Asset", foreign_keys=[source_asset_id], lazy="joined"
    )
    target_asset: Mapped[Asset] = relationship(
        "Asset", foreign_keys=[target_asset_id], lazy="joined"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_asset_id",
            "target_asset_id",
            "relationship_type",
            name="uq_asset_relationship",
        ),
        CheckConstraint("source_asset_id != target_asset_id", name="ck_relationship_not_self"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_relationship_confidence"),
    )


class RelationshipObservation(Base, TimestampMixin):
    __tablename__ = "relationship_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_id: Mapped[int] = mapped_column(
        ForeignKey("asset_relationships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("recon_tasks.id", ondelete="SET NULL"), nullable=True
    )
    source_module: Mapped[str] = mapped_column(String(128), nullable=False)
    provenance_key: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "target_id",
            "provenance_key",
            name="uq_relationship_observation_provenance",
        ),
    )


class ScopeRule(Base, TimestampMixin):
    __tablename__ = "scope_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(24), nullable=False)
    asset_kind: Mapped[str | None] = mapped_column(String(48), nullable=True)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    target: Mapped[Target] = relationship("Target", back_populates="scope_rules")

    __table_args__ = (
        UniqueConstraint(
            "target_id",
            "action",
            "rule_type",
            "asset_kind",
            "normalized_pattern",
            name="uq_scope_rule",
        ),
        Index("ix_scope_rules_target_priority", "target_id", "priority"),
    )


class ReconEvent(Base):
    __tablename__ = "recon_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("recon_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (Index("ix_recon_events_scan_created", "target_id", "created_at"),)
