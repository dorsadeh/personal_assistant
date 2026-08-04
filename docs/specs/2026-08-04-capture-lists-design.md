# Capture & Lists — Design Spec

## Goal

Dor and Tal currently send each other "remember this" WhatsApp messages: books,
TV series, places to visit, restaurants, courses, gift ideas, todos. Instead,
they'll send these to the assistant in the Telegram group, and it will organize
them into categorized lists they can browse on their phones.

## Decisions (from brainstorming, 2026-08-04)

- Data ("the database") lives on this PC as plain markdown in `workspace/`.
- The workspace becomes a **separate private GitHub repo** (`sadeh-family-notebook`)
  that the daemon auto-commits and pushes to after every assistant change:
  phone browsing via the GitHub app/website + off-PC backup + history.
  Tal joins as repo collaborator (needs a free GitHub account — user action).
- Browsing today: GitHub rendered markdown + asking the bot in chat.
- A real web dashboard is a **later phase** (deliberately deferred until they've
  lived with the lists); it will read the same files, so nothing is throwaway.

## Changes

### 1. Repo split
- Create private GitHub repo `sadeh-family-notebook` under Dor's account.
- `workspace/` becomes its own git repo pushed there (contents: `CLAUDE.md`,
  `todos.md`, `ideas/`, `travel/`, `lists/`, `.claude/settings.json`).
- Code repo: `git rm -r --cached workspace/`, add `workspace/` to `.gitignore`,
  update `deploy/SETUP.md` (new-machine setup now clones the notebook repo into
  `workspace/`).

### 2. Lists structure
- `workspace/lists/` with starter category files: `books.md`, `tv-series.md`,
  `places.md`, `restaurants.md`, `education.md`, `gifts.md`.
- Each file: `# <Category>` heading, then checkbox items:
  `- [ ] Title — short context (Dor|Tal, Mon YYYY)`. Checked = read/watched/visited/done.
- `workspace/lists/README.md`: one-line index linking each list (GitHub renders
  it as the folder's landing page).
- The assistant may create new category files when something doesn't fit,
  and must add them to the README index.

### 3. Capture conventions (CLAUDE.md)
- New behavior: any message that reads like "save/remember/we should…" — or a
  bare title ("shogun", "brunch place in Florentin") — is classified into the
  right list, added, and confirmed in one short sentence naming the file.
- Sender attribution: the daemon prefixes each prompt with the sender's first
  name (`Dor: <message>`), so the assistant can attribute items `(Dor, Aug 2026)`.
- Ambiguity (book vs. series, todo vs. list item) → ask one short question.
- Todos keep living in `todos.md` (unchanged).

### 4. Auto-sync (new `bot/git_sync.py`)
- After each successful Claude run, if `workspace/` git status is dirty:
  `git add -A && git commit -m "assistant: <first 50 chars of user message>" && git push`.
- Runs in the daemon (not Claude — Bash is denied in the sandbox), off the
  reply path: reply is sent first, sync after; sync failures are logged and
  never break the conversation. A failed push retries on the next sync.
- Uses Dor's existing git credentials (already push to GitHub from this PC).

## Out of scope
- Web dashboard (own later phase). Reminders/morning agenda (plan Phase 2).
- Google Calendar (plan Phase 3). WhatsApp integration (not wanted — they'll
  message the Telegram group instead).

## Verification
- Unit: git_sync tested against a temp git repo (init bare remote, verify
  commit+push, verify dirty-detection, verify failure doesn't raise).
- Live: send "the bear - tal wants to watch" → appears in `lists/tv-series.md`
  with attribution; visible on github.com in the notebook repo within seconds;
  "what's on our series list?" answered from the file; item checked off via
  chat ("we watched the bear") moves to `- [x]`.
- User actions: Tal's GitHub account + collaborator invite.
