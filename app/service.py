from __future__ import annotations

import asyncio
import json
import uuid

from app.agent import DataAnalystAgent
from app.config import Settings
from app.contracts import ConversationMessage, FinalReply, JsonValue
from app.storage import RunLogger, SQLiteStore
from app.tools import Toolbox

TELEGRAM_TEXT_LIMIT = 4_096


class BotService:
    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        agent: DataAnalystAgent,
    ) -> None:
        self.settings = settings
        self.store = store
        self.agent = agent
        self._run_slots = asyncio.Semaphore(settings.max_concurrent_runs)

    async def handle_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        text: str,
        update_id: int,
    ) -> str | None:
        if not await self.store.claim_update(update_id):
            return None
        async with self.store.chat_lock(chat_id), self._run_slots:
            run_id = uuid.uuid4().hex
            logger = RunLogger(self.store, run_id)
            log_url = (
                f"{self.settings.public_base_url.rstrip('/')}/logs/{run_id}.jsonl"
            )
            await logger.log(
                "run_started",
                chat_id=chat_id,
                user_id=user_id,
                update_id=update_id,
                message=text,
            )
            history = await self.store.append_message(
                chat_id, ConversationMessage(role="user", content=text)
            )
            toolbox = Toolbox(self.settings.tavily_api_key, logger)
            answer: JsonValue
            try:
                async with asyncio.timeout(self.settings.agent_timeout_seconds):
                    answer = await self.agent.solve(history, toolbox, logger)
            except Exception as exc:
                await logger.log(
                    "run_failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
                answer = {"error": "analysis_failed"}

            reply = FinalReply(answer=answer, log_url=log_url).serialize()
            if len(reply) > TELEGRAM_TEXT_LIMIT:
                await logger.log(
                    "answer_too_large",
                    serialized_characters=len(reply),
                    limit=TELEGRAM_TEXT_LIMIT,
                )
                answer = {"error": "answer_exceeds_telegram_limit"}
                reply = FinalReply(answer=answer, log_url=log_url).serialize()

            await logger.log(
                "run_completed",
                answer=answer,
                log_url=log_url,
                sources=toolbox.sources,
                telegram_reply=reply,
            )
            await self.store.append_message(
                chat_id,
                ConversationMessage(
                    role="assistant",
                    content=json.dumps(
                        answer,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            return reply

    async def reset(self, chat_id: int) -> None:
        await self.store.reset_session(chat_id)
