# Personal Assistant Phase 1 (Core Loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Telegram bot on this PC that forwards messages from one whitelisted group chat to headless Claude Code (`claude -p`) running in a file-based workspace, and replies with Claude's answer — giving Dor and his wife a shared assistant for todos, ideas, and travel notes.

**Architecture:** A thin Python daemon (`bot/`) long-polls Telegram, processes messages serially, and shells out to `claude -p --output-format json` with `cwd=workspace/`. The workspace is the assistant's entire world: persona in `CLAUDE.md`, data as markdown files, permissions locked down via `workspace/.claude/settings.json`. One resumable Claude session per chat, stored in `data/sessions.json`.

**Tech Stack:** Python 3.12, python-telegram-bot ≥21 (async), python-dotenv, pytest + pytest-asyncio, Claude Code CLI 2.x (subscription auth), systemd user unit.

## Global Constraints

- Spec: `docs/specs/2026-07-16-personal-assistant-design.md` — Phase 1 only (no reminders, no calendar yet).
- Security boundary: the bot must ignore every update not from `ALLOWED_CHAT_IDS`.
- Headless Claude must not touch anything outside the workspace: permissions via `workspace/.claude/settings.json`, `Bash` denied.
- Claude invocation verified on this machine: `claude -p --output-format json` returns JSON with `result`, `session_id`, `is_error` fields; resume flag is `--resume <session_id>`; `claude` binary at `~/.local/bin/claude`.
- Telegram message limit is 4096 chars — long replies must be chunked.
- Secrets (`.env`, `data/`, `.venv/`) must never be committed.
- All commits on `main`, small and frequent, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Project scaffolding + config module

**Files:**
- Create: `.gitignore`, `.env.example`, `requirements.txt`, `bot/__init__.py`, `bot/config.py`
- Test: `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(env) -> Config` where `Config` is a dataclass with fields `bot_token: str`, `allowed_chat_ids: set[int]`, `workspace_dir: Path`, `data_dir: Path`, `claude_bin: str`, `claude_timeout: int`. Later tasks import `from bot.config import Config, load_config`.

- [ ] **Step 1: Create venv and install deps**

```bash
cd /home/dorsadeh/workspace/sandbox/personal_projects/personal_assistant
python3 -m venv .venv
printf 'python-telegram-bot>=21\npython-dotenv>=1\npytest>=8\npytest-asyncio>=0.23\n' > requirements.txt
.venv/bin/pip install -r requirements.txt
```

- [ ] **Step 2: Write `.gitignore` and `.env.example`**

`.gitignore`:
```
.venv/
.env
data/
__pycache__/
*.pyc
.pytest_cache/
```

`.env.example`:
```
# Token from @BotFather
TELEGRAM_BOT_TOKEN=123456:ABC...
# Comma-separated Telegram chat IDs allowed to use the bot (group IDs are negative)
ALLOWED_CHAT_IDS=-1001234567890
# Optional overrides
#CLAUDE_BIN=claude
#CLAUDE_TIMEOUT=300
#WORKSPACE_DIR=/path/to/workspace
#DATA_DIR=/path/to/data
```

- [ ] **Step 3: Write the failing test** — `tests/test_config.py`:

```python
import pytest

from bot.config import load_config


def _env(**overrides):
    env = {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "ALLOWED_CHAT_IDS": "-100123, 456",
    }
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def test_loads_token_and_chat_ids():
    config = load_config(_env())
    assert config.bot_token == "123:abc"
    assert config.allowed_chat_ids == {-100123, 456}


def test_defaults():
    config = load_config(_env())
    assert config.claude_bin == "claude"
    assert config.claude_timeout == 300
    assert config.workspace_dir.name == "workspace"
    assert config.data_dir.name == "data"


def test_missing_token_raises():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        load_config(_env(TELEGRAM_BOT_TOKEN=None))


def test_missing_chat_ids_raises():
    with pytest.raises(ValueError, match="ALLOWED_CHAT_IDS"):
        load_config(_env(ALLOWED_CHAT_IDS=""))
```

