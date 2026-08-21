import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.metrics import EvalMetrics
from app.core.model_profiles import settings_for_profile
from app.db.models import EvaluationImage, EvaluationResult, EvaluationRun, ManualScore
from app.evaluations import runner, suite_loader
from app.evaluations.schemas import (
    EvalErrorPayload,
    EvalImageAttachment,
    EvalMetricsPayload,
    EvalProgressPayload,
    EvalResultEvent,
    EvalResultPayload,
    EvalRunDonePayload,
    EvalRunSummary,
)
from app.schemas.chat import ChatMessage, ChatStreamRequest, ReasoningEffort

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StreamEvent(BaseModel):
    event: str
    payload: BaseModel


def _error_payload(code: str | None, message: str | None) -> EvalErrorPayload | None:
    if not code or message is None:
        return None
    return EvalErrorPayload(code=code, message=message)


def _metrics_payload(metrics: EvalMetrics) -> EvalMetricsPayload | None:
    if metrics.request_started_at is None:
        return None
    return EvalMetricsPayload(
        ttft_seconds=metrics.ttft_seconds,
        completion_seconds=metrics.completion_seconds,
        generation_tps=metrics.generation_tps,
        generation_tps_source=metrics.generation_tps_source,
        prompt_tokens=metrics.prompt_tokens,
        completion_tokens=metrics.completion_tokens,
        token_source=metrics.token_source,
        request_started_at=metrics.request_started_at,
    )


def _result_metrics(result: EvaluationResult) -> EvalMetricsPayload | None:
    if result.request_started_at is None:
        return None
    return EvalMetricsPayload(
        ttft_seconds=result.ttft_seconds,
        completion_seconds=result.completion_seconds,
        generation_tps=result.generation_tps,
        generation_tps_source=result.generation_tps_source,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        token_source=result.token_source,
        request_started_at=result.request_started_at,
    )


def _result_payload(result: EvaluationResult) -> EvalResultPayload:
    return EvalResultPayload(
        case_id=result.case_id,
        category=result.category,
        prompt=result.prompt,
        response=result.response,
        finish_reason=result.finish_reason,
        error=_error_payload(result.error_code, result.error_message),
        metrics=_result_metrics(result),
        state=result.state,
    )


def _stream_payload(result: EvaluationResult, run_summary: EvalRunSummary) -> EvalResultEvent:
    return EvalResultEvent(
        run_id=run_summary.id,
        case_index=result.index,
        total=run_summary.total_cases,
        case_id=result.case_id,
        state=result.state,
        response=result.response,
        finish_reason=result.finish_reason,
        error=_error_payload(result.error_code, result.error_message),
        metrics=_result_metrics(result),
    )


def _reset_and_seed(session: Session, run: EvaluationRun, loaded: suite_loader.LoadedSuite) -> None:
    attachments = _attachments_by_case(run)
    for index, case in enumerate(loaded.enabled_cases(), start=1):
        result = EvaluationResult(
            case_id=case.id,
            index=index,
            category=case.category,
            prompt=case.prompt,
            input_type=case.input_type,
            case_type=case.case_type,
            state="created",
        )
        if case.is_image:
            attachment = attachments.get(case.id)
            if attachment is not None:
                result.image_data = attachment.bytes
                result.image_media_type = attachment.media_type
                result.image_source = attachment.source
                result.image_data_url = attachment.data_url
        run.results.append(result)
    session.flush()
    for result in run.results:
        session.add(ManualScore(result_id=result.id))
    session.commit()


def _attachments_by_case(run: EvaluationRun) -> dict[str, EvaluationImage]:
    return {image.case_id: image for image in run.images}


def _read_fixture(suites_dir: str, filename: str) -> bytes:
    import os

    path = os.path.join(suites_dir, filename)
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"the fixture image for this case is missing: {filename}",
        ) from exc


