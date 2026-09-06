#!/usr/bin/env python3
"""Archive a privacy-filtered coding-agent conversation as readable Markdown."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime
from html import escape
from itertools import chain
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


ARCHIVE_DIR_NAME = ".agent-sessions"
CONFIG_RELATIVE_PATH = Path(".codex") / "langfuse.json"
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
    """Read only the shared Langfuse mode; setup handles legacy migration."""
    config_path = repository_root / CONFIG_RELATIVE_PATH
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return MODE_MESSAGES
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(
            f"rcore-session-archive: cannot read {config_path}: {error}; "
            f"using {MODE_MESSAGES!r}",
            file=sys.stderr,
        )
        return MODE_MESSAGES

    mode = config.get("mode", MODE_MESSAGES) if isinstance(config, dict) else None
    if not isinstance(mode, str) or mode not in SUPPORTED_MODES:
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
        elif mode == MODE_FULL and role in {"assistant", "system", "developer"}:
            yield event_with_timestamp(
                record, type="intermediate", role=role, content=content
            )
        return

    if mode in {MODE_TOOL_CALLS, MODE_FULL}:
        call = codex_tool_call(payload)
        if call is not None:
            yield event_with_timestamp(record, **call)
            return

    if mode == MODE_FULL:
        item_type = payload.get("type")
        if isinstance(item_type, str) and item_type.endswith("_call_output"):
            yield event_with_timestamp(
                record,
                type="tool_result",
                call_id=payload.get("call_id", payload.get("id")),
                content=payload.get("output", payload.get("content")),
            )
        elif item_type == "reasoning":
            # Opaque encrypted_content is not readable conversation text.
            content = [payload.get("summary"), payload.get("content")]
            yield event_with_timestamp(record, type="reasoning", content=content)


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

    final_content = claude_final_content(record)
    if final_content is not None and mode != MODE_FULL:
        yield event_with_timestamp(
            record, type="message", role="assistant", content=final_content
        )

    message = record.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, list):
        if (
            mode == MODE_FULL
            and record.get("type") == "assistant"
        ):
            yield event_with_timestamp(
                record, type="message" if final_content is not None else "intermediate",
                role="assistant", content=content
            )
        return

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if (
            block_type == "tool_use"
            and record.get("type") == "assistant"
            and mode in {MODE_TOOL_CALLS, MODE_FULL}
        ):
            call: Dict[str, Any] = {"type": "tool_call", "tool_type": "tool_use"}
            for source_key, destination_key in (
                ("name", "name"), ("id", "call_id"),
                ("input", "input"), ("caller", "caller"),
            ):
                if source_key in block:
                    call[destination_key] = block[source_key]
            yield event_with_timestamp(record, **call)
        elif mode == MODE_FULL:
            if block_type == "tool_result":
                yield event_with_timestamp(
                    record, type="tool_result", call_id=block.get("tool_use_id"),
                    content=block.get("content"), is_error=block.get("is_error", False),
                )
            elif block_type == "thinking":
                yield event_with_timestamp(
                    record, type="reasoning", content=block.get("thinking")
                )
            elif (
                block_type == "text"
                and record.get("type") == "assistant"
            ):
                yield event_with_timestamp(
                    record, type="message" if final_content is not None else "intermediate",
                    role="assistant", content=block.get("text")
                )


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


def decode_structured_text(value: Any) -> Any:
    """Decode structured tool arguments without interpreting ordinary text."""
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, RecursionError):
            pass
    return value


def readable_values(value: Any) -> str:
    """Render tool parameters as indented key/value text, not escaped JSON."""
    if value is None:
        return "空"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            text = readable_values(item)
            if "\n" in text or isinstance(item, (dict, list)):
                lines.append(f"{key}:\n" + "\n".join(f"  {line}" for line in text.splitlines()))
            else:
                lines.append(f"{key}: {text}")
        return "\n".join(lines) or "（无参数）"
    if isinstance(value, list):
        return "\n".join("- " + readable_values(item).replace("\n", "\n  ") for item in value)
    return str(value)


def content_text(content: Any) -> str:
    """Extract visible text and attachment descriptions from agent content blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content if content.strip() else ""
    if isinstance(content, list):
        return "\n\n".join(text for item in content if (text := content_text(item)))
    if isinstance(content, dict):
        block_type = content.get("type")
        if block_type in {"image", "input_image", "image_url", "document", "input_audio", "audio"}:
            label = "文档" if block_type == "document" else "音频" if "audio" in block_type else "图片"
            name = content.get("title") or content.get("filename") or content.get("name")
            source = content.get("source", {})
            location = content.get("image_url") or content.get("url") or content.get("path")
            if isinstance(location, dict):
                location = location.get("url")
            if not location and isinstance(source, dict):
                location = source.get("url")
            description = f"[{label}附件" + (f"：{name}" if name else "") + "]"
            if isinstance(location, str) and not location.startswith("data:"):
                description += " " + escape(location)
            if block_type == "document" and isinstance(source, dict) and source.get("type") == "text":
                description += "\n\n" + str(source.get("data", ""))
            return description
        for key in ("text", "thinking", "content", "output"):
            if key in content:
                return content_text(content[key])
        return readable_values(content)
    return str(content)


