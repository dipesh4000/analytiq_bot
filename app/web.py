from __future__ import annotations

import asyncio
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Response
from telegram import Update

from app.config import Settings
from app.runtime import build_runtime


def create_web_app(settings: Settings | None = None) -> FastAPI:
    selected = settings or Settings.from_env()
    runtime = build_runtime(selected)
    background_tasks: set[asyncio.Task[object]] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        await runtime.telegram.initialize()
        await runtime.telegram.start()
        await runtime.telegram.bot.set_webhook(
            url=selected.webhook_url,
            allowed_updates=["message"],
            secret_token=selected.telegram_webhook_secret,
            drop_pending_updates=False,
        )
        try:
            yield
        finally:
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)
            await runtime.telegram.stop()
            await runtime.telegram.shutdown()

    app = FastAPI(
        title="Analytiq Bot",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = runtime

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready() -> dict[str, str]:
        try:
            await runtime.store.ping()
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Database is unavailable"
            ) from exc
        return {"status": "ready"}

    @app.get("/logs/{run_id}.jsonl")
    async def public_log(run_id: str) -> Response:
        if len(run_id) != 32 or any(char not in "0123456789abcdef" for char in run_id):
            raise HTTPException(status_code=404)
        content = await runtime.store.get_log_jsonl(run_id)
        if content is None:
            raise HTTPException(status_code=404)
        return Response(
            content=content,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    async def telegram_webhook(
        payload: dict,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if not hmac.compare_digest(
            x_telegram_bot_api_secret_token or "",
            selected.telegram_webhook_secret,
        ):
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
        update = Update.de_json(payload, runtime.telegram.bot)
        task = asyncio.create_task(runtime.telegram.process_update(update))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return {"ok": True}

    app.post(selected.webhook_path)(telegram_webhook)
    return app
