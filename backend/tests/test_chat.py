import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fake_upstream import (
    FakeUpstream,
    chunk_frame,
    error_body,
    finish_frame,
    sse_done,
    usage_frame,
)
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.model_provider import openai_compatible
from app.model_provider.base import (
    ProviderChunk,
    ProviderError,
    ProviderEvent,
    ProviderResult,
    ProviderUsage,
)
from app.schemas.chat import ChatMessage, ChatStreamRequest, ReasoningEffort
from app.schemas.health import UpstreamHealth
from conftest import DUAL_PROFILES_JSON, MODEL_API_KEY, make_settings


def _request(
    content: str = "hi",
    *,
    model_profile: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    reasoning_effort: ReasoningEffort = "off",
) -> ChatStreamRequest:
    return ChatStreamRequest(
        model_profile=model_profile,
        messages=[ChatMessage(role="user", content=content)],
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )


def collect(gen: AsyncIterator[ProviderEvent]) -> list[ProviderEvent]:
    async def _run() -> list[ProviderEvent]:
        events: list[ProviderEvent] = []
        async for event in gen:
            events.append(event)
        return events

    return asyncio.run(_run())


def _reachable_probe(settings: Settings) -> UpstreamHealth:
    return UpstreamHealth(state="reachable")


def _happy_frames() -> list[str]:
    return [
        chunk_frame("Hello"),
        chunk_frame(" world"),
        finish_frame("stop"),
        usage_frame(4, 12),
        sse_done(),
    ]