def code_block(text: str, language: str = "text") -> str:
    # A tool result may itself contain fenced Markdown. A longer fence ensures
    # the result cannot accidentally close the surrounding code block.
    longest = max((len(match.group()) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    text = text.rstrip("\r\n")
    return f"{fence}{language}\n{text}\n{fence}"


def tool_output_text(value: Any) -> str:
    value = decode_structured_text(value)
    if isinstance(value, dict) and not value.get("type"):
        content_key = next((key for key in ("content", "output") if key in value), None)
        if content_key:
            text = content_text(value[content_key])
            remaining = {key: item for key, item in value.items() if key != content_key}
            if remaining:
                text += "\n\n" + readable_values(remaining)
            return text
    return content_text(value)


def timestamp_text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(sep=" ", timespec="seconds")
    except ValueError:
        return value.replace("\n", " ").replace("\r", " ")


def tool_input_markdown(event: Dict[str, Any]) -> str:
    value = next((event[key] for key in ("input", "arguments", "action", "command") if key in event), None)
    value = decode_structured_text(value)
    if value is None:
        return "（无参数）"
    if isinstance(value, dict):
        command_key = next((key for key in ("cmd", "command") if key in value), None)
        command = value.get(command_key) if command_key else None
        if isinstance(command, list) and all(isinstance(part, str) for part in command):
            command = shlex.join(command)
        if isinstance(command, str):
            text = "执行命令：\n\n" + code_block(command, "bash")
            remaining = {key: item for key, item in value.items() if key != command_key}
            if remaining:
                text += "\n\n其他参数：\n\n" + code_block(readable_values(remaining))
            return text
    if "command" in event and isinstance(value, str):
        return "执行命令：\n\n" + code_block(value, "bash")
    return "工具输入：\n\n" + code_block(readable_values(value))


def event_markdown(event: Dict[str, Any], agent_label: str, tool_names: Dict[str, str]) -> str:
    kind = event.get("type")
    content = content_text(event.get("content"))
    timestamp = timestamp_text(event.get("timestamp"))
    title = ""
    collapse = False

    if kind == "tool_call":
        name = str(event.get("name") or event.get("tool_name") or event.get("tool_type") or "未命名工具")
        call_id = event.get("call_id") or event.get("id")
        if call_id:
            tool_names[str(call_id)] = name
        title = f"工具调用：{name}"
        content = tool_input_markdown(event)
        if call_id:
            content = f"调用 ID：{escape(str(call_id))}\n\n{content}"
    elif kind == "tool_result":
        call_id = str(event.get("call_id") or "")
        title = "工具输出：" + tool_names.get(call_id, call_id or "未命名工具")
        if event.get("is_error"):
            title += "（错误）"
        content = tool_output_text(event.get("content")) or "（无文本输出）"
        collapse = len(content) > 1200 or len(content.splitlines()) > 12
        content = code_block(content)
    elif kind == "message":
        title = "用户" if event.get("role") == "user" else agent_label
    elif kind in {"intermediate", "reasoning"}:
        title = {
            "system": "系统指令", "developer": "开发者指令",
        }.get(event.get("role"), f"{agent_label} 中间输出")
        if kind == "reasoning":
            title = f"{agent_label} 推理摘要"
        collapse = len(content) > 1200 or len(content.splitlines()) > 12

    if not title or not content.strip():
        return ""
    title = title.replace("\n", " ").replace("\r", " ")
    if collapse:
        label = escape(title + (f" · {timestamp}" if timestamp else ""))
        return f"<details>\n<summary>{label}</summary>\n\n{content}\n\n</details>\n\n"
    metadata = f"时间：{timestamp}\n\n" if timestamp else ""
    return f"### {escape(title)}\n\n{metadata}{content}\n\n"


def write_archive(
    transcript_path: Path,
    output_file: Any,
    agent_name: str,
    mode: str,
    session_id: Optional[str] = None,
) -> None:
    """Stream one Markdown view; never write a second raw transcript copy."""
    agent_label = "Codex" if agent_name == "codex" else "Claude Code"
    events = filtered_events(transcript_path, agent_name, mode)
    first_event = next(events, None)
    started = timestamp_text(first_event.get("timestamp")) if first_event else ""

    def write(text: str) -> None:
        output_file.write(text.encode("utf-8"))

    write(f"# {agent_label} 会话记录\n\n")
    write(f"会话 ID：{escape(session_id or transcript_path.stem)}\n\n")
    if started:
        write(f"开始时间：{started}\n\n")
    write(f"归档等级：{mode}\n\n")

    turn = 0
    agent_has_responded = False
    tool_names: Dict[str, str] = {}
    wrote_event = False
    for event in chain([first_event], events) if first_event else ():
        rendered = event_markdown(event, agent_label, tool_names)
        if not rendered:
            continue
        is_user = event.get("type") == "message" and event.get("role") == "user"
        is_context = event.get("role") in {"system", "developer"}
        if not is_context and (turn == 0 or (is_user and agent_has_responded)):
            turn += 1
            write(f"## 第 {turn} 轮\n\n")
            agent_has_responded = False
        write(rendered)
        wrote_event = True
        if not is_user and not is_context:
            agent_has_responded = True
    if not wrote_event:
        write("本归档等级下暂无可保存的消息。\n")


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

    destination = archive_dir / f"{session_id}.md"
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=archive_dir,
        prefix=f".{session_id}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(file_descriptor, "wb") as output_file:
            write_archive(transcript_path, output_file, agent_name, archive_mode, session_id)
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

    # Retire only this session's legacy archive after Markdown was safely saved.
    # Never remove the agent's source transcript, a symlink, or another session.
    legacy = archive_dir / f"{session_id}.jsonl"
    if legacy.is_file() and not legacy.is_symlink() and legacy.resolve() != transcript_path:
        try:
            legacy.unlink()
        except OSError as error:
            print(f"rcore-session-archive: cannot remove legacy archive {legacy}: {error}", file=sys.stderr)


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
