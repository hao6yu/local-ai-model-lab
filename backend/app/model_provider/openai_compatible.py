import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

import httpx

from app.core.config import Settings
from app.model_provider.base import (
    ProviderChunk,
    ProviderError,
    ProviderEvent,
    ProviderResult,
    ProviderUsage,
)
from app.schemas.chat import ChatStreamRequest

logger = logging.getLogger(__name__)

MAX_ERROR_DETAIL_LENGTH = 300
SSE_DATA_PREFIX = "data:"
SSE_DONE_MARKER = "[DONE]"


class _MalformedStream(Exception):
    pass


@dataclass
class _StreamState:
    usage: ProviderUsage | None = None
    finish_reason: str | None = None


def build_upstream_body(settings: Settings, request: ChatStreamRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": settings.model_id,
        "messages": [message.model_dump() for message in request.messages],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if request.temperature is not None:
        body["temperature"] = request.temperature
    max_tokens = request.max_tokens or settings.default_max_tokens
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    # SGLang models default to thinking. Omitting reasoning_effort is not enough
    # to disable it, so send the chat template kwarg explicitly on both paths.
    if request.reasoning_effort != "off":
        body["reasoning_effort"] = request.reasoning_effort
        body["chat_template_kwargs"] = {"enable_thinking": True}
    else:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def build_upstream_headers(settings: Settings) -> dict[str, str] | None:
    api_key = settings.model_api_key
    if not api_key:
        return None
    return {"Authorization": f"Bearer {api_key}"}


def _extract_data_payload(line: str) -> str | None:
    text = line.strip()
    if not text.startswith(SSE_DATA_PREFIX):
        return None
    payload = text[len(SSE_DATA_PREFIX) :].strip()
    return payload or None


def _parse_upstream_event(payload: str) -> tuple[str | None, str | None, ProviderUsage | None]:
    try:
        event = json.loads(payload)
    except JSONDecodeError as exc:
        raise _MalformedStream from exc
    if not isinstance(event, dict):
        raise _MalformedStream

    content: str | None = None
    finish_reason: str | None = None
    choices = event.get("choices")
    if choices is not None:
        if not isinstance(choices, list):
            raise _MalformedStream
        for choice in choices:
            if not isinstance(choice, dict):
                raise _MalformedStream
            delta = choice.get("delta")
            if delta is not None:
                if not isinstance(delta, dict):
                    raise _MalformedStream
                fragment = delta.get("content")
                if fragment is not None:
                    if not isinstance(fragment, str):
                        raise _MalformedStream
                    content = fragment if content is None else f"{content}{fragment}"
            reason = choice.get("finish_reason")
            if reason is not None:
                if not isinstance(reason, str):
                    raise _MalformedStream
                finish_reason = reason

    return content, finish_reason, _parse_usage(event.get("usage"))


def _parse_usage(raw: Any) -> ProviderUsage | None:
    if not isinstance(raw, dict):
        return None
    return ProviderUsage(
        prompt_tokens=_to_token_count(raw.get("prompt_tokens")),
        completion_tokens=_to_token_count(raw.get("completion_tokens")),
    )


def _to_token_count(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _classify_http_error(status_code: int, body: bytes) -> ProviderError:
    message = _extract_upstream_message(body)
    lowered = message.lower()
    if "context" in lowered:
        return ProviderError(
            "context_limit",
            f"Request exceeded the model's context window (HTTP {status_code}): {message}",
        )
    if "reasoning" in lowered:
        return ProviderError(
            "upstream_error",
            "The model endpoint rejected the selected reasoning mode "
            f"(HTTP {status_code}): {message}",
        )
    return ProviderError(
        "upstream_error",
        f"The model endpoint returned HTTP {status_code}: {message}",
    )


def _extract_upstream_message(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    try:
        payload: Any = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return _shorten(error["message"])
        if isinstance(payload.get("message"), str):
            return _shorten(payload["message"])
    return _shorten(text) or "unknown upstream error"


def _shorten(text: str, limit: int = MAX_ERROR_DETAIL_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


async def _consume_stream(
    response: httpx.Response,
    state: _StreamState,
) -> AsyncGenerator[ProviderEvent]:
    saw_data = False
    try:
        async for line in response.aiter_lines():
            payload = _extract_data_payload(line)
            if payload is None:
                continue
            saw_data = True
            if payload == SSE_DONE_MARKER:
                break
            content, finish_reason, usage = _parse_upstream_event(payload)
            if finish_reason is not None:
                state.finish_reason = finish_reason
            if usage is not None:
                state.usage = usage
            if content:
                yield ProviderChunk(content=content)
    except _MalformedStream:
        yield ProviderError(
            "malformed_stream",
            "The model endpoint sent a malformed stream response.",
        )
        return
    except httpx.TimeoutException:
        yield ProviderError("upstream_timeout", "The model endpoint timed out while streaming.")
        return
    except httpx.ReadError:
        yield ProviderError("disconnected", "The model endpoint disconnected while streaming.")
        return
    except httpx.RequestError:
        yield ProviderError("disconnected", "The model endpoint connection failed while streaming.")
        return
    if not saw_data:
        yield ProviderError(
            "malformed_stream",
            "The model endpoint closed the stream without sending data.",
        )
        return
    yield ProviderResult(usage=state.usage, finish_reason=state.finish_reason)


async def stream_chat(
    settings: Settings,
    request: ChatStreamRequest,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float | None = None,
) -> AsyncGenerator[ProviderEvent]:
    """Stream a chat completion from an OpenAI-compatible endpoint.

    The caller owns the generator: closing it (for example when the browser
    disconnects) closes the in-flight upstream request.
    """
    if not settings.model_api_base:
        yield ProviderError("not_configured", "The model endpoint is not configured.")
        return
    if not settings.model_id:
        yield ProviderError("not_configured", "The model ID is not configured.")
        return

    url = settings.model_api_base.rstrip("/") + "/chat/completions"
    effective_timeout = timeout if timeout is not None else settings.upstream_timeout_seconds
    logger.debug("chat generation started")

    async with httpx.AsyncClient(transport=transport, timeout=effective_timeout) as client:
        try:
            async with client.stream(
                "POST",
                url,
                json=build_upstream_body(settings, request),
                headers=build_upstream_headers(settings),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    yield _classify_http_error(response.status_code, body)
                    return
                state = _StreamState()
                async for event in _consume_stream(response, state):
                    yield event
        except httpx.ConnectError:
            yield ProviderError("disconnected", "Could not connect to the model endpoint.")
            return
        except httpx.TimeoutException:
            yield ProviderError(
                "upstream_timeout",
                "The model endpoint timed out before responding.",
            )
            return
        except httpx.HTTPError:
            yield ProviderError("disconnected", "The model endpoint connection failed.")
            return
