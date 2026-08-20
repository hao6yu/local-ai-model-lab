from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve paths relative to the repository root so behavior does not depend on
# the current working directory (e.g. running uvicorn from `backend` or a test).
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = f"sqlite:///{REPO_ROOT / 'data' / 'model-lab.db'}"
DEFAULT_EVALUATIONS_DIR = str(REPO_ROOT / "data" / "suites")
DATA_DIRECTORY = REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model_api_base: str | None = None
    model_api_key: str | None = Field(default=None, repr=False)
    model_id: str | None = None
    model_profile_label: str | None = None
    model_context_window: int | None = Field(default=None, ge=1)
    model_profiles_json: str | None = None
    default_model_profile: str | None = None
    default_reasoning_effort: str | None = None
    default_max_tokens: int | None = Field(default=None, ge=1)
    upstream_timeout_seconds: float = Field(default=60.0, gt=0)
    # Empty string disables persistence (legacy 503 behavior); the default
    # path mirrors the README dev command so `uvicorn app.main:app` "just works".
    database_url: str = Field(default=DEFAULT_DATABASE_URL, min_length=0)
    evaluations_dir: str = Field(default=DEFAULT_EVALUATIONS_DIR, min_length=1)


def load_settings() -> Settings:
    return Settings()
