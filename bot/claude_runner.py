import json
import subprocess
from pathlib import Path


class ClaudeError(Exception):
    """Raised when a headless Claude invocation fails."""


# Invoker-side sandbox: file tools scoped to the workspace cwd, plus web.
# Passed as CLI flags because settings.json allow rules are ignored when the
# workspace directory has not been interactively trusted.
ALLOWED_TOOLS = [
    "Read(./**)",
    "Write(./**)",
    "Edit(./**)",
    "Glob(./**)",
    "Grep(./**)",
    "WebSearch",
    "WebFetch",
]


def build_command(prompt: str, session_id: str | None, claude_bin: str) -> list[str]:
    # --allowedTools is variadic: keep --output-format after it so the
    # positional prompt is never swallowed by the tool list.
    cmd = [claude_bin, "-p", "--allowedTools", *ALLOWED_TOOLS, "--output-format", "json"]
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
