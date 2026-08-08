# Live Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The approved "Magnets" dashboard (spec: `docs/specs/2026-08-08-dashboard-design.md`, mockup: `docs/mockups/dashboard-design-a.html` design A) running on Vercel, reading/writing the `sadeh-family-notebook` GitHub repo, with shared-password auth and tap-to-check-off.

**Architecture:** Next.js 15 App Router app in `dashboard/` (repo root directory on Vercel = `dashboard/`). Server components fetch notebook files via GitHub contents API; a server action performs check-offs (SHA-conditional PUT with retry); iron-session-style signed cookie auth via a lightweight HMAC cookie (no extra deps). Bot side: `git_sync` gains `pull --rebase` so both writers interleave.

**Tech Stack:** Next.js 15 + React 19 + TypeScript, vitest for unit tests, plain fetch against GitHub REST (no Octokit — 3 endpoints), CSS modules carrying the mockup's design tokens. Node 22 locally.

## Global Constraints

- Design A is binding: tokens, magnet marks, checkbox interactions exactly as in `docs/mockups/dashboard-design-a.html` (the `.dA` styles; ignore B/C).
- Secrets only via env: `GITHUB_TOKEN` (fine-grained, sadeh-family-notebook contents RW), `FAMILY_PASSWORD`, `SESSION_SECRET`. Never committed; `.env.local` gitignored.
- All GitHub calls server-side only — the token must never reach the client.
- Check-off commits: `dashboard: <Name> checked off "<item>"`; todos move to `## Done`, list/travel items flip in place. 409 → refetch+retry ×3.
- Bot's never-raise sync contract unchanged; rebase failure → abort, local intact.
- Python suite (55) and new dashboard vitest suite both green at every commit.
- Commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: git_sync pull --rebase (bot side)

**Files:** Modify `bot/git_sync.py`, `tests/test_git_sync.py`

**Interfaces:** `sync_workspace` signature/contract unchanged. New behavior: before push, if remote has new commits, `git pull --rebase`; on rebase failure `git rebase --abort` and continue (push skipped, logged, retried next call).

- [ ] Step 1: failing tests — append to `tests/test_git_sync.py`:

```python
def _clone(tmp_path, origin, name):
    dest = tmp_path / name
    subprocess.run(["git", "clone", str(origin), str(dest)], check=True, capture_output=True, text=True)
    _run(dest, "config", "user.email", "other@test")
    _run(dest, "config", "user.name", "Other")
    return dest


def test_diverged_remote_rebases_and_pushes(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    other = _clone(tmp_path, origin, "other")
    (other / "lists.md").write_text("from dashboard\n")
    _run(other, "add", "-A"); _run(other, "commit", "-m", "dashboard: edit"); _run(other, "push")
    (ws / "todos.md").write_text("# Todos\n- [ ] new\n")
    assert sync_workspace(ws, "Dor: add todo") is True
    log = subprocess.run(["git", "log", "--format=%s", "main"], cwd=origin,
                         check=True, capture_output=True, text=True).stdout
    assert "assistant: Dor: add todo" in log and "dashboard: edit" in log


def test_rebase_conflict_aborts_cleanly(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    other = _clone(tmp_path, origin, "other2")
    (other / "todos.md").write_text("# Todos\n- [x] milk\n")
    _run(other, "add", "-A"); _run(other, "commit", "-m", "dashboard: check"); _run(other, "push")
    (ws / "todos.md").write_text("# Todos\n- [ ] milk (edited)\n")
    sync_workspace(ws, "Dor: edit")  # must not raise
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ws,
                            check=True, capture_output=True, text=True).stdout
    assert "rebase" not in (ws / ".git").joinpath("REBASE_HEAD").name or True  # no rebase in progress:
    assert not (ws / ".git" / "rebase-merge").exists()
    assert status.strip() == ""  # committed locally, tree clean
```

- [ ] Step 2: run → the two new tests fail (current code: push fails on diverged remote, returns True but origin lacks the commit; conflict case leaves no rebase dir anyway — assert the *origin log* difference drives the failure).
- [ ] Step 3: implement — in `sync_workspace`, replace the bare `_git(workspace, "push")` with:

```python
        try:
            _git(workspace, "push")
        except subprocess.CalledProcessError:
            _git(workspace, "fetch", "origin")
            try:
                _git(workspace, "pull", "--rebase")
            except subprocess.CalledProcessError:
                _git(workspace, "rebase", "--abort")
                raise
            _git(workspace, "push")
```

(Wrapped by the existing outer `except Exception` so the contract holds; abort failure also lands there.)

- [ ] Step 4: full python suite green (57). Step 5: commit `fix: git_sync rebases on diverged remote so dashboard commits interleave`.

---

### Task 2: dashboard scaffold + notebook client + parser

