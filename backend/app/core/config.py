from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from the environment, then from the repo-root `.env`."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str | None = Field(None, validation_alias="RIO_HEALTH_DATABASE_URL")
    db_schema: str = "app_rio_health"

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_s: float = 45.0
    openrouter_max_tokens: int = 8000
    vision_model: str = ""
    rerank_model: str = ""

    use_mocks: bool = Field(False, validation_alias="RIO_USE_MOCKS")
    cors_origins: list[str] = ["http://localhost:5173", "https://rio.buildspacelabs.com"]
    parse_rate_limit_per_hour: int = 10
    max_upload_mb: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
