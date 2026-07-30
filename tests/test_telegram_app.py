from __future__ import annotations

import asyncio
from contextlib import suppress

from telegram.constants import ChatAction

from app.telegram_app import _keep_typing


class FakeBot:
    def __init__(self) -> None:
        self.actions: list[tuple[int, str]] = []
        self.two_actions = asyncio.Event()

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        self.actions.append((chat_id, action))
        if len(self.actions) >= 2:
            self.two_actions.set()


async def test_typing_status_is_refreshed_until_cancelled() -> None:
    bot = FakeBot()
    task = asyncio.create_task(
        _keep_typing(bot, 42, interval_seconds=0.001)  # type: ignore[arg-type]
    )
    try:
        async with asyncio.timeout(1):
            await bot.two_actions.wait()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert bot.actions[:2] == [
        (42, ChatAction.TYPING),
        (42, ChatAction.TYPING),
    ]
