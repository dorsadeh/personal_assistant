# File Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Documents (PDFs etc.) and photos sent to the Telegram group get downloaded into the notebook (`workspace/files/YYYY-MM/`), announced to the assistant (with the caption) so it files/links them in the right doc, and synced to GitHub like everything else. Other non-text types get a polite "can't handle that yet" reply instead of silence.

**Architecture:** New `bot/files.py` (filename sanitization, collision-safe dest paths, download via PTB `File.download_to_drive`); `bot/main.py` gains `handle_file` and `handle_unsupported` handlers and a shared `_run_and_reply(update, context, prompt)` helper extracted from `handle_message` (Claude call → chunks → sync). Assistant conventions in `workspace/CLAUDE.md` teach filing. Sync needs no changes (`git add -A` covers binaries).

**Tech Stack:** existing; python-telegram-bot 22.8 file API.

## Global Constraints

- Design as approved in chat 2026-08-06: download to `workspace/files/YYYY-MM/<sanitized-name>`; caption drives filing; Telegram bot-API 20 MB download cap honored with a friendly refusal above it; voice/video/stickers/etc. get a short "not handled" reply.
- Handled after this feature: text, documents (any type ≤20 MB), photos (largest size). NOT handled: voice/audio (no transcription), video, stickers, locations, contacts, polls; edited messages remain deliberately ignored.
- Whitelist and serial processing semantics unchanged; sync contract unchanged (never delays/breaks the reply for the triggering message).
- Filenames sanitized: keep `A-Za-z0-9._-`, replace other runs with `-`, strip leading dots (no hidden files/traversal); empty → `file`; collisions get `-2`, `-3`… before the extension. Photos named `photo-YYYYMMDD-HHMMSS.jpg` from `message.date`.
- Suite green after each task (45 now); commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: files module + handlers (code)

**Files:**
- Create: `bot/files.py`, `tests/test_files.py`
- Modify: `bot/main.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `sanitize_filename(name: str) -> str`; `dest_path(files_root: Path, name: str, subdir: str) -> Path` (collision-safe, creates dirs); in main: `handle_file`, `handle_unsupported`, `_run_and_reply(update, context, prompt)`.

- [ ] **Step 1: failing tests** — `tests/test_files.py`:

```python
from pathlib import Path

from bot.files import dest_path, sanitize_filename


def test_sanitize_replaces_unsafe_runs_with_dash():
    assert sanitize_filename("Road Toll 2026.pdf") == "Road-Toll-2026.pdf"


def test_sanitize_strips_leading_dots():
    assert not sanitize_filename("...secret.pdf").startswith(".")


def test_sanitize_empty_becomes_file():
    assert sanitize_filename("???") == "file"


def test_dest_path_creates_dirs_and_avoids_collisions(tmp_path):
    p1 = dest_path(tmp_path, "doc.pdf", "2026-08")
    p1.write_text("a")
    p2 = dest_path(tmp_path, "doc.pdf", "2026-08")
    assert p1 == tmp_path / "2026-08" / "doc.pdf"
    assert p2 == tmp_path / "2026-08" / "doc-2.pdf"
    assert p2.parent.is_dir()


def test_dest_path_counts_up(tmp_path):
    for expected in ["doc.pdf", "doc-2.pdf", "doc-3.pdf"]:
        p = dest_path(tmp_path, "doc.pdf", "2026-08")
        assert p.name == expected
        p.write_text("x")
```

- [ ] **Step 2: run, expect ModuleNotFoundError.** `.venv/bin/pytest tests/test_files.py -v`

- [ ] **Step 3: `bot/files.py`:**

```python
import re
from pathlib import Path

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # Telegram bot-API download cap


