import pytest

from app.core.model_profiles import ModelProfileError, load_model_profiles, settings_for_profile
from conftest import DUAL_PROFILES_JSON, make_settings


def test_selecting_qwen_routes_to_its_private_endpoint() -> None:
    settings = make_settings(
        model_profiles_json=DUAL_PROFILES_JSON,
        default_model_profile="ornith",
    )

    selected = settings_for_profile(settings, "qwen")

    assert selected.model_api_base == "http://127.0.0.1:30001/v1"
    assert selected.model_id == "qwen3.8-27b"
    assert selected.default_reasoning_effort == "low"
    assert selected.default_max_tokens == 16384


def test_default_profile_is_ornith() -> None:
    settings = make_settings(
        model_profiles_json=DUAL_PROFILES_JSON,
        default_model_profile="ornith",
    )

    selected = settings_for_profile(settings)

    assert selected.model_api_base == "http://127.0.0.1:30000/v1"
    assert selected.model_id == "ornith-1.5-35b-a3b"


def test_invalid_or_unknown_profiles_fail_closed() -> None:
    with pytest.raises(ModelProfileError, match="valid JSON"):
        load_model_profiles(make_settings(model_profiles_json="not-json"))
    with pytest.raises(ModelProfileError, match="unknown model profile"):
        settings_for_profile(
            make_settings(model_profiles_json=DUAL_PROFILES_JSON),
            "missing",
        )


VISION_PROFILES_JSON = """[
    {
        "key": "ornith",
        "api_base": "http://127.0.0.1:30000/v1",
        "model_id": "ornith-1.5-35b-a3b",
        "profile_label": "Ornith 1.5 35B-A3B NVFP4",
        "context_window": 131072,
        "default_reasoning_effort": "medium",
        "default_max_tokens": 16384,
        "supports_vision": false
    },
    {
        "key": "qwen",
        "api_base": "http://127.0.0.1:30001/v1",
        "model_id": "qwen3.8-27b",
        "profile_label": "Qwen3.8-27B NVFP4 + DFlash2",
        "context_window": 131072,
        "default_reasoning_effort": "low",
        "default_max_tokens": 16384,
        "supports_vision": true
    }
]"""


def test_profiles_parse_supports_vision_from_json() -> None:
    profiles = load_model_profiles(make_settings(model_profiles_json=VISION_PROFILES_JSON))

    by_key = {profile.key: profile for profile in profiles}
    assert by_key["ornith"].supports_vision is False
    assert by_key["qwen"].supports_vision is True


def test_profile_defaults_supports_vision_to_false() -> None:
    profiles = load_model_profiles(make_settings(model_profiles_json=VISION_PROFILES_JSON))

    by_key = {profile.key: profile for profile in profiles}
    assert by_key["ornith"].supports_vision is False


def test_legacy_profile_supports_vision_defaults_to_false() -> None:
    profile = load_model_profiles(make_settings())[0]

    assert profile.supports_vision is False


def test_legacy_profile_supports_vision_follows_settings() -> None:
    profile = load_model_profiles(make_settings(default_model_supports_vision=True))[0]

    assert profile.supports_vision is True
