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
The sandbox is enforced by invoker-passed `--allowedTools`/`--disallowedTools`
flags (file tools + web only, no Bash, `.claude/**` off-limits — see
`bot/claude_runner.py`); `workspace/.claude/settings.json` provides the model
choice and matching deny rules as defense-in-depth. Data lives in markdown
files, tracked in git.
Data lives in a separate private repo ([sadeh-family-notebook](https://github.com/dorsadeh/sadeh-family-notebook))
cloned at `workspace/`; the daemon auto-commits and pushes every assistant
change there (browse it in the GitHub app; full history; off-PC backup).