def sanitize_filename(name: str) -> str:
    """Keep [A-Za-z0-9._-]; collapse other runs to '-'; no leading dots."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).lstrip(".-")
    cleaned = cleaned.strip("-")
    return cleaned or "file"


def dest_path(files_root: Path, name: str, subdir: str) -> Path:
    """Collision-safe destination under files_root/subdir; creates dirs."""
    folder = files_root / subdir
    folder.mkdir(parents=True, exist_ok=True)
    safe = sanitize_filename(name)
    candidate = folder / safe
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate
```

(Check `test_sanitize_strips_leading_dots`: `"...secret.pdf"` → lstrip(".-") → `"secret.pdf"` ✓.)

- [ ] **Step 4: `bot/main.py` — extract shared helper and add handlers.**

Refactor `handle_message` so everything from the typing-action through the sync call lives in:

```python
async def _run_and_reply(update, context, prompt: str) -> None:
    config: Config = context.bot_data["config"]
    store: SessionStore = context.bot_data["store"]
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    session_id = store.get(chat_id)
    try:
        reply, new_session = await asyncio.to_thread(
            run_claude, prompt, config.workspace_dir, session_id,
            config.claude_bin, config.claude_timeout,
        )
    except ClaudeError as err:
        if session_id is None:
            await update.effective_message.reply_text(f"Sorry, something went wrong: {err}")
            return
        log.warning("resume of session %s failed (%s); retrying fresh", session_id, err)
        try:
            reply, new_session = await asyncio.to_thread(
                run_claude, prompt, config.workspace_dir, None,
                config.claude_bin, config.claude_timeout,
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
```

New file handler (imports: `from bot.files import MAX_DOWNLOAD_BYTES, dest_path`):

```python
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
    tg_file = await source.get_file()
    await tg_file.download_to_drive(dest)
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
```

Registration in `build_app` (order matters; all still gated by `allowed` and `filters.UpdateType.MESSAGE`):

```python
    app.add_handler(MessageHandler(
        allowed & (filters.Document.ALL | filters.PHOTO) & filters.UpdateType.MESSAGE,
        handle_file,
    ))
    app.add_handler(MessageHandler(
        allowed & ~filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
        handle_unsupported,
    ))
```

Insert both AFTER the existing text MessageHandler and BEFORE the `~allowed` logger. Note the unsupported handler comes after the file handler, so documents/photos never reach it (PTB dispatches to the first matching handler in the group).

- [ ] **Step 5: tests** — extend `tests/test_main.py`:
- Helper `_file_update(document=None, photo=None, caption=None)` building the SimpleNamespace shape with `date` a real `datetime(2026, 8, 6, 12, 0)`, `document`/`photo` (photo as a list, use `photo=[SimpleNamespace(file_size=..., get_file=AsyncMock(...))]`), `caption`, `from_user`, `reply_text=AsyncMock()`.
- `test_document_downloaded_and_prompt_built(tmp_path, monkeypatch)`: fake `get_file` returns SimpleNamespace with `download_to_drive=AsyncMock()`; monkeypatch `run_claude` capturing prompt + `sync_workspace` no-op; assert download called with a path under `tmp_path/ws/files/2026-08/` named `Road-Toll.pdf`, and prompt contains `files/2026-08/Road-Toll.pdf` and the caption.
- `test_oversized_document_refused(...)`: file_size = 25 MB → reply mentions "20 MB", `run_claude` NOT called.
- `test_photo_named_by_date(...)`: prompt/download path contains `photo-20260806-120000.jpg`.
- `test_unsupported_type_notice(...)`: `handle_unsupported` replies the fixed sentence.
- `test_build_app_registers_handlers`: handler count 4 → 6.
- Existing handle_message tests must keep passing unchanged (the refactor preserves behavior).

- [ ] **Step 6: full suite** `.venv/bin/pytest -v` → expect ~55 passing, pristine.

- [ ] **Step 7: commit + push** — `feat: file and photo attachments with polite unsupported-type notices`

---

### Task 2: conventions + HELP_TEXT + live E2E

- [ ] **Step 1: `workspace/CLAUDE.md`** — add to "Your files":

```markdown
- `files/` — attachments we send you (PDFs, photos), stored by month
  (e.g. `files/2026-08/road-toll.pdf`). When a file arrives you'll get its
  saved path and the sender's caption: link it from the doc it belongs to
  (trip file, todo, list item) as a markdown link, or ask one short question
  if the destination is unclear. You can Read PDFs and images to answer
  questions about them.
```

- [ ] **Step 2: HELP_TEXT** in `bot/main.py` — extend the capabilities sentence: after "travel plans", add `"You can also send me PDFs and photos to file. "`. Keep tests green.

- [ ] **Step 3: commit + push both repos as needed** (CLAUDE.md change syncs via the notebook repo — commit it directly with an appropriate message since the daemon only auto-commits its own changes... actually just `git -C workspace add -A && git -C workspace commit -m "docs: file-attachment conventions" && git -C workspace push`).

- [ ] **Step 4: restart bot; live E2E with Dor:** he re-sends the toll-permit PDF with its Hebrew caption → expect: saved under `files/2026-08/`, linked from `travel/slovakia.md`, confirmation reply, notebook commit visible on GitHub. Also send a voice note → expect the polite refusal.
