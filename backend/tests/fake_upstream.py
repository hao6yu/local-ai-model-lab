"""Fake OpenAI-compatible upstream endpoint for provider and route tests."""

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import httpx


def sse_data(payload: str) -> str:
    return f"data: {payload}\n\n"


def sse_done() -> str:
    return "data: [DONE]\n\n"


def chunk_frame(content: str) -> str:
    payload = json.dumps(
        {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]}
    )
    return sse_data(payload)


def finish_frame(finish_reason: str) -> str:
    payload = json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]})
    return sse_data(payload)


def usage_frame(prompt_tokens: int, completion_tokens: int) -> str:
    payload = json.dumps(
        {
            "choices": [],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        }
    )
    return sse_data(payload)


def error_body(message: str) -> bytes:
    return json.dumps(
        {"error": {"message": message, "type": "invalid_request_error", "code": "bad_request"}}
    ).encode("utf-8")


@dataclass
class RecordedRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: dict[str, object] | None


@dataclass
class FakeUpstreamState:
    fail_after: int | None = None
    timeout_after: int | None = None
    frames_delivered: int = 0
    closed: bool = False
    requests: list[RecordedRequest] = field(default_factory=list)


class _FrameStream(httpx.AsyncByteStream):
    """Replays recorded SSE frames while tracking consumption and closing."""

    def __init__(self, state: FakeUpstreamState, frames: list[str]) -> None:
        self._state = state
        self._frames = frames

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._aiter()

    async def _aiter(self) -> AsyncIterator[bytes]:
        for index, frame in enumerate(self._frames):
            if self._state.fail_after is not None and index == self._state.fail_after:
                raise httpx.ReadError("fake upstream disconnected mid-stream")
            if self._state.timeout_after is not None and index == self._state.timeout_after:
                raise httpx.ReadTimeout("fake upstream timed out mid-stream")
            self._state.frames_delivered = index + 1
            yield frame.encode("utf-8")

    async def aclose(self) -> None:
        self._state.closed = True


class _BytesStream(httpx.AsyncByteStream):
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._aiter()

    async def _aiter(self) -> AsyncIterator[bytes]:
        yield self._data

    async def aclose(self) -> None:
        pass


class FakeUpstream:
    """A controllable fake for the OpenAI-compatible /chat/completions endpoint.

    Inject ``transport`` into ``stream_chat(transport=...)`` or
    ``create_app(upstream_transport=...)`` and inspect ``state`` / ``last_request``.
    """

    def __init__(
        self,
        *,
        frames: Sequence[str] = (),
        status: int = 200,
        error_response: bytes = b"",
        fail_after: int | None = None,
        timeout_after: int | None = None,
    ) -> None:
        self.state = FakeUpstreamState(fail_after=fail_after, timeout_after=timeout_after)
        self._frames = list(frames)
        self._status = status
        self._error_body = error_response
        self.transport = httpx.MockTransport(self._handle)

    @property
    def last_request(self) -> RecordedRequest | None:
        return self.state.requests[-1] if self.state.requests else None

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, object] | None = None
        if request.content:
            body = json.loads(request.content)
        self.state.requests.append(
            RecordedRequest(
                method=request.method,
                url=str(request.url),
                headers=dict(request.headers),
                body=body,
            )
        )
        if self._status >= 400:
            return httpx.Response(self._status, stream=_BytesStream(self._error_body))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=_FrameStream(self.state, self._frames),
        )
