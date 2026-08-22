"""Add uniqueness on (run_id, case_id) for results and images.

Revision ID: 4_result_image_uniqueness
Revises: 3_image_storage
Create Date: 2026-08-21 12:00:00.000000

Defense in depth for Milestone 5: the suite loader already rejects
duplicate case ids, but the database now also enforces that a run holds
at most one result row and one stored image per case id.
"""

from alembic import op

revision: str = "4_result_image_uniqueness"
down_revision: str | None = "3_image_storage"


def upgrade() -> None:
    op.create_index(
        "iq_evaluation_results_run_case",
        "evaluation_results",
        ["run_id", "case_id"],
        unique=True,
    )
    op.create_index(
        "iq_evaluation_images_run_case",
        "evaluation_images",
        ["run_id", "case_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("iq_evaluation_images_run_case", table_name="evaluation_images")
    op.drop_index("iq_evaluation_results_run_case", table_name="evaluation_results")
