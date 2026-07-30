from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when runtime configuration is unsafe or incomplete."""


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    bot_api_key: str
    openrouter_api_key: str
    tavily_api_key: str
    llm_models: tuple[str, ...]
    bot_mode: str
    public_base_url: str
    telegram_webhook_secret: str
    data_dir: Path
    session_ttl_seconds: int
    max_agent_steps: int
    agent_timeout_seconds: int
    max_concurrent_runs: int
    port: int
    database_url: str = ""

    @property
    def database_path(self) -> Path:
        return self.data_dir / "analytiq.db"

    @property
    def webhook_path(self) -> str:
        return f"/telegram/{self.telegram_webhook_secret}"

    @property
    def webhook_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}{self.webhook_path}"

    @classmethod
    def from_env(cls, *, require_bot: bool = True) -> Settings:
        load_dotenv()
        bot_api_key = os.getenv("BOT_API_KEY", "").strip()
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        tavily_api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if require_bot and not bot_api_key:
            raise ConfigError("BOT_API_KEY is required")
        if not openrouter_api_key:
            raise ConfigError("OPENROUTER_API_KEY is required")
        if not tavily_api_key:
            raise ConfigError("TAVILY_API_KEY is required")

        raw_models = os.getenv("LLM_MODELS") or os.getenv("LLM_MODEL") or "openrouter/free"
        models = tuple(model.strip() for model in raw_models.split(",") if model.strip())
        if not models:
            raise ConfigError("At least one LLM model is required")
        paid = [
            model
            for model in models
            if model != "openrouter/free" and not model.endswith(":free")
        ]
        if paid:
            raise ConfigError(
                "Only free OpenRouter models are allowed; invalid IDs: " + ", ".join(paid)
            )

        mode = os.getenv("BOT_MODE", "polling").strip().lower()
        if mode not in {"polling", "webhook"}:
            raise ConfigError("BOT_MODE must be polling or webhook")
        public_base_url = (
            os.getenv("PUBLIC_BASE_URL")
            or os.getenv("RENDER_EXTERNAL_URL")
            or "http://localhost:8000"
        ).rstrip("/")
        database_url = os.getenv("DATABASE_URL", "").strip()
        if database_url:
            if not database_url.startswith(("postgresql://", "postgres://")):
                raise ConfigError("DATABASE_URL must be a PostgreSQL connection string")
            if "[YOUR-PASSWORD]" in database_url:
                raise ConfigError(
                    "Replace [YOUR-PASSWORD] in DATABASE_URL with the real database password"
                )
        webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "development-secret").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", webhook_secret):
            raise ConfigError(
                "TELEGRAM_WEBHOOK_SECRET must contain only letters, digits, _ and -"
            )
        if mode == "webhook" and not public_base_url.startswith("https://"):
            raise ConfigError("PUBLIC_BASE_URL must use HTTPS in webhook mode")

        return cls(
            bot_api_key=bot_api_key,
            openrouter_api_key=openrouter_api_key,
            tavily_api_key=tavily_api_key,
            llm_models=models,
            bot_mode=mode,
            public_base_url=public_base_url,
            telegram_webhook_secret=webhook_secret,
            data_dir=Path(os.getenv("DATA_DIR", "data")).resolve(),
            session_ttl_seconds=_positive_int("SESSION_TTL_SECONDS", 900),
            max_agent_steps=_positive_int("MAX_AGENT_STEPS", 8),
            agent_timeout_seconds=_positive_int("AGENT_TIMEOUT_SECONDS", 180),
            max_concurrent_runs=_positive_int("MAX_CONCURRENT_RUNS", 3),
            port=_positive_int("PORT", 8000),
            database_url=database_url,
        )
