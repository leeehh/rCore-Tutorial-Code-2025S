import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "archive_session.py"
SPEC = importlib.util.spec_from_file_location("archive_session", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load archive script: {SCRIPT_PATH}")
archive_session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive_session)


def transcript_file(directory: Path, records):
    path = directory / "transcript.jsonl"
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            json.dump(record, output)
            output.write("\n")
    return path


class ArchiveModeTests(unittest.TestCase):
    def test_missing_and_invalid_config_use_messages_mode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.assertEqual(
                archive_session.MODE_MESSAGES,
                archive_session.read_archive_mode(root),
            )

            config_directory = root / ".agents"
            config_directory.mkdir()
            config_path = config_directory / "session-archive.json"
            config_path.write_text('{"mode":"unexpected"}\n', encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                mode = archive_session.read_archive_mode(root)
            self.assertEqual(archive_session.MODE_MESSAGES, mode)
            self.assertIn("unsupported archive mode", errors.getvalue())

    def test_all_supported_modes_are_read(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_directory = root / ".agents"
            config_directory.mkdir()
            config_path = config_directory / "session-archive.json"
            for expected_mode in archive_session.SUPPORTED_MODES:
                config_path.write_text(
                    json.dumps({"mode": expected_mode}), encoding="utf-8"
                )
                self.assertEqual(
                    expected_mode, archive_session.read_archive_mode(root)
                )


class CodexFilterTests(unittest.TestCase):
    RECORDS = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "user question"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "developer-secret"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "intermediate-secret"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-1",
                "input": "run-command --flag",
                "status": "completed",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-1",
                "output": "tool-output-secret",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "summary": "reasoning-secret",
            },
        },
        {
            "timestamp": "2026-01-01T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "final answer"}],
            },
        },
    ]

    def collect(self, mode):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = transcript_file(Path(temporary_directory), self.RECORDS)
            return list(archive_session.filtered_events(path, "codex", mode))

    def test_messages_mode_keeps_only_user_and_final_messages(self):
        events = self.collect(archive_session.MODE_MESSAGES)
        self.assertEqual(["user", "assistant"], [event["role"] for event in events])
        serialized = json.dumps(events)
        self.assertNotIn("developer-secret", serialized)
        self.assertNotIn("intermediate-secret", serialized)
        self.assertNotIn("run-command", serialized)
        self.assertNotIn("tool-output-secret", serialized)
        self.assertNotIn("reasoning-secret", serialized)

    def test_tool_calls_mode_keeps_call_but_not_output(self):
        events = self.collect(archive_session.MODE_TOOL_CALLS)
        self.assertEqual(
            ["message", "tool_call", "message"],
            [event["type"] for event in events],
        )
        serialized = json.dumps(events)
        self.assertIn("run-command --flag", serialized)
        self.assertNotIn("tool-output-secret", serialized)


class ClaudeFilterTests(unittest.TestCase):
    RECORDS = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "user",
            "isSidechain": False,
            "message": {"role": "user", "content": "user question"},
        },
        {
            "type": "user",
            "isMeta": True,
            "message": {"role": "user", "content": "metadata-secret"},
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "tool_use",
                "content": [{"type": "text", "text": "intermediate-secret"}],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:01Z",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Bash",
                        "input": {"command": "run-command --flag"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "tool-output-secret",
                    }
                ],
            },
        },
        {
            "timestamp": "2026-01-01T00:00:02Z",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [
                    {"type": "thinking", "thinking": "reasoning-secret"},
                    {"type": "text", "text": "final answer"},
                ],
            },
        },
    ]

    def collect(self, mode):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = transcript_file(Path(temporary_directory), self.RECORDS)
            return list(
                archive_session.filtered_events(path, "claude-code", mode)
            )

    def test_messages_mode_keeps_only_user_and_final_messages(self):
        events = self.collect(archive_session.MODE_MESSAGES)
        self.assertEqual(["user", "assistant"], [event["role"] for event in events])
        serialized = json.dumps(events)
        self.assertNotIn("metadata-secret", serialized)
        self.assertNotIn("intermediate-secret", serialized)
        self.assertNotIn("run-command", serialized)
        self.assertNotIn("tool-output-secret", serialized)
        self.assertNotIn("reasoning-secret", serialized)

    def test_tool_calls_mode_keeps_call_but_not_result(self):
        events = self.collect(archive_session.MODE_TOOL_CALLS)
        self.assertEqual(
            ["message", "tool_call", "message"],
            [event["type"] for event in events],
        )
        serialized = json.dumps(events)
        self.assertIn("run-command --flag", serialized)
        self.assertNotIn("tool-output-secret", serialized)


class ArchiveWriterTests(unittest.TestCase):
    def test_full_mode_is_a_byte_for_byte_copy(self):
        raw_transcript = b'{"type":"arbitrary","secret":"raw-output"}\n'
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "transcript.jsonl"
            path.write_bytes(raw_transcript)
            output = io.BytesIO()
            archive_session.write_archive(
                path, output, "codex", archive_session.MODE_FULL
            )
            self.assertEqual(raw_transcript, output.getvalue())

    def test_archive_transcript_uses_repository_mode_and_atomic_destination(self):
        records = CodexFilterTests.RECORDS
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_directory = root / ".agents"
            config_directory.mkdir()
            (config_directory / "session-archive.json").write_text(
                '{"mode":"tool-calls"}\n', encoding="utf-8"
            )
            source = transcript_file(root, records)
            payload = {
                "transcript_path": str(source),
                "session_id": "session/with unsafe characters",
                "cwd": str(root),
            }

            with mock.patch.object(
                archive_session, "find_repository_root", return_value=root
            ), mock.patch.object(
                archive_session, "is_rcore_repository", return_value=True
            ), mock.patch.dict(os.environ, {"PLUGIN_ROOT": "plugin"}, clear=True):
                archive_session.archive_transcript(payload)

            destination = (
                root
                / ".agent-sessions"
                / "codex"
                / "session_with_unsafe_characters.jsonl"
            )
            self.assertTrue(destination.is_file())
            archived = destination.read_text(encoding="utf-8")
            self.assertIn("run-command --flag", archived)
            self.assertNotIn("tool-output-secret", archived)
            self.assertEqual(0o600, destination.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
