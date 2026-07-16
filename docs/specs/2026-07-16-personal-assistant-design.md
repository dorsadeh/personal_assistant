# Personal Assistant — Telegram bot powered by headless Claude Code

## Context

Dor and his wife want a shared personal assistant they can talk to from a messaging app, for:
1. A shared TODO list
2. Organizing information (ideas, travel plans)
3. Managing calendar events (Google Calendar — **events-only permission**, never full account access)
4. Bonus: reminders, morning agenda, travel research, weekly digest

Decisions made during brainstorming:
- **Messaging app:** Telegram, one shared group chat (Dor + wife + bot)
- **Hosting:** this Linux PC first; later Dor's brother's home server → design must be portable
- **AI backend:** headless Claude Code CLI (`claude -p`) using Dor's **Claude subscription quota** via `claude setup-token` — $0 extra cost. (Verified: Agent SDK requires an API key, but Claude Code CLI headless mode officially supports subscription OAuth tokens for scripts/automation.) If quota ever becomes a problem, an API key can be swapped in without changing architecture.
- Environment verified: Python 3.12.3, Node 22, Claude Code 2.1.211 at `~/.local/bin/claude`.

## Architecture

Everything lives in `/home/dorsadeh/workspace/sandbox/personal_projects/personal_assistant/` (make it a git repo).

```
personal_assistant/
├── bot/                  # thin Python daemon
│   ├── main.py           # telegram long-polling, message → claude → reply
│   ├── claude_runner.py  # subprocess wrapper around `claude -p`
│   ├── reminders.py      # every-minute scheduler firing due reminders
│   └── config.py         # env loading, chat-id whitelist
├── workspace/            # the assistant's entire world (also a git repo or subdir)
│   ├── CLAUDE.md         # persona + house rules + file conventions
│   ├── todos.md          # shared TODO list (plain markdown)
│   ├── ideas/            # idea notes
│   ├── travel/           # trip plans
│   ├── reminders.json    # schema: [{id, text, due_iso, chat_id, sent}]
│   ├── .mcp.json         # Google Calendar MCP server config (phase 3)
│   └── .claude/settings.json  # permission allowlist for headless runs
├── deploy/
│   ├── assistant.service # systemd user unit
│   └── SETUP.md          # how to install on a new machine (brother's server)
├── .env.example          # TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_IDS, CLAUDE_CODE_OAUTH_TOKEN
└── README.md
```

### Message flow
1. Daemon long-polls Telegram (`python-telegram-bot` lib; no open ports needed — fine behind home NAT).
2. Reject anything not from whitelisted chat IDs (the group) — bots are publicly discoverable, whitelist is the security boundary.
3. Dedicated group ⇒ every message is for the assistant (disable bot privacy mode via BotFather so it sees group messages).
4. Messages are queued and processed **serially**. Each message runs:
   `claude -p "<message>" --resume <session-id> --output-format json` with `cwd=workspace/`, restricted `--allowedTools` (Read/Write/Edit/Glob/Grep in workspace, WebSearch/WebFetch, calendar MCP tools later). Timeout ~5 min.
5. One persistent session per chat, session-id stored on disk; `/new` command starts a fresh session. Reply sent back to the group (convert markdown → Telegram formatting, chunk long messages at 4096 chars).
6. On Claude error/timeout: send a short apology + error summary to the chat, log details.

### Reminders (phase 2)
- The assistant (Claude) creates/edits `reminders.json` per conventions in `CLAUDE.md`.
- The daemon's scheduler checks it every minute and sends due reminders **directly** via Telegram API (no Claude call to fire), then marks them sent.
- Morning agenda: cron (or in-daemon schedule) invokes `claude -p "compose the morning agenda"` and sends the result to the group.

### Google Calendar (phase 3)
- Community Google Calendar MCP server configured in `workspace/.mcp.json`.
- OAuth consent granted with **`https://www.googleapis.com/auth/calendar.events` scope only** — read/add/edit/delete events; no Gmail/Drive/contacts. Revocable from Google security settings. Credentials stored locally on the machine.
- Pick the best-maintained MCP server at implementation time (e.g. `google-calendar-mcp` on npm) and verify its scope request before authorizing.

### Auth & portability
- `claude setup-token` → long-lived `CLAUDE_CODE_OAUTH_TOKEN` in the service environment (survives headless/systemd use; works on the future server without browser login).
- systemd user unit (`assistant.service`) with `Restart=always`; `loginctl enable-linger` so it runs without an active login.
- Moving to the brother's server = clone repo, install claude CLI, `setup-token`, copy `.env`, enable service (documented in `deploy/SETUP.md`).

## Build phases

**Phase 1 — core loop (the MVP):**
1. Create BotFather bot (user does this; needs bot token), create the group, get chat ID, disable privacy mode.
2. `bot/` daemon: polling, whitelist, serial queue, `claude -p` runner with `--resume` sessions, markdown→Telegram reply, `/new` + `/help` commands.
3. `workspace/` with `CLAUDE.md` persona (household context, file conventions for todos/ideas/travel), seed `todos.md`.
4. `.claude/settings.json` permission allowlist so headless Claude only touches the workspace + web search.
5. systemd unit + `.env` handling.

**Phase 2 — proactive:** `reminders.json` conventions + daemon scheduler + morning-agenda scheduled Claude run.

**Phase 3 — Google Calendar:** choose + configure MCP server, events-only OAuth, add its tools to the allowlist, teach conventions in `CLAUDE.md`.

**Phase 4 — portability polish:** `deploy/SETUP.md`, backup note (workspace git remote, e.g. private GitHub repo).

## User-provided inputs needed during implementation
- Telegram bot token from @BotFather (user creates the bot, ~2 minutes, guided).
- Running `claude setup-token` interactively once.
- Google Cloud OAuth client for the calendar MCP (phase 3, guided).

## Verification
- **Phase 1:** send "add milk to the todo list" in the group → bot replies, `workspace/todos.md` contains the item; "what's on our list?" → correct answer; message from a non-whitelisted chat is ignored; kill daemon → systemd restarts it.
- **Phase 2:** "remind me in 2 minutes to test" → reminder message arrives in the group ~2 min later; morning agenda fires at configured time.
- **Phase 3:** "add dentist appointment tomorrow 10:00" → event appears in Google Calendar; "what's on our calendar this week?" → correct listing; confirm granted scope in Google account permissions page shows calendar-events only.

## Notes / risks
- Subscription quota is shared with Dor's own Claude Code usage; heavy bot use could hit plan limits (usage-limit errors surface in bot replies). Mitigation: swap to API key later if needed.
- This PC must stay on for the bot to be responsive until the server move.
- Telegram messages are visible to Telegram; nothing more sensitive than todos/plans should be expected there.
