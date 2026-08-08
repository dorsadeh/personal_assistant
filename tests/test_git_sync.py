import subprocess
from pathlib import Path

from bot.git_sync import sync_workspace


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """A workspace repo with a bare origin, one pushed commit."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run(origin, "init", "--bare", "-b", "main")
    ws = tmp_path / "ws"
    ws.mkdir()
    _run(ws, "init", "-b", "main")
    _run(ws, "config", "user.email", "test@test")
    _run(ws, "config", "user.name", "Test")
    (ws / "todos.md").write_text("# Todos\n")
    _run(ws, "add", "-A")
    _run(ws, "commit", "-m", "init")
    _run(ws, "remote", "add", "origin", str(origin))
    _run(ws, "push", "-u", "origin", "main")
    return ws, origin


def _origin_head_subject(origin: Path) -> str:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%s", "main"],
        cwd=origin, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def test_clean_workspace_no_commit(tmp_path):
    ws, _ = _make_workspace(tmp_path)
    assert sync_workspace(ws, "Dor: hello") is False


def test_dirty_workspace_commits_and_pushes(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    (ws / "todos.md").write_text("# Todos\n- [ ] milk\n")
    assert sync_workspace(ws, "Dor: add milk to the list") is True
    assert _origin_head_subject(origin) == "assistant: Dor: add milk to the list"


def test_summary_truncated_to_50_chars(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    (ws / "new.md").write_text("x")
    sync_workspace(ws, "Dor: " + "y" * 100)
    assert _origin_head_subject(origin) == "assistant: " + ("Dor: " + "y" * 100)[:50]


def test_empty_summary_fallback(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    (ws / "new.md").write_text("x")
    sync_workspace(ws, "   ")
    assert _origin_head_subject(origin) == "assistant: update"


def test_push_failure_does_not_raise_and_retries_next_time(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    _run(ws, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    (ws / "todos.md").write_text("changed\n")
    assert sync_workspace(ws, "Dor: x") is True  # commit made, push failed silently
    _run(ws, "remote", "set-url", "origin", str(origin))
    assert sync_workspace(ws, "Dor: y") is False  # clean tree, but pending push goes out
    assert _origin_head_subject(origin) == "assistant: Dor: x"


def test_not_a_repo_does_not_raise(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert sync_workspace(plain, "Dor: x") is False


def test_missing_workspace_dir_does_not_raise(tmp_path):
    assert sync_workspace(tmp_path / "does-not-exist", "Dor: x") is False


def test_multiline_summary_becomes_single_line_subject(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    (ws / "new.md").write_text("x")
    sync_workspace(ws, "Dor: line one\nline two")
    assert _origin_head_subject(origin) == "assistant: Dor: line one line two"


def test_unexpected_error_does_not_raise(tmp_path, monkeypatch):
    import bot.git_sync as gs

    def boom(*a, **k):
        raise ValueError("unexpected")

    monkeypatch.setattr(gs.subprocess, "run", boom)
    assert sync_workspace(tmp_path, "Dor: x") is False


def _clone(tmp_path, origin, name):
    dest = tmp_path / name
    subprocess.run(["git", "clone", str(origin), str(dest)], check=True, capture_output=True, text=True)
    _run(dest, "config", "user.email", "other@test")
    _run(dest, "config", "user.name", "Other")
    return dest


def test_diverged_remote_rebases_and_pushes(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    other = _clone(tmp_path, origin, "other")
    (other / "lists.md").write_text("from dashboard\n")
    _run(other, "add", "-A"); _run(other, "commit", "-m", "dashboard: edit"); _run(other, "push")
    (ws / "todos.md").write_text("# Todos\n- [ ] new\n")
    assert sync_workspace(ws, "Dor: add todo") is True
    log = subprocess.run(["git", "log", "--format=%s", "main"], cwd=origin,
                         check=True, capture_output=True, text=True).stdout
    assert "assistant: Dor: add todo" in log and "dashboard: edit" in log


def test_rebase_conflict_aborts_cleanly(tmp_path):
    ws, origin = _make_workspace(tmp_path)
    other = _clone(tmp_path, origin, "other2")
    (other / "todos.md").write_text("# Todos\n- [x] milk\n")
    _run(other, "add", "-A"); _run(other, "commit", "-m", "dashboard: check"); _run(other, "push")
    (ws / "todos.md").write_text("# Todos\n- [ ] milk (edited)\n")
    sync_workspace(ws, "Dor: edit")  # must not raise
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ws,
                            check=True, capture_output=True, text=True).stdout
    assert not (ws / ".git" / "rebase-merge").exists()  # no rebase in progress
    assert status.strip() == ""  # committed locally, tree clean
