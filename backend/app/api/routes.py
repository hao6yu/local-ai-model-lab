import asyncio
import time
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core import runtime as runtime_service
from app.core.config import Settings
from app.core.health import Probe
from app.core.model_profiles import (
    ModelProfileError,
    load_model_profiles,
    select_model_profile,
    settings_for_profile,
)
from app.model_provider import ProviderChunk, ProviderResult, ProviderUsage, openai_compatible
from app.schemas.chat import (
    ChatChunkPayload,
    ChatDonePayload,
    ChatErrorPayload,
    ChatMetrics,
    ChatStreamRequest,
    ChatUsage,
)
from app.schemas.health import HealthResponse, ProfileHealth, UpstreamHealth
from app.schemas.runtime import RuntimeResponse

router = APIRouter(prefix="/api")

STREAM_MEDIA_TYPE = "text/event-stream"
SECONDS_PRECISION = 3


def _sse_event(event: str, payload: BaseModel) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    probe: Probe = request.app.state.probe_upstream
    profiles = load_model_profiles(settings)
    models = [_profile_health(probe, settings, profile.key) for profile in profiles]
    selected_key = select_model_profile(settings).key
    selected = next((entry for entry in models if entry.key == selected_key), models[0])
    return HealthResponse(
        portal="ok",
        model=UpstreamHealth(state=selected.state, detail=selected.detail),
        models=models,
    )


def _profile_health(probe: Probe, settings: Settings, key: str) -> ProfileHealth:
    health = probe(settings_for_profile(settings, key))
    return ProfileHealth(key=key, state=health.state, detail=health.detail)


@router.get("/runtime", response_model=RuntimeResponse)
def get_runtime(request: Request) -> RuntimeResponse:
    settings: Settings = request.app.state.settings
    return runtime_service.build_runtime(settings)


@router.post("/chat/stream")
async def post_chat_stream(request: Request, payload: ChatStreamRequest) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    transport: httpx.AsyncBaseTransport | None = request.app.state.upstream_transport
    generation_lock: asyncio.Lock = request.app.state.generation_lock
    try:
        selected_settings = settings_for_profile(settings, payload.model_profile)
    except ModelProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        _chat_stream_events(selected_settings, payload, transport, generation_lock),
        media_type=STREAM_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache"},
    )


async def _chat_stream_events(
    settings: Settings,
    payload: ChatStreamRequest,
    transport: httpx.AsyncBaseTransport | None,
    generation_lock: asyncio.Lock,
) -> AsyncIterator[str]:
    async with generation_lock:
        started = time.perf_counter()
        completed = started
        first_chunk_at: float | None = None
        result: ProviderResult | None = None

        streamer = openai_compatible.stream_chat(settings, payload, transport=transport)
        try:
            async for event in streamer:
                if isinstance(event, ProviderChunk):
                    if first_chunk_at is None:
                        first_chunk_at = time.perf_counter()
                    yield _sse_event("chunk", ChatChunkPayload(content=event.content))
                elif isinstance(event, ProviderResult):
                    completed = time.perf_counter()
                    result = event
                else:
                    completed = time.perf_counter()
                    yield _sse_event(
                        "error",
                        ChatErrorPayload(code=event.code, message=event.message),
                    )
        finally:
            await streamer.aclose()

        if result is None:
            return
        usage: ChatUsage | None = None
        if result.usage is not None:
            usage = ChatUsage(
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
            )
        metrics = _build_metrics(
            started,
            completed,
            first_chunk_at,
            result.usage,
            reasoning_active=payload.reasoning_effort != "off",
        )
        yield _sse_event(
            "done",
            ChatDonePayload(
                usage=usage,
                finish_reason=result.finish_reason,
                metrics=metrics,
            ),
        )


def _build_metrics(
    started: float,
    completed: float,
    first_chunk_at: float | None,
    usage: ProviderUsage | None,
    *,
    reasoning_active: bool,
) -> ChatMetrics:
    # When reasoning is active, the server-reported completion_tokens include
    # hidden reasoning tokens that are not part of the visible-token interval,
    # so a tokens/second figure would overstate generation speed. Report null.
    ttft = first_chunk_at - started if first_chunk_at is not None else None
    total = completed - started
    generation_tps = None if reasoning_active else _generation_tps(usage, ttft, total)
    return ChatMetrics(
        ttft_seconds=None if ttft is None else round(ttft, SECONDS_PRECISION),
        completion_seconds=round(total, SECONDS_PRECISION),
        generation_tps=generation_tps,
        token_source="upstream"
        if usage is not None and usage.completion_tokens is not None and usage.completion_tokens > 0
        else None,
    )


def _generation_tps(
    usage: ProviderUsage | None,
    ttft: float | None,
    total: float,
) -> float | None:
    if (
        usage is None
        or usage.completion_tokens is None
        or usage.completion_tokens <= 0
        or ttft is None
    ):
        return None
    span = total - ttft
    if span <= 0:
        return None
    return round(usage.completion_tokens / span, 1)
