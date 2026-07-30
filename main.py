from __future__ import annotations

import logging

import uvicorn

from app.config import Settings
from app.runtime import build_runtime
from app.web import create_web_app


def configure_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    if settings.bot_mode == "polling":
        runtime = build_runtime(settings)
        runtime.telegram.run_polling(
            allowed_updates=["message"],
            drop_pending_updates=False,
        )
        return
    uvicorn.run(
        create_web_app(settings),
        host="0.0.0.0",
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
