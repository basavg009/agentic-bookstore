"""Environment-driven configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SESSION_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "production"] = "development"
    database_url: str = f"sqlite:///{(_ROOT / 'data' / 'bookstore.db').as_posix()}"
    # HMAC key for signing the session cookie. Must be overridden in production.
    session_secret: str = DEFAULT_SESSION_SECRET
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    host: str = "127.0.0.1"
    port: int = 8000

    # Agent budgets — a turn stops at whichever limit is hit first.
    agent_max_iterations: int = 10
    agent_max_tool_calls: int = 20
    agent_max_seconds: float = 120.0
    agent_max_tokens: int = 32_000

    # Conversation memory: how many stored messages are replayed to the model.
    chat_history_max_messages: int = 30

    # Two-phase checkout: how long a quote (and its locked prices) stays valid.
    checkout_quote_ttl_seconds: int = 15 * 60

    # MCP stdio server: the cart this process acts on. Unset = fresh cart per process.
    mcp_session_id: str | None = None

    @property
    def is_production(self) -> bool:
        return self.env == "production"


settings = Settings()