def _run_image_from_data_url(data_url: str) -> bytes:
    import base64

    if not data_url.startswith("data:"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the uploaded image must be provided as a data URL.",
        )
    _, _, payload = data_url.partition(":")
    media_type, _, fragment = payload.partition(";")
    if not fragment.startswith("base64"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the uploaded image must use base64 data URL transport.",
        )
    candidate = fragment[len("base64") :]
    if candidate.startswith(","):
        candidate = candidate[1:]
    candidate = candidate.strip()
    candidate += "=" * (-len(candidate) % 4)
    try:
        raw = base64.b64decode(candidate, validate=False)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the uploaded image data is not valid base64.",
        ) from exc
    if media_type and "image/" not in media_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the uploaded image must use an image media type.",
        )
    return raw


def _find_case(loaded: suite_loader.LoadedSuite, case_id: str) -> suite_loader.LoadedCase | None:
    for case in loaded.all_cases():
        if case.id == case_id:
            return case
    return None


def assert_image_attachments(
    images: list[EvalImageAttachment], loaded: suite_loader.LoadedSuite
) -> None:
    seen: set[str] = set()
    for attachment in images:
        case = _find_case(loaded, attachment.case_id)
        if case is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"no case '{attachment.case_id}' accepts an image attachment.",
            )
        if case.disabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"case '{case.id}' is disabled and cannot carry an image.",
            )
        if not case.is_image:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"case '{case.id}' is a text case and cannot carry an image.",
            )
        if case.id in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"case '{case.id}' has more than one image attachment.",
            )
        seen.add(case.id)


def store_run_images(
    session: Session,
    run: EvaluationRun,
    loaded: suite_loader.LoadedSuite,
    attachments: list[EvalImageAttachment],
    suites_dir: str,
) -> None:
    from app.image import validation

    by_case = {attachment.case_id: attachment for attachment in attachments}
    for case in loaded.enabled_image_cases():
        attachment = by_case.get(case.id)
        if attachment is not None:
            raw = _run_image_from_data_url(attachment.data_url)
            source = "attachment"
        elif case.image is not None:
            raw = _read_fixture(suites_dir, case.image.file)
            source = "fixture"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"no image was provided for image case '{case.id}'.",
            )
        try:
            image = validation.prepare_image(raw)
        except validation.MediaValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        session.add(
            EvaluationImage(
                run_id=run.id,
                case_id=case.id,
                media_type=image.media_type,
                source=source,
                data_url=image.data_url,
                bytes=image.bytes,
            )
        )


def _ensure_result_row(
    session: Session,
    run: EvaluationRun,
    case: suite_loader.LoadedCase,
    index: int,
) -> EvaluationResult:
    result = session.query(EvaluationResult).filter_by(run_id=run.id, case_id=case.id).one_or_none()
    if result is None:
        result = EvaluationResult(
            run_id=run.id,
            case_id=case.id,
            index=index,
            category=case.category,
            prompt=case.prompt,
            state="created",
        )
        session.add(result)
        session.flush()
        session.add(ManualScore(result_id=result.id))
    return result


def _outcome_payload(outcome: runner.EvalCaseOutcome) -> EvalResultPayload:
    return EvalResultPayload(
        case_id=outcome.case.id,
        category=outcome.case.category,
        prompt=outcome.case.prompt,
        response=outcome.response,
        finish_reason=outcome.finish_reason,
        error=_error_payload(
            outcome.error.code if outcome.error else None,
            outcome.error.message if outcome.error else None,
        ),
        metrics=_metrics_payload(outcome.metrics),
        state="completed" if outcome.error is None else "failed",
    )


def load_run_suite(run: EvaluationRun, suites_dir: str) -> suite_loader.LoadedSuite:
    """Load the suite that governs ``run``, preferring the stored snapshot.

    A run executes the immutable snapshot saved when it was created, so editing
    the suite on disk after the run does not change what it runs. Only a run
    with no snapshot (legacy data) falls back to the on-disk file, and an edit
    to that file still surfaces as a 409.
    """
    if run.suite_snapshot:
        return suite_loader.parse_snapshot(run.suite_name, run.suite_snapshot)
    return suite_loader.load_suite(run.suite_name, suites_dir)


