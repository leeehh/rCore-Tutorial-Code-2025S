#!/usr/bin/env python3
"""Archive a coding-agent transcript in the current rCore repository."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


ARCHIVE_DIR_NAME = ".agent-sessions"
SESSION_ID_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def find_repository_root(cwd: str) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def is_rcore_repository(root: Path) -> bool:
    config_path = root / ".codex" / "langfuse.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        tags = config.get("tags", [])
        if isinstance(tags, list) and any(
            str(tag).lower() == "rcore" for tag in tags
        ):
            return True
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    readme_path = root / "README.md"
    try:
        return "rCore-Tutorial-Code-2025S" in readme_path.read_text(
            encoding="utf-8", errors="replace"
        )[:4096]
    except OSError:
        return False


def safe_session_id(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = SESSION_ID_PATTERN.sub("_", value.strip()).strip("._")
    return normalized[:160] or None


def archive_transcript(payload: Dict[str, Any]) -> None:
    transcript_value = payload.get("transcript_path")
    session_id = safe_session_id(payload.get("session_id"))
    cwd = payload.get("cwd")

    if not isinstance(transcript_value, str) or not transcript_value or not session_id:
        return
    if not isinstance(cwd, str) or not cwd:
        return

    repository_root = find_repository_root(cwd)
    if repository_root is None or not is_rcore_repository(repository_root):
        return

    transcript_path = Path(transcript_value).expanduser()
    try:
        transcript_path = transcript_path.resolve(strict=True)
    except OSError:
        return
    if not transcript_path.is_file():
        return

    agent_name = "codex" if os.environ.get("PLUGIN_ROOT") else "claude-code"
    archive_root = repository_root / ARCHIVE_DIR_NAME
    archive_dir = archive_root / agent_name
    archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory in (archive_root, archive_dir):
        try:
            directory.chmod(0o700)
        except OSError:
            pass

    destination = archive_dir / f"{session_id}.jsonl"
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=archive_dir,
        prefix=f".{session_id}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(file_descriptor, "wb") as output_file:
            with transcript_path.open("rb") as input_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, destination)
    except BaseException:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be a JSON object")
        archive_transcript(payload)
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(f"rcore-session-archive: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
