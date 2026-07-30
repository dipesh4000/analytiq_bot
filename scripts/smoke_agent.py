"""Run one local agent turn without contacting Telegram."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

from app.agent import DataAnalystAgent
from app.config import Settings
from app.contracts import ConversationMessage
from app.storage import RunLogger, SQLiteStore
from app.tools import Toolbox


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "question",
        nargs="?",
        default=(
            "Values are [12, 18, 30, 40]. Return only the answer value shaped as "
            '{"mean": <number>}.'
        ),
    )
    args = parser.parse_args()
    settings = Settings.from_env(require_bot=False)
    store = SQLiteStore(settings.database_path, settings.session_ttl_seconds)
    store.initialize()
    run_id = uuid.uuid4().hex
    logger = RunLogger(store, run_id)
    agent = DataAnalystAgent(
        settings.openrouter_api_key,
        settings.llm_models,
        settings.max_agent_steps,
        settings.public_base_url,
    )
    toolbox = Toolbox(settings.tavily_api_key, logger)
    answer = await agent.solve(
        [ConversationMessage(role="user", content=args.question)],
        toolbox,
        logger,
    )
    print(json.dumps({"answer": answer, "run_id": run_id}, separators=(",", ":")))


if __name__ == "__main__":
    asyncio.run(main())
