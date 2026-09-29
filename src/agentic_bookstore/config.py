"""Environment-driven configuration."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{(_ROOT / 'data' / 'bookstore.db').as_posix()}"
    session_secret: str = "change-me-in-production"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    host: str = "127.0.0.1"
    port: int = 8000


settings = Settings()
