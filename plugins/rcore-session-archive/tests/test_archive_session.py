import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "archive_session.py"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
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


def write_config(root: Path, relative_path: str, config):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class ArchiveModeTests(unittest.TestCase):
    def test_missing_and_invalid_config_use_messages_mode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.assertEqual(
                archive_session.MODE_MESSAGES,
                archive_session.read_archive_mode(root),
            )

            config_directory = root / ".codex"
            config_directory.mkdir()
            config_path = config_directory / "langfuse.json"
            config_path.write_text('{"mode":"unexpected"}\n', encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                mode = archive_session.read_archive_mode(root)
            self.assertEqual(archive_session.MODE_MESSAGES, mode)
            self.assertIn("unsupported archive mode", errors.getvalue())

    def test_all_supported_modes_are_read(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for expected_mode in archive_session.SUPPORTED_MODES:
                write_config(root, ".codex/langfuse.json", {"mode": expected_mode})
                self.assertEqual(expected_mode, archive_session.read_archive_mode(root))
                write_config(root, ".claude/settings.local.json", {
                    "env": {"RCORE_SESSION_ARCHIVE_MODE": expected_mode},
                })
                self.assertEqual(expected_mode, archive_session.read_archive_mode(root, "claude-code"))

    def test_agent_modes_are_independent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_config(root, ".codex/langfuse.json", {"mode": "full"})
            write_config(root, ".claude/settings.local.json", {
                "env": {"RCORE_SESSION_ARCHIVE_MODE": "tool-calls"},
            })
            self.assertEqual("full", archive_session.read_archive_mode(root, "codex"))
            self.assertEqual("tool-calls", archive_session.read_archive_mode(root, "claude-code"))

    def test_claude_missing_mode_does_not_use_codex_or_process_environment(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_config(root, ".codex/langfuse.json", {"mode": "full"})
            write_config(root, ".agents/session-archive.json", {"mode": "full"})
            with mock.patch.dict(os.environ, {"RCORE_SESSION_ARCHIVE_MODE": "full"}):
                self.assertEqual("messages", archive_session.read_archive_mode(root, "claude-code"))
                write_config(root, ".claude/settings.local.json", {"env": {"LANGFUSE_PUBLIC_KEY": "example"}})
                self.assertEqual("messages", archive_session.read_archive_mode(root, "claude-code"))

    def test_invalid_claude_config_does_not_fall_back_to_codex(self):
        for content in (
            b"{", b"\xff", b"[]", b'{"env": []}', b'{"env": null}',
            b'{"env": {"RCORE_SESSION_ARCHIVE_MODE": []}}',
            b'{"env": {"RCORE_SESSION_ARCHIVE_MODE": "unknown"}}',
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                write_config(root, ".codex/langfuse.json", {"mode": "full"})
                path = write_config(root, ".claude/settings.local.json", {})
                path.write_bytes(content)
                with redirect_stderr(io.StringIO()):
                    self.assertEqual("messages", archive_session.read_archive_mode(root, "claude-code"))

    def test_langfuse_mode_overrides_legacy_choice(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_config(root, ".agents/session-archive.json", {"mode": "full"})
            write_config(root, ".codex/langfuse.json", {"mode": "messages", "enabled": False})
            self.assertEqual("messages", archive_session.read_archive_mode(root))

    def test_missing_langfuse_mode_defaults_without_reading_retired_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_config(root, ".agents/session-archive.json", {"mode": "full"})
            self.assertEqual("messages", archive_session.read_archive_mode(root))
            write_config(root, ".codex/langfuse.json", {"public_key": "example-key"})
            self.assertEqual("messages", archive_session.read_archive_mode(root))

    def test_invalid_langfuse_config_does_not_enable_full_legacy_mode(self):
        for content in (b"{", b"\xff", b"[]", b'{"mode": []}', b'{"mode": null}', b'{"mode": "unknown"}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                write_config(root, ".agents/session-archive.json", {"mode": "full"})
                path = write_config(root, ".codex/langfuse.json", {})
                path.write_bytes(content)
                with redirect_stderr(io.StringIO()):
                    self.assertEqual("messages", archive_session.read_archive_mode(root))


    def test_non_string_mode_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_config(root, ".codex/langfuse.json", {"mode": []})
            with redirect_stderr(io.StringIO()):
                self.assertEqual("messages", archive_session.read_archive_mode(root))


class SetupConfigTests(unittest.TestCase):
    def run_setup(self, root, steps="read_archive_config\nprepare_archive_config", credential=""):
        return subprocess.run(
            [
                "bash", "-c",
                'source "$1"\nREPOSITORY_ROOT="$2"\nCREDENTIAL_FILE="$4"\n' + steps,
                "archive-config-test",
                str(REPOSITORY_ROOT / "scripts/setup-agent-plugins.sh"),
                str(root),
                str(REPOSITORY_ROOT / ".codex/langfuse.example.json"),
                str(credential),
                str(REPOSITORY_ROOT / ".claude/settings.local.example.json"),
            ],
            capture_output=True, text=True, timeout=10,
        )

    def test_setup_creates_codex_mode_without_legacy_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self.run_setup(root)
            self.assertEqual(0, result.returncode, result.stderr)
            config_path = root / ".codex/langfuse.json"
            self.assertEqual({"mode": "messages"}, json.loads(config_path.read_text()))
            self.assertEqual(0o600, config_path.stat().st_mode & 0o777)
            self.assertFalse((root / ".agents/session-archive.json").exists())
            self.assertEqual([config_path], list(config_path.parent.iterdir()))

    def test_setup_preserves_credentials_and_prefers_explicit_new_mode(self):
        for chosen_mode in (None, "messages", "tool-calls", "full"):
            with self.subTest(mode=chosen_mode), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                existing = {"public_key": "private-public-key", "secret_key": "private-secret-key", "enabled": False, "custom": {"keep": True}}
                if chosen_mode is not None:
                    existing["mode"] = chosen_mode
                config_path = write_config(root, ".codex/langfuse.json", existing)
                legacy = write_config(root, ".agents/session-archive.json", {"mode": "full"})
                marketplace = write_config(root, ".agents/plugins/marketplace.json", {"name": "test-marketplace"})
                for _ in range(2):
                    result = self.run_setup(root)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual({**existing, "mode": chosen_mode or "full"}, json.loads(config_path.read_text()))
                    self.assertNotIn("private-secret-key", result.stdout + result.stderr)
                self.assertFalse(legacy.exists())
                self.assertTrue(marketplace.exists())
                self.assertEqual(0o600, config_path.stat().st_mode & 0o777)

    def test_first_codex_setup_migrates_legacy_mode_after_template_creation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_config(root, ".agents/session-archive.json", {"mode": "full"})
            result = self.run_setup(root, '\n'.join((
                "read_archive_config",
                'prepare_private_config "$3" "$REPOSITORY_ROOT/.codex/langfuse.json" "Codex"',
                "prepare_archive_config",
            )))
            self.assertEqual(0, result.returncode, result.stderr)
            config = json.loads((root / ".codex/langfuse.json").read_text())
            self.assertEqual("full", config["mode"])
            self.assertIn("public_key", config)
            self.assertIn("占位配置", result.stderr)
            self.assertFalse((root / ".agents/session-archive.json").exists())

    def test_codex_setup_with_old_mode_only_config_adds_template_fields(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self.run_setup(root)
            self.assertEqual(0, result.returncode, result.stderr)
            config_path = write_config(root, ".codex/langfuse.json", {"mode": "tool-calls"})
            result = self.run_setup(root, '\n'.join((
                "read_archive_config",
                'prepare_private_config "$3" "$REPOSITORY_ROOT/.codex/langfuse.json" "Codex"',
                "prepare_archive_config",
            )))
            self.assertEqual(0, result.returncode, result.stderr)
            config = json.loads(config_path.read_text())
            self.assertEqual("tool-calls", config["mode"])
            self.assertIn("secret_key", config)
            self.assertIn("占位配置", result.stderr)

    def test_credential_import_keeps_mode_and_other_settings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = write_config(root, ".codex/langfuse.json", {"mode": "tool-calls", "custom": "retained"})
            credential = {
                "student_id": "20250001", "public_key": "pk-lf-stu-20250001",
                "secret_key": "sk-lf-token-" + "example" * 5,
                "base_url": "https://example.invalid:8443",
            }
            credential_path = write_config(root, "credential.json", credential)
            result = self.run_setup(root, '\n'.join((
                "read_archive_config",
                'prepare_private_config "$3" "$REPOSITORY_ROOT/.codex/langfuse.json" "Codex"',
                "prepare_archive_config",
            )), credential_path)
            self.assertEqual(0, result.returncode, result.stderr)
            config = json.loads(config_path.read_text())
            self.assertEqual("tool-calls", config["mode"])
            self.assertEqual("retained", config["custom"])
            self.assertEqual(credential["secret_key"], config["secret_key"])
            self.assertNotIn(credential["secret_key"], result.stdout + result.stderr)

    def test_setup_rejects_invalid_config_without_replacing_it(self):
        for content in (b"{", b"\xff", b"[]", b'{"mode": []}', b'{"mode": "unknown"}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                config_path = write_config(root, ".codex/langfuse.json", {})
                config_path.write_bytes(content)
                legacy = write_config(root, ".agents/session-archive.json", {"mode": "full"})
                result = self.run_setup(root)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(content, config_path.read_bytes())
                self.assertTrue(legacy.exists())

    def test_valid_credentials_using_template_server_are_not_placeholders(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            template = json.loads((REPOSITORY_ROOT / ".codex/langfuse.example.json").read_text())
            existing = {**template, "public_key": "pk-lf-stu-20250001", "secret_key": "private-token"}
            config_path = write_config(root, ".codex/langfuse.json", existing)
            result = self.run_setup(root, '\n'.join((
                "read_archive_config",
                'prepare_private_config "$3" "$REPOSITORY_ROOT/.codex/langfuse.json" "Codex"',
                "prepare_archive_config",
            )))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("占位配置", result.stdout + result.stderr)
            self.assertNotIn("private-token", result.stdout + result.stderr)
            self.assertEqual(existing, json.loads(config_path.read_text()))

    def test_claude_only_setup_creates_settings_without_codex_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self.run_setup(root, '\n'.join((
                "read_archive_config claude",
                'prepare_private_config "$5" "$REPOSITORY_ROOT/.claude/settings.local.json" "Claude Code"',
                "prepare_archive_config claude",
                'COMPLETED_AGENTS=("Claude Code")',
                "print_summary",
            )))
            self.assertEqual(0, result.returncode, result.stderr)
            path = root / ".claude/settings.local.json"
            config = json.loads(path.read_text())
            self.assertEqual("messages", config["env"]["RCORE_SESSION_ARCHIVE_MODE"])
            self.assertIn("LANGFUSE_SECRET_KEY", config["env"])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertFalse((root / ".codex").exists())
            self.assertFalse((root / ".claude/langfuse.json").exists())
            self.assertIn("Claude Code 留档等级：messages", result.stdout)
            self.assertNotIn("Codex 留档等级", result.stdout)
            self.assertIn("占位配置", result.stderr)

    def test_claude_migrates_shared_mode_once_without_changing_codex_or_credentials(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            codex_path = write_config(root, ".codex/langfuse.json", {"mode": "full", "secret_key": "codex-secret"})
            original_codex = codex_path.read_bytes()
            existing = {
                "$schema": "https://json.schemastore.org/claude-code-settings.json",
                "permissions": {"allow": ["Read"]},
                "env": {"LANGFUSE_SECRET_KEY": "claude-secret", "UNRELATED": "retained", "CC_LANGFUSE_DEBUG": "true"},
            }
            path = write_config(root, ".claude/settings.local.json", existing)
            steps = '\n'.join((
                "read_archive_config claude",
                'prepare_private_config "$5" "$REPOSITORY_ROOT/.claude/settings.local.json" "Claude Code"',
                "prepare_archive_config claude",
            ))
            result = self.run_setup(root, steps)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(original_codex, codex_path.read_bytes())
            expected = {**existing, "env": {**existing["env"], "RCORE_SESSION_ARCHIVE_MODE": "full"}}
            self.assertEqual(expected, json.loads(path.read_text()))
            self.assertNotIn("claude-secret", result.stdout + result.stderr)
            codex_path.write_text('{"mode": "messages"}')
            for _ in range(2):
                result = self.run_setup(root, steps)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, json.loads(path.read_text()))
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_claude_setup_ignores_invalid_codex_when_own_mode_is_set(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            codex_path = write_config(root, ".codex/langfuse.json", {})
            codex_path.write_bytes(b"{broken")
            path = write_config(root, ".claude/settings.local.json", {"env": {"RCORE_SESSION_ARCHIVE_MODE": "messages"}})
            result = self.run_setup(root, "read_archive_config claude\nprepare_archive_config claude")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("messages", json.loads(path.read_text())["env"]["RCORE_SESSION_ARCHIVE_MODE"])
            self.assertEqual(b"{broken", codex_path.read_bytes())

    def test_claude_first_setup_migrates_legacy_before_template_default(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            legacy = write_config(root, ".agents/session-archive.json", {"mode": "tool-calls"})
            marketplace = write_config(root, ".agents/plugins/marketplace.json", {"name": "test-marketplace"})
            result = self.run_setup(root, '\n'.join((
                "read_archive_config claude",
                'prepare_private_config "$5" "$REPOSITORY_ROOT/.claude/settings.local.json" "Claude Code"',
                "prepare_archive_config claude",
            )))
            self.assertEqual(0, result.returncode, result.stderr)
            config = json.loads((root / ".claude/settings.local.json").read_text())
            self.assertEqual("tool-calls", config["env"]["RCORE_SESSION_ARCHIVE_MODE"])
            self.assertFalse(legacy.exists())
            self.assertTrue(marketplace.exists())
            self.assertFalse((root / ".codex").exists())

    def test_claude_credential_import_preserves_mode_and_other_settings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            existing = {
                "permissions": {"allow": ["Read"]},
                "env": {"RCORE_SESSION_ARCHIVE_MODE": "tool-calls", "UNRELATED": "retained", "LANGFUSE_USER_ID": "untrusted"},
            }
            path = write_config(root, ".claude/settings.local.json", existing)
            credential = {
                "student_id": "20250001", "public_key": "pk-lf-stu-20250001",
                "secret_key": "sk-lf-token-" + "example" * 5,
                "base_url": "https://example.invalid:8443",
            }
            credential_path = write_config(root, "credential.json", credential)
            result = self.run_setup(root, '\n'.join((
                "read_archive_config claude",
                'prepare_private_config "$5" "$REPOSITORY_ROOT/.claude/settings.local.json" "Claude Code"',
                "prepare_archive_config claude",
            )), credential_path)
            self.assertEqual(0, result.returncode, result.stderr)
            config = json.loads(path.read_text())
            self.assertEqual("tool-calls", config["env"]["RCORE_SESSION_ARCHIVE_MODE"])
            self.assertEqual("retained", config["env"]["UNRELATED"])
            self.assertEqual(existing["permissions"], config["permissions"])
            self.assertEqual(credential["secret_key"], config["env"]["LANGFUSE_SECRET_KEY"])
            self.assertNotIn("LANGFUSE_USER_ID", config["env"])
            self.assertNotIn(credential["secret_key"], result.stdout + result.stderr)
            self.assertFalse((root / ".codex").exists())

    def test_setup_keeps_different_modes_for_both_agents(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            codex = write_config(root, ".codex/langfuse.json", {"mode": "full"})
            claude = write_config(root, ".claude/settings.local.json", {"env": {"RCORE_SESSION_ARCHIVE_MODE": "messages"}})
            result = self.run_setup(root, '\n'.join((
                "read_archive_config codex", "prepare_archive_config codex",
                "read_archive_config claude", "prepare_archive_config claude",
                'COMPLETED_AGENTS=("Codex" "Claude Code")', "print_summary",
            )))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("full", json.loads(codex.read_text())["mode"])
            self.assertEqual("messages", json.loads(claude.read_text())["env"]["RCORE_SESSION_ARCHIVE_MODE"])
            self.assertIn("Codex 留档等级：full", result.stdout)
            self.assertIn("Claude Code 留档等级：messages", result.stdout)

    def test_invalid_claude_config_is_not_overwritten(self):
        for content in (b"{", b"\xff", b"[]", b'{"env": []}', b'{"env": {"RCORE_SESSION_ARCHIVE_MODE": "unknown"}}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                path = write_config(root, ".claude/settings.local.json", {})
                path.write_bytes(content)
                legacy = write_config(root, ".agents/session-archive.json", {"mode": "full"})
                result = self.run_setup(root, "read_archive_config claude\nprepare_archive_config claude")
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(content, path.read_bytes())
                self.assertTrue(legacy.exists())
                self.assertFalse((root / ".codex").exists())


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


class ClaudeStopMessageTests(unittest.TestCase):
    @staticmethod
    def assistant(text, message_id="reply-1", stop_reason="end_turn", **record_fields):
        return {
            "type": "assistant", "isSidechain": False,
            "message": {
                "id": message_id, "role": "assistant", "stop_reason": stop_reason,
                "content": [{"type": "text", "text": text}],
            },
            **record_fields,
        }

    def render(self, records, final_text=None, mode="messages"):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = transcript_file(Path(temporary_directory), records)
            output = io.BytesIO()
            archive_session.write_archive(path, output, "claude-code", mode, "session", final_text)
            return output.getvalue().decode("utf-8")

    def test_unflushed_reply_is_present_in_every_archive_mode(self):
        records = ClaudeFilterTests.RECORDS[:-1]
        for mode in archive_session.SUPPORTED_MODES:
            with self.subTest(mode=mode):
                result = self.render(records, "latest reply", mode)
                self.assertEqual(1, result.count("latest reply"))
                self.assertEqual(1, result.count("### Claude Code\n"))
                self.assertIn("user question", result)
                self.assertEqual(mode != "messages", "run-command --flag" in result)
                self.assertEqual(mode == "full", "tool-output-secret" in result)
                self.assertEqual(mode == "full", "intermediate-secret" in result)

    def test_flushed_reply_is_not_duplicated_or_changed(self):
        records = [ClaudeFilterTests.RECORDS[0], self.assistant("latest reply")]
        for mode in archive_session.SUPPORTED_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(self.render(records, mode=mode), self.render(records, "latest reply", mode))

    def test_same_answer_to_a_new_prompt_is_not_suppressed(self):
        records = [ClaudeFilterTests.RECORDS[0], self.assistant("same answer"), ClaudeFilterTests.RECORDS[0]]
        for mode in archive_session.SUPPORTED_MODES:
            with self.subTest(mode=mode):
                result = self.render(records, "same answer", mode)
                self.assertEqual(2, result.count("same answer"))
                self.assertEqual(2, result.count("### Claude Code\n"))
                self.assertEqual(2, result.count("## 第 "))

    def test_only_latest_api_message_is_eligible_for_deduplication(self):
        records = [
            ClaudeFilterTests.RECORDS[0],
            self.assistant("repeated text", "earlier"),
            self.assistant("a different continuation", "later"),
        ]
        result = self.render(records, "repeated text")
        self.assertEqual(2, result.count("repeated text"))
        self.assertIn("a different continuation", result)

    def test_tool_result_and_intermediate_text_do_not_suppress_final(self):
        intermediate = self.assistant("latest reply", stop_reason="tool_use")
        intermediate["message"]["content"].append({"type": "tool_use", "name": "Bash", "id": "tool-1", "input": {"command": "pwd"}})
        records = [ClaudeFilterTests.RECORDS[0], intermediate, ClaudeFilterTests.RECORDS[-2]]
        for mode in archive_session.SUPPORTED_MODES:
            with self.subTest(mode=mode):
                result = self.render(records, "latest reply", mode)
                self.assertEqual(1, result.count("### Claude Code\n"))
                self.assertEqual(2 if mode == "full" else 1, result.count("latest reply"))

    def test_text_in_a_tool_call_message_is_not_promoted_to_final(self):
        intermediate = self.assistant("latest reply", stop_reason="tool_use")
        intermediate["message"]["content"].append({"type": "tool_use", "name": "Bash", "id": "tool-1", "input": {"command": "pwd"}})
        result = self.render([ClaudeFilterTests.RECORDS[0], intermediate], "latest reply", "full")
        self.assertEqual(1, result.count("### Claude Code\n"))
        self.assertIn("### Claude Code 中间输出", result)
        self.assertIn("### 工具调用：Bash", result)

    def test_multipart_reply_with_same_message_id_is_deduplicated(self):
        records = [ClaudeFilterTests.RECORDS[0], self.assistant("first block"), self.assistant("second block")]
        for separator in ("", "\n", "\n\n"):
            for mode in archive_session.SUPPORTED_MODES:
                with self.subTest(separator=separator, mode=mode):
                    result = self.render(records, separator.join(("first block", "second block")), mode)
                    self.assertEqual(self.render(records, mode=mode), result)
                    self.assertEqual(1, result.count("first block"))
                    self.assertEqual(1, result.count("second block"))

    def test_partial_text_is_replaced_with_complete_reply(self):
        complete = "回复开始\n\n```rust\nfn main() {}\n```\n\n回复完成"
        partial = self.assistant("回复开始", stop_reason=None)
        partial["message"]["content"].insert(0, {"type": "thinking", "thinking": "readable reasoning"})
        for mode in archive_session.SUPPORTED_MODES:
            with self.subTest(mode=mode):
                result = self.render([ClaudeFilterTests.RECORDS[0], partial], complete, mode)
                self.assertEqual(1, result.count("回复开始"))
                self.assertEqual(1, result.count("### Claude Code\n"))
                self.assertIn(complete, result)
                self.assertEqual(mode == "full", "readable reasoning" in result)

    def test_final_text_without_persisted_stop_reason_is_promoted(self):
        records = [ClaudeFilterTests.RECORDS[0], self.assistant("latest reply", stop_reason=None)]
        for mode in archive_session.SUPPORTED_MODES:
            with self.subTest(mode=mode):
                result = self.render(records, "latest reply", mode)
                self.assertEqual(1, result.count("latest reply"))
                self.assertEqual(1, result.count("### Claude Code\n"))

    def test_sidechain_reply_does_not_suppress_main_reply(self):
        records = [ClaudeFilterTests.RECORDS[0], self.assistant("latest reply", isSidechain=True)]
        result = self.render(records, "latest reply")
        self.assertEqual(1, result.count("latest reply"))
        self.assertEqual(1, result.count("### Claude Code\n"))

    def test_reply_after_interrupted_turn_is_included(self):
        records = [
            *ClaudeFilterTests.RECORDS[:-1],
            {"type": "user", "message": {"role": "user", "content": "[Request interrupted by user]"}},
            {"type": "user", "message": {"role": "user", "content": "continue"}},
        ]
        result = self.render(records, "resumed final reply")
        self.assertIn("continue", result)
        self.assertEqual(1, result.count("resumed final reply"))
        self.assertNotIn("tool-output-secret", result)

    def test_missing_empty_and_non_string_fallbacks_are_ignored(self):
        records = [ClaudeFilterTests.RECORDS[0]]
        for value in (None, "", " \n", [], {}, 123):
            with self.subTest(value=value):
                self.assertEqual(self.render(records), self.render(records, value))

    def test_incomplete_tail_is_tolerated_only_with_stop_reply(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = transcript_file(Path(temporary_directory), [ClaudeFilterTests.RECORDS[0]])
            with path.open("ab") as output:
                output.write(b'{"type":"assistant","message":{"content":"partial')
            original = path.read_bytes()
            for mode in archive_session.SUPPORTED_MODES:
                output = io.BytesIO()
                archive_session.write_archive(path, output, "claude-code", mode, "session", "complete reply")
                self.assertIn(b"complete reply", output.getvalue())
                self.assertEqual(original, path.read_bytes())
            with self.assertRaises(ValueError):
                list(archive_session.read_jsonl_records(path))

    def test_corrupt_complete_line_is_not_hidden_by_stop_reply(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = transcript_file(Path(temporary_directory), [ClaudeFilterTests.RECORDS[0]])
            with path.open("ab") as output:
                output.write(b'{broken JSON}\n')
            with self.assertRaisesRegex(ValueError, "invalid transcript JSON on line 2"):
                list(archive_session.filtered_events(path, "claude-code", "messages", "complete reply"))

    def test_repeated_stop_then_session_end_keep_one_complete_reply(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = transcript_file(root, ClaudeFilterTests.RECORDS[:-1])
            original = path.read_bytes()
            payload = {
                "cwd": str(root), "session_id": "session", "transcript_path": str(path),
                "hook_event_name": "Stop", "last_assistant_message": "latest reply",
            }
            destination = root / ".agent-sessions/claude-code/session.md"
            with mock.patch.object(archive_session, "find_repository_root", return_value=root), \
                 mock.patch.object(archive_session, "is_rcore_repository", return_value=True), \
                 mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "plugin"}, clear=True):
                archive_session.archive_transcript(payload)
                first_render = destination.read_bytes()
                for _ in range(2):
                    archive_session.archive_transcript(payload)
                    self.assertEqual(first_render, destination.read_bytes())
                self.assertEqual(original, path.read_bytes())
                transcript_file(root, [*ClaudeFilterTests.RECORDS[:-1], self.assistant("latest reply")])
                flushed = path.read_bytes()
                archive_session.archive_transcript(payload)
                self.assertEqual(first_render, destination.read_bytes())
                archive_session.archive_transcript({**payload, "hook_event_name": "SessionEnd"})
                self.assertEqual(first_render, destination.read_bytes())
                self.assertEqual(flushed, path.read_bytes())
            self.assertEqual(1, destination.read_text().count("latest reply"))
            self.assertEqual([destination], list(destination.parent.iterdir()))
            self.assertEqual(0o600, destination.stat().st_mode & 0o777)

    def test_fallback_is_used_only_for_claude_stop(self):
        for agent, event in (("claude-code", "SessionEnd"), ("claude-code", "StopFailure"), ("claude-code", "SubagentStop"), ("claude-code", None), ("codex", "Stop")):
            with self.subTest(agent=agent, event=event), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                source = transcript_file(root, ClaudeFilterTests.RECORDS if agent == "claude-code" else CodexFilterTests.RECORDS)
                payload = {"cwd": str(root), "session_id": "session", "transcript_path": str(source), "hook_event_name": event, "last_assistant_message": "should-not-be-injected"}
                environment = {"CLAUDE_PLUGIN_ROOT": "plugin"} if agent == "claude-code" else {"PLUGIN_ROOT": "plugin"}
                with mock.patch.object(archive_session, "find_repository_root", return_value=root), \
                     mock.patch.object(archive_session, "is_rcore_repository", return_value=True), \
                     mock.patch.dict(os.environ, environment, clear=True):
                    archive_session.archive_transcript(payload)
                result = (root / ".agent-sessions" / agent / "session.md").read_text()
                self.assertNotIn("should-not-be-injected", result)
                self.assertIn("final answer", result)

    def test_cli_stop_recovers_first_reply_in_claude_only_repository(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
            (root / "README.md").write_text("# rCore-Tutorial-Code-2025S\n")
            write_config(root, ".claude/settings.local.json", {"env": {"RCORE_SESSION_ARCHIVE_MODE": "messages"}})
            path = transcript_file(root, [ClaudeFilterTests.RECORDS[0]])
            original = path.read_bytes()
            environment = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(SCRIPT_PATH.parents[1]), "RCORE_SESSION_ARCHIVE_MODE": "full"}
            environment.pop("PLUGIN_ROOT", None)
            payload = {"cwd": str(root), "session_id": "session", "transcript_path": str(path), "hook_event_name": "Stop", "last_assistant_message": "reply delivered in hook input"}
            result = subprocess.run(["python3", str(SCRIPT_PATH.resolve())], input=json.dumps(payload), text=True, capture_output=True, env=environment, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            archived = (root / ".agent-sessions/claude-code/session.md").read_text()
            self.assertIn("归档等级：messages", archived)
            self.assertEqual(1, archived.count("reply delivered in hook input"))
            self.assertEqual(original, path.read_bytes())
            self.assertFalse((root / ".codex").exists())


class ArchiveWriterTests(unittest.TestCase):
    def render(self, records, agent="codex", mode="messages"):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = transcript_file(Path(temporary_directory), records)
            output = io.BytesIO()
            archive_session.write_archive(path, output, agent, mode, "example-session")
            return output.getvalue().decode("utf-8")

    def test_messages_are_markdown_and_keep_only_user_and_final(self):
        for agent, records, label in (
            ("codex", CodexFilterTests.RECORDS, "Codex"),
            ("claude-code", ClaudeFilterTests.RECORDS, "Claude Code"),
        ):
            with self.subTest(agent=agent):
                result = self.render(records, agent)
                self.assertTrue(result.startswith(f"# {label} 会话记录\n"))
                self.assertIn("开始时间：2026-01-01 00:00:00+00:00", result)
                self.assertIn("会话 ID：example-session", result)
                self.assertIn("归档等级：messages", result)
                self.assertIn("## 第 1 轮\n\n### 用户", result)
                self.assertIn(f"### {label}\n", result)
                self.assertIn("user question", result)
                self.assertIn("final answer", result)
                for excluded in (
                    "intermediate-secret", "developer-secret", "reasoning-secret",
                    "tool-output-secret", "run-command", '"response_item"',
                ):
                    self.assertNotIn(excluded, result)

    def test_codex_full_is_readable_and_ignores_mirrored_transport_events(self):
        records = CodexFilterTests.RECORDS + [
            {"type": "event_msg", "payload": {"type": "agent_message", "message": "mirror-secret"}},
            {"type": "token_usage_record", "payload": {"opaque": "usage-secret"}},
            {"type": "response_item", "payload": {"type": "reasoning", "encrypted_content": "ciphertext-secret"}},
        ]
        result = self.render(records, mode="full")
        for expected in ("intermediate-secret", "developer-secret", "reasoning-secret", "tool-output-secret"):
            self.assertIn(expected, result)
        self.assertLess(result.index("intermediate-secret"), result.index("run-command"))
        self.assertLess(result.index("run-command"), result.index("tool-output-secret"))
        self.assertLess(result.index("tool-output-secret"), result.index("final answer"))
        for excluded in ("mirror-secret", "usage-secret", "ciphertext-secret"):
            self.assertNotIn(excluded, result)
        self.assertEqual(1, result.count("final answer"))

    def test_claude_full_keeps_thinking_text_calls_and_results_in_order(self):
        result = self.render(ClaudeFilterTests.RECORDS, "claude-code", "full")
        self.assertIn("### Claude Code 中间输出", result)
        self.assertIn("### 工具调用：Bash", result)
        self.assertIn("### 工具输出：Bash", result)
        self.assertIn("### Claude Code 推理摘要", result)
        for earlier, later in (
            ("intermediate-secret", "run-command"),
            ("run-command", "tool-output-secret"),
            ("tool-output-secret", "reasoning-secret"),
            ("reasoning-secret", "final answer"),
        ):
            self.assertLess(result.index(earlier), result.index(later))

    def test_tool_arguments_are_unescaped_and_shell_command_is_separate(self):
        records = [CodexFilterTests.RECORDS[0], {
            "type": "response_item", "payload": {
                "type": "function_call", "name": "exec_command", "call_id": "exec-1",
                "arguments": json.dumps({"cmd": "printf '你好\\n'\ncargo test", "workdir": "/tmp/实验"}),
            },
        }, CodexFilterTests.RECORDS[-1]]
        result = self.render(records, mode="tool-calls")
        self.assertIn("### 工具调用：exec_command", result)
        self.assertIn("调用 ID：exec-1", result)
        self.assertIn("执行命令：\n\n```bash\nprintf '你好\\n'\ncargo test\n```", result)
        self.assertIn("workdir: /tmp/实验", result)
        self.assertNotIn('"arguments"', result)
        self.assertNotIn("\\u", result)

    def test_long_intermediate_and_output_fold_without_truncation(self):
        long_text = "\n".join(f"line {number}" for number in range(30))
        output_text = long_text + "\n```markdown\n# tool text\n```\nlast-output-line"
        records = [CodexFilterTests.RECORDS[0], {
            "type": "response_item", "payload": {
                "type": "message", "role": "assistant", "phase": "commentary",
                "content": [{"type": "output_text", "text": long_text}],
            },
        }, {
            "type": "response_item", "payload": {
                "type": "function_call_output", "call_id": "call-1", "output": output_text,
            },
        }, CodexFilterTests.RECORDS[-1]]
        result = self.render(records, mode="full")
        self.assertEqual(2, result.count("<details>"))
        self.assertEqual(2, result.count("</details>"))
        self.assertIn(long_text, result)
        self.assertIn("````text\n" + output_text + "\n````", result)

    def test_turns_skip_empty_events_and_preserve_message_markdown(self):
        prompt = "检查代码：\n\n```rust\nfn main() {}\n```"
        empty = {"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": "  "}}
        question = {"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": prompt}}
        final = CodexFilterTests.RECORDS[-1]
        result = self.render([empty, question, final, question, final])
        self.assertEqual(2, result.count("## 第 "))
        self.assertEqual(2, result.count("### 用户\n"))
        self.assertEqual(2, result.count(prompt))
        self.assertNotIn("第 3 轮", result)

    def test_structured_tool_output_keeps_text_spacing_and_exit_status(self):
        record = {"type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "call-1",
            "output": json.dumps({"content": [{"type": "text", "text": "    indented output\n下一行"}], "exit_code": 2}),
        }}
        result = self.render([record], mode="full")
        self.assertIn("```text\n    indented output\n下一行", result)
        self.assertIn("exit_code: 2", result)
        self.assertNotIn('"content"', result)

    def test_attachment_is_described_without_copying_base64(self):
        record = {"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "看这张截图"},
                {"type": "input_image", "image_url": "data:image/png;base64,BINARY-SECRET"},
            ]}}
        result = self.render([record])
        self.assertIn("看这张截图", result)
        self.assertIn("[图片附件]", result)
        self.assertNotIn("BINARY-SECRET", result)

    def test_empty_session_has_no_empty_turn_or_message(self):
        result = self.render([])
        self.assertIn("暂无可保存的消息", result)
        self.assertNotIn("## 第 ", result)
        self.assertNotIn("### 用户", result)

    def test_archive_transcript_uses_repository_mode_and_atomic_destination(self):
        records = CodexFilterTests.RECORDS
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_directory = root / ".codex"
            config_directory.mkdir()
            (config_directory / "langfuse.json").write_text(
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
                archive_session.archive_transcript(payload)

            destination = (
                root
                / ".agent-sessions"
                / "codex"
                / "session_with_unsafe_characters.md"
            )
            self.assertTrue(destination.is_file())
            archived = destination.read_text(encoding="utf-8")
            self.assertIn("run-command --flag", archived)
            self.assertNotIn("tool-output-secret", archived)
            self.assertEqual(0o600, destination.stat().st_mode & 0o777)
            self.assertEqual([destination], list(destination.parent.iterdir()))
            self.assertEqual(1, archived.count("user question"))
            self.assertTrue(source.is_file())

    def test_replace_legacy_only_after_markdown_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = transcript_file(root, CodexFilterTests.RECORDS)
            archive_dir = root / ".agent-sessions" / "codex"
            archive_dir.mkdir(parents=True)
            legacy = archive_dir / "session.jsonl"
            legacy.write_text("legacy transcript", encoding="utf-8")
            other = archive_dir / "other-session.jsonl"
            other.write_text("unrelated session", encoding="utf-8")
            destination = archive_dir / "session.md"
            destination.write_text("previous markdown", encoding="utf-8")
            payload = {"transcript_path": str(source), "session_id": "session", "cwd": str(root)}
            with mock.patch.object(archive_session, "find_repository_root", return_value=root), \
                 mock.patch.object(archive_session, "is_rcore_repository", return_value=True), \
                 mock.patch.dict(os.environ, {"PLUGIN_ROOT": "plugin"}, clear=True):
                with mock.patch.object(archive_session, "write_archive", side_effect=ValueError("bad input")):
                    with self.assertRaises(ValueError):
                        archive_session.archive_transcript(payload)
                self.assertEqual("previous markdown", destination.read_text())
                self.assertTrue(legacy.exists())
                self.assertFalse(list(archive_dir.glob("*.tmp")))

                archive_session.archive_transcript(payload)
                self.assertFalse(legacy.exists())
                self.assertTrue(other.exists())
                self.assertIn("final answer", destination.read_text())
                self.assertTrue(source.exists())

    def test_never_delete_the_agent_source_transcript(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_dir = root / ".agent-sessions" / "codex"
            archive_dir.mkdir(parents=True)
            source = transcript_file(archive_dir, CodexFilterTests.RECORDS)
            payload = {"transcript_path": str(source), "session_id": "transcript", "cwd": str(root)}
            with mock.patch.object(archive_session, "find_repository_root", return_value=root), \
                 mock.patch.object(archive_session, "is_rcore_repository", return_value=True), \
                 mock.patch.dict(os.environ, {"PLUGIN_ROOT": "plugin"}, clear=True):
                archive_session.archive_transcript(payload)
            self.assertTrue(source.exists())
            self.assertTrue((archive_dir / "transcript.md").exists())


    def test_claude_mode_change_rewrites_one_markdown_without_json_backup(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = write_config(root, ".claude/settings.local.json", {})
            codex_config = write_config(root, ".codex/langfuse.json", {"mode": "full"})
            codex_original = codex_config.read_bytes()
            source = transcript_file(root, ClaudeFilterTests.RECORDS)
            original = source.read_bytes()
            payload = {"transcript_path": str(source), "session_id": "claude-session", "cwd": str(root)}
            destination = root / ".agent-sessions/claude-code/claude-session.md"
            with mock.patch.object(archive_session, "find_repository_root", return_value=root), \
                 mock.patch.object(archive_session, "is_rcore_repository", return_value=True), \
                 mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "plugin", "RCORE_SESSION_ARCHIVE_MODE": "full"}, clear=True):
                for mode in ("full", "tool-calls", "messages"):
                    config.write_text(json.dumps({"env": {"RCORE_SESSION_ARCHIVE_MODE": mode}}))
                    archive_session.archive_transcript(payload)
                    rendered = destination.read_text()
                    self.assertEqual(mode == "full", "tool-output-secret" in rendered)
                    self.assertEqual(mode != "messages", "run-command --flag" in rendered)
                    self.assertEqual(1, rendered.count("final answer"))
                    self.assertEqual([destination], list(destination.parent.iterdir()))
            self.assertEqual(original, source.read_bytes())
            self.assertEqual(codex_original, codex_config.read_bytes())

    def test_legacy_symlinks_are_not_removed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = transcript_file(root, CodexFilterTests.RECORDS)
            archive_dir = root / ".agent-sessions/codex"
            archive_dir.mkdir(parents=True)
            legacy = archive_dir / "session.jsonl"
            legacy.symlink_to(source)
            payload = {"transcript_path": str(source), "session_id": "session", "cwd": str(root)}
            with mock.patch.object(archive_session, "find_repository_root", return_value=root), \
                 mock.patch.object(archive_session, "is_rcore_repository", return_value=True), \
                 mock.patch.dict(os.environ, {"PLUGIN_ROOT": "plugin"}, clear=True):
                archive_session.archive_transcript(payload)
            self.assertTrue(legacy.is_symlink())
            self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
