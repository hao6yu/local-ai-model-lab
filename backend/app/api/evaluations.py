import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Literal, cast

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import app.evaluations.orchestrator as orchestrator
from app.core.config import Settings
from app.core.model_profiles import (
    ModelProfile,
    ModelProfileError,
    load_model_profiles,
    select_model_profile,
)
from app.db.models import EvaluationResult, EvaluationRun, ManualScore
from app.db.session import session_scope
from app.evaluations import suite_loader
from app.evaluations.comparison import (
    ComparisonError,
    assert_compatible,
    build_comparison_response,
    render_comparison_json,
    render_comparison_markdown,
)
from app.evaluations.orchestrator import (
    _error_payload,
    _result_metrics,
    load_run_summary,
)
from app.evaluations.schemas import (
    ComparisonResponse,
    EvalResultWithScores,
    EvalRunDetail,
    EvalRunSummary,
    EvalScorePayload,
    EvaluationRunRequest,
    ManualScoreUpdate,
    SuiteListItem,
)
from app.schemas.chat import ReasoningEffort

router = APIRouter(prefix="/api")

STREAM_MEDIA_TYPE = "text/event-stream"


def _sse_event(event: str, payload: BaseModel) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


def _now() -> datetime:
    return datetime.now(UTC)


def _resolve_profile(settings: Settings, profile_label: str | None) -> ModelProfile:
    profiles = load_model_profiles(settings)
    selected = select_model_profile(settings)
    if profile_label:
        for profile in profiles:
            if profile.profile_label == profile_label or profile.model_id == profile_label:
                return profile
        raise ModelProfileError(f"unknown model profile: {profile_label}")
    return selected


def _list_suites(suites_dir: str) -> list[SuiteListItem]:
    suites: list[SuiteListItem] = []
    if not os.path.isdir(suites_dir):
        return suites
    for filename in sorted(os.listdir(suites_dir)):
        if not filename.endswith(".json"):
            continue
        name = filename[: -len(".json")]
        try:
            loaded = suite_loader.load_suite(name, suites_dir)
        except suite_loader.SuiteValidationError:
            continue
        suites.append(
            SuiteListItem(
                name=loaded.name,
                version=loaded.version,
                hash=loaded.hash,
                case_count=loaded.case_count,
                source_path=loaded.source_path,
            ),
        )
    return suites


def _score_payload(score: ManualScore | None) -> EvalScorePayload | None:
    if score is None:
        return None
    return EvalScorePayload(
        accuracy=score.accuracy,
        completeness=score.completeness,
        instruction_following=score.instruction_following,
        appropriate_judgment=score.appropriate_judgment,
        refusal=score.refusal,
        hallucination=score.hallucination,
        truncation=score.truncation,
        unsafe_output=score.unsafe_output,
        format_failure=score.format_failure,
        note=score.note,
    )


def _result_with_scores(result: EvaluationResult) -> EvalResultWithScores:
    return EvalResultWithScores(
        id=result.id,
        case_id=result.case_id,
        index=result.index,
        category=result.category,
        prompt=result.prompt,
        response=result.response,
        finish_reason=result.finish_reason,
        error=_error_payload(result.error_code, result.error_message),
        metrics=_result_metrics(result),
        state=result.state,
        scores=_score_payload(result.scores),
    )


def _run_detail(run: EvaluationRun) -> EvalRunDetail:
    summary: EvalRunSummary = load_run_summary(run)
    return EvalRunDetail(
        id=summary.id,
        suite_name=summary.suite_name,
        suite_version=summary.suite_version,
        suite_hash=summary.suite_hash,
        profile_label=summary.profile_label,
        model_id=summary.model_id,
        suite_snapshot=run.suite_snapshot,
        modality=summary.modality,
        state=summary.state,
        created_at=summary.created_at,
        completed_at=summary.completed_at,
        completed_cases=summary.completed_cases,
        total_cases=summary.total_cases,
        reasoning_effort=cast(ReasoningEffort, run.reasoning_effort),
        temperature=run.temperature,
        max_tokens=run.max_tokens,
        context_window=run.context_window,
        notes=run.notes,
        results=[_result_with_scores(row) for row in run.results],
    )


def _engine(request: Request) -> Engine | None:
    return cast(Engine | None, getattr(request.app.state, "engine", None))


@router.get("/suites")
def list_suites(request: Request) -> list[SuiteListItem]:
    settings: Settings = request.app.state.settings
    return _list_suites(settings.evaluations_dir)


@router.post("/evaluation-runs")
def create_evaluation_run(request: Request, payload: EvaluationRunRequest) -> EvalRunDetail:
    settings: Settings = request.app.state.settings
    engine = _engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation persistence is not configured for this server.",
        )
    try:
        loaded = suite_loader.load_suite(payload.suite_name, settings.evaluations_dir)
    except suite_loader.SuiteNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Suite '{payload.suite_name}' was not found."
        ) from None
    if loaded.version != payload.suite_version:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Suite '{payload.suite_name}' is at version {loaded.version}, "
                f"not the requested version {payload.suite_version}."
            ),
        )
    try:
        profile = _resolve_profile(settings, payload.profile_label)
    except ModelProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with session_scope(engine) as session:
        run = EvaluationRun(
            suite_name=payload.suite_name,
            suite_version=loaded.version,
            suite_hash=loaded.hash,
            profile_key=profile.key,
            profile_label=payload.profile_label or profile.profile_label or profile.key,
            model_id=payload.model_id or profile.model_id,
            context_window=payload.context_window or profile.context_window,
            reasoning_effort=payload.reasoning_effort,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            modality=payload.modality,
            suite_snapshot=loaded.raw,
            notes=payload.notes,
            state="created",
        )
        session.add(run)
        session.commit()
        return _run_detail(run)


