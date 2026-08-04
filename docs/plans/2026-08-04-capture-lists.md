# Capture & Lists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quick-capture of shared items (books, series, places, restaurants, courses, gifts…) into categorized markdown lists in the workspace, with the workspace split into its own private GitHub repo (`sadeh-family-notebook`) that the daemon auto-commits and pushes so Dor & Tal can browse it in the GitHub app.

**Architecture:** Content-only changes to `workspace/` (lists + CLAUDE.md conventions); the workspace becomes a standalone git repo nested inside the code repo's working tree (untracked there); a new `bot/git_sync.py` module commits+pushes workspace changes after each reply, off the reply path; `handle_message` prefixes prompts with the sender's first name for attribution.

**Tech Stack:** Existing stack (Python 3.12, python-telegram-bot 22.8, pytest). Plain `git` subprocess calls for sync; `gh` CLI (authed as dorsadeh) for repo creation.

## Global Constraints

- Spec: `docs/specs/2026-08-04-capture-lists-design.md` is binding.
- Sync failures must NEVER break or delay the Telegram reply: reply first, sync after, log-and-continue on any git error.
- The assistant's sandbox is unchanged (no Bash for Claude — the *daemon* does git).
- List item format: `- [ ] Title — short context (Name, Mon YYYY)`; checked items stay in the file.
- Secrets rules unchanged; the notebook repo must be **private**.
- The running bot process uses old code — restart it as part of live verification (manual run, NO systemd — user decision).
- Suite currently 35 passing; every task ends green. Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Lists content + capture conventions (workspace files only)

**Files:**
- Create: `workspace/lists/README.md`, `workspace/lists/books.md`, `workspace/lists/tv-series.md`, `workspace/lists/places.md`, `workspace/lists/restaurants.md`, `workspace/lists/education.md`, `workspace/lists/gifts.md`
- Modify: `workspace/CLAUDE.md`

**Interfaces:**
- Produces: the file conventions Task 4's live test exercises. No code.

- [ ] **Step 1: Create the six category files.** Each is exactly (substituting Title):

```markdown
# Books

<!-- - [ ] Title — short context (Name, Mon YYYY) ; checked = done/read/watched/visited -->
```

Titles per file: `Books`, `TV & Movies` (tv-series.md), `Places to Visit` (places.md), `Restaurants & Cafés` (restaurants.md), `Learning & Courses` (education.md), `Gift Ideas` (gifts.md).

- [ ] **Step 2: Create `workspace/lists/README.md`:**

```markdown
# Our Lists

- [Books](books.md)
- [TV & Movies](tv-series.md)
- [Places to Visit](places.md)
- [Restaurants & Cafés](restaurants.md)
- [Learning & Courses](education.md)
- [Gift Ideas](gifts.md)

Sent to our assistant in Telegram, organized here. Checked = done.
```

- [ ] **Step 3: Update `workspace/CLAUDE.md`.** After the existing "## Your files" bullet for `travel/`, add:

```markdown
- `lists/` — categorized "remember this" lists (books, tv-series, places,
  restaurants, education, gifts). Item format:
  `- [ ] Title — short context (Name, Mon YYYY)`.
  Mark items done with `- [x]` when told (watched/read/visited); never delete.
  If something fits no existing list, create a new kebab-case file and add it
  to `lists/README.md`.
```

And after the "## Rules" list, append these rules:

```markdown
- Messages arrive prefixed with the sender's name (e.g. "Dor: ..." or
  "Tal: ...") — use it to attribute list items and todos.
- Quick capture: when a message is a recommendation, a "we should..." or even
  a bare title ("shogun", "brunch place in Florentin"), file it into the right
  list with attribution and confirm in one short sentence naming the file.
  If the category is genuinely unclear (book vs. series?), ask one short
  question instead of guessing.
```

- [ ] **Step 4: Commit (in the CODE repo — workspace is still tracked there until Task 2):**

```bash
git add workspace/ && git commit -m "feat: lists structure and capture conventions"
```

---

### Task 2: Repo split — workspace becomes `sadeh-family-notebook`

**Files:**
- Modify: `.gitignore` (code repo), `deploy/SETUP.md`, `README.md`
- Create: `workspace/.git` (new standalone repo), private GitHub repo `sadeh-family-notebook`

