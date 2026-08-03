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

# Invoker-side deny rules: ALLOWED_TOOLS grants Write/Edit/Read under ./** ,
# which includes .claude/ itself. Settings-file deny rules are not enforced
# in an untrusted workspace, so carve .claude/** out here too.
DISALLOWED_TOOLS = [
    "Read(./.claude/**)",
    "Write(./.claude/**)",
    "Edit(./.claude/**)",
]


def build_command(session_id: str | None, claude_bin: str) -> list[str]:
    # --allowedTools/--disallowedTools are variadic: keep --output-format
    # after them so it is never swallowed by a tool list.
    cmd = [
        claude_bin, "-p",
        "--allowedTools", *ALLOWED_TOOLS,
        "--disallowedTools", *DISALLOWED_TOOLS,
        "--output-format", "json",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def run_claude(
    prompt: str,
    workspace: Path,
    session_id: str | None = None,
    claude_bin: str = "claude",
    timeout: int = 300,
) -> tuple[str, str]:
    cmd = build_command(session_id, claude_bin)
    try:
        proc = subprocess.run(
            cmd, cwd=workspace, input=prompt, capture_output=True, text=True,
            timeout=timeout,
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
    if not isinstance(data, dict) or "result" not in data or "session_id" not in data:
        raise ClaudeError(f"claude returned unexpected JSON shape: {proc.stdout[:200]}")
    if data.get("is_error"):
        raise ClaudeError(data.get("result") or "unknown Claude error")
    return data["result"], data["session_id"]
