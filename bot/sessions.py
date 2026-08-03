import json
import logging
import os
from pathlib import Path

log = logging.getLogger("assistant.sessions")


class SessionStore:
    """Maps Telegram chat id -> Claude session id, persisted as JSON."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except json.JSONDecodeError:
                log.warning("session store at %s is corrupted; starting fresh", self.path)
                return {}
        return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        os.replace(tmp_path, self.path)

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
