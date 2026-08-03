import asyncio
import logging

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.claude_runner import ClaudeError, run_claude
from bot.config import Config, load_config
from bot.sessions import SessionStore
from bot.telegram_format import chunk_message

log = logging.getLogger("assistant")

HELP_TEXT = (
    "I'm your household assistant. Just talk to me — I keep our shared "
    "todo list, ideas, and travel plans.\n\n"
    "/new — start a fresh conversation (I keep my files, lose the chat thread)\n"
    "/help — this message"
)


async def handle_message(update, context) -> None:
    config: Config = context.bot_data["config"]
    store: SessionStore = context.bot_data["store"]
    chat_id = update.effective_chat.id
    prompt = update.message.text
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    session_id = store.get(chat_id)
    try:
        reply, new_session = await asyncio.to_thread(
            run_claude, prompt, config.workspace_dir, session_id,
            claude_bin=config.claude_bin, timeout=config.claude_timeout,
        )
    except ClaudeError as err:
        if session_id is None:
            await update.message.reply_text(f"Sorry, something went wrong: {err}")
            return
        log.warning("resume of session %s failed (%s); retrying fresh", session_id, err)
        try:
            reply, new_session = await asyncio.to_thread(
                run_claude, prompt, config.workspace_dir, None,
                claude_bin=config.claude_bin, timeout=config.claude_timeout,
            )
        except ClaudeError as err2:
            await update.message.reply_text(f"Sorry, something went wrong: {err2}")
            return

    store.set(chat_id, new_session)
    for chunk in chunk_message(reply):
        await update.message.reply_text(chunk)


async def new_cmd(update, context) -> None:
    store: SessionStore = context.bot_data["store"]
    store.clear(update.effective_chat.id)
    await update.message.reply_text("Fresh conversation started. My files are intact.")


async def help_cmd(update, context) -> None:
    await update.message.reply_text(HELP_TEXT)


def build_app(config: Config, store: SessionStore) -> Application:
    app = Application.builder().token(config.bot_token).build()
    allowed = filters.Chat(chat_id=list(config.allowed_chat_ids))
    app.add_handler(CommandHandler("help", help_cmd, filters=allowed))
    app.add_handler(CommandHandler("new", new_cmd, filters=allowed))
    app.add_handler(
        MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.bot_data["config"] = config
    app.bot_data["store"] = store
    return app


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    config = load_config()
    store = SessionStore(config.data_dir / "sessions.json")
    app = build_app(config, store)
    log.info("assistant starting; workspace=%s", config.workspace_dir)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
