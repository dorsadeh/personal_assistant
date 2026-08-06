import asyncio
from datetime import datetime
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
    message = SimpleNamespace(
        text=text, reply_text=AsyncMock(), from_user=SimpleNamespace(first_name="Dor")
    )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=message,
        effective_message=message,
    )


def _context(config, store):
    return SimpleNamespace(
        bot_data={"config": config, "store": store},
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
    )


def _file_update(document=None, photo=None, caption=None):
    message = SimpleNamespace(
        document=document,
        photo=photo,
        caption=caption,
        date=datetime(2026, 8, 6, 12, 0),
        reply_text=AsyncMock(),
        from_user=SimpleNamespace(first_name="Dor"),
    )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123),
        message=message,
        effective_message=message,
    )


@pytest.mark.asyncio
async def test_message_gets_claude_reply(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    monkeypatch.setattr(main_mod, "run_claude", lambda *a, **k: ("the reply", "sess-1"))
    sync_calls = []
    monkeypatch.setattr(
        main_mod,
        "sync_workspace",
        lambda workspace, summary: sync_calls.append((workspace, summary)),
    )
    update = _update()
    await main_mod.handle_message(update, _context(config, store))
    update.message.reply_text.assert_awaited_once_with("the reply")
    assert store.get(-100123) == "sess-1"
    assert sync_calls == [(config.workspace_dir, "Dor: hello")]


@pytest.mark.asyncio
async def test_prompt_carries_sender_name(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    seen = {}

    def fake_run(prompt, workspace, session_id=None, **kwargs):
        seen["prompt"] = prompt
        return ("ok", "sess-1")

    monkeypatch.setattr(main_mod, "run_claude", fake_run)
    monkeypatch.setattr(main_mod, "sync_workspace", lambda *a, **k: None)
    await main_mod.handle_message(_update(), _context(config, store))
    assert seen["prompt"] == "Dor: hello"


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
    monkeypatch.setattr(main_mod, "sync_workspace", lambda *a, **k: None)
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
    sync_calls = []
    monkeypatch.setattr(
        main_mod,
        "sync_workspace",
        lambda workspace, summary: sync_calls.append((workspace, summary)),
    )
    update = _update()
    await main_mod.handle_message(update, _context(config, store))
    assert calls == ["stale", None]
    update.message.reply_text.assert_awaited_once_with("fresh reply")
    assert store.get(-100123) == "new-sess"
    assert sync_calls == [(config.workspace_dir, "Dor: hello")]


@pytest.mark.asyncio
async def test_error_reported_to_chat(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")

    def fake_run(*a, **k):
        raise ClaudeError("usage limit reached")

    monkeypatch.setattr(main_mod, "run_claude", fake_run)
    sync_calls = []
    monkeypatch.setattr(
        main_mod,
        "sync_workspace",
        lambda workspace, summary: sync_calls.append((workspace, summary)),
    )
    update = _update()
    await main_mod.handle_message(update, _context(config, store))
    (reply,), _ = update.message.reply_text.await_args
    assert "usage limit reached" in reply
    assert sync_calls == []


@pytest.mark.asyncio
async def test_handle_message_uses_effective_message_when_message_is_none(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    monkeypatch.setattr(main_mod, "run_claude", lambda *a, **k: ("the reply", "sess-1"))
    monkeypatch.setattr(main_mod, "sync_workspace", lambda *a, **k: None)
    effective_message = SimpleNamespace(
        text="hello", reply_text=AsyncMock(), from_user=SimpleNamespace(first_name="Dor")
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123),
        message=None,
        effective_message=effective_message,
    )
    await main_mod.handle_message(update, _context(config, store))
    effective_message.reply_text.assert_awaited_once_with("the reply")
    assert store.get(-100123) == "sess-1"


@pytest.mark.asyncio
async def test_new_command_clears_session(tmp_path):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    store.set(-100123, "sess")
    update = _update(text="/new")
    await main_mod.new_cmd(update, _context(config, store))
    assert store.get(-100123) is None
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_document_downloaded_and_prompt_built(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    download_calls = []

    async def fake_download_to_drive(path):
        download_calls.append(path)

    document = SimpleNamespace(
        file_size=1024,
        file_name="Road Toll.pdf",
        get_file=AsyncMock(
            return_value=SimpleNamespace(
                download_to_drive=AsyncMock(side_effect=fake_download_to_drive)
            )
        ),
    )
    update = _file_update(document=document, caption="pay by Friday")

    seen = {}

    def fake_run(prompt, workspace, session_id=None, *args, **kwargs):
        seen["prompt"] = prompt
        return ("ok", "sess-1")

    monkeypatch.setattr(main_mod, "run_claude", fake_run)
    monkeypatch.setattr(main_mod, "sync_workspace", lambda *a, **k: None)

    await main_mod.handle_file(update, _context(config, store))

    assert len(download_calls) == 1
    dest = download_calls[0]
    assert dest.parent == tmp_path / "ws" / "files" / "2026-08"
    assert dest.name == "Road-Toll.pdf"
    assert "files/2026-08/Road-Toll.pdf" in seen["prompt"]
    assert "pay by Friday" in seen["prompt"]


@pytest.mark.asyncio
async def test_oversized_document_refused(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    document = SimpleNamespace(
        file_size=25 * 1024 * 1024,
        file_name="big.pdf",
        get_file=AsyncMock(),
    )
    update = _file_update(document=document, caption=None)

    run_calls = []
    monkeypatch.setattr(
        main_mod, "run_claude", lambda *a, **k: run_calls.append(1) or ("ok", "sess-1")
    )
    monkeypatch.setattr(main_mod, "sync_workspace", lambda *a, **k: None)

    await main_mod.handle_file(update, _context(config, store))

    (reply,), _ = update.message.reply_text.await_args
    assert "20 MB" in reply
    assert run_calls == []
    document.get_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_photo_named_by_date(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    download_calls = []

    async def fake_download_to_drive(path):
        download_calls.append(path)

    photo = SimpleNamespace(
        file_size=1024,
        get_file=AsyncMock(
            return_value=SimpleNamespace(
                download_to_drive=AsyncMock(side_effect=fake_download_to_drive)
            )
        ),
    )
    update = _file_update(photo=[photo], caption=None)

    seen = {}

    def fake_run(prompt, workspace, session_id=None, *args, **kwargs):
        seen["prompt"] = prompt
        return ("ok", "sess-1")

    monkeypatch.setattr(main_mod, "run_claude", fake_run)
    monkeypatch.setattr(main_mod, "sync_workspace", lambda *a, **k: None)

    await main_mod.handle_file(update, _context(config, store))

    assert download_calls[0].name == "photo-20260806-120000.jpg"
    assert "photo-20260806-120000.jpg" in seen["prompt"]


@pytest.mark.asyncio
async def test_unsupported_type_notice(tmp_path):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    update = _file_update()
    await main_mod.handle_unsupported(update, _context(config, store))
    update.message.reply_text.assert_awaited_once_with(
        "I can only handle text, documents, and photos for now."
    )


def test_build_app_registers_handlers(tmp_path):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    app = main_mod.build_app(config, store)
    assert app.bot_data["config"] is config
    assert app.bot_data["store"] is store
    assert len(app.handlers[0]) == 6


def test_build_app_registers_error_handler(tmp_path):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    app = main_mod.build_app(config, store)
    assert app.error_handlers


@pytest.mark.asyncio
async def test_failed_download_cleans_up_and_replies(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = SessionStore(tmp_path / "sessions.json")
    called = []
    monkeypatch.setattr(main_mod, "run_claude", lambda *a, **k: called.append(a) or ("x", "s"))

    async def boom(*a, **k):
        raise RuntimeError("network died")

    document = SimpleNamespace(
        file_size=1000,
        file_name="doc.pdf",
        get_file=AsyncMock(side_effect=boom),
    )
    update = _file_update(document=document)
    await main_mod.handle_file(update, _context(config, store))
    (reply,), _ = update.effective_message.reply_text.await_args
    assert "try sending it again" in reply
    assert called == []
    assert not list((tmp_path / "ws" / "files").rglob("*.pdf")) if (tmp_path / "ws" / "files").exists() else True
