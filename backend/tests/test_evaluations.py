import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fake_upstream import (
    FakeUpstream,
    chunk_frame,
    finish_frame,
    sse_done,
    usage_frame,
)
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import app.evaluations.orchestrator as orchestrator
from app.core.metrics import EvalMetrics
from app.db.models import EvaluationResult, EvaluationRun, ManualScore
from app.db.session import init_schema, session_scope
from app.evaluations import runner, suite_loader
from app.evaluations.orchestrator import StreamEvent
from app.evaluations.runner import EvalCaseOutcome
from app.evaluations.schemas import (
    EvalProgressPayload,
    EvalResultEvent,
    EvalRunDonePayload,
    ManualScoreUpdate,
)
from conftest import make_settings


def _happy_frames() -> list[str]:
    return [
        chunk_frame("Hello"),
        chunk_frame(" world"),
        finish_frame("stop"),
        usage_frame(4, 12),
        sse_done(),
    ]


def _write_suite(path: Path, *, disabled: list[int] | None = None) -> None:
    active: set[int] = set(disabled or [])
    cases = [
        {
            "id": "u1",
            "category": "categorized",
            "prompt": "hello",
            "disabled": 1 in active,
        },
        {"id": "u2", "category": "categorized", "prompt": "world"},
        {"id": "u3", "category": "categorized", "prompt": "again", "disabled": True},
    ]
    path.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")


def _sqlite_engine(tmp_path: Path) -> Engine:
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_schema(engine)
    return engine


def _seed_run(session: Session, name: str, case_hash: str) -> EvaluationRun:
    run = EvaluationRun(
        suite_name=name,
        suite_version="1",
        suite_hash=case_hash,
        profile_key="default",
        profile_label="default",
        state="created",
    )
    session.add(run)
    session.commit()
    return run


def _collect(
    run_id: int,
    engine: Engine,
    *,
    suites_dir: str,
    transport: httpx.AsyncBaseTransport | None,
) -> list[StreamEvent]:
    events: list[StreamEvent] = []

    async def _run() -> None:
        with session_scope(engine) as session:
            run = session.get(EvaluationRun, run_id)
            if run is None:
                return
            async for event in orchestrator.orchestrate_suite(
                run,
                session,
                settings=make_settings(),
                suites_dir=suites_dir,
                transport=transport,
            ):
                events.append(event)

    asyncio.run(_run())
    return events


async def _run_case(fake: FakeUpstream, case: suite_loader.LoadedCase) -> EvalCaseOutcome:
    from app.schemas.chat import ChatMessage, ChatStreamRequest

    request = ChatStreamRequest(
        model_profile="default",
        messages=[ChatMessage(role="user", content=case.prompt)],
    )
    return await runner.run_case(case, make_settings(), request, transport=fake.transport)


def test_run_case_records_response_and_metrics() -> None:
    fake = FakeUpstream(frames=_happy_frames())
    case = suite_loader.LoadedCase("u1", "categorized", "hello", [], False)

    outcome = asyncio.run(_run_case(fake, case))

    assert outcome.response == "Hello world"
    assert outcome.finish_reason == "stop"
    assert outcome.error is None
    assert isinstance(outcome.metrics, EvalMetrics)
    assert outcome.metrics.prompt_tokens == 4
    assert outcome.metrics.completion_tokens == 12
    assert outcome.metrics.token_source == "upstream"
    assert outcome.metrics.request_started_at is not None
    assert fake.state.frames_delivered > 0


def test_run_case_reports_upstream_error_without_reraising() -> None:
    fake = FakeUpstream(status=400, error_response=b'{"error": {"message": "bad request"}}')
    case = suite_loader.LoadedCase("u1", "categorized", "hello", [], False)

    outcome = asyncio.run(_run_case(fake, case))

    assert outcome.error is not None
    assert outcome.error.code == "upstream_error"
    assert outcome.error.message != ""
    assert outcome.response == ""
    assert outcome.metrics is not None


def test_orchestrator_runs_enabled_cases_and_skips_disabled(tmp_path: Path) -> None:
    suite_file = tmp_path / "demo-v1.json"
    _write_suite(suite_file)
    case_hash = suite_loader.hash_bytes(suite_file.read_bytes())
    engine = _sqlite_engine(tmp_path)

    with session_scope(engine) as session:
        run = _seed_run(session, "demo-v1", case_hash)
        run_id = run.id

    events = _collect(
        run_id,
        engine,
        suites_dir=str(tmp_path),
        transport=FakeUpstream(frames=_happy_frames()).transport,
    )

    kinds = [event.event for event in events]
    assert kinds == ["progress", "result", "progress", "result", "done"]
    progress_payloads = [
        payload
        for payload in [event.payload for event in events]
        if isinstance(payload, EvalProgressPayload)
    ]
    result_payloads = [
        payload
        for payload in [event.payload for event in events]
        if isinstance(payload, EvalResultEvent)
    ]
    done_payloads = [
        payload
        for payload in [event.payload for event in events]
        if isinstance(payload, EvalRunDonePayload)
    ]

    assert [payload.case_id for payload in progress_payloads] == ["u1", "u2"]
    for payload in progress_payloads:
        assert payload.total == 2
    assert [payload.case_id for payload in result_payloads] == ["u1", "u2"]
    for rp in result_payloads:
        assert rp.state == "completed"
        assert rp.response == "Hello world"
        assert rp.metrics is not None
        assert rp.metrics.prompt_tokens == 4
        assert rp.metrics.completion_tokens == 12
    assert len(done_payloads) == 1
    assert done_payloads[0].state == "completed"


