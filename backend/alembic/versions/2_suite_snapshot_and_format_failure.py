"""Add suite_snapshot and rename failed to format_failure.

Revision ID: 2_suite_snapshot_and_format_failure
Revises: 1_initial
Create Date: 2026-08-19 12:00:00.000000

Brings the milestone 3 schema (1_initial) up to the current
``app.db.models`` definitions: evaluation gains ``suite_snapshot`` and
``manual_scores`` gains ``format_failure`` (formerly ``failed``).
"""

from sqlalchemy import Column, Text

from alembic import op

revision: str = "2_suite_snapshot_and_format_failure"
down_revision: str | None = "1_initial"


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        Column("suite_snapshot", Text, nullable=False, server_default=""),
    )
    op.execute("ALTER TABLE manual_scores RENAME COLUMN failed TO format_failure")


def downgrade() -> None:
    op.drop_column("evaluation_runs", "suite_snapshot")
    op.execute("ALTER TABLE manual_scores RENAME COLUMN format_failure TO failed")
