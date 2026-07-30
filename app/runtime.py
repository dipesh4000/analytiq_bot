from __future__ import annotations

from dataclasses import dataclass

from telegram.ext import Application

from app.agent import DataAnalystAgent
from app.config import Settings
from app.postgres_storage import PostgresStore
from app.service import BotService
from app.storage import SQLiteStore, Store
from app.telegram_app import build_telegram_application


@dataclass(slots=True)
class Runtime:
    settings: Settings
    store: Store
    service: BotService
    telegram: Application


def build_runtime(settings: Settings) -> Runtime:
    store: Store
    if settings.database_url:
        store = PostgresStore(
            settings.database_url, settings.session_ttl_seconds
        )
    else:
        store = SQLiteStore(settings.database_path, settings.session_ttl_seconds)
    store.initialize()
    agent = DataAnalystAgent(
        api_key=settings.openrouter_api_key,
        models=settings.llm_models,
        max_steps=settings.max_agent_steps,
        public_base_url=settings.public_base_url,
    )
    service = BotService(settings, store, agent)
    telegram = build_telegram_application(settings, service)
    return Runtime(settings, store, service, telegram)