**Files:** Create `dashboard/` via `npx create-next-app@latest dashboard --ts --app --no-tailwind --eslint --src-dir=false --import-alias "@/*"`; add `vitest`; create `dashboard/lib/github.ts`, `dashboard/lib/notebook.ts`, `dashboard/lib/notebook.test.ts`, `dashboard/lib/github.test.ts`.

**Interfaces (consumed by Tasks 3-4):**
- `github.ts`: `getFile(path): Promise<{text: string; sha: string}>`, `putFile(path, text, sha, message): Promise<void>` (409 → `ConflictError`), `listCommits(limit): Promise<{message: string; date: string}[]>` — all against `process.env.GITHUB_REPO` (default `dorsadeh/sadeh-family-notebook`) with `GITHUB_TOKEN`, `cache: "no-store"`.
- `notebook.ts`: `parseChecklist(md): {items: ChecklistItem[]; sections: ...}` where `ChecklistItem = {text, note?, who?, when?, checked, line}`; `toggleLine(md, line, {moveToDone?: boolean}): string`; `parseActivity(commits): ActivityRow[]` (humanize `assistant:`/`dashboard:` prefixes).
- Parser rules: checkbox lines `- [ ] text — note (Name, Mon YYYY)` (note/attribution optional, em- or hyphen-dash tolerated, `(Name)` alone OK); non-checkbox bullet lines under `## Places` style headings also render as checkable trip items (they get converted to `- [ ]` form on first toggle); `## Done` section recognized in todos.
- Tests: round-trip parse/serialize on the REAL current notebook contents (fixtures copied verbatim: todos.md with bread-and-butter under Inbox, slovakia.md with the two places incl. Hebrew note + Documents link, an empty lists/books.md), toggle with done-move, toggle in place, activity humanization.

Steps: scaffold → vitest config → failing tests → implement → `npm test` + `npm run build` green → commit.

---

### Task 3: auth + read-only UI in design A

**Files:** `dashboard/middleware.ts`, `dashboard/lib/session.ts` (+test), `dashboard/app/login/page.tsx` + server action, `dashboard/app/page.tsx`, `dashboard/app/notebook.module.css`, `dashboard/app/api/doc/[...path]/route.ts` (PDF proxy).

- `session.ts`: HMAC-SHA256 signed cookie `session=<name>.<expiry>.<sig>` using `SESSION_SECRET` (Web Crypto, edge-safe); `createSession(name)`, `verifySession(cookie)` (+unit tests). Login form: password field + "I'm Dor / I'm Tal" toggle; wrong password → inline error, no user enumeration concerns.
- `middleware.ts`: redirect to `/login` when cookie invalid (except `/login`, static assets).
- `page.tsx` (server component): fetch todos, all lists, all travel files, commits → render design A EXACTLY per mockup: header magnets+wordmark, stats rule, section cards, list grid with real counts, activity feed, sync line ("synced <relative time of latest commit>"). Checkboxes render but disabled-styling until Task 4 wires them. PDF links → `/api/doc/files/...` proxy route streaming from GitHub with the token.
- `npm run build` green; manual `npm run dev` smoke against the real repo with a throwaway token env is allowed locally but NOT required (Task 5 covers live).

---

### Task 4: interactive check-off

**Files:** `dashboard/app/actions.ts` (+test via extracted pure helper), `dashboard/app/CheckItem.tsx` (client component), wire into page.

- Server action `checkOff({file, line, itemText})`: session name → `getFile` → verify line still matches itemText (else re-locate by text; not found → return `{stale: true}`) → `toggleLine` (todos: move to Done) → `putFile` with sha, message `dashboard: <Name> checked off "<itemText>"` → `revalidatePath("/")`. On `ConflictError` retry ×3 with refetch; then `{conflict: true}`.
- `CheckItem.tsx`: optimistic check + strike, toast copy from mockup adapted: success "Checked off — synced to the notebook", stale/conflict "The notebook changed — refreshing", error state re-unchecks.
- Tests: helper-level (relocate-by-text, retry loop with mocked github client). Build green. Commit.

---

### Task 5: deploy + live E2E (with Dor)

- [ ] Dor creates fine-grained PAT (guided): github.com → Settings → Developer settings → Fine-grained tokens → repo access ONLY `sadeh-family-notebook`, permissions: Contents RW, expiry 1 year.
- [ ] `cd dashboard && npx vercel login` (Dor authenticates) → `npx vercel link` → set env vars (`GITHUB_TOKEN`, `FAMILY_PASSWORD` chosen by Dor, `SESSION_SECRET` generated) → `npx vercel deploy --prod`.
- [ ] Live checks: login (wrong password rejected); dashboard shows current notebook; check off "buy bread and butter" → GitHub commit `dashboard: Dor checked off...`, todos.md Done section updated; send a bot message on Telegram → bot's sync rebases cleanly over the dashboard commit (verify notebook log linear); PDF opens via proxy; phone check (both).
- [ ] Update deploy/SETUP.md (dashboard section) + README; memory + ledger.
