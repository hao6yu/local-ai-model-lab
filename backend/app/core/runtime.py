from app.core.config import Settings
from app.schemas.runtime import RuntimeResponse

EXPERIMENTAL_MARKERS = ("experimental", "community", "uncensored")


def is_experimental_label(label: str | None) -> bool:
    if not label:
        return False
    lowered = label.lower()
    return any(marker in lowered for marker in EXPERIMENTAL_MARKERS)


def build_runtime(settings: Settings) -> RuntimeResponse:
    return RuntimeResponse(
        model_id=settings.model_id,
        profile_label=settings.model_profile_label,
        context_window=settings.model_context_window,
        experimental=is_experimental_label(settings.model_profile_label),
    )
