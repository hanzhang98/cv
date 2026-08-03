from __future__ import annotations

import logging
from typing import Callable, Awaitable

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import get_settings
from pipeline import IdeaPipeline

logger = logging.getLogger(__name__)

HELP = """Investment Ideas Bot — crowdsourced themes from Substack & Twitter

Commands:
/start — intro
/help — this help
/ideas [n] — top scored ideas (default 8)
/digest — same as /ideas, formatted digest
/theme <id> — filter by theme id (see /themes)
/themes — list thematic scanners
/status — mode & source config

Themes look for catalysts / headwinds / buy-side positioning
(e.g. CXMT→memory, Kimi→AI). WSB-style noise is kept but down-weighted.
"""


def _authorized(update: Update) -> bool:
    settings = get_settings()
    allowed = settings.allowed_chat_ids
    if not allowed:
        return True
    chat = update.effective_chat
    user = update.effective_user
    ids = set()
    if chat:
        ids.add(chat.id)
    if user:
        ids.add(user.id)
    return bool(ids & allowed)


async def _guard(update: Update) -> bool:
    if _authorized(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Unauthorized chat.")
    return False


def _pipeline(context: ContextTypes.DEFAULT_TYPE) -> IdeaPipeline:
    pipe = context.application.bot_data.get("pipeline")
    if pipe is None:
        pipe = IdeaPipeline()
        context.application.bot_data["pipeline"] = pipe
    return pipe


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    await update.effective_message.reply_text(
        "Crowdsourced investment themes from Substack + Twitter.\n"
        "Noise (meme/WSB-style) is filtered down, not deleted.\n\n"
        + HELP
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    await update.effective_message.reply_text(HELP)


async def cmd_themes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    pipe = _pipeline(context)
    lines = ["Tracked themes:"]
    for tid, label, desc in pipe.list_themes():
        lines.append(f"• {tid} — {label}\n  {desc}")
    await update.effective_message.reply_text("\n".join(lines)[:4000])


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    settings = get_settings()
    pipe = _pipeline(context)
    n_sub = len(pipe.sources_cfg.get("substack") or [])
    n_tw = len((pipe.sources_cfg.get("twitter") or {}).get("accounts") or [])
    await update.effective_message.reply_text(
        f"Mode: {settings.bot_mode}\n"
        f"Substack feeds: {n_sub}\n"
        f"Twitter accounts: {n_tw}\n"
        f"Twitter API: {'yes' if settings.twitter_bearer_token else 'no (fixtures/demo)'}\n"
        f"Lookback: {pipe.lookback_hours}h"
    )


async def _send_ideas(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    theme_id: str | None = None,
    limit: int = 8,
) -> None:
    if not await _guard(update):
        return
    pipe = _pipeline(context)
    await update.effective_message.reply_text("Scanning sources…")
    ideas = await pipe.digest(theme_id=theme_id, limit=limit)
    if not ideas:
        await update.effective_message.reply_text(
            "No ideas above the score threshold. Try /themes or widen sources."
        )
        return
    header = f"Top {len(ideas)} ideas"
    if theme_id:
        header += f" · theme `{theme_id}`"
    await update.effective_message.reply_text(header)
    for idea in ideas:
        await update.effective_message.reply_html(
            idea.telegram_html(),
            disable_web_page_preview=True,
        )


async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    limit = 8
    if context.args:
        try:
            limit = max(1, min(15, int(context.args[0])))
        except ValueError:
            pass
    await _send_ideas(update, context, limit=limit)


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_ideas(update, context, limit=10)


async def cmd_theme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /theme <theme_id>\nTry /themes for ids."
        )
        return
    theme_id = context.args[0].strip()
    await _send_ideas(update, context, theme_id=theme_id, limit=8)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    text = (update.effective_message.text or "").strip().lower()
    if text in {"ideas", "digest"}:
        await _send_ideas(update, context)
        return
    await update.effective_message.reply_text("Try /ideas, /themes, or /help")


def build_app(token: str) -> Application:
    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )
    app.bot_data["pipeline"] = IdeaPipeline()
    handlers: list[tuple[str, Callable[..., Awaitable[None]]]] = [
        ("start", cmd_start),
        ("help", cmd_help),
        ("ideas", cmd_ideas),
        ("digest", cmd_digest),
        ("theme", cmd_theme),
        ("themes", cmd_themes),
        ("status", cmd_status),
    ]
    for name, fn in handlers:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit(
            "Set TELEGRAM_BOT_TOKEN in bot/.env (see .env.example). "
            "You can still run: python -m cli digest"
        )
    app = build_app(settings.telegram_bot_token)
    logger.info("Starting bot mode=%s", settings.bot_mode)
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=2.0,
        timeout=30,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