def build_run_request(
    run: EvaluationRun, case: suite_loader.LoadedCase, result_row: EvaluationResult
) -> ChatStreamRequest:
    return ChatStreamRequest(
        model_profile=run.profile_key,
        messages=[ChatMessage(role="user", content=case.prompt)],
        temperature=run.temperature,
        max_tokens=run.max_tokens,
        reasoning_effort=cast(ReasoningEffort, run.reasoning_effort),
        image_url=result_row.image_data_url,
    )


def load_run_summary(run: EvaluationRun) -> EvalRunSummary:
    completed_cases = sum(1 for row in run.results if row.state == "completed")
    total_cases = len(run.results)
    return EvalRunSummary(
        id=run.id,
        suite_name=run.suite_name,
        suite_version=run.suite_version,
        suite_hash=run.suite_hash,
        profile_label=run.profile_label,
        model_id=run.model_id,
        modality=run.modality,
        state=run.state,
        created_at=run.created_at,
        completed_at=run.completed_at,
        completed_cases=completed_cases,
        total_cases=total_cases,
    )


async def orchestrate_suite(
    run: EvaluationRun,
    session: Session,
    *,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    suites_dir: str | None = None,
) -> AsyncIterator[StreamEvent]:
    from app.core.config import load_settings

    if suites_dir is None:
        suites_dir = load_settings().evaluations_dir

    try:
        loaded = load_run_suite(run, suites_dir)
    except suite_loader.SuiteNotFoundError:
        run.state = "failed"
        run.completed_at = _utcnow()
        session.commit()
        yield StreamEvent(
            event="done",
            payload=EvalRunDonePayload(run_id=run.id, state="failed"),
        )
        return

    if loaded.hash != run.suite_hash:
        run.state = "failed"
        run.completed_at = _utcnow()
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Suite '{run.suite_name}' version {loaded.version} no longer matches the "
                f"snapshot recorded for run {run.id} (expected hash {run.suite_hash})."
            ),
        )

    if not run.results:
        _reset_and_seed(session, run, loaded)
    run.state = "running"
    session.commit()

    enabled = loaded.enabled_cases()
    total = len(enabled)

    for index, case in enumerate(enabled, start=1):
        result_row = _ensure_result_row(session, run, case, index)
        result_row.state = "in_progress"
        session.commit()
        yield StreamEvent(
            event="progress",
            payload=EvalProgressPayload(
                run_id=run.id,
                case_index=index,
                total=total,
                case_id=case.id,
                status="in_progress",
            ),
        )

        outcome = await runner.run_case(
            case,
            settings_for_profile(settings, run.profile_key),
            build_run_request(run, case, result_row),
            transport=transport,
        )
        result_row.response = outcome.response
        result_row.finish_reason = outcome.finish_reason
        result_row.error_code = outcome.error.code if outcome.error else None
        result_row.error_message = outcome.error.message if outcome.error else None
        result_row.request_started_at = outcome.metrics.request_started_at
        result_row.ttft_seconds = outcome.metrics.ttft_seconds
        result_row.completion_seconds = outcome.metrics.completion_seconds
        result_row.generation_tps = outcome.metrics.generation_tps
        result_row.generation_tps_source = outcome.metrics.generation_tps_source
        result_row.prompt_tokens = outcome.metrics.prompt_tokens
        result_row.completion_tokens = outcome.metrics.completion_tokens
        result_row.token_source = outcome.metrics.token_source
        result_row.state = "completed" if outcome.error is None else "failed"
        session.commit()

        yield StreamEvent(
            event="result",
            payload=_stream_payload(result_row, load_run_summary(run)),
        )

    run.state = "completed" if not any(row.state == "failed" for row in run.results) else "failed"
    run.completed_at = _utcnow()
    session.commit()

    yield StreamEvent(
        event="done",
        payload=EvalRunDonePayload(run_id=run.id, state=run.state),
    )
