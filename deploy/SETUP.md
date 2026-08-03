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

Note: on first headless runs you may see a stderr warning that
`permissions.allow` entries from `workspace/.claude/settings.json` are
ignored because the workspace is untrusted. This is expected and harmless:
the bot passes its tool allowlist explicitly via `--allowedTools` flags
(see `bot/claude_runner.py`), which apply regardless of directory trust.
