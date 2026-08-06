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