# --------------------------------------------------------------------------- #
# Provider-level tests (fake upstream injected into stream_chat)
# --------------------------------------------------------------------------- #
def test_stream_chat_streams_chunks_usage_finish_reason_and_request_fields() -> None:
    fake = FakeUpstream(frames=_happy_frames())
    settings = make_settings()
    request = _request(content="please answer")

    events = collect(openai_compatible.stream_chat(settings, request, transport=fake.transport))

    assert events == [
        ProviderChunk(content="Hello"),
        ProviderChunk(content=" world"),
        ProviderResult(
            usage=ProviderUsage(prompt_tokens=4, completion_tokens=12), finish_reason="stop"
        ),
    ]

    assert fake.last_request is not None
    assert fake.last_request.method == "POST"
    assert fake.last_request.url == "http://127.0.0.1:30000/v1/chat/completions"
    assert fake.last_request.headers["authorization"] == f"Bearer {MODEL_API_KEY}"
    assert fake.last_request.body == {
        "model": "qwen3.8-27b",
        "messages": [{"role": "user", "content": "please answer"}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": settings.default_max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_stream_chat_sends_optional_request_fields_when_set() -> None:
    fake = FakeUpstream(frames=_happy_frames())
    settings = make_settings()
    request = _request(
        content="hi",
        temperature=0.7,
        max_tokens=2048,
        reasoning_effort="high",
    )

    collect(openai_compatible.stream_chat(settings, request, transport=fake.transport))

    body = fake.last_request
    assert body is not None
    assert body.body is not None
    assert body.body["temperature"] == 0.7
    assert body.body["max_tokens"] == 2048
    assert body.body["reasoning_effort"] == "high"
    assert body.body["chat_template_kwargs"] == {"enable_thinking": True}


def test_stream_chat_applies_default_limit_and_omits_unset_reasoning() -> None:
    fake = FakeUpstream(frames=_happy_frames())
    settings = make_settings()
    request = _request(content="hi")

    collect(openai_compatible.stream_chat(settings, request, transport=fake.transport))

    body = fake.last_request
    assert body is not None
    assert body.body is not None
    assert "temperature" not in body.body
    assert body.body["max_tokens"] == settings.default_max_tokens
    assert "reasoning_effort" not in body.body
    assert body.body["chat_template_kwargs"] == {"enable_thinking": False}


def test_stream_chat_sends_no_authorization_header_without_key() -> None:
    fake = FakeUpstream(frames=_happy_frames())
    settings = make_settings(model_api_key=None)

    collect(openai_compatible.stream_chat(settings, _request(), transport=fake.transport))

    assert fake.last_request is not None
    assert "authorization" not in fake.last_request.headers


def test_stream_chat_maps_http_error_to_stream() -> None:
    fake = FakeUpstream(status=400, error_response=error_body("Bad request oops"))
    events = collect(
        openai_compatible.stream_chat(make_settings(), _request(), transport=fake.transport)
    )
    assert events == [
        ProviderError("upstream_error", "The model endpoint returned HTTP 400: Bad request oops")
    ]
    assert fake.last_request is not None
    assert fake.last_request.body is not None
    assert "reasoning" not in str(fake.last_request.body.get("reasoning_effort")).lower()


def test_stream_chat_maps_context_error_to_context_limit() -> None:
    body = error_body("prompt too long: 200000 tokens exceed the context window of 131072")
    fake = FakeUpstream(status=413, error_response=body)
    events = collect(
        openai_compatible.stream_chat(make_settings(), _request(), transport=fake.transport)
    )
    assert len(events) == 1
    err = events[0]
    assert isinstance(err, ProviderError) and err.code == "context_limit"


def test_stream_chat_maps_stream_failure_without_context_keyword() -> None:
    fake = FakeUpstream(status=500, error_response=error_body("internal server failure"))
    events = collect(
        openai_compatible.stream_chat(make_settings(), _request(), transport=fake.transport)
    )
    assert events == [
        ProviderError(
            "upstream_error", "The model endpoint returned HTTP 500: internal server failure"
        )
    ]


def test_stream_chat_reports_missing_stream_without_data() -> None:
    fake = FakeUpstream(frames=[])
    events = collect(
        openai_compatible.stream_chat(make_settings(), _request(), transport=fake.transport)
    )
    assert events == [
        ProviderError(
            "malformed_stream",
            "The model endpoint closed the stream without sending data.",
        )
    ]


def test_stream_chat_reports_malformed_stream() -> None:
    fake = FakeUpstream(frames=["data: not valid json", "data: {unterminated}"])
    events = collect(
        openai_compatible.stream_chat(make_settings(), _request(), transport=fake.transport)
    )
    assert events == [
        ProviderError(
            "malformed_stream",
            "The model endpoint sent a malformed stream response.",
        )
    ]


def test_stream_chat_reports_timeout_mid_stream() -> None:
    fake = FakeUpstream(
        frames=[chunk_frame("a"), chunk_frame("b"), chunk_frame("c")], timeout_after=2
    )
    events = collect(
        openai_compatible.stream_chat(make_settings(), _request(), transport=fake.transport)
    )
    assert events == [
        ProviderChunk(content="a"),
        ProviderChunk(content="b"),
        ProviderError("upstream_timeout", "The model endpoint timed out while streaming."),
    ]


def test_stream_chat_reports_disconnect_mid_stream() -> None:
    fake = FakeUpstream(frames=[chunk_frame("a"), chunk_frame("b"), chunk_frame("c")], fail_after=2)
    events = collect(
        openai_compatible.stream_chat(make_settings(), _request(), transport=fake.transport)
    )
    assert events == [
        ProviderChunk(content="a"),
        ProviderChunk(content="b"),
        ProviderError("disconnected", "The model endpoint disconnected while streaming."),
    ]


def test_stream_chat_reports_unconfigured_endpoint_without_request() -> None:
    fake = FakeUpstream(frames=_happy_frames())
    settings = make_settings(model_api_base=None)
    events = collect(openai_compatible.stream_chat(settings, _request(), transport=fake.transport))
    assert events == [ProviderError("not_configured", "The model endpoint is not configured.")]
    assert fake.last_request is None


def test_stream_chat_closes_upstream_when_consumer_stops() -> None:
    frames = [chunk_frame(f"part{i}") for i in range(10)]
    fake = FakeUpstream(frames=frames)
    settings = make_settings()
    request = _request(content="hi")

    gen = openai_compatible.stream_chat(settings, request, transport=fake.transport)
    consumed = 0

    async def _run() -> None:
        nonlocal consumed
        async for _event in gen:
            consumed += 1
            if consumed == 2:
                break
        await gen.aclose()

    asyncio.run(_run())

    assert consumed == 2
    assert fake.state.closed is True
    assert fake.state.frames_delivered == 2


def test_generation_tps_suppressed_when_reasoning_active() -> None:
    from app.core.metrics import build_chat_metrics

    usage = ProviderUsage(prompt_tokens=4, completion_tokens=12)
    # started=0.0, completed=3.0, first_chunk_at=1.0 -> span = 2.0 -> tps = 6.0.
    off = build_chat_metrics(0.0, 3.0, 1.0, usage, reasoning_active=False)
    assert off.generation_tps == 6.0

    on = build_chat_metrics(0.0, 3.0, 1.0, usage, reasoning_active=True)
    assert on.generation_tps is None

    no_first_chunk = build_chat_metrics(0.0, 3.0, None, usage, reasoning_active=False)
    assert no_first_chunk.generation_tps is None


# --------------------------------------------------------------------------- #
# Route-level tests (fastapi TestClient + create_app)
# --------------------------------------------------------------------------- #
def parse_sse(text: str) -> list[tuple[str, str]]:
    frames: list[tuple[str, str]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event: str | None = None
        data = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data += line[len("data:") :].strip()
        if event is not None and data:
            frames.append((event, data))
    return frames


def _route_client(fake: FakeUpstream) -> TestClient:
    return TestClient(
        create_app(
            settings=make_settings(), probe=_reachable_probe, upstream_transport=fake.transport
        )
    )


def test_chat_stream_endpoint_emits_sse_for_happy_path() -> None:
    fake = FakeUpstream(frames=_happy_frames())
    client = _route_client(fake)

    response = client.post(
        "/api/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"

    frames = parse_sse(response.text)
    parsed = [(event, json.loads(data)) for event, data in frames]

    assert parsed[0][0] == "chunk"
    assert parsed[0][1] == {"content": "Hello"}
    assert parsed[1][0] == "chunk"
    assert parsed[1][1] == {"content": " world"}

    assert parsed[-1][0] == "done"
    done = parsed[-1][1]
    assert done["finish_reason"] == "stop"
    assert done["usage"] == {"prompt_tokens": 4, "completion_tokens": 12}

    metrics = done["metrics"]
    assert metrics["token_source"] == "upstream"
    assert metrics["ttft_seconds"] is not None
    assert metrics["completion_seconds"] >= 0
    assert metrics["ttft_seconds"] <= metrics["completion_seconds"]
    assert metrics["generation_tps"] is None or isinstance(metrics["generation_tps"], float)


def test_chat_stream_endpoint_emits_error_frame_for_http_error() -> None:
    body = error_body("prompt too long: 200000 tokens exceed the context window of 131072")
    fake = FakeUpstream(status=413, error_response=body)
    client = _route_client(fake)

    response = client.post(
        "/api/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    frames = parse_sse(response.text)
    assert len(frames) == 1
    event, data = frames[0]
    assert event == "error"
    parsed = json.loads(data)
    assert parsed["code"] == "context_limit"
    assert parsed["message"].startswith("Request exceeded the model's context window")


def test_chat_stream_endpoint_rejects_empty_messages() -> None:
    fake = FakeUpstream()
    client = _route_client(fake)

    response = client.post("/api/chat/stream", json={"messages": []})
    assert response.status_code == 422
    assert fake.last_request is None


def test_chat_stream_endpoint_routes_selected_resident_profile() -> None:
    fake = FakeUpstream(frames=_happy_frames())
    settings = make_settings(
        model_profiles_json=DUAL_PROFILES_JSON,
        default_model_profile="ornith",
    )
    client = TestClient(
        create_app(
            settings=settings,
            probe=_reachable_probe,
            upstream_transport=fake.transport,
        )
    )

    response = client.post(
        "/api/chat/stream",
        json={
            "model_profile": "qwen",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    assert fake.last_request is not None
    assert fake.last_request.url == "http://127.0.0.1:30001/v1/chat/completions"
    assert fake.last_request.body is not None
    assert fake.last_request.body["model"] == "qwen3.8-27b"


def test_chat_stream_endpoint_rejects_unknown_profile() -> None:
    fake = FakeUpstream()
    settings = make_settings(model_profiles_json=DUAL_PROFILES_JSON)
    client = TestClient(
        create_app(
            settings=settings,
            probe=_reachable_probe,
            upstream_transport=fake.transport,
        )
    )

    response = client.post(
        "/api/chat/stream",
        json={
            "model_profile": "missing",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown model profile: missing"
    assert fake.last_request is None


def test_chat_stream_endpoint_does_not_log_raw_data(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG, logger="app.model_provider")
    fake = FakeUpstream(frames=[chunk_frame("secret response fragment"), sse_done()])
    client = _route_client(fake)

    response = client.post(
        "/api/chat/stream",
        json={"messages": [{"role": "user", "content": "secret prompt"}]},
    )
    assert response.status_code == 200
    assert "secret prompt" not in caplog.text
    assert "secret response fragment" not in caplog.text
