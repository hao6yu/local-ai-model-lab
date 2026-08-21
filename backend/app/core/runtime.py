from app.core.config import Settings
from app.core.model_profiles import load_model_profiles, select_model_profile
from app.schemas.runtime import RuntimeModel, RuntimeResponse

EXPERIMENTAL_MARKERS = ("experimental", "community", "uncensored")


def is_experimental_label(label: str | None) -> bool:
    if not label:
        return False
    lowered = label.lower()
    return any(marker in lowered for marker in EXPERIMENTAL_MARKERS)


def build_runtime(settings: Settings) -> RuntimeResponse:
    profiles = load_model_profiles(settings)
    selected = select_model_profile(settings)
    return RuntimeResponse(
        model_id=selected.model_id,
        profile_label=selected.profile_label,
        context_window=selected.context_window,
        experimental=is_experimental_label(selected.profile_label),
        default_reasoning_effort=selected.default_reasoning_effort,
        default_max_tokens=selected.default_max_tokens,
        default_model_profile=selected.key,
        models=[
            RuntimeModel(
                key=profile.key,
                model_id=profile.model_id,
                profile_label=profile.profile_label,
                context_window=profile.context_window,
                experimental=is_experimental_label(profile.profile_label),
                default_reasoning_effort=profile.default_reasoning_effort,
                default_max_tokens=profile.default_max_tokens,
                supports_vision=profile.supports_vision,
            )
            for profile in profiles
        ],
    )
