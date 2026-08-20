from dataclasses import dataclass

from app.model_provider.base import ProviderUsage
from app.schemas.chat import ChatMetrics, TokenSource

SECONDS_PRECISION = 3


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


def _token_source(usage: ProviderUsage | None) -> TokenSource | None:
    if usage is not None and usage.completion_tokens is not None and usage.completion_tokens > 0:
        return "upstream"
    return None


@dataclass
class EvalMetrics:
    """Performance measurements for a single evaluation case."""

    ttft_seconds: float | None
    completion_seconds: float | None
    generation_tps: float | None
    generation_tps_source: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    token_source: str | None
    request_started_at: float | None


def build_chat_metrics(
    started: float,
    completed: float,
    first_chunk_at: float | None,
    usage: ProviderUsage | None,
    *,
    reasoning_active: bool,
) -> ChatMetrics:
    ttft = first_chunk_at - started if first_chunk_at is not None else None
    total = completed - started
    generation_tps = None if reasoning_active else _generation_tps(usage, ttft, total)
    token_source = _token_source(usage)
    return ChatMetrics(
        ttft_seconds=None if ttft is None else round(ttft, SECONDS_PRECISION),
        completion_seconds=round(total, SECONDS_PRECISION),
        generation_tps=generation_tps,
        token_source=token_source,
    )


def build_eval_metrics(
    started: float,
    first_chunk_at: float | None,
    completed: float,
    usage: ProviderUsage | None,
    *,
    reasoning_active: bool,
    request_started_epoch: float,
) -> EvalMetrics:
    ttft = first_chunk_at - started if first_chunk_at is not None else None
    total = completed - started
    generation_tps = None if reasoning_active else _generation_tps(usage, ttft, total)
    token_source = _token_source(usage)
    return EvalMetrics(
        ttft_seconds=None if ttft is None else round(ttft, SECONDS_PRECISION),
        completion_seconds=round(total, SECONDS_PRECISION),
        generation_tps=generation_tps,
        generation_tps_source=None if generation_tps is None else token_source,
        prompt_tokens=None if usage is None else usage.prompt_tokens,
        completion_tokens=None if usage is None else usage.completion_tokens,
        token_source=token_source,
        request_started_at=request_started_epoch,
    )
