from dataclasses import dataclass

from app.schemas.chat import ChatErrorCode


@dataclass(frozen=True)
class ProviderChunk:
    """A non-empty fragment of visible assistant content."""

    content: str


@dataclass(frozen=True)
class ProviderUsage:
    """Token counts reported by the upstream server, when available."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class ProviderResult:
    """Normal end of a generation stream."""

    usage: ProviderUsage | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class ProviderError:
    """Failure of a generation stream, with a user-presentable message."""

    code: ChatErrorCode
    message: str


ProviderEvent = ProviderChunk | ProviderResult | ProviderError
