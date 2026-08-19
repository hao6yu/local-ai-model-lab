from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


def load_settings() -> Settings:
    return Settings()
