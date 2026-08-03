TELEGRAM_LIMIT = 4096


def chunk_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split text into Telegram-sized chunks, preferring newline boundaries.

    Chunks are sent as separate Telegram messages, so newlines at a chunk
    boundary are stripped — the message break itself is the separator.
    """
    text = text.strip()
    if not text:
        return ["(empty reply)"]
    if limit < 1:
        raise ValueError("limit must be >= 1")
    chunks = []
    while len(text) > limit:
        split = text.rfind("\n", 0, limit + 1)
        if split <= 0:
            split = limit
        chunks.append(text[:split].rstrip("\n"))
        text = text[split:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks
