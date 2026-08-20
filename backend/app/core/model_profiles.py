import json
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


class ModelProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ModelProfile:
    key: str
    api_base: str | None
    model_id: str | None
    profile_label: str | None
    context_window: int | None
    default_reasoning_effort: str | None
    default_max_tokens: int | None

    def apply(self, settings: Settings) -> Settings:
        """Return legacy-shaped settings for the existing provider adapter."""
        return settings.model_copy(
            update={
                "model_api_base": self.api_base,
                "model_id": self.model_id,
                "model_profile_label": self.profile_label,
                "model_context_window": self.context_window,
                "default_reasoning_effort": self.default_reasoning_effort,
                "default_max_tokens": self.default_max_tokens,
            }
        )


def load_model_profiles(settings: Settings) -> tuple[ModelProfile, ...]:
    if not settings.model_profiles_json:
        return (_legacy_profile(settings),)
    try:
        raw: Any = json.loads(settings.model_profiles_json)
    except json.JSONDecodeError as exc:
        raise ModelProfileError("MODEL_PROFILES_JSON must be valid JSON") from exc
    if not isinstance(raw, list) or not raw:
        raise ModelProfileError("MODEL_PROFILES_JSON must contain a non-empty list")

    profiles: list[ModelProfile] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ModelProfileError("every model profile must be an object")
        key = str(item.get("key") or "").strip()
        if not key or key in seen:
            raise ModelProfileError("every model profile needs a unique non-empty key")
        seen.add(key)
        api_base = _optional_text(item.get("api_base"))
        model_id = _optional_text(item.get("model_id"))
        if not api_base or not model_id:
            raise ModelProfileError(f"model profile {key!r} needs api_base and model_id")
        profiles.append(
            ModelProfile(
                key=key,
                api_base=api_base,
                model_id=model_id,
                profile_label=_optional_text(item.get("profile_label")),
                context_window=_optional_positive_int(item.get("context_window"), "context_window"),
                default_reasoning_effort=_optional_text(item.get("default_reasoning_effort")),
                default_max_tokens=_optional_positive_int(
                    item.get("default_max_tokens"),
                    "default_max_tokens",
                ),
            )
        )
    return tuple(profiles)


def select_model_profile(settings: Settings, key: str | None = None) -> ModelProfile:
    profiles = load_model_profiles(settings)
    selected_key = key or settings.default_model_profile or profiles[0].key
    for profile in profiles:
        if profile.key == selected_key:
            return profile
    raise ModelProfileError(f"unknown model profile: {selected_key}")


def settings_for_profile(settings: Settings, key: str | None = None) -> Settings:
    return select_model_profile(settings, key).apply(settings)


def _legacy_profile(settings: Settings) -> ModelProfile:
    return ModelProfile(
        key=settings.default_model_profile or "default",
        api_base=settings.model_api_base,
        model_id=settings.model_id,
        profile_label=settings.model_profile_label,
        context_window=settings.model_context_window,
        default_reasoning_effort=settings.default_reasoning_effort,
        default_max_tokens=settings.default_max_tokens,
    )


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        parsed = value
    elif isinstance(value, str) and value.isdecimal():
        parsed = int(value)
    else:
        raise ModelProfileError(f"{field} must be a positive integer")
    if parsed < 1:
        raise ModelProfileError(f"{field} must be a positive integer")
    return parsed
