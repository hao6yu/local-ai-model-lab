"""Initial SQLite schema for the evaluation portal.

Revision ID: 1_initial
Revises:
Create Date: 2026-08-19 00:00:00.000000

The tables below reproduce the schema shipped at milestone 3 (M3), before
``evaluation_runs.suite_snapshot`` and ``manual_scores.format_failure`` were
introduced (that column was named ``failed``). ``app.db.models`` now adds those
columns, and revision 2 brings M3 databases up to that schema. This keeps a
clean ``alembic upgrade head`` working on an empty database while still
allowing M3 databases created before those columns to upgrade cleanly.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)

from alembic import op

revision: str = "1_initial"
down_revision: str | None = None


def upgrade() -> None:
    op.create_table(
        "model_profiles",
        Column("key", String, primary_key=True),
        Column("label", String, nullable=False),
        Column("model_id", String, nullable=True),
        Column("context_window", Integer, nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "test_suites",
        Column("key", String, primary_key=True),
        Column("name", String, nullable=False, unique=True),
        Column("version", String, nullable=False),
        Column("hash", String, nullable=False),
        Column("source_path", String, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "evaluation_runs",
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("suite_name", String, nullable=False),
        Column("suite_version", String, nullable=False),
        Column("suite_hash", String, nullable=False),
        Column("profile_key", String, nullable=False),
        Column("profile_label", String, nullable=False),
        Column("model_id", String, nullable=True),
        Column("context_window", Integer, nullable=True),
        Column("reasoning_effort", String, nullable=False),
        Column("temperature", Float, nullable=True),
        Column("max_tokens", Integer, nullable=True),
        Column("modality", String, nullable=False),
        Column("notes", Text, nullable=True),
        Column("state", String, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("completed_at", DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "evaluation_results",
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column(
            "run_id",
            Integer,
            ForeignKey("evaluation_runs.id"),
            index=True,
            nullable=False,
        ),
        Column("case_id", String, nullable=False),
        Column("index", Integer, nullable=False),
        Column("category", String, nullable=True),
        Column("prompt", Text, nullable=False),
        Column("response", Text, nullable=True),
        Column("finish_reason", String, nullable=True),
        Column("error_code", String, nullable=True),
        Column("error_message", Text, nullable=True),
        Column("state", String, nullable=False),
        Column("request_started_at", Float, nullable=True),
        Column("ttft_seconds", Float, nullable=True),
        Column("completion_seconds", Float, nullable=True),
        Column("generation_tps", Float, nullable=True),
        Column("generation_tps_source", String, nullable=True),
        Column("prompt_tokens", Integer, nullable=True),
        Column("completion_tokens", Integer, nullable=True),
        Column("token_source", String, nullable=True),
    )
    op.create_table(
        "manual_scores",
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column(
            "result_id",
            Integer,
            ForeignKey("evaluation_results.id"),
            index=True,
            unique=True,
            nullable=False,
        ),
        Column("accuracy", Integer, nullable=True),
        Column("completeness", Integer, nullable=True),
        Column("instruction_following", Integer, nullable=True),
        Column("appropriate_judgment", Integer, nullable=True),
        Column("refusal", Boolean, nullable=False),
        Column("hallucination", Boolean, nullable=False),
        Column("truncation", Boolean, nullable=False),
        Column("unsafe_output", Boolean, nullable=False),
        Column("failed", Boolean, nullable=False),
        Column("note", Text, nullable=True),
    )
    op.create_index("ix_test_suites_name", "test_suites", ["name"], unique=True)
    op.create_index(
        "ix_evaluation_runs_profile_key",
        "evaluation_runs",
        ["profile_key"],
        unique=False,
    )


def downgrade() -> None:
    for table in (
        "manual_scores",
        "evaluation_results",
        "evaluation_runs",
        "test_suites",
        "model_profiles",
    ):
        op.drop_table(table)
