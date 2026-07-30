from __future__ import annotations

import json

from app.contracts import ConversationMessage
from app.storage import RunLogger, SQLiteStore


async def test_sessions_logs_and_deduplication(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.db", session_ttl_seconds=900)
    store.initialize()

    assert await store.claim_update(10) is True
    assert await store.claim_update(10) is False

    await store.append_message(
        1, ConversationMessage(role="user", content="first")
    )
    messages = await store.append_message(
        1, ConversationMessage(role="assistant", content='{"ok":true}')
    )
    assert [message.role for message in messages] == ["user", "assistant"]

    logger = RunLogger(store, "a" * 32)
    await logger.log("run_started", api_key="must-not-be-logged", value=1)
    await logger.log("run_completed", answer={"value": 2})
    content = await store.get_log_jsonl("a" * 32)
    assert content is not None
    rows = [json.loads(line) for line in content.splitlines()]
    assert [row["event"] for row in rows] == ["run_started", "run_completed"]
    assert "api_key" not in rows[0]["data"]
