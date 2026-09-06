#!/usr/bin/env python3
"""Project-only Cursor hooks: readable Markdown + student-authenticated OTLP.

Cursor's documented event payloads are the source; never scan its private database
or copy transcript_path. The SQLite index contains IDs, hashes and times ONLY.
Conversation bodies live only in the mode-filtered Markdown file. Network failures
do not block the agent; there is deliberately no unfiltered disk upload queue.
"""

import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from archive_session import (
    SUPPORTED_MODES, event_markdown, find_repository_root, safe_session_id,
)


EVENTS = (
    "beforeSubmitPrompt", "afterAgentResponse", "afterAgentThought",
    "preToolUse", "postToolUse", "postToolUseFailure", "stop",
)
COMMAND = 'python3 ".cursor/rcore-hooks/cursor_hook.py"'
LEGACY_COMMAND = 'python3 "plugins/rcore-session-archive/scripts/cursor_hook.py"'
BLOCK = re.compile(
    r"<!-- rcore-cursor:([0-9a-f]{64}) -->\n(.*?)<!-- /rcore-cursor -->\n",
    re.DOTALL,
)


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def warn(message):
    print(f"[rCore Cursor] {message}", file=sys.stderr)


def atomic_write(path, text):
    if path.is_symlink():
        raise ValueError("refusing a symlink output")
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def private_directory(path):
    if path.is_symlink():
        raise ValueError("refusing a symlink archive directory")
    path.mkdir(mode=0o700, exist_ok=True)
    path.chmod(0o700)


def read_blocks(path, agent_label="Cursor", marker="rcore-cursor"):
    if path.is_symlink():
        raise ValueError("refusing a symlink archive")
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    pattern = BLOCK if marker == "rcore-cursor" else re.compile(
        rf"<!-- {re.escape(marker)}:([0-9a-f]{{64}}) -->\n(.*?)<!-- /{re.escape(marker)} -->\n", re.DOTALL)
    blocks = dict(pattern.findall(text))
    if text.strip() and not blocks and not (text.startswith(f"# {agent_label} 会话\n") and f"<!-- {marker}:" not in text):
        raise ValueError("existing Cursor archive is not a managed Markdown file")
    return blocks


def put_block(blocks, key, events, names=None, agent_label="Cursor", marker="rcore-cursor"):
    names = {} if names is None else names
    text = "".join(event_markdown(event, agent_label, names) for event in events)
    # User/tool text must not be able to forge our invisible record boundaries.
    text = text.replace(f"<!-- {marker}:", f"&lt;!-- {marker}:")
    text = text.replace(f"<!-- /{marker}", f"&lt;!-- /{marker}")
    if text.strip():
        blocks[key] = text


def message_text(blocks, key):
    body = blocks.get(key, "")
    return body.split("\n\n", 1)[1].rstrip() if "\n\n" in body else ""


