from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from telegram import Bot, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import Settings
from app.service import BotService

logger = logging.getLogger(__name__)


async def _keep_typing(
    bot: Bot,
    chat_id: int,
    *,
    interval_seconds: float = 4.0,
) -> None:
    """Refresh Telegram's short-lived typing status until cancelled."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            logger.warning("Could not refresh Telegram typing status", exc_info=True)


def build_telegram_application(
    settings: Settings, service: BotService
) -> Application:
    application = Application.builder().token(settings.bot_api_key).build()

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.message:
            await update.message.reply_text(
                "Send a data-analysis question. Replies are returned as one JSON object."
            )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.message:
            await update.message.reply_text(
                "Send inline data or a question pointing to a public dataset. Use /reset "
                "to clear multi-turn context."
            )

    async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.effective_chat and update.message:
            await service.reset(update.effective_chat.id)
            await update.message.reply_text("Conversation reset.")

    async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat or not message.text:
            return

        with suppress(Exception):
            await context.bot.send_chat_action(
                chat_id=chat.id, action=ChatAction.TYPING
            )
        typing_task = asyncio.create_task(_keep_typing(context.bot, chat.id))
        try:
            result = await service.handle_message(
                chat_id=chat.id,
                user_id=update.effective_user.id if update.effective_user else None,
                text=message.text,
                update_id=update.update_id,
            )
        finally:
            typing_task.cancel()
            with suppress(asyncio.CancelledError):
                await typing_task

        if result is not None:
            await message.reply_text(
                result,
                parse_mode=None,
                disable_web_page_preview=True,
            )

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Telegram update failed", exc_info=context.error)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))
    application.add_error_handler(on_error)
    return application
