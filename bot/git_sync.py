import logging
import subprocess
from pathlib import Path

log = logging.getLogger("assistant.git_sync")


def sync_workspace(workspace: Path, summary: str) -> bool:
    """Commit and push workspace changes. Returns True if a commit was made.

    Never raises: failures are logged and swallowed. Push is attempted on
    every call, so a commit stranded by a failed push goes out next time.
    """
    committed = False
    try:
        if _git(workspace, "status", "--porcelain").strip():
            _git(workspace, "add", "-A")
            summary = " ".join(summary.split()) or "update"
            _git(workspace, "commit", "-m", f"assistant: {summary[:50]}")
            committed = True
        _git(workspace, "push")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as err:
        detail = getattr(err, "stderr", "") or str(err)
        log.warning("workspace sync incomplete: %s", detail.strip())
    return committed


def _git(workspace: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=workspace, capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, proc.stdout, proc.stderr
        )
    return proc.stdout
