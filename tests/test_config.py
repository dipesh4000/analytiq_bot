from __future__ import annotations

import pytest

from app.config import ConfigError, Settings


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_API_KEY", "test-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily")
    monkeypatch.setenv("BOT_MODE", "polling")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")


def test_default_model_is_free_router(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.delenv("LLM_MODELS", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    settings = Settings.from_env()
    assert settings.llm_models == ("openrouter/free",)


def test_paid_model_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_MODELS", "openai/gpt-4o")
    with pytest.raises(ConfigError, match="Only free"):
        Settings.from_env()


def test_webhook_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://example.com")
    with pytest.raises(ConfigError, match="HTTPS"):
        Settings.from_env()


def test_database_url_placeholder_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:[YOUR-PASSWORD]@db.example.supabase.co:5432/postgres",
    )
    with pytest.raises(ConfigError, match="real database password"):
        Settings.from_env()


def test_render_external_url_becomes_public_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://analytiq-bot.onrender.com")
    settings = Settings.from_env()
    assert settings.public_base_url == "https://analytiq-bot.onrender.com"
