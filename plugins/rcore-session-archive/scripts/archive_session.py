#!/usr/bin/env python3
"""Archive a privacy-filtered coding-agent transcript in an rCore repository."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


ARCHIVE_DIR_NAME = ".agent-sessions"
CONFIG_RELATIVE_PATH = Path(".agents") / "session-archive.json"
MODE_MESSAGES = "messages"
MODE_TOOL_CALLS = "tool-calls"
MODE_FULL = "full"
SUPPORTED_MODES = frozenset({MODE_MESSAGES, MODE_TOOL_CALLS, MODE_FULL})
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


def read_archive_mode(repository_root: Path) -> str:
    """Read the repository-local archive mode, defaulting safely to messages."""
    config_path = repository_root / CONFIG_RELATIVE_PATH
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return MODE_MESSAGES
    except (OSError, json.JSONDecodeError) as error:
        print(
            f"rcore-session-archive: cannot read {config_path}: {error}; "
            f"using {MODE_MESSAGES!r}",
            file=sys.stderr,
        )
        return MODE_MESSAGES

    mode = config.get("mode") if isinstance(config, dict) else None
    if mode not in SUPPORTED_MODES:
        print(
            f"rcore-session-archive: unsupported archive mode {mode!r}; "
            f"using {MODE_MESSAGES!r}",
            file=sys.stderr,
        )
        return MODE_MESSAGES
    return mode


def event_with_timestamp(record: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    """Create a normalized archive event with optional source timestamp."""
    event: Dict[str, Any] = dict(fields)
    timestamp = record.get("timestamp")
    if isinstance(timestamp, str) and timestamp:
        event["timestamp"] = timestamp
    return event


def codex_tool_call(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return call metadata for a Codex response item, never its output."""
    item_type = payload.get("type")
    if not isinstance(item_type, str) or not item_type.endswith("_call"):
        return None

    event: Dict[str, Any] = {
        "type": "tool_call",
        "tool_type": item_type,
    }
    # Keep only request-side fields. In particular, do not copy fields named
    # output, result, error, or internal_chat_message_metadata_passthrough.
    for key in (
        "name",
        "call_id",
        "id",
        "server_label",
        "tool_name",
        "input",
        "arguments",
        "action",
        "command",
    ):
        if key in payload:
            event[key] = payload[key]
    return event


def filter_codex_record(
    record: Dict[str, Any], mode: str
) -> Iterator[Dict[str, Any]]:
    """Yield normalized user/final/call events from one Codex record."""
    if record.get("type") != "response_item":
        return
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return

    if payload.get("type") == "message":
        role = payload.get("role")
        content = payload.get("content")
        if role == "user":
            yield event_with_timestamp(
                record, type="message", role="user", content=content
            )
        elif role == "assistant" and payload.get("phase") == "final_answer":
            yield event_with_timestamp(
                record, type="message", role="assistant", content=content
            )
        return

    if mode == MODE_TOOL_CALLS:
        call = codex_tool_call(payload)
        if call is not None:
            yield event_with_timestamp(record, **call)


def claude_user_content(record: Dict[str, Any]) -> Optional[Any]:
    """Extract user-authored Claude content while rejecting tool results/meta."""
    if record.get("type") != "user":
        return None
    if record.get("isMeta") or record.get("isCompactSummary"):
        return None
    if record.get("isSidechain"):
        return None
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return None

    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None

    user_blocks = [
        block
        for block in content
        if isinstance(block, dict)
        and block.get("type") in {"text", "image", "document"}
    ]
    return user_blocks or None


def claude_final_content(record: Dict[str, Any]) -> Optional[Any]:
    """Extract visible text from a completed Claude assistant turn."""
    if record.get("type") != "assistant" or record.get("isSidechain"):
        return None
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    if message.get("stop_reason") != "end_turn":
        return None

    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    text_blocks = [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return text_blocks or None


def filter_claude_record(
    record: Dict[str, Any], mode: str
) -> Iterator[Dict[str, Any]]:
    """Yield normalized user/final/call events from one Claude record."""
    user_content = claude_user_content(record)
    if user_content is not None:
        yield event_with_timestamp(
            record, type="message", role="user", content=user_content
        )
        return

    final_content = claude_final_content(record)
    if final_content is not None:
        yield event_with_timestamp(
            record, type="message", role="assistant", content=final_content
        )

    if mode != MODE_TOOL_CALLS or record.get("type") != "assistant":
        return
    message = record.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        call: Dict[str, Any] = {
            "type": "tool_call",
            "tool_type": "tool_use",
        }
        for source_key, destination_key in (
            ("name", "name"),
            ("id", "call_id"),
            ("input", "input"),
            ("caller", "caller"),
        ):
            if source_key in block:
                call[destination_key] = block[source_key]
        yield event_with_timestamp(record, **call)


def read_jsonl_records(transcript_path: Path) -> Iterator[Dict[str, Any]]:
    """Read a JSONL transcript one record at a time."""
    with transcript_path.open("rb") as input_file:
        for line_number, raw_line in enumerate(input_file, start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ValueError(
                    f"invalid transcript JSON on line {line_number}: {error}"
                ) from error
            if not isinstance(record, dict):
                raise ValueError(
                    f"invalid transcript record on line {line_number}: "
                    "expected an object"
                )
            yield record


def filtered_events(
    transcript_path: Path, agent_name: str, mode: str
) -> Iterator[Dict[str, Any]]:
    """Yield privacy-filtered events for a supported coding agent."""
    filter_record = (
        filter_codex_record if agent_name == "codex" else filter_claude_record
    )
    for record in read_jsonl_records(transcript_path):
        yield from filter_record(record, mode)


def write_archive(
    transcript_path: Path,
    output_file: Any,
    agent_name: str,
    mode: str,
) -> None:
    """Write either the raw transcript or its configured filtered view."""
    if mode == MODE_FULL:
        with transcript_path.open("rb") as input_file:
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
        return

    for event in filtered_events(transcript_path, agent_name, mode):
        encoded = json.dumps(
            event, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        output_file.write(encoded + b"\n")


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
    archive_mode = read_archive_mode(repository_root)
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
            write_archive(transcript_path, output_file, agent_name, archive_mode)
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
