"""recon knowledge graph, scope engine, and resumable task queue

Revision ID: 0002_recon_engine
Revises: 0001_initial
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_recon_engine"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_targets_url", table_name="targets")
    op.alter_column(
        "targets",
        "url",
        existing_type=sa.String(length=255),
        type_=sa.String(length=2048),
        existing_nullable=False,
    )
    op.add_column(
        "targets",
        sa.Column(
            "target_kind", sa.String(length=24), nullable=False, server_default="domain"
        ),
    )
    op.create_index("ix_targets_kind_status", "targets", ["target_kind", "status"])
    op.add_column(
        "targets",
        sa.Column("profile", sa.String(length=32), nullable=False, server_default="balanced"),
    )
    op.add_column(
        "targets",
        sa.Column(
            "parent_target_id",
            sa.Integer(),
            sa.ForeignKey("targets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_targets_parent_target_id", "targets", ["parent_target_id"])
    op.add_column(
        "targets",
        sa.Column("scan_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "targets",
        sa.Column(
            "authorization_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("canonical_value", sa.Text(), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("kind", "identity_hash", name="uq_assets_kind_identity"),
    )
    op.create_index("ix_assets_kind", "assets", ["kind"])
    op.create_index("ix_assets_kind_last_seen", "assets", ["kind", "last_seen_at"])
    op.create_index("ix_assets_priority", "assets", ["priority_score", "last_seen_at"])

    op.create_table(
        "recon_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "input_asset_id",
            sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_task_id",
            sa.Integer(),
            sa.ForeignKey("recon_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cache_hit_task_id",
            sa.Integer(),
            sa.ForeignKey("recon_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("module_name", sa.String(length=128), nullable=False),
        sa.Column("module_version", sa.String(length=32), nullable=False, server_default="1"),
        sa.Column("capability", sa.String(length=96), nullable=False),
        sa.Column("scope_basis", sa.String(length=16), nullable=False, server_default="direct"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_task_attempts_nonnegative"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_task_max_attempts_positive"),
        sa.CheckConstraint("timeout_seconds >= 1", name="ck_task_timeout_positive"),
        sa.UniqueConstraint("target_id", "idempotency_key", name="uq_task_idempotency"),
    )
    op.create_index("ix_recon_tasks_target_id", "recon_tasks", ["target_id"])
    op.create_index("ix_recon_tasks_input_asset_id", "recon_tasks", ["input_asset_id"])
    op.create_index("ix_recon_tasks_module_name", "recon_tasks", ["module_name"])
    op.create_index("ix_recon_tasks_capability", "recon_tasks", ["capability"])
    op.create_index("ix_recon_tasks_status", "recon_tasks", ["status"])
    op.create_index("ix_recon_tasks_cache_key", "recon_tasks", ["cache_key"])
    op.create_index("ix_recon_tasks_lease_expires_at", "recon_tasks", ["lease_expires_at"])
    op.create_index(
        "ix_recon_tasks_claim",
        "recon_tasks",
        ["status", "available_at", "priority", "created_at"],
    )

    op.create_table(
        "task_dependencies",
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("recon_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_id",
            sa.Integer(),
            sa.ForeignKey("recon_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.CheckConstraint("task_id != depends_on_id", name="ck_task_dependency_not_self"),
    )

    op.create_table(
        "asset_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("recon_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_module", sa.String(length=128), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=True),
        sa.Column("provenance_key", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_observation_confidence"
        ),
        sa.UniqueConstraint(
            "target_id", "provenance_key", name="uq_asset_observation_provenance"
        ),
    )
    op.create_index("ix_asset_observations_target_id", "asset_observations", ["target_id"])
    op.create_index("ix_asset_observations_asset_id", "asset_observations", ["asset_id"])
    op.create_index("ix_asset_observations_task_id", "asset_observations", ["task_id"])
    op.create_index(
        "ix_asset_observation_scan_asset", "asset_observations", ["target_id", "asset_id"]
    )

    op.create_table(
        "asset_relationships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_asset_id",
            sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_asset_id",
            sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "source_asset_id != target_asset_id", name="ck_relationship_not_self"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_relationship_confidence"
        ),
        sa.UniqueConstraint(
            "source_asset_id",
            "target_asset_id",
            "relationship_type",
            name="uq_asset_relationship",
        ),
    )
    op.create_index(
        "ix_asset_relationships_source_asset_id", "asset_relationships", ["source_asset_id"]
    )
    op.create_index(
        "ix_asset_relationships_target_asset_id", "asset_relationships", ["target_asset_id"]
    )
    op.create_index(
        "ix_asset_relationships_relationship_type",
        "asset_relationships",
        ["relationship_type"],
    )

    op.create_table(
        "relationship_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relationship_id",
            sa.Integer(),
            sa.ForeignKey("asset_relationships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("recon_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_module", sa.String(length=128), nullable=False),
        sa.Column("provenance_key", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "target_id",
            "provenance_key",
            name="uq_relationship_observation_provenance",
        ),
    )
    op.create_index(
        "ix_relationship_observations_target_id", "relationship_observations", ["target_id"]
    )
    op.create_index(
        "ix_relationship_observations_relationship_id",
        "relationship_observations",
        ["relationship_id"],
    )

    op.create_table(
        "scope_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("rule_type", sa.String(length=24), nullable=False),
        sa.Column("asset_kind", sa.String(length=48), nullable=True),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("normalized_pattern", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "target_id",
            "action",
            "rule_type",
            "asset_kind",
            "normalized_pattern",
            name="uq_scope_rule",
        ),
    )
    op.create_index("ix_scope_rules_target_id", "scope_rules", ["target_id"])
    op.create_index(
        "ix_scope_rules_target_priority", "scope_rules", ["target_id", "priority"]
    )

    op.create_table(
        "recon_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("recon_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_recon_events_target_id", "recon_events", ["target_id"])
    op.create_index("ix_recon_events_task_id", "recon_events", ["task_id"])
    op.create_index("ix_recon_events_event_type", "recon_events", ["event_type"])
    op.create_index("ix_recon_events_created_at", "recon_events", ["created_at"])
    op.create_index(
        "ix_recon_events_scan_created", "recon_events", ["target_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("recon_events")
    op.drop_table("scope_rules")
    op.drop_table("relationship_observations")
    op.drop_table("asset_relationships")
    op.drop_table("asset_observations")
    op.drop_table("task_dependencies")
    op.drop_table("recon_tasks")
    op.drop_table("assets")
    op.drop_index("ix_targets_parent_target_id", table_name="targets")
    op.drop_column("targets", "parent_target_id")
    op.drop_column("targets", "authorization_confirmed")
    op.drop_column("targets", "scan_config")
    op.drop_column("targets", "profile")
    op.drop_index("ix_targets_kind_status", table_name="targets")
    op.drop_column("targets", "target_kind")
    op.alter_column(
        "targets",
        "url",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.create_index("ix_targets_url", "targets", ["url"])
