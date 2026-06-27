"""add task sync metadata

Revision ID: 9d3b7d5f8c21
Revises: 134b6b6cf676
Create Date: 2026-06-27 13:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d3b7d5f8c21"
down_revision: Union[str, Sequence[str], None] = "134b6b6cf676"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("sync_status", sa.String(), nullable=False, server_default="pending"))
    op.add_column("tasks", sa.Column("last_synced_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_tasks_sync_status"), "tasks", ["sync_status"], unique=False)
    op.alter_column("tasks", "sync_status", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_sync_status"), table_name="tasks")
    op.drop_column("tasks", "last_synced_at")
    op.drop_column("tasks", "sync_status")
