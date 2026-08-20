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
