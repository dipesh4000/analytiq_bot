from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict

import psycopg
from psycopg import errors

from app.contracts import ConversationMessage, LogEvent


class PostgresStore:
    """Supabase/PostgreSQL storage for sessions, deduplication, and run logs."""

    def __init__(self, database_url: str, session_ttl_seconds: int) -> None:
        self.database_url = database_url
        self.session_ttl_seconds = session_ttl_seconds
        self._chat_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def initialize(self) -> None:
        with psycopg.connect(
            self.database_url,
            autocommit=True,
            connect_timeout=15,
            sslmode="require",
        ) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    chat_id BIGINT PRIMARY KEY,
                    messages_json TEXT NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_updates (
                    update_id BIGINT PRIMARY KEY,
                    processed_at DOUBLE PRECISION NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS log_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_log_events_run
                ON log_events(run_id, sequence)
                """
            )

    def chat_lock(self, chat_id: int) -> asyncio.Lock:
        return self._chat_locks[chat_id]

    async def _connect(self) -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(
            self.database_url, connect_timeout=15, sslmode="require"
        )

    async def ping(self) -> None:
        async with await self._connect() as connection:
            await connection.execute("SELECT 1")

    async def claim_update(self, update_id: int) -> bool:
        try:
            async with await self._connect() as connection:
                await connection.execute(
                    """
                    INSERT INTO processed_updates(update_id, processed_at)
                    VALUES (%s, %s)
                    """,
                    (update_id, time.time()),
                )
            return True
        except errors.UniqueViolation:
            return False

    async def get_messages(self, chat_id: int) -> list[ConversationMessage]:
        async with await self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT messages_json, updated_at
                FROM sessions WHERE chat_id = %s
                """,
                (chat_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return []
            if time.time() - float(row[1]) > self.session_ttl_seconds:
                await connection.execute(
                    "DELETE FROM sessions WHERE chat_id = %s", (chat_id,)
                )
                return []
        return [
            ConversationMessage.model_validate(item) for item in json.loads(row[0])
        ]

    async def append_message(
        self, chat_id: int, message: ConversationMessage, *, max_messages: int = 12
    ) -> list[ConversationMessage]:
        messages = await self.get_messages(chat_id)
        messages.append(message)
        messages = messages[-max_messages:]
        raw = json.dumps(
            [item.model_dump(mode="json") for item in messages],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        async with await self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO sessions(chat_id, messages_json, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT(chat_id) DO UPDATE SET
                    messages_json = excluded.messages_json,
                    updated_at = excluded.updated_at
                """,
                (chat_id, raw, time.time()),
            )
        return messages

    async def reset_session(self, chat_id: int) -> None:
        async with await self._connect() as connection:
            await connection.execute(
                "DELETE FROM sessions WHERE chat_id = %s", (chat_id,)
            )

    async def append_log_event(self, event: LogEvent) -> None:
        encoded = event.model_dump_json(exclude_none=True)
        async with await self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO log_events(run_id, sequence, event_json, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (event.run_id, event.sequence, encoded, time.time()),
            )

    async def get_log_jsonl(self, run_id: str) -> str | None:
        async with await self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT event_json FROM log_events
                WHERE run_id = %s ORDER BY sequence ASC
                """,
                (run_id,),
            )
            rows = await cursor.fetchall()
        if not rows:
            return None
        return "".join(f"{row[0]}\n" for row in rows)