@router.post("/evaluation-runs/{run_id}/start")
async def start_evaluation_run(request: Request, run_id: int) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    engine = _engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation persistence is not configured for this server.",
        )
    transport: httpx.AsyncBaseTransport | None = request.app.state.upstream_transport
    generation_lock: asyncio.Lock = request.app.state.generation_lock
    with session_scope(engine) as session:
        run = _get_run(session, run_id)
        if run.state != "created":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Evaluation run {run_id} is in state '{run.state}'. "
                    f"Only a created run can be started."
                ),
            )
        try:
            loaded = orchestrator.load_run_suite(run, settings.evaluations_dir)
        except suite_loader.SuiteNotFoundError:
            run.state = "failed"
            run.completed_at = _now()
            session.commit()
            raise HTTPException(
                status_code=404,
                detail=f"Suite file '{run.suite_name}' is missing.",
            ) from None
        if loaded.hash != run.suite_hash:
            run.state = "failed"
            run.completed_at = _now()
            session.commit()
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Suite '{run.suite_name}' changed since run {run_id} "
                    f"was created. Start a new evaluation run."
                ),
            )
        if (_conflict := _active_run(session, run_id)) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Evaluation run {_conflict.id} is already running.",
            )
    return StreamingResponse(
        _start_stream_events(run_id, engine, settings, transport, generation_lock),
        media_type=STREAM_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/evaluation-runs")
def list_evaluation_runs(request: Request) -> list[EvalRunSummary]:
    engine = _engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation persistence is not configured for this server.",
        )
    with session_scope(engine) as session:
        runs = session.query(EvaluationRun).order_by(EvaluationRun.created_at.desc()).all()
        return [load_run_summary(run) for run in runs]


@router.get("/evaluation-runs/{run_id}")
def get_evaluation_run(request: Request, run_id: int) -> EvalRunDetail:
    engine = _engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation persistence is not configured for this server.",
        )
    with session_scope(engine) as session:
        run = _get_run(session, run_id)
        return _run_detail(run)


def _load_compatible_runs(
    session: Session,
    left: int,
    right: int,
) -> tuple[EvalRunDetail, EvalRunDetail]:
    left_run = _get_run(session, left)
    right_run = _get_run(session, right)
    left_detail = _run_detail(left_run)
    right_detail = _run_detail(right_run)
    try:
        assert_compatible(left_detail, right_detail)
    except ComparisonError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return left_detail, right_detail


@router.get("/comparisons")
def get_comparison(request: Request, left: int, right: int) -> ComparisonResponse:
    engine = _engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation persistence is not configured for this server.",
        )
    with session_scope(engine) as session:
        left_detail, right_detail = _load_compatible_runs(session, left, right)
    return build_comparison_response(left_detail, right_detail)


@router.get("/comparisons/export")
def get_comparison_export(
    request: Request,
    left: int,
    right: int,
    format: Literal["markdown", "json"] = Query("markdown"),
) -> Response:
    engine = _engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation persistence is not configured for this server.",
        )
    with session_scope(engine) as session:
        left_detail, right_detail = _load_compatible_runs(session, left, right)
    return _export_comparison(format, left_detail, right_detail)


def _export_comparison(
    format: str, left_detail: EvalRunDetail, right_detail: EvalRunDetail
) -> Response:
    if format == "json":
        content = render_comparison_json(left_detail, right_detail)
        media_type = "application/json"
        filename = "comparison.json"
    else:
        content = render_comparison_markdown(left_detail, right_detail)
        media_type = "text/markdown"
        filename = "comparison.md"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/results/{result_id}/score")
def patch_result_score(
    request: Request,
    result_id: int,
    payload: ManualScoreUpdate,
) -> EvalScorePayload:
    engine = _engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation persistence is not configured for this server.",
        )
    with session_scope(engine) as session:
        result = _get_result(session, result_id)
        score = result.scores
        if score is None:
            score = ManualScore(result_id=result.id)
            session.add(score)
        score.accuracy = payload.accuracy
        score.completeness = payload.completeness
        score.instruction_following = payload.instruction_following
        score.appropriate_judgment = payload.appropriate_judgment
        score.refusal = payload.refusal
        score.hallucination = payload.hallucination
        score.truncation = payload.truncation
        score.unsafe_output = payload.unsafe_output
        score.format_failure = payload.format_failure
        score.note = payload.note
        session.commit()
        score_payload = _score_payload(score)
        assert score_payload is not None
        return score_payload


async def _start_stream_events(
    run_id: int,
    engine: Engine,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
    generation_lock: asyncio.Lock,
) -> AsyncIterator[str]:
    async with generation_lock:
        with session_scope(engine) as session:
            run = _get_run(session, run_id)
            async for event in orchestrator.orchestrate_suite(
                run,
                session,
                settings=settings,
                transport=transport,
                suites_dir=settings.evaluations_dir,
            ):
                yield _sse_event(event.event, event.payload)


def _get_run(session: Session, run_id: int) -> EvaluationRun:
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation run {run_id} was not found.")
    return run


def _get_result(session: Session, result_id: int) -> EvaluationResult:
    result = session.get(EvaluationResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Result {result_id} was not found.")
    return result


def _active_run(session: Session, exclude_run_id: int) -> EvaluationRun | None:
    return (
        session.query(EvaluationRun)
        .filter(EvaluationRun.state == "running", EvaluationRun.id != exclude_run_id)
        .first()
    )
