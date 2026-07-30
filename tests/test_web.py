from __future__ import annotations

import json

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.storage import RunLogger
from app.web import create_web_app


async def test_health_public_log_and_webhook_secret(tmp_path) -> None:
    settings = Settings(
        bot_api_key="123:ABC",
        openrouter_api_key="test",
        tavily_api_key="test",
        llm_models=("openrouter/free",),
        bot_mode="webhook",
        public_base_url="https://bot.example",
        telegram_webhook_secret="test-secret",
        data_dir=tmp_path,
        session_ttl_seconds=900,
        max_agent_steps=8,
        agent_timeout_seconds=10,
        max_concurrent_runs=2,
        port=8000,
    )
    app = create_web_app(settings)
    run_id = "c" * 32
    logger = RunLogger(app.state.runtime.store, run_id)
    await logger.log("run_completed", answer={"state": "Assam"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://bot.example") as client:
        health = await client.get("/healthz")
        assert health.json() == {"status": "ok"}

        log = await client.get(f"/logs/{run_id}.jsonl")
        assert log.status_code == 200
        assert log.headers["content-type"].startswith("application/x-ndjson")
        assert json.loads(log.text)["event"] == "run_completed"

        forbidden = await client.post(settings.webhook_path, json={})
        assert forbidden.status_code == 403
