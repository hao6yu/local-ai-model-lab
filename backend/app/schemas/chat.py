from typing import Literal

from pydantic import BaseModel, Field

ReasoningEffort = Literal["off", "low", "medium", "high", "xhigh"]
ChatRole = Literal["system", "user", "assistant"]
TokenSource = Literal["upstream"]

# Error codes the backend may report for a failed generation.
ChatErrorCode = Literal[
    "not_configured",
    "upstream_timeout",
    "disconnected",
    "upstream_error",
    "context_limit",
    "malformed_stream",
]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str


class ChatStreamRequest(BaseModel):
    model_profile: str | None = Field(default=None, min_length=1, max_length=80)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    reasoning_effort: ReasoningEffort = "off"


class ChatUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ChatMetrics(BaseModel):
    ttft_seconds: float | None = None
    completion_seconds: float
    generation_tps: float | None = None
    token_source: TokenSource | None = None


class ChatChunkPayload(BaseModel):
    content: str


class ChatDonePayload(BaseModel):
    usage: ChatUsage | None = None
    finish_reason: str | None = None
    metrics: ChatMetrics


class ChatErrorPayload(BaseModel):
    code: ChatErrorCode
    message: str
