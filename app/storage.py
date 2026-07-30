from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Protocol

from app.contracts import ConversationMessage, LogEvent


class Store(Protocol):
    def initialize(self) -> None: ...

    async def ping(self) -> None: ...

    def chat_lock(self, chat_id: int) -> asyncio.Lock: ...

    async def claim_update(self, update_id: int) -> bool: ...

    async def get_messages(self, chat_id: int) -> list[ConversationMessage]: ...

    async def append_message(
        self, chat_id: int, message: ConversationMessage, *, max_messages: int = 12
    ) -> list[ConversationMessage]: ...

    async def reset_session(self, chat_id: int) -> None: ...

    async def append_log_event(self, event: LogEvent) -> None: ...

    async def get_log_jsonl(self, run_id: str) -> str | None: ...


class SQLiteStore:
    """Small persistent store for sessions, deduplication, and public run logs."""

    def __init__(self, path: Path, session_ttl_seconds: int) -> None:
        self.path = path
        self.session_ttl_seconds = session_ttl_seconds
        self._db_lock = asyncio.Lock()
        self._chat_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    chat_id INTEGER PRIMARY KEY,
                    messages_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_updates (
                    update_id INTEGER PRIMARY KEY,
                    processed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS log_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_log_events_run
                    ON log_events(run_id, sequence);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def chat_lock(self, chat_id: int) -> asyncio.Lock:
        return self._chat_locks[chat_id]

    async def ping(self) -> None:
        async with self._db_lock:
            with self._connect() as connection:
                connection.execute("SELECT 1").fetchone()

    async def claim_update(self, update_id: int) -> bool:
        async with self._db_lock:
            try:
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO processed_updates(update_id, processed_at) VALUES (?, ?)",
                        (update_id, time.time()),
                    )
                return True
            except sqlite3.IntegrityError:
                return False

    async def get_messages(self, chat_id: int) -> list[ConversationMessage]:
        async with self._db_lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT messages_json, updated_at FROM sessions WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
                if row is None:
                    return []
                if time.time() - float(row[1]) > self.session_ttl_seconds:
                    connection.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
                    return []
                return [
                    ConversationMessage.model_validate(item)
                    for item in json.loads(row[0])
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
        async with self._db_lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO sessions(chat_id, messages_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        messages_json = excluded.messages_json,
                        updated_at = excluded.updated_at
                    """,
                    (chat_id, raw, time.time()),
                )
        return messages

    async def reset_session(self, chat_id: int) -> None:
        async with self._db_lock:
            with self._connect() as connection:
                connection.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))

    async def append_log_event(self, event: LogEvent) -> None:
        encoded = event.model_dump_json(exclude_none=True)
        async with self._db_lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO log_events(run_id, sequence, event_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (event.run_id, event.sequence, encoded, time.time()),
                )

    async def get_log_jsonl(self, run_id: str) -> str | None:
        async with self._db_lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT event_json FROM log_events
                    WHERE run_id = ? ORDER BY sequence ASC
                    """,
                    (run_id,),
                ).fetchall()
        if not rows:
            return None
        return "".join(f"{row[0]}\n" for row in rows)


class RunLogger:
    def __init__(self, store: Store, run_id: str) -> None:
        self.store = store
        self.run_id = run_id
        self.sequence = 0

    async def log(self, event: str, **data: Any) -> None:
        safe_data = _truncate(data)
        item = LogEvent(
            run_id=self.run_id,
            sequence=self.sequence,
            event=event,
            data=safe_data,
        )
        await self.store.append_log_event(item)
        self.sequence += 1


def _truncate(value: Any, *, max_string: int = 8_000, depth: int = 0) -> Any:
    if depth > 6:
        return "<truncated>"
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + "…"
    if isinstance(value, dict):
        return {
            str(key): _truncate(item, max_string=max_string, depth=depth + 1)
            for key, item in list(value.items())[:100]
            if "token" not in str(key).lower()
            and "authorization" not in str(key).lower()
            and "api_key" not in str(key).lower()
        }
    if isinstance(value, (list, tuple)):
        return [
            _truncate(item, max_string=max_string, depth=depth + 1)
            for item in list(value)[:100]
        ]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)
