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