def test_orchestrator_seeds_two_results_each_with_a_score(tmp_path: Path) -> None:
    suite_file = tmp_path / "demo-v1.json"
    _write_suite(suite_file)
    case_hash = suite_loader.hash_bytes(suite_file.read_bytes())
    engine = _sqlite_engine(tmp_path)

    with session_scope(engine) as session:
        run = _seed_run(session, "demo-v1", case_hash)
        run_id = run.id

    _collect(
        run_id,
        engine,
        suites_dir=str(tmp_path),
        transport=FakeUpstream(frames=_happy_frames()).transport,
    )

    with session_scope(engine) as session:
        rows = session.scalars(select(EvaluationResult)).all()
        case_ids = sorted(row.case_id for row in rows)
        assert case_ids == ["u1", "u2"]
        assert "u3" not in case_ids
        for row in rows:
            assert row.state == "completed"
            assert isinstance(row.scores, ManualScore)
        assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 2
        assert session.scalar(select(func.count()).select_from(ManualScore)) == 2


def test_orchestrator_persists_across_restart_without_duplicates(tmp_path: Path) -> None:
    suite_file = tmp_path / "demo-v1.json"
    _write_suite(suite_file)
    case_hash = suite_loader.hash_bytes(suite_file.read_bytes())
    engine = _sqlite_engine(tmp_path)

    with session_scope(engine) as session:
        run = _seed_run(session, "demo-v1", case_hash)
        run_id = run.id

    events = _collect(
        run_id,
        engine,
        suites_dir=str(tmp_path),
        transport=FakeUpstream(frames=_happy_frames()).transport,
    )

    with session_scope(engine) as session:
        rows = session.scalars(select(EvaluationResult)).all()
        assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 2
        assert session.scalar(select(func.count()).select_from(ManualScore)) == 2
        assert [row.case_id for row in rows] == ["u1", "u2"]
        assert all(row.state == "completed" for row in rows)
        result_events = [
            payload
            for payload in [event.payload for event in events]
            if isinstance(payload, EvalResultEvent)
        ]
        assert [payload.state for payload in result_events] == ["completed", "completed"]


def test_orchestrator_rejects_suite_hash_mismatch(tmp_path: Path) -> None:
    suite_file = tmp_path / "demo-v1.json"
    _write_suite(suite_file)
    engine = _sqlite_engine(tmp_path)

    with session_scope(engine) as session:
        run = _seed_run(session, "demo-v1", "totally-different-hash")
        run_id = run.id

    with pytest.raises(HTTPException) as exc_info:
        _collect(
            run_id,
            engine,
            suites_dir=str(tmp_path),
            transport=FakeUpstream(frames=_happy_frames()).transport,
        )
    assert exc_info.value.status_code == 409


def test_orchestrator_handles_missing_suite(tmp_path: Path) -> None:
    engine = _sqlite_engine(tmp_path)

    with session_scope(engine) as session:
        run = _seed_run(session, "does-not-exist", "whatever")
        run_id = run.id

    events = _collect(run_id, engine, suites_dir=str(tmp_path), transport=None)

    with session_scope(engine) as session:
        refreshed = session.get(EvaluationRun, run_id)
        assert refreshed is not None
        assert refreshed.state == "failed"
        assert refreshed.completed_at is not None
        assert events[-1].event == "done"
        assert isinstance(events[-1].payload, EvalRunDonePayload)
        assert events[-1].payload.state == "failed"


def test_orchestrator_records_failed_state_when_upstream_errors(tmp_path: Path) -> None:
    suite_file = tmp_path / "demo-v1.json"
    _write_suite(suite_file)
    case_hash = suite_loader.hash_bytes(suite_file.read_bytes())
    engine = _sqlite_engine(tmp_path)

    with session_scope(engine) as session:
        run = _seed_run(session, "demo-v1", case_hash)
        run_id = run.id

    _collect(
        run_id,
        engine,
        suites_dir=str(tmp_path),
        transport=FakeUpstream(
            status=400, error_response=b'{"error": {"message": "boom"}}'
        ).transport,
    )

    with session_scope(engine) as session:
        rows = session.scalars(select(EvaluationResult)).all()
        assert all(row.state == "failed" for row in rows)
        refreshed = session.get(EvaluationRun, run_id)
        assert refreshed is not None
        assert refreshed.state == "failed"


def test_load_run_summary_counts_completed_cases(tmp_path: Path) -> None:
    suite_file = tmp_path / "demo-v1.json"
    _write_suite(suite_file)
    case_hash = suite_loader.hash_bytes(suite_file.read_bytes())
    engine = _sqlite_engine(tmp_path)

    with session_scope(engine) as session:
        run = _seed_run(session, "demo-v1", case_hash)
        run_id = run.id

    _collect(
        run_id,
        engine,
        suites_dir=str(tmp_path),
        transport=FakeUpstream(frames=_happy_frames()).transport,
    )

    from app.evaluations.orchestrator import load_run_summary

    with session_scope(engine) as session:
        reloaded = session.get(EvaluationRun, run_id)
        assert reloaded is not None
        summary = load_run_summary(reloaded)
        assert summary.id == run_id
        assert summary.total_cases == 2
        assert summary.completed_cases == 2
        assert summary.state == "completed"


def test_manual_score_update_defaults() -> None:
    update = ManualScoreUpdate()
    assert update.accuracy is None
    assert update.format_failure is False
    assert update.note is None
