import json
import subprocess
from types import SimpleNamespace

import pytest

from bot.claude_runner import (
    ALLOWED_TOOLS,
    DISALLOWED_TOOLS,
    ClaudeError,
    build_command,
    run_claude,
)


def _fake_result(payload, returncode=0, stderr=""):
    return SimpleNamespace(
        stdout=json.dumps(payload) if isinstance(payload, dict) else payload,
        stderr=stderr,
        returncode=returncode,
    )


SUCCESS = {"is_error": False, "result": "done!", "session_id": "abc-123", "type": "result"}


def test_build_command_new_session():
    cmd = build_command(None, "claude")
    assert cmd == [
        "claude", "-p",
        "--allowedTools", *ALLOWED_TOOLS,
        "--disallowedTools", *DISALLOWED_TOOLS,
        "--output-format", "json",
    ]


def test_build_command_resume():
    cmd = build_command("abc-123", "claude")
    assert "--resume" in cmd and "abc-123" in cmd
    assert cmd.index("--output-format") > cmd.index("--allowedTools")
    assert cmd.index("--disallowedTools") > cmd.index("--allowedTools")


def test_run_claude_success(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _fake_result(SUCCESS)

    monkeypatch.setattr(subprocess, "run", fake_run)
    reply, session = run_claude("hi", tmp_path)
    assert reply == "done!"
    assert session == "abc-123"
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["input"] == "hi"


def test_run_claude_error_flag(monkeypatch, tmp_path):
    payload = {"is_error": True, "result": "usage limit reached", "session_id": "x"}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_result(payload))
    with pytest.raises(ClaudeError, match="usage limit"):
        run_claude("hi", tmp_path)


def test_run_claude_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _fake_result("", returncode=1, stderr="boom")
    )
    with pytest.raises(ClaudeError, match="boom"):
        run_claude("hi", tmp_path)


def test_run_claude_timeout(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 300))

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeError, match="timed out"):
        run_claude("hi", tmp_path, timeout=5)


def test_run_claude_bad_json(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_result("not json"))
    with pytest.raises(ClaudeError, match="unexpected output"):
        run_claude("hi", tmp_path)


def test_run_claude_non_dict_json(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_result(json.dumps([1, 2])))
    with pytest.raises(ClaudeError, match="unexpected JSON shape"):
        run_claude("hi", tmp_path)


def test_run_claude_missing_session_id(monkeypatch, tmp_path):
    payload = {"is_error": False, "result": "done!"}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_result(payload))
    with pytest.raises(ClaudeError, match="unexpected JSON shape"):
        run_claude("hi", tmp_path)
