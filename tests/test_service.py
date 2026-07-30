from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.service import BotService
from app.storage import SQLiteStore


class FakeAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def solve(self, history, toolbox, logger, route=None):
        self.calls += 1
        assert history[-1].content == "Which state?"
        await logger.log("fake_agent")
        return {"state": "Assam"}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_api_key="test",
        openrouter_api_key="test",
        tavily_api_key="test",
        llm_models=("openrouter/free",),
        bot_mode="polling",
        public_base_url="https://bot.example",
        telegram_webhook_secret="test-secret",
        data_dir=tmp_path,
        session_ttl_seconds=900,
        max_agent_steps=8,
        agent_timeout_seconds=10,
        max_concurrent_runs=2,
        port=8000,
    )


async def test_service_wraps_answer_and_publishes_log(tmp_path) -> None:
    settings = _settings(tmp_path)
    store = SQLiteStore(settings.database_path, settings.session_ttl_seconds)
    store.initialize()
    service = BotService(settings, store, FakeAgent())  # type: ignore[arg-type]

    reply = await service.handle_message(
        chat_id=1,
        user_id=2,
        text="Which state?",
        update_id=3,
    )
    assert reply is not None
    parsed = json.loads(reply)
    assert parsed["answer"] == {"state": "Assam"}
    assert parsed["log_url"].startswith("https://bot.example/logs/")

    run_id = parsed["log_url"].rsplit("/", 1)[1].removesuffix(".jsonl")
    log = await store.get_log_jsonl(run_id)
    assert log is not None
    assert '"event":"run_completed"' in log


async def test_duplicate_update_gets_no_second_reply(tmp_path) -> None:
    settings = _settings(tmp_path)
    store = SQLiteStore(settings.database_path, settings.session_ttl_seconds)
    store.initialize()
    service = BotService(settings, store, FakeAgent())  # type: ignore[arg-type]
    first = await service.handle_message(
        chat_id=1, user_id=2, text="Which state?", update_id=4
    )
    second = await service.handle_message(
        chat_id=1, user_id=2, text="Which state?", update_id=4
    )
    assert first is not None
    assert second is None


async def test_smalltalk_skips_model_and_returns_useful_answer(tmp_path) -> None:
    settings = _settings(tmp_path)
    store = SQLiteStore(settings.database_path, settings.session_ttl_seconds)
    store.initialize()
    agent = FakeAgent()
    service = BotService(settings, store, agent)  # type: ignore[arg-type]

    reply = await service.handle_message(
        chat_id=8, user_id=9, text="hi", update_id=10
    )

    assert reply is not None
    parsed = json.loads(reply)
    assert parsed["answer"] == {"message": "Send a data-analysis question."}
    assert agent.calls == 0

    run_id = parsed["log_url"].rsplit("/", 1)[1].removesuffix(".jsonl")
    log = await store.get_log_jsonl(run_id)
    assert log is not None
    assert '"event":"smalltalk_handled_without_model"' in log
