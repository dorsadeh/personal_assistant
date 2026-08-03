from bot.sessions import SessionStore


def test_get_missing_returns_none(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    assert store.get(-100123) is None


def test_set_then_get(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.set(-100123, "abc-123")
    assert store.get(-100123) == "abc-123"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "sessions.json"
    SessionStore(path).set(-100123, "abc-123")
    assert SessionStore(path).get(-100123) == "abc-123"


def test_clear(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.set(-100123, "abc-123")
    store.clear(-100123)
    assert store.get(-100123) is None


def test_clear_missing_is_noop(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.clear(-100123)  # must not raise


def test_creates_parent_dir(tmp_path):
    store = SessionStore(tmp_path / "nested" / "sessions.json")
    store.set(1, "s")
    assert store.get(1) == "s"
