"""Regression tests for the milestone 3 schema upgrade migration.

These exercise the alembic path that lets a database created before
``evaluation_runs.suite_snapshot`` and ``manual_scores.format_failure`` were
added upgrade to the current schema, and that ``--sql`` rendering works.
"""

from pathlib import Path

import pytest
from alembic.command import check, downgrade, upgrade
from alembic.config import Config
from sqlalchemy import create_engine, text

ALMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
ALMBIC_DIR = ALMBIC_INI.parent / "alembic"


def _alembic_config(db_url: str) -> Config:
    config = Config(file_=str(ALMBIC_INI))
    config.set_main_option("script_location", str(ALMBIC_DIR))
    return config


def _columns(db_url: str, table: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
            return {row[1] for row in rows}
    finally:
        engine.dispose()


def _seed_m3_row(db_url: str) -> None:
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            run_id = conn.execute(
                text(
                    "INSERT INTO evaluation_runs "
                    "(suite_name, suite_version, suite_hash, profile_key, "
                    "profile_label, reasoning_effort, modality, state, "
                    "created_at, updated_at) "
                    "VALUES ('demo', '1', 'hash', 'default', 'default', "
                    "'off', 'text', 'running', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            ).lastrowid
            result_id = conn.execute(
                text(
                    "INSERT INTO evaluation_results "
                    "(run_id, case_id, `index`, prompt, state) "
                    "VALUES (:run_id, 'demo-1', 1, 'the prompt', 'in_progress')"
                ),
                {"run_id": run_id},
            ).lastrowid
            conn.execute(
                text(
                    "INSERT INTO manual_scores "
                    "(result_id, accuracy, refusal, hallucination, truncation, "
                    "unsafe_output, failed) "
                    "VALUES (:rid, 1, 0, 0, 0, 0, 1)"
                ),
                {"rid": result_id},
            )
            conn.commit()
    finally:
        engine.dispose()


def test_m3_database_upgrades_to_current_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    config = _alembic_config(db_url)

    # A database built by milestone 3 is stamped at 1_initial and predates the
    # suite_snapshot / format_failure columns.
    upgrade(config, "1_initial")
    assert "suite_snapshot" not in _columns(db_url, "evaluation_runs")
    score_before = _columns(db_url, "manual_scores")
    assert "failed" in score_before
    assert "format_failure" not in score_before

    _seed_m3_row(db_url)

    # The only revision between 1_initial and head transforms M3 to the current
    # schema.
    upgrade(config, "head")
    assert "suite_snapshot" in _columns(db_url, "evaluation_runs")
    score_after = _columns(db_url, "manual_scores")
    assert "format_failure" in score_after
    assert "failed" not in score_after

    # The score row survives the column rename.
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT format_failure FROM manual_scores WHERE result_id = 1")
            ).one()
            assert row[0] == 1
    finally:
        engine.dispose()


def test_upgrade_head_sql_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_url = f"sqlite:///{tmp_path / 'render.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    config = _alembic_config(db_url)

    upgrade(config, "1_initial")
    upgrade(config, "head", sql=True)

    rendered = capsys.readouterr().out
    assert "ADD COLUMN" in rendered
    assert "RENAME COLUMN failed TO format_failure" in rendered


def test_fresh_upgrade_matches_orm_and_downgrades_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    config = _alembic_config(db_url)

    upgrade(config, "head")
    check(config)

    downgrade(config, "base")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            tables = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name != 'sqlite_sequence'"
                )
            ).scalars()
            assert set(tables) == {"alembic_version"}
    finally:
        engine.dispose()
