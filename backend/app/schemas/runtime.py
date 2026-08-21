from pydantic import BaseModel, Field


class RuntimeModel(BaseModel):
    key: str
    model_id: str | None = None
    profile_label: str | None = None
    context_window: int | None = None
    experimental: bool = False
    default_reasoning_effort: str | None = None
    default_max_tokens: int | None = None
    supports_vision: bool = False


class RuntimeResponse(BaseModel):
    model_id: str | None = None
    profile_label: str | None = None
    context_window: int | None = None
    experimental: bool = False
    default_reasoning_effort: str | None = None
    default_max_tokens: int | None = None
    default_model_profile: str | None = None
    models: list[RuntimeModel] = Field(default_factory=list)