def open_index(path):
    if path.is_symlink():
        raise ValueError("refusing a symlink index")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(descriptor)
    path.chmod(0o600)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS turns (
            id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE, started INTEGER,
            phase INTEGER DEFAULT 0, reply TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS events (
            ordinal INTEGER PRIMARY KEY, id TEXT UNIQUE, turn_id TEXT,
            kind TEXT, started INTEGER, ended INTEGER, content_hash TEXT,
            sent_hash TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS text_callbacks (
            turn_id TEXT, event TEXT, phase INTEGER, content_hash TEXT, event_id TEXT,
            PRIMARY KEY(turn_id,event,phase)
        );
    """)
    return db


def text_event_id(db, turn, event, text):
    # Text callbacks have no tool_use_id. Only coalesce consecutive identical
    # notifications in the same tool phase; A -> B -> A are three real messages.
    fingerprint = digest(text)
    previous = db.execute(
        "SELECT * FROM text_callbacks WHERE turn_id=? AND event=? AND phase=?",
        (turn["id"], event, turn["phase"]),
    ).fetchone()
    if previous and previous["content_hash"] == fingerprint:
        return previous["event_id"]
    ordinal = db.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM events").fetchone()[0]
    key = digest(turn["id"], event, turn["phase"], ordinal, fingerprint)
    db.execute("INSERT OR REPLACE INTO text_callbacks VALUES(?,?,?,?,?)",
               (turn["id"], event, turn["phase"], fingerprint, key))
    return key


def event_row(db, turn, key, kind, fingerprint, now, duration=0):
    row = db.execute("SELECT * FROM events WHERE id=?", (key,)).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO events(id,turn_id,kind,started,ended,content_hash) VALUES(?,?,?,?,?,?)",
            (key, turn["id"], kind, max(turn["started"], now - duration), now, fingerprint),
        )
    elif row["content_hash"] != fingerprint:
        db.execute("UPDATE events SET ended=?,content_hash=?,kind=? WHERE id=?",
                   (now, fingerprint, kind, key))
    return db.execute("SELECT * FROM events WHERE id=?", (key,)).fetchone()


def write_markdown(path, db, blocks, mode, session_id, agent_label="Cursor", marker="rcore-cursor"):
    chunks = [f"# {agent_label} 会话\n\n会话 ID：{session_id}\n\n本地留档等级：`{mode}`\n\n"]
    for turn in db.execute("SELECT * FROM turns ORDER BY ordinal"):
        rendered = []
        for row in db.execute("SELECT * FROM events WHERE turn_id=? ORDER BY ordinal", (turn["id"],)):
            key, kind = row["id"], row["kind"]
            keep = kind in {"user", "reply"} or mode == "full" or (mode == "tool-calls" and kind in {"tool", "tool_pending"})
            if not keep:
                blocks.pop(key, None)
            body = blocks.get(key)
            if body:
                rendered.append(f"<!-- {marker}:{key} -->\n{body}<!-- /{marker} -->\n\n")
        if rendered:
            started = datetime.fromtimestamp(turn["started"] / 1_000_000_000, timezone.utc).isoformat(sep=" ", timespec="seconds")
            chunks.append(f"## 第 {turn['ordinal']} 轮\n\n时间：{started}\n\n" + "".join(rendered))
    if len(chunks) > 1 or path.exists():
        text = "".join(chunks)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            atomic_write(path, text)


def attribute(key, value):
    if isinstance(value, list):
        encoded = {"arrayValue": {"values": [{"stringValue": str(item)} for item in value]}}
    else:
        encoded = {"stringValue": str(value)}
    return {"key": key, "value": encoded}


def make_span(config, payload, turn, row, name, kind, input_text=None, output_text=None, error="", root=False,
              agent_name="cursor", agent_label="Cursor"):
    # Namespace IDs by credential identity, agent, conversation and generation.
    # Retrying the same event never allocates a fresh trace or observation ID.
    trace_id = digest(agent_name, config.get("public_key"), payload["conversation_id"], payload["generation_id"])[:32]
    root_id = digest(trace_id, "root")[:16]
    values = {
        "langfuse.session.id": agent_name + "-" + digest(config.get("public_key"), payload["conversation_id"])[:32],
        "langfuse.trace.name": f"{agent_label} Turn",
        "langfuse.trace.tags": list(dict.fromkeys(["rcore", agent_name] + config.get("tags", []))),
        "langfuse.observation.type": kind,
        "langfuse.observation.metadata.agent": agent_name,
    }
    model = payload.get("model_id") or payload.get("model")
    if model and kind == "generation":
        values["langfuse.observation.model.name"] = model
    if input_text is not None:
        values["langfuse.observation.input"] = json.dumps(input_text, ensure_ascii=False)
    if output_text is not None:
        values["langfuse.observation.output"] = json.dumps(output_text, ensure_ascii=False)
    if error:
        values["langfuse.observation.level"] = "ERROR"
        values["langfuse.observation.status_message"] = error
    if kind == "tool":
        values[f"langfuse.observation.metadata.{agent_name}_tool"] = payload.get("tool_name", name)
    span = {
        "traceId": trace_id, "spanId": root_id if root else row["id"][:16],
        "name": name, "kind": 1,
        "startTimeUnixNano": str(turn["started"] if root else row["started"]),
        "endTimeUnixNano": str(row["ended"]),
        "attributes": [attribute(key, value) for key, value in values.items()],
        "status": {"code": 2, "message": error} if error else {"code": 0},
    }
    if not root:
        span["parentSpanId"] = root_id
    return span


def valid_credentials(config):
    if not isinstance(config.get("base_url"), str):
        return False
    parsed = urllib.parse.urlsplit(config["base_url"])
    return bool(
        re.fullmatch(r"pk-lf-stu-[0-9]{6,20}", str(config.get("public_key", "")))
        and re.fullmatch(r"sk-lf-token-[A-Za-z0-9_-]{20,}", str(config.get("secret_key", "")))
        and parsed.scheme == "https" and parsed.hostname and not parsed.username
        and not parsed.password and not parsed.query and not parsed.fragment
        and parsed.path in ("", "/")
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a student token to a redirected host.


def upload(config, spans, agent_name="cursor"):
    envelope = {"resourceSpans": [{
        "resource": {"attributes": [attribute("service.name", f"rcore-{agent_name}")]},
        "scopeSpans": [{"scope": {"name": f"rcore.{agent_name}-hooks"}, "spans": spans}],
    }]}
    authorization = base64.b64encode(f"{config['public_key']}:{config['secret_key']}".encode()).decode()
    request = urllib.request.Request(
        config["base_url"].rstrip("/") + "/api/public/otel/v1/traces",
        data=json.dumps(envelope, ensure_ascii=False).encode(),
        headers={"Authorization": f"Basic {authorization}", "Content-Type": "application/json",
                 "x-langfuse-ingestion-version": "4"}, method="POST",
    )
    opener = urllib.request.build_opener(NoRedirect())
    failure = "network error"
    for attempt in range(2):
        try:
            with opener.open(request, timeout=2) as response:
                result = response.read(65536)
                if result:
                    decoded = json.loads(result)
                    if not isinstance(decoded, dict):
                        raise ValueError("invalid OTLP response")
                    partial = decoded.get("partialSuccess", decoded.get("partial_success", {}))
                    if int(partial.get("rejectedSpans", partial.get("rejected_spans", 0))):
                        raise ValueError("OTLP partial rejection")
                return True
        except urllib.error.HTTPError as error:
            failure = f"HTTP {error.code}"
            if error.code != 429 and error.code < 500:
                break
        except (OSError, ValueError, urllib.error.URLError) as error:
            failure = type(error).__name__
    # No response body, credential, raw payload or URL is printed in error logs.
    message = f"上传失败（{failure}），本地留档不受影响；本次事件未排入磁盘补传队列。"
    if agent_name == "cursor":
        warn(message)
    else:
        print(f"[rCore {agent_name}] {message}", file=sys.stderr)
    return False


def handle(payload, project_root=None, sender=upload):
    if not isinstance(payload, dict) or payload.get("hook_event_name") not in EVENTS:
        return
    root = project_root or find_repository_root(str(Path.cwd()))
    if root is None:
        return
    root = Path(root).resolve()
    # A multi-root workspace containing another project is intentionally excluded.
    roots = payload.get("workspace_roots")
    if not isinstance(roots, list) or not roots:
        return
    for workspace in roots:
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            return
        resolved = Path(workspace).resolve()
        if resolved != root and root not in resolved.parents:
            return
    config_path = root / ".cursor/langfuse.json"
    if config_path.parent.is_symlink() or not config_path.is_file() or config_path.is_symlink():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("enabled") is not True:
        return
    mode = config.get("mode", "messages")
    if not isinstance(mode, str) or mode not in SUPPORTED_MODES:
        warn("归档等级无效，使用 messages。")
        mode = "messages"
    if not isinstance(config.get("tags", []), list) or not all(isinstance(tag, str) for tag in config.get("tags", [])):
        raise ValueError("invalid tags")
    conversation, generation = payload.get("conversation_id"), payload.get("generation_id")
    if not isinstance(conversation, str) or not conversation or not isinstance(generation, str) or not generation:
        return
    event = payload["hook_event_name"]
    sid = safe_session_id(conversation)
    # Preserve ordinary Cursor UUID filenames, without allowing sanitization collisions.
    if sid != conversation:
        sid = sid[:100] + "-" + digest(conversation)[:16]
    directory = root / ".agent-sessions" / "cursor"
    index = directory / ".state" / f"{sid}.sqlite3"
    archive_path = directory / f"{sid}.md"
    if archive_path.exists() and not index.exists():
        raise ValueError("archive index is missing; preserve the existing Markdown")
    if event == "stop" and not index.exists():
        return  # Never create an empty "Cursor Turn (...)" from a lifecycle event.
    for path in (directory.parent, directory, index.parent):
        private_directory(path)
    turn_id = digest(conversation, generation)
    now = time.time_ns()
    jobs = []
    with closing(open_index(index)) as db:
        with db:
            db.execute("BEGIN IMMEDIATE")
            blocks = read_blocks(archive_path)
            db.execute(
                "INSERT OR IGNORE INTO turns(id,ordinal,started) VALUES(?,(SELECT COALESCE(MAX(ordinal),0)+1 FROM turns),?)",
                (turn_id, now),
            )
            turn = db.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()

            def queue(key, kind, name, input_text=None, output_text=None, error="", is_root=False, duration=0):
                fingerprint = digest(kind, name, input_text, output_text, error)
                row = event_row(db, turn, key, "root" if is_root else kind, fingerprint, now, duration)
                if row["sent_hash"] != fingerprint:
                    jobs.append((key, fingerprint, make_span(config, payload, turn, row, name, kind,
                                                             input_text, output_text, error, is_root)))

            def demote_reply(key):
                text = message_text(blocks, key)
                if text:
                    queue(key, "event", "Cursor 中间输出", output_text=text)
                db.execute("UPDATE events SET kind='intermediate' WHERE id=?", (key,))
                blocks[key] = blocks.get(key, "").replace("### Cursor\n", "### Cursor 中间输出\n", 1)

            if event == "beforeSubmitPrompt":
                prompt = payload.get("prompt", "")
                if not isinstance(prompt, str):
                    raise ValueError("invalid prompt")
                attachments = payload.get("attachments", [])
                references = [str(item["file_path"]) for item in attachments
                              if isinstance(item, dict) and item.get("file_path")]
                if references:
                    prompt += "\n\n附件引用：\n" + "\n".join(f"- {path}" for path in references)
                if prompt.strip():
                    key = digest(turn_id, "user")
                    event_row(db, turn, key, "user", digest(prompt), now)
                    put_block(blocks, key, [{"type": "message", "role": "user", "content": prompt}])

            elif event in {"preToolUse", "postToolUse", "postToolUseFailure"}:
                tool_id = payload.get("tool_use_id")
                if not isinstance(tool_id, str) or not tool_id:
                    raise ValueError("Cursor tool_use_id is missing; update Cursor")
                key = digest(turn_id, "tool", tool_id)
                previous = db.execute("SELECT * FROM events WHERE id=?", (key,)).fetchone()
                if previous is None:
                    db.execute("UPDATE turns SET phase=phase+1 WHERE id=?", (turn_id,))
                # A message followed by another tool is commentary, not the final answer.
                if previous is None and turn["reply"]:
                    demote_reply(turn["reply"])
                    db.execute("UPDATE turns SET reply='' WHERE id=?", (turn_id,))
                name = str(payload.get("tool_name") or "Tool")
                call = {"type": "tool_call", "name": name, "call_id": tool_id, "input": payload.get("tool_input")}
                result = {"type": "tool_result", "call_id": tool_id, "content": payload.get("tool_output"),
                          "is_error": event == "postToolUseFailure"}
                error = str(payload.get("error_message") or payload.get("failure_type") or "工具执行失败") if result["is_error"] else ""
                if error:
                    result["content"] = error
                note = payload.get("agent_message")
                if isinstance(note, str) and note.strip():
                    note_key = digest(key, "note")
                    queue(note_key, "event", "Cursor 中间输出", output_text=note)
                    if mode == "full":
                        put_block(blocks, note_key, [{"type": "intermediate", "content": note}])
                # Do not let a replayed pre hook overwrite an already completed tool.
                if not (event == "preToolUse" and previous and previous["kind"] == "tool"):
                    input_text = event_markdown(call, "Cursor", {})
                    output_text = event_markdown(result, "Cursor", {tool_id: name}) if event != "preToolUse" else None
                    duration = payload.get("duration", 0)
                    duration = int(max(0, duration) * 1_000_000) if isinstance(duration, (int, float)) else 0
                    # The course collector preserves shell input for its existing Bash allowlist.
                    queue(key, "tool", "Bash" if name in {"Shell", "Bash"} else name,
                          input_text, output_text, error, duration=duration)
                    db.execute("UPDATE events SET kind=? WHERE id=?", ("tool_pending" if event == "preToolUse" else "tool", key))
                    if mode != "messages":
                        put_block(blocks, key, [call])
                    if event != "preToolUse":
                        result_key = digest(key, "result")
                        event_row(db, turn, result_key, "tool_result", digest(output_text), now)
                        if mode == "full":
                            put_block(blocks, result_key, [result], {tool_id: name})

            elif event in {"afterAgentResponse", "afterAgentThought"}:
                text = payload.get("text")
                if isinstance(text, str) and text.strip():
                    key = text_event_id(db, turn, event, text)
                    if event == "afterAgentResponse":
                        if turn["reply"] and turn["reply"] != key:
                            demote_reply(turn["reply"])
                        event_row(db, turn, key, "reply", digest(text), now)
                        db.execute("UPDATE turns SET reply=? WHERE id=?", (key, turn_id))
                        put_block(blocks, key, [{"type": "message", "role": "assistant", "content": text}])
                    else:
                        queue(key, "event", "Cursor 推理摘要", output_text=text)
                        if mode == "full":
                            put_block(blocks, key, [{"type": "reasoning", "content": text}])

            if event in {"afterAgentResponse", "stop"}:
                turn = db.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
                prompt = message_text(blocks, digest(turn_id, "user"))
                reply = message_text(blocks, turn["reply"])
                if prompt or reply:
                    status = payload.get("status") if event == "stop" else "completed"
                    error = {"aborted": "用户中止", "error": "Agent 出错"}.get(status, "")
                    queue(digest(turn_id, "root"), "generation", "Cursor Turn",
                          [{"role": "user", "content": prompt}] if prompt else None,
                          [{"role": "assistant", "content": reply}] if reply else [],
                          error, is_root=True)
            write_markdown(archive_path, db, blocks, mode, sid)

        # Do not hold the SQLite/file write lock over network I/O.
        if jobs and valid_credentials(config):
            if sender(config, [job[2] for job in jobs]):
                with db:
                    for key, fingerprint, _span in jobs:
                        db.execute("UPDATE events SET sent_hash=? WHERE id=? AND content_hash=?",
                                   (fingerprint, key, fingerprint))
        elif jobs:
            warn("缺少有效的学生凭据，只保存本地 Markdown；请重新运行 cursor 配置并传入 token JSON。")


def install_hooks(root):
    path = Path(root) / ".cursor/hooks.json"
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Cursor project configuration must not be a symlink")
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "hooks": {}}
    if not isinstance(config, dict) or config.get("version", 1) != 1:
        raise ValueError("unsupported Cursor hooks configuration")
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Cursor hooks must be an object")
    config.setdefault("version", 1)
    for event in EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError(f"invalid Cursor hook list: {event}")
        # Preserve all unrelated hooks; repeat setup must not add duplicate handlers.
        hooks[event] = [entry for entry in entries if entry.get("command") not in {COMMAND, LEGACY_COMMAND}] + [{"command": COMMAND}]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the native hook AND its runtime in the ignored project directory.
    # A checkout of a lab branch must not remove the installed Cursor integration.
    runtime = path.parent / "rcore-hooks"
    private_directory(runtime)
    for filename in ("archive_session.py", "cursor_hook.py"):
        source = Path(__file__).resolve().parent / filename
        atomic_write(runtime / filename, source.read_text(encoding="utf-8"))
    atomic_write(path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--install":
        install_hooks(Path(sys.argv[2]).resolve())
        return 0
    try:
        handle(json.load(sys.stdin))
    except Exception as error:
        # Fail open without leaking any content or modifying a permission decision.
        warn(f"hook 未完成（{type(error).__name__}）；请检查项目配置及归档目录权限。")
    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
