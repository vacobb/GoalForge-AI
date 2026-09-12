from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Keep the development database in one predictable place.  A relative
    # SQLite URL changes its location when uvicorn is launched from a
    # different directory, which can make existing goals appear to vanish.
    database_url: str = f"sqlite:///{Path(__file__).resolve().parents[2] / 'goalforge.db'}"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    cors_origins: str = "http://localhost:3000"
    hevy_api_key: str | None = None
    hevy_sync_interval_minutes: int = 180
    # Resolve relative to the backend package, not the terminal's working directory.
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
