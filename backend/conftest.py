from app.core.config import Settings

MODEL_API_KEY = "sk-test-secret"

DEFAULTS: dict[str, object] = {
    "model_api_base": "http://127.0.0.1:30000/v1",
    "model_api_key": MODEL_API_KEY,
    "model_id": "qwen3.8-27b",
    "model_profile_label": "community uncensored Qwen3.8-27B NVFP4 + optimized DSpark",
    "model_context_window": 131072,
}


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {**DEFAULTS, **overrides}
    return Settings(**values)  # type: ignore[arg-type]