**Interfaces:**
- Produces: `workspace/` is a standalone git repo with remote `origin` = `https://github.com/dorsadeh/sadeh-family-notebook.git`, branch `main`, fully pushed. Task 3's sync module assumes exactly this.

- [ ] **Step 1: Create the private repo and initialize the workspace as a repo:**

```bash
gh repo create sadeh-family-notebook --private --description "Dor & Tal's shared notebook — maintained by our assistant"
cd workspace
git init -b main
git add -A
git commit -m "Initial notebook: persona, todos, lists"
git remote add origin https://github.com/dorsadeh/sadeh-family-notebook.git
git push -u origin main
cd ..
```

- [ ] **Step 2: Untrack workspace in the code repo:**

```bash
git rm -r --cached workspace
echo "workspace/" >> .gitignore
```

- [ ] **Step 3: Update `deploy/SETUP.md`** — in the clone step (step 4), after the existing clone line, add:

```markdown
   Then clone the family notebook (the assistant's data) into `workspace/`:
   `git clone https://github.com/dorsadeh/sadeh-family-notebook.git workspace`
   (the code repo ignores `workspace/` — data lives in its own private repo,
   and the daemon auto-pushes changes to it).
```

- [ ] **Step 4: Update `README.md`** — in the architecture section, append:

```markdown
Data lives in a separate private repo ([sadeh-family-notebook](https://github.com/dorsadeh/sadeh-family-notebook))
cloned at `workspace/`; the daemon auto-commits and pushes every assistant
change there (browse it in the GitHub app; full history; off-PC backup).
```

- [ ] **Step 5: Verify split:** `git status` in code repo shows workspace gone + modified files only; `git -C workspace status` clean; repo visible: `gh repo view sadeh-family-notebook --json visibility` → PRIVATE.

- [ ] **Step 6: Commit code repo:**

```bash
git add .gitignore deploy/SETUP.md README.md
git commit -m "feat: split workspace into private sadeh-family-notebook repo"
```

---

### Task 3: Auto-sync module + sender attribution (code)

**Files:**
- Create: `bot/git_sync.py`
- Modify: `bot/main.py`
- Test: `tests/test_git_sync.py`, modify `tests/test_main.py`

**Interfaces:**
- Consumes: `Config.workspace_dir`; called from `handle_message` after replies are sent.
- Produces: `sync_workspace(workspace: Path, summary: str) -> bool` (True if a commit was made; never raises).

- [ ] **Step 1: Write failing tests** — `tests/test_git_sync.py`:

```python
import subprocess
from pathlib import Path

from bot.git_sync import sync_workspace


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """A workspace repo with a bare origin, one pushed commit."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run(origin, "init", "--bare", "-b", "main")
    ws = tmp_path / "ws"
    ws.mkdir()
    _run(ws, "init", "-b", "main")
    _run(ws, "config", "user.email", "test@test")
    _run(ws, "config", "user.name", "Test")
    (ws / "todos.md").write_text("# Todos\n")
    _run(ws, "add", "-A")
    _run(ws, "commit", "-m", "init")
    _run(ws, "remote", "add", "origin", str(origin))
    _run(ws, "push", "-u", "origin", "main")
    return ws, origin


def _origin_head_subject(origin: Path) -> str:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%s", "main"],
        cwd=origin, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def test_clean_workspace_no_commit(tmp_path):
    ws, _ = _make_workspace(tmp_path)
    assert sync_workspace(ws, "Dor: hello") is False


def test_dirty_workspace_commits_and_pushes(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    (ws / "todos.md").write_text("# Todos\n- [ ] milk\n")
    assert sync_workspace(ws, "Dor: add milk to the list") is True
    assert _origin_head_subject(origin) == "assistant: Dor: add milk to the list"


def test_summary_truncated_to_50_chars(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    (ws / "new.md").write_text("x")
    sync_workspace(ws, "Dor: " + "y" * 100)
    assert _origin_head_subject(origin) == "assistant: " + ("Dor: " + "y" * 100)[:50]


def test_empty_summary_fallback(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    (ws / "new.md").write_text("x")
    sync_workspace(ws, "   ")
    assert _origin_head_subject(origin) == "assistant: update"


def test_push_failure_does_not_raise_and_retries_next_time(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    _run(ws, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    (ws / "todos.md").write_text("changed\n")
    assert sync_workspace(ws, "Dor: x") is True  # commit made, push failed silently
    _run(ws, "remote", "set-url", "origin", str(origin))
    assert sync_workspace(ws, "Dor: y") is False  # clean tree, but pending push goes out
    assert _origin_head_subject(origin) == "assistant: Dor: x"


def test_not_a_repo_does_not_raise(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert sync_workspace(plain, "Dor: x") is False
```

- [ ] **Step 2: Run to verify failure:** `.venv/bin/pytest tests/test_git_sync.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Write `bot/git_sync.py`:**

```python
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("assistant.git_sync")


def sync_workspace(workspace: Path, summary: str) -> bool:
    """Commit and push workspace changes. Returns True if a commit was made.

    Never raises: failures are logged and swallowed. Push is attempted on
    every call, so a commit stranded by a failed push goes out next time.
    """
    committed = False
    try:
        if _git(workspace, "status", "--porcelain").strip():
            _git(workspace, "add", "-A")
            summary = summary.strip() or "update"
            _git(workspace, "commit", "-m", f"assistant: {summary[:50]}")
            committed = True
        _git(workspace, "push")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
        detail = getattr(err, "stderr", "") or str(err)
        log.warning("workspace sync incomplete: %s", detail.strip())
    return committed


def _git(workspace: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=workspace, capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, proc.stdout, proc.stderr
        )
    return proc.stdout
```

- [ ] **Step 4: Wire into `bot/main.py`.** Add import `from bot.git_sync import sync_workspace`. In `handle_message`:

After `prompt = update.effective_message.text`, add sender attribution:

```python
    user = update.effective_message.from_user
    sender = user.first_name if user and user.first_name else "Someone"
    prompt = f"{sender}: {prompt}"
```

At the end of `handle_message`, after the chunk-sending loop:

```python
    await asyncio.to_thread(sync_workspace, config.workspace_dir, prompt)
```

- [ ] **Step 5: Update `tests/test_main.py`:**
- In the `_update` helper, give the message a `from_user`: `SimpleNamespace(text=text, reply_text=AsyncMock(), from_user=SimpleNamespace(first_name="Dor"))` (both `message` and `effective_message`).
- `test_message_gets_claude_reply`: monkeypatch `main_mod.sync_workspace` with a recording fake; assert the recorded summary is `"Dor: hello"` and the recorded workspace is `config.workspace_dir`.
- New `test_prompt_carries_sender_name`: capture the prompt passed to `run_claude`; assert it equals `"Dor: hello"`.
- All other handle_message tests: monkeypatch `main_mod.sync_workspace` to a no-op lambda so tests don't run git.

- [ ] **Step 6: Full suite green:** `.venv/bin/pytest -v` → expect 35 + 7 new + 1 modified ≈ 42-43 passing, pristine.

- [ ] **Step 7: Commit (code repo):**

```bash
git add bot/git_sync.py bot/main.py tests/test_git_sync.py tests/test_main.py
git commit -m "feat: auto-commit+push workspace after replies; sender attribution"
```

---

### Task 4: Live E2E (with Dor)

- [ ] **Step 1:** Restart the bot (stop old process, `.venv/bin/python -m bot.main` in background — manual run, no systemd).
- [ ] **Step 2:** Dor sends `the bear - tal wants to watch` → expect confirmation naming `lists/tv-series.md`; verify the file contains `- [ ] The Bear — Tal wants to watch (Dor, Aug 2026)`-style item; verify the notebook repo on GitHub shows the commit `assistant: Dor: the bear - tal wants to watch` within seconds.
- [ ] **Step 3:** Dor sends `what's on our series list?` → answered from file.
- [ ] **Step 4:** Dor sends `we watched the bear` → item becomes `- [x]`, new commit pushed.
- [ ] **Step 5:** User action: Tal creates a GitHub account; Dor runs `gh api repos/dorsadeh/sadeh-family-notebook/collaborators/<tal-username> -X PUT` (or invites via github.com → repo → Settings → Collaborators).
- [ ] **Step 6:** Update memory + progress ledger; push code repo.