Also create empty `bot/__init__.py` and `tests/__init__.py`.

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'bot.config'`

- [ ] **Step 5: Write `bot/config.py`**

```python
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_chat_ids: set[int]
    workspace_dir: Path
    data_dir: Path
    claude_bin: str
    claude_timeout: int


def load_config(env=None) -> Config:
    if env is None:
        env = os.environ
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    raw_ids = env.get("ALLOWED_CHAT_IDS", "")
    chat_ids = {int(part) for part in raw_ids.replace(" ", "").split(",") if part}
    if not chat_ids:
        raise ValueError("ALLOWED_CHAT_IDS is required (comma-separated chat IDs)")
    return Config(
        bot_token=token,
        allowed_chat_ids=chat_ids,
        workspace_dir=Path(env.get("WORKSPACE_DIR", PROJECT_ROOT / "workspace")),
        data_dir=Path(env.get("DATA_DIR", PROJECT_ROOT / "data")),
        claude_bin=env.get("CLAUDE_BIN", "claude"),
        claude_timeout=int(env.get("CLAUDE_TIMEOUT", "300")),
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add .gitignore .env.example requirements.txt bot/ tests/
git commit -m "feat: project scaffolding and config module"
```

---

### Task 2: Claude runner

**Files:**
- Create: `bot/claude_runner.py`
- Test: `tests/test_claude_runner.py`

**Interfaces:**
- Produces: `run_claude(prompt: str, workspace: Path, session_id: str | None = None, claude_bin: str = "claude", timeout: int = 300) -> tuple[str, str]` returning `(reply_text, session_id)`; raises `ClaudeError(Exception)` on failure. `build_command(prompt, session_id, claude_bin) -> list[str]` exposed for testing.

- [ ] **Step 1: Write the failing test** — `tests/test_claude_runner.py`:

```python
import json
import subprocess
from types import SimpleNamespace

import pytest

from bot.claude_runner import ClaudeError, build_command, run_claude


def _fake_result(payload, returncode=0, stderr=""):
    return SimpleNamespace(
        stdout=json.dumps(payload) if isinstance(payload, dict) else payload,
        stderr=stderr,
        returncode=returncode,
    )


SUCCESS = {"is_error": False, "result": "done!", "session_id": "abc-123", "type": "result"}


def test_build_command_new_session():
    cmd = build_command("hello", None, "claude")
    assert cmd == ["claude", "-p", "--output-format", "json", "hello"]


def test_build_command_resume():
    cmd = build_command("hello", "abc-123", "claude")
    assert "--resume" in cmd and "abc-123" in cmd
    assert cmd[-1] == "hello"


def test_run_claude_success(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _fake_result(SUCCESS)

    monkeypatch.setattr(subprocess, "run", fake_run)
    reply, session = run_claude("hi", tmp_path)
    assert reply == "done!"
    assert session == "abc-123"
    assert captured["kwargs"]["cwd"] == tmp_path


def test_run_claude_error_flag(monkeypatch, tmp_path):
    payload = {"is_error": True, "result": "usage limit reached", "session_id": "x"}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_result(payload))
    with pytest.raises(ClaudeError, match="usage limit"):
        run_claude("hi", tmp_path)


def test_run_claude_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _fake_result("", returncode=1, stderr="boom")
    )
    with pytest.raises(ClaudeError, match="boom"):
        run_claude("hi", tmp_path)


def test_run_claude_timeout(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 300))

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeError, match="timed out"):
        run_claude("hi", tmp_path, timeout=5)


def test_run_claude_bad_json(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_result("not json"))
    with pytest.raises(ClaudeError, match="unexpected output"):
        run_claude("hi", tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_claude_runner.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'bot.claude_runner'`

- [ ] **Step 3: Write `bot/claude_runner.py`**

```python
import json
import subprocess
from pathlib import Path


class ClaudeError(Exception):
    """Raised when a headless Claude invocation fails."""


def build_command(prompt: str, session_id: str | None, claude_bin: str) -> list[str]:
    cmd = [claude_bin, "-p", "--output-format", "json"]
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)
    return cmd


