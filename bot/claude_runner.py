import json
import subprocess
from pathlib import Path


class ClaudeError(Exception):
    """Raised when a headless Claude invocation fails."""


def build_command(prompt: str, session_id: str | None, claude_bin: str) -> list[str]:
    cmd = [claude_bin, "-p", "--output-format", "json"]
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)
    return cmd


def run_claude(
    prompt: str,
    workspace: Path,
    session_id: str | None = None,
    claude_bin: str = "claude",
    timeout: int = 300,
) -> tuple[str, str]:
    cmd = build_command(prompt, session_id, claude_bin)
    try:
        proc = subprocess.run(
            cmd, cwd=workspace, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"Claude timed out after {timeout}s")
    except FileNotFoundError:
        raise ClaudeError(f"claude binary not found: {claude_bin}")
    if proc.returncode != 0:
        raise ClaudeError(proc.stderr.strip() or f"claude exited with {proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ClaudeError(f"claude returned unexpected output: {proc.stdout[:200]}")
    if data.get("is_error"):
        raise ClaudeError(data.get("result") or "unknown Claude error")
    return data["result"], data["session_id"]
