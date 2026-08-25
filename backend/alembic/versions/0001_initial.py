"""initial schema — targets + scan_results

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


target_status = sa.Enum(
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="target_status",
)
module_status = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    name="module_status",
)


def upgrade() -> None:
    op.create_table(
        "targets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("url", sa.String(length=255), nullable=False, index=True),
        sa.Column(
            "status",
            target_status,
            nullable=False,
            server_default="queued",
            index=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("tags", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("selected_modules", sa.JSON, nullable=True),
        sa.Column(
            "cancel_requested",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_targets_status_created", "targets", ["status", "created_at"]
    )

    op.create_table(
        "scan_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "target_id",
            sa.Integer,
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            module_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("output", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_scan_results_target_module",
        "scan_results",
        ["target_id", "module"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_scan_results_target_module", table_name="scan_results")
    op.drop_table("scan_results")
    op.drop_index("ix_targets_status_created", table_name="targets")
    op.drop_table("targets")
    bind = op.get_bind()
    module_status.drop(bind, checkfirst=True)
    target_status.drop(bind, checkfirst=True)