def run_claude(
    prompt: str,
    workspace: Path,
    session_id: str | None = None,
    claude_bin: str = "claude",
    timeout: int = 300,
) -> tuple[str, str]:
    cmd = build_command(prompt, session_id, claude_bin)
    try:
        proc = subprocess.run(
            cmd, cwd=workspace, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"Claude timed out after {timeout}s")
    except FileNotFoundError:
        raise ClaudeError(f"claude binary not found: {claude_bin}")
    if proc.returncode != 0:
        raise ClaudeError(proc.stderr.strip() or f"claude exited with {proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ClaudeError(f"claude returned unexpected output: {proc.stdout[:200]}")
    if data.get("is_error"):
        raise ClaudeError(data.get("result") or "unknown Claude error")
    return data["result"], data["session_id"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_claude_runner.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add bot/claude_runner.py tests/test_claude_runner.py
git commit -m "feat: headless claude runner with JSON output parsing"
```

---

### Task 3: Session store

**Files:**
- Create: `bot/sessions.py`
- Test: `tests/test_sessions.py`

**Interfaces:**
- Produces: `SessionStore(path: Path)` with methods `get(chat_id: int) -> str | None`, `set(chat_id: int, session_id: str) -> None`, `clear(chat_id: int) -> None`. JSON file keyed by stringified chat id.

- [ ] **Step 1: Write the failing test** — `tests/test_sessions.py`:

```python
from bot.sessions import SessionStore


def test_get_missing_returns_none(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    assert store.get(-100123) is None


def test_set_then_get(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.set(-100123, "abc-123")
    assert store.get(-100123) == "abc-123"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "sessions.json"
    SessionStore(path).set(-100123, "abc-123")
    assert SessionStore(path).get(-100123) == "abc-123"


def test_clear(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.set(-100123, "abc-123")
    store.clear(-100123)
    assert store.get(-100123) is None


def test_clear_missing_is_noop(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.clear(-100123)  # must not raise


def test_creates_parent_dir(tmp_path):
    store = SessionStore(tmp_path / "nested" / "sessions.json")
    store.set(1, "s")
    assert store.get(1) == "s"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_sessions.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'bot.sessions'`

- [ ] **Step 3: Write `bot/sessions.py`**

```python
import json
from pathlib import Path


class SessionStore:
    """Maps Telegram chat id -> Claude session id, persisted as JSON."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def get(self, chat_id: int) -> str | None:
        return self._load().get(str(chat_id))

    def set(self, chat_id: int, session_id: str) -> None:
        data = self._load()
        data[str(chat_id)] = session_id
        self._save(data)

    def clear(self, chat_id: int) -> None:
        data = self._load()
        if data.pop(str(chat_id), None) is not None:
            self._save(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_sessions.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add bot/sessions.py tests/test_sessions.py
git commit -m "feat: per-chat claude session persistence"
```

---

### Task 4: Reply chunking

**Files:**
- Create: `bot/telegram_format.py`
- Test: `tests/test_telegram_format.py`

**Interfaces:**
- Produces: `chunk_message(text: str, limit: int = 4096) -> list[str]` — non-empty list, every element ≤ limit, prefers splitting on newlines.

- [ ] **Step 1: Write the failing test** — `tests/test_telegram_format.py`:

```python
from bot.telegram_format import chunk_message


def test_short_message_single_chunk():
    assert chunk_message("hello") == ["hello"]


def test_empty_message_yields_placeholder():
    assert chunk_message("   ") == ["(empty reply)"]


def test_long_message_split_within_limit():
    text = "\n".join(f"line {i}" for i in range(1000))
    chunks = chunk_message(text, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(c + "\n" for c in chunks).strip() == text


def test_splits_on_newline_boundary():
    text = "a" * 90 + "\n" + "b" * 90
    chunks = chunk_message(text, limit=100)
    assert chunks == ["a" * 90, "b" * 90]


def test_hard_split_without_newlines():
    text = "x" * 250
    chunks = chunk_message(text, limit=100)
    assert chunks == ["x" * 100, "x" * 100, "x" * 50]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_telegram_format.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'bot.telegram_format'`

- [ ] **Step 3: Write `bot/telegram_format.py`**

```python
TELEGRAM_LIMIT = 4096


def chunk_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split text into Telegram-sized chunks, preferring newline boundaries."""
    text = text.strip()
    if not text:
        return ["(empty reply)"]
    chunks = []
    while len(text) > limit:
        split = text.rfind("\n", 0, limit + 1)
        if split <= 0:
            split = limit
        chunks.append(text[:split].rstrip("\n"))
        text = text[split:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks or ["(empty reply)"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_telegram_format.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add bot/telegram_format.py tests/test_telegram_format.py
git commit -m "feat: telegram reply chunking"
```

---

### Task 5: Bot wiring (handlers + main)

**Files:**
- Create: `bot/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `load_config` (Task 1), `run_claude`/`ClaudeError` (Task 2), `SessionStore` (Task 3), `chunk_message` (Task 4).
- Produces: `handle_message(update, context)`, `new_cmd(update, context)`, `help_cmd(update, context)` async handlers; `build_app(config, store)` returning a configured `telegram.ext.Application`; `main()` entrypoint runnable as `python -m bot.main`.

- [ ] **Step 1: Write the failing test** — `tests/test_main.py`:

Handlers read config/store from `context.bot_data`, so they can be tested with `SimpleNamespace` + `AsyncMock` — no Telegram network involved.

```python
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
    assert len(app.handlers[0]) == 3
```

Add `pytest.ini` at project root so pytest-asyncio works without per-test decorator noise being an issue:

```ini
[pytest]
asyncio_mode = auto
```

(With `asyncio_mode = auto` the `@pytest.mark.asyncio` decorators are harmless and explicit.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_main.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'bot.main'`

- [ ] **Step 3: Write `bot/main.py`**

```python
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
            config.claude_bin, config.claude_timeout,
        )
    except ClaudeError as err:
        if session_id is None:
            await update.message.reply_text(f"Sorry, something went wrong: {err}")
            return
        log.warning("resume of session %s failed (%s); retrying fresh", session_id, err)
        try:
            reply, new_session = await asyncio.to_thread(
                run_claude, prompt, config.workspace_dir, None,
                config.claude_bin, config.claude_timeout,
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
```

Note: updates are processed **serially** — python-telegram-bot's default (`concurrent_updates=False`), which is exactly what we want so Claude runs never overlap in the workspace.

- [ ] **Step 4: Run all tests to verify they pass**

Run: `.venv/bin/pytest -v`
Expected: all tests pass (config 4, runner 7, sessions 6, format 5, main 6)

- [ ] **Step 5: Commit**

```bash
git add bot/main.py tests/test_main.py pytest.ini
git commit -m "feat: telegram bot wiring with whitelist, sessions, error handling"
```

---

### Task 6: Assistant workspace (persona + permissions + seed files)

**Files:**
- Create: `workspace/CLAUDE.md`, `workspace/todos.md`, `workspace/ideas/.gitkeep`, `workspace/travel/.gitkeep`, `workspace/.claude/settings.json`

**Interfaces:**
- Consumes: nothing from code — this is the content `run_claude` operates on (`cwd=workspace/`).
- Produces: the assistant's behavior contract; Phase 2/3 will extend `CLAUDE.md` with reminder and calendar conventions.

- [ ] **Step 1: Write `workspace/.claude/settings.json`** — locks headless Claude inside the workspace:

```json
{
  "model": "sonnet",
  "permissions": {
    "allow": [
      "Read(./**)",
      "Write(./**)",
      "Edit(./**)",
      "Glob(./**)",
      "Grep(./**)",
      "WebSearch",
      "WebFetch"
    ],
    "deny": [
      "Bash",
      "Read(./.claude/**)",
      "Write(./.claude/**)",
      "Edit(./.claude/**)"
    ]
  }
}
```

`model: sonnet` keeps quota usage low for everyday assistant work; bump to a bigger model later if needed. In headless mode anything not allowed is simply denied (no prompt), so this is a hard sandbox.

- [ ] **Step 2: Write `workspace/CLAUDE.md`**:

```markdown
# Household Assistant

You are the shared personal assistant for Dor and his wife. You talk with them
in a Telegram group chat. Your replies are sent verbatim to Telegram.

## Reply style
- Warm, brief, practical. No headers, no markdown tables, no code blocks —
  Telegram shows plain text. Short lists with "-" are fine.
- Answer in the language you were addressed in (Hebrew or English).
- When you change a file, confirm in one short sentence what you did.

## Your files (your only memory besides this conversation)
- `todos.md` — the shared todo list. Format: `- [ ] task` under a `## Section`
  heading; add `(Dor)` or `(wife)` when a task belongs to one person.
  Mark done with `- [x]`, and move done items to the `## Done` section at the
  bottom. Never delete done items.
- `ideas/` — one markdown file per idea, kebab-case filename
  (e.g. `balcony-garden.md`). Start each file with a one-line summary.
- `travel/` — one markdown file per trip (e.g. `2026-10-rome.md`) holding
  plans, links, bookings, and open questions for that trip.

## Rules
- Anything worth remembering goes into a file — the conversation may be reset
  at any time, files are forever.
- When asked "what's on our list" style questions, read the file fresh and
  summarize; don't answer from conversation memory.
- If a request is ambiguous (whose task? which trip?), ask one short question.
- You can search the web for research (restaurants, flights, ideas) and save
  findings into the relevant file.
```

- [ ] **Step 3: Write seed `workspace/todos.md`**:

```markdown
# Shared Todos

## Inbox

## Done
```

Create empty `workspace/ideas/.gitkeep` and `workspace/travel/.gitkeep`.

- [ ] **Step 4: Verify the sandbox actually works** (headless smoke test):

```bash
cd workspace
claude -p "Add 'buy milk (Dor)' to the todo list, then reply with one confirmation sentence." --output-format json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['is_error'], d['result'])"
grep "buy milk" todos.md
claude -p "Run the shell command 'whoami' and tell me the output." --output-format json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result'])"
cd ..
```

Expected: first command prints `False` + a confirmation; `grep` finds the item; third reply says it cannot run shell commands (Bash denied). Afterwards reset the seed file: `git checkout workspace/todos.md` is not possible yet (not committed) — just edit `todos.md` back to the seed content before committing.

- [ ] **Step 5: Commit**

```bash
git add workspace/
git commit -m "feat: assistant workspace with persona, sandbox permissions, seed files"
```

---

### Task 7: Deployment (systemd) + README

**Files:**
- Create: `deploy/assistant.service`, `deploy/SETUP.md`, `README.md`

**Interfaces:**
- Consumes: `python -m bot.main` entrypoint (Task 5), `.env` contract (Task 1).

- [ ] **Step 1: Write `deploy/assistant.service`** (systemd **user** unit):

```ini
[Unit]
Description=Household assistant Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=%h/workspace/sandbox/personal_projects/personal_assistant
ExecStart=%h/workspace/sandbox/personal_projects/personal_assistant/.venv/bin/python -m bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

(`.env` is loaded by the app itself via python-dotenv from the working directory, so no `EnvironmentFile` needed.)

- [ ] **Step 2: Write `deploy/SETUP.md`** — full from-scratch install guide for the future server move:

```markdown
# Setup on a new machine

1. Install prerequisites: git, python3.12+, Node 18+ (for Claude Code).
2. Install Claude Code: `npm install -g @anthropic-ai/claude-code`
3. Authenticate with the Claude subscription (one-time, needs a browser
   anywhere): run `claude setup-token` on any machine, copy the token, and on
   the server put it in the service environment:
   add `CLAUDE_CODE_OAUTH_TOKEN=...` to `.env`.
4. Clone: `git clone https://github.com/dorsadeh/personal_assistant.git && cd personal_assistant`
5. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
6. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN` and `ALLOWED_CHAT_IDS`.
7. Test in foreground: `.venv/bin/python -m bot.main` — send a message in the
   group, expect a reply. Ctrl-C when satisfied.
8. Install the service:
   mkdir -p ~/.config/systemd/user
   cp deploy/assistant.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now assistant
   loginctl enable-linger $USER   # keep it running after logout
9. Logs: `journalctl --user -u assistant -f`

Note: if the repo lives at a different path on the new machine, edit the two
paths in `assistant.service` accordingly.
```

- [ ] **Step 3: Write `README.md`**:

```markdown
# Personal Assistant

A Telegram bot for our household — shared todos, ideas, travel plans —
powered by headless Claude Code running in `workspace/`.

- Design spec: `docs/specs/2026-07-16-personal-assistant-design.md`
- Setup guide: `deploy/SETUP.md`
- Run tests: `.venv/bin/pytest`
- Run locally: `.venv/bin/python -m bot.main`

## One-time Telegram setup
1. In Telegram, talk to @BotFather → `/newbot` → pick a name and username →
   copy the token into `.env` as `TELEGRAM_BOT_TOKEN`.
2. In BotFather: `/setprivacy` → select the bot → **Disable** (so it sees all
   group messages).
3. Create a group with you, your wife, and the bot.
4. Get the group chat id: run the bot once with a placeholder
   `ALLOWED_CHAT_IDS=0`, send a message in the group, and read the rejected
   chat id from the log line — or message @userinfobot in the group.
   Put it in `.env` as `ALLOWED_CHAT_IDS` (group ids are negative).

## Architecture
Telegram group → python-telegram-bot daemon (serial queue) →
`claude -p --resume <session>` in `workspace/` → reply → Telegram.
The workspace is sandboxed by `workspace/.claude/settings.json`
(file tools + web only, no Bash). Data lives in markdown files, tracked in git.
```

- [ ] **Step 4: Add a rejected-update log line** so step 4 of the README works. In `bot/main.py`, add after the three `add_handler` calls in `build_app`:

```python
    async def log_rejected(update, context):
        if update.effective_chat:
            log.info("ignored update from chat %s", update.effective_chat.id)

    app.add_handler(MessageHandler(~allowed, log_rejected))
```

Run: `.venv/bin/pytest -v` — the `test_build_app_registers_handlers` assertion changes from 3 to 4 handlers; update that test accordingly:

```python
    assert len(app.handlers[0]) == 4
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add deploy/ README.md bot/main.py tests/test_main.py
git commit -m "feat: systemd unit, setup guide, README, rejected-chat logging"
```

---

### Task 8: End-to-end verification (manual, with Dor)

**Files:** none (verification only)

This task needs Dor's involvement (BotFather token, group creation).

- [ ] **Step 1:** Dor creates the bot via @BotFather, disables privacy mode, creates the group, fills `.env` (see README). 
- [ ] **Step 2:** Run in foreground: `.venv/bin/python -m bot.main`
- [ ] **Step 3:** In the group, send: `add "buy milk" to our todo list` → expect a confirmation reply and the item in `workspace/todos.md`.
- [ ] **Step 4:** Send: `what's on our todo list?` → expect the item listed back.
- [ ] **Step 5:** Send a message from a private chat with the bot (not the group) → expect no reply + an `ignored update` log line.
- [ ] **Step 6:** Send `/new`, then `what did I just ask you?` → expect it not to know (fresh session) but todos still intact.
- [ ] **Step 7:** Install the systemd unit per `deploy/SETUP.md` step 8; `systemctl --user status assistant` shows active; kill the process and confirm systemd restarts it; send another group message → reply arrives.
- [ ] **Step 8:** Commit workspace data changes if any, push: `git push`.

---

## Deferred to later phases (per spec)
- Phase 2: `reminders.json` + in-daemon scheduler + morning agenda.
- Phase 3: Google Calendar MCP (events-only OAuth scope).
- Phase 4: backup remote for workspace data, server migration.
