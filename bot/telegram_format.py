TELEGRAM_LIMIT = 4096


def chunk_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split text into Telegram-sized chunks, preferring newline boundaries."""
    text = text.strip()
    if not text:
        return ["(empty reply)"]
    chunks = []
    while len(text) > limit:
        split = text.rfind("\n", 0, limit + 1)
        if split <= 0:
            split = limit
        chunks.append(text[:split].rstrip("\n"))
        text = text[split:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks or ["(empty reply)"]
