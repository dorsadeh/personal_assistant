from bot.telegram_format import chunk_message


def test_short_message_single_chunk():
    assert chunk_message("hello") == ["hello"]


def test_empty_message_yields_placeholder():
    assert chunk_message("   ") == ["(empty reply)"]


def test_long_message_split_within_limit():
    text = "\n".join(f"line {i}" for i in range(1000))
    chunks = chunk_message(text, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(c + "\n" for c in chunks).strip() == text


def test_splits_on_newline_boundary():
    text = "a" * 90 + "\n" + "b" * 90
    chunks = chunk_message(text, limit=100)
    assert chunks == ["a" * 90, "b" * 90]


def test_hard_split_without_newlines():
    text = "x" * 250
    chunks = chunk_message(text, limit=100)
    assert chunks == ["x" * 100, "x" * 100, "x" * 50]
