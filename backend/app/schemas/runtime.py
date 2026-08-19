from pydantic import BaseModel


class RuntimeResponse(BaseModel):
    model_id: str | None = None
    profile_label: str | None = None
    context_window: int | None = None
    experimental: bool = False
