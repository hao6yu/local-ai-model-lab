from app.core.config import Settings

MODEL_API_KEY = "sk-test-secret"

DUAL_PROFILES_JSON = """[
  {
    "key": "ornith",
    "api_base": "http://127.0.0.1:30000/v1",
    "model_id": "ornith-1.5-35b-a3b",
    "profile_label": "Ornith 1.5 35B-A3B NVFP4",
    "context_window": 131072,
    "default_reasoning_effort": "medium",
    "default_max_tokens": 16384
  },
  {
    "key": "qwen",
    "api_base": "http://127.0.0.1:30001/v1",
    "model_id": "qwen3.8-27b",
    "profile_label": "Qwen3.8-27B NVFP4 + DFlash2",
    "context_window": 131072,
    "default_reasoning_effort": "low",
    "default_max_tokens": 16384
  }
]"""

DEFAULTS: dict[str, object] = {
    "model_api_base": "http://127.0.0.1:30000/v1",
    "model_api_key": MODEL_API_KEY,
    "model_id": "qwen3.8-27b",
    "model_profile_label": "community uncensored Qwen3.8-27B NVFP4 + optimized DSpark",
    "model_context_window": 131072,
    "default_reasoning_effort": "low",
    "default_max_tokens": 8192,
    "upstream_timeout_seconds": 30.0,
}


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {**DEFAULTS, **overrides}
    # Unit tests must not inherit a developer's live backend/.env profiles.
    # Each test supplies its complete synthetic runtime configuration here.
    return Settings(_env_file=None, **values)  # type: ignore[arg-type,call-arg]
