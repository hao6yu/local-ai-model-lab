import time
from dataclasses import dataclass

import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.core.metrics import EvalMetrics, build_eval_metrics
from app.evaluations import suite_loader
from app.evaluations.schemas import EvalErrorPayload
from app.model_provider import openai_compatible
from app.model_provider.base import (
    ProviderChunk,
    ProviderError,
    ProviderResult,
)
from app.schemas.chat import ChatMessage, ChatStreamRequest


@dataclass
class EvalCaseOutcome:
    case: suite_loader.LoadedCase
    response: str
    finish_reason: str | None
    error: EvalErrorPayload | None
    metrics: EvalMetrics


def _case_error(exc: Exception) -> EvalErrorPayload:
    code = "upstream_error" if isinstance(exc, HTTPException) else "evaluation_error"
    message = str(exc) or f"The evaluation case failed: {exc.__class__.__name__}"
    return EvalErrorPayload(code=code, message=message)


async def run_case(
    case: suite_loader.LoadedCase,
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    request_started_epoch: float | None = None,
) -> EvalCaseOutcome:
    started = time.perf_counter()
    request_started_epoch = (
        request_started_epoch if request_started_epoch is not None else time.time()
    )
    started_epoch = request_started_epoch
    first_chunk_at: float | None = None
    chunks: list[str] = []
    finish_reason: str | None = None
    usage = None
    saw_result = False
    error: EvalErrorPayload | None = None

    request = ChatStreamRequest(
        model_profile=None,
        messages=[ChatMessage(role="user", content=case.prompt)],
        reasoning_effort="off",
    )

    async for event in openai_compatible.stream_chat(settings, request, transport=transport):
        if isinstance(event, ProviderChunk):
            if not event.content:
                continue
            if first_chunk_at is None:
                first_chunk_at = time.perf_counter()
            chunks.append(event.content)
        elif isinstance(event, ProviderResult):
            saw_result = True
            finish_reason = event.finish_reason
            usage = event.usage
        elif isinstance(event, ProviderError):
            error = EvalErrorPayload(code=event.code, message=event.message)
            break

    completed = time.perf_counter()
    if error is None and not saw_result:
        error = EvalErrorPayload(
            code="malformed_stream",
            message="The model endpoint closed the stream without responding.",
        )

    metrics = build_eval_metrics(
        started,
        first_chunk_at,
        completed,
        usage,
        reasoning_active=False,
        request_started_epoch=started_epoch,
    )
    return EvalCaseOutcome(
        case=case,
        response="".join(chunks),
        finish_reason=finish_reason,
        error=error,
        metrics=metrics,
    )
