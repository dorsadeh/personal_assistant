import asyncio
import logging

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.claude_runner import ClaudeError, run_claude
from bot.config import Config, load_config
from bot.files import MAX_DOWNLOAD_BYTES, dest_path
from bot.git_sync import sync_workspace
from bot.sessions import SessionStore
from bot.telegram_format import chunk_message

log = logging.getLogger("assistant")

HELP_TEXT = (
    "I'm your household assistant. Just talk to me — I keep our shared "
    "todo list, \"remember this\" lists (books, series, places...), ideas, "
    "and travel plans.\n\n"
    "/new — start a fresh conversation (I keep my files, lose the chat thread)\n"
    "/help — this message"
)


async def _run_and_reply(update, context, prompt: str) -> None:
    config: Config = context.bot_data["config"]
    store: SessionStore = context.bot_data["store"]
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    session_id = store.get(chat_id)
    try:
        reply, new_session = await asyncio.to_thread(
            run_claude, prompt, config.workspace_dir, session_id,
            claude_bin=config.claude_bin, timeout=config.claude_timeout,
        )
    except ClaudeError as err:
        if session_id is None:
            await update.effective_message.reply_text(f"Sorry, something went wrong: {err}")
            return
        log.warning("resume of session %s failed (%s); retrying fresh", session_id, err)
        try:
            reply, new_session = await asyncio.to_thread(
                run_claude, prompt, config.workspace_dir, None,
                claude_bin=config.claude_bin, timeout=config.claude_timeout,
            )
        except ClaudeError as err2:
            await update.effective_message.reply_text(f"Sorry, something went wrong: {err2}")
            return
    store.set(chat_id, new_session)
    for chunk in chunk_message(reply):
        await update.effective_message.reply_text(chunk)
    await asyncio.to_thread(sync_workspace, config.workspace_dir, prompt)


async def handle_message(update, context) -> None:
    prompt = f"{_sender_name(update)}: {update.effective_message.text}"
    await _run_and_reply(update, context, prompt)


def _sender_name(update) -> str:
    user = update.effective_message.from_user
    return user.first_name if user and user.first_name else "Someone"


async def handle_file(update, context) -> None:
    config: Config = context.bot_data["config"]
    message = update.effective_message
    if message.document is not None:
        size = message.document.file_size
        original_name = message.document.file_name or "file"
        source = message.document
    else:
        photo = message.photo[-1]
        size = photo.file_size
        original_name = f"photo-{message.date:%Y%m%d-%H%M%S}.jpg"
        source = photo
    if size and size > MAX_DOWNLOAD_BYTES:
        await message.reply_text(
            "That file is over Telegram's 20 MB bot limit — I can't download it. "
            "Can you send a smaller version?"
        )
        return
    dest = dest_path(config.workspace_dir / "files", original_name, f"{message.date:%Y-%m}")
    try:
        tg_file = await source.get_file()
        await tg_file.download_to_drive(dest)
    except Exception:
        log.exception("download failed for %s", dest.name)
        dest.unlink(missing_ok=True)
        await message.reply_text(
            "I couldn't download that file — please try sending it again."
        )
        return
    rel = dest.relative_to(config.workspace_dir)
    caption = message.caption or "(no caption)"
    prompt = (
        f"{_sender_name(update)} sent a file; I saved it to {rel} . "
        f"Their caption: {caption} — file it per your conventions "
        f"(link it from the relevant doc, or ask if unclear)."
    )
    await _run_and_reply(update, context, prompt)


async def handle_unsupported(update, context) -> None:
    await update.effective_message.reply_text(
        "I can only handle text, documents, and photos for now."
    )


async def new_cmd(update, context) -> None:
    store: SessionStore = context.bot_data["store"]
    store.clear(update.effective_chat.id)
    await update.effective_message.reply_text(
        "Fresh conversation started. My files are intact."
    )


async def help_cmd(update, context) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


async def on_error(update, context) -> None:
    log.exception("unhandled error handling update", exc_info=context.error)
    message = getattr(update, "effective_message", None)
    if message is not None:
        try:
            await message.reply_text("Sorry, something went wrong on my side.")
        except Exception:
            log.exception("failed to send error notice")


def build_app(config: Config, store: SessionStore) -> Application:
    app = Application.builder().token(config.bot_token).build()
    allowed = filters.Chat(chat_id=list(config.allowed_chat_ids))
    app.add_handler(CommandHandler("help", help_cmd, filters=allowed))
    app.add_handler(CommandHandler("new", new_cmd, filters=allowed))
    app.add_handler(
        MessageHandler(
            allowed & filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
            handle_message,
        )
    )
    app.add_handler(MessageHandler(
        allowed & (filters.Document.ALL | filters.PHOTO) & filters.UpdateType.MESSAGE,
        handle_file,
    ))
    app.add_handler(MessageHandler(
        allowed & ~filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
        handle_unsupported,
    ))

    async def log_rejected(update, context):
        if update.effective_chat:
            log.info("ignored update from chat %s", update.effective_chat.id)

    app.add_handler(MessageHandler(~allowed, log_rejected))
    app.add_error_handler(on_error)
    app.bot_data["config"] = config
    app.bot_data["store"] = store
    return app


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    config = load_config()
    if not config.workspace_dir.is_dir():
        raise SystemExit(
            f"workspace missing — clone sadeh-family-notebook into "
            f"{config.workspace_dir} (see deploy/SETUP.md)"
        )
    store = SessionStore(config.data_dir / "sessions.json")
    app = build_app(config, store)
    log.info("assistant starting; workspace=%s", config.workspace_dir)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
