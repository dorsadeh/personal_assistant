import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot.main as main_mod
from bot.claude_runner import ClaudeError
from bot.config import Config
from bot.sessions import SessionStore


def _config(tmp_path):
    return Config(
        bot_token="t",
        allowed_chat_ids={-100123},
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        claude_bin="claude",
        claude_timeout=300,
    )


def _update(chat_id=-100123, text="hello"):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id), message=message
    )


def _context(config, store):
    return SimpleNamespace(
        bot_data={"config": config, "store": store},
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_message_gets_claude_reply(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    monkeypatch.setattr(main_mod, "run_claude", lambda *a, **k: ("the reply", "sess-1"))
    update = _update()
    await main_mod.handle_message(update, _context(config, store))
    update.message.reply_text.assert_awaited_once_with("the reply")
    assert store.get(-100123) == "sess-1"


@pytest.mark.asyncio
async def test_resumes_existing_session(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    store.set(-100123, "old-sess")
    seen = {}

    def fake_run(prompt, workspace, session_id=None, **kwargs):
        seen["session_id"] = session_id
        return ("ok", "old-sess")

    monkeypatch.setattr(main_mod, "run_claude", fake_run)
    await main_mod.handle_message(_update(), _context(config, store))
    assert seen["session_id"] == "old-sess"


@pytest.mark.asyncio
async def test_stale_session_retries_fresh(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    store.set(-100123, "stale")
    calls = []

    def fake_run(prompt, workspace, session_id=None, **kwargs):
        calls.append(session_id)
        if session_id is not None:
            raise ClaudeError("No conversation found")
        return ("fresh reply", "new-sess")

    monkeypatch.setattr(main_mod, "run_claude", fake_run)
    update = _update()
    await main_mod.handle_message(update, _context(config, store))
    assert calls == ["stale", None]
    update.message.reply_text.assert_awaited_once_with("fresh reply")
    assert store.get(-100123) == "new-sess"


@pytest.mark.asyncio
async def test_error_reported_to_chat(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")

    def fake_run(*a, **k):
        raise ClaudeError("usage limit reached")

    monkeypatch.setattr(main_mod, "run_claude", fake_run)
    update = _update()
    await main_mod.handle_message(update, _context(config, store))
    (reply,), _ = update.message.reply_text.await_args
    assert "usage limit reached" in reply


@pytest.mark.asyncio
async def test_new_command_clears_session(tmp_path):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    store.set(-100123, "sess")
    update = _update(text="/new")
    await main_mod.new_cmd(update, _context(config, store))
    assert store.get(-100123) is None
    update.message.reply_text.assert_awaited_once()


def test_build_app_registers_handlers(tmp_path):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    app = main_mod.build_app(config, store)
    assert app.bot_data["config"] is config
    assert app.bot_data["store"] is store
    assert len(app.handlers[0]) == 4
