"""add_sync_and_plugin_tables

Revision ID: f047afab5e35
Revises: 8cb29b3d2888
Create Date: 2026-05-11 09:24:43.667373

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f047afab5e35"
down_revision: Union[str, Sequence[str], None] = "8cb29b3d2888"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sync_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("is_synced", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "sync_status",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_cursor", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="idle", nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider"),
    )
    op.create_table(
        "plugins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("entry_point", sa.String(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("installed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "plugin_hooks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plugin_id", sa.Integer(), nullable=False),
        sa.Column("hook_name", sa.String(length=100), nullable=False),
        sa.Column("handler_fn", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("plugin_hooks")
    op.drop_table("plugins")
    op.drop_table("sync_status")
    op.drop_table("sync_queue")
