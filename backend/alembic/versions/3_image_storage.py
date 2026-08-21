"""Add image storage and case metadata to evaluation results.

Revision ID: 3_image_storage
Revises: 2_suite_snapshot_and_format_failure
Create Date: 2026-08-20 12:00:00.000000

Brings the milestone 5 schema up to the ``app.db.models`` definitions:
``evaluation_results`` gains ``input_type``, ``case_type``, and the image
columns used for vision cases, and ``evaluation_images`` stores the validated
image bytes attached to (or loaded from the fixture of) each run.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)

from alembic import op

revision: str = "3_image_storage"
down_revision: str | None = "2_suite_snapshot_and_format_failure"


def upgrade() -> None:
    op.create_table(
        "evaluation_images",
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column(
            "run_id",
            Integer,
            ForeignKey("evaluation_runs.id"),
            index=True,
            nullable=False,
        ),
        Column("case_id", String, nullable=False),
        Column("media_type", String, nullable=False),
        Column("source", String, nullable=False),
        Column("data_url", Text, nullable=False),
        Column("bytes", LargeBinary, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "evaluation_results",
        Column("input_type", String, nullable=True),
    )
    op.add_column(
        "evaluation_results",
        Column("case_type", String, nullable=True),
    )
    op.add_column(
        "evaluation_results",
        Column("image_data", LargeBinary, nullable=True),
    )
    op.add_column(
        "evaluation_results",
        Column("image_media_type", String, nullable=True),
    )
    op.add_column(
        "evaluation_results",
        Column("image_source", String, nullable=True),
    )
    op.add_column(
        "evaluation_results",
        Column("image_data_url", Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("evaluation_images")
    op.drop_column("evaluation_results", "image_data_url")
    op.drop_column("evaluation_results", "image_source")
    op.drop_column("evaluation_results", "image_media_type")
    op.drop_column("evaluation_results", "image_data")
    op.drop_column("evaluation_results", "case_type")
    op.drop_column("evaluation_results", "input_type")
