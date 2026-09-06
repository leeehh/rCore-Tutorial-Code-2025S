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
            ],
            capture_output=True, text=True, timeout=10,
        )

    def test_setup_creates_shared_mode_without_legacy_file(self):
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

    def test_codex_setup_after_claude_only_keeps_mode_and_adds_template_fields(self):
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
            (root / ".codex").mkdir()
            config = root / ".codex/langfuse.json"
            source = transcript_file(root, ClaudeFilterTests.RECORDS)
            original = source.read_bytes()
            payload = {"transcript_path": str(source), "session_id": "claude-session", "cwd": str(root)}
            destination = root / ".agent-sessions/claude-code/claude-session.md"
            with mock.patch.object(archive_session, "find_repository_root", return_value=root), \
                 mock.patch.object(archive_session, "is_rcore_repository", return_value=True), \
                 mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "plugin"}, clear=True):
                for mode in ("full", "tool-calls", "messages"):
                    config.write_text(json.dumps({"mode": mode}))
                    archive_session.archive_transcript(payload)
                    rendered = destination.read_text()
                    self.assertEqual(mode == "full", "tool-output-secret" in rendered)
                    self.assertEqual(mode != "messages", "run-command --flag" in rendered)
                    self.assertEqual(1, rendered.count("final answer"))
                    self.assertEqual([destination], list(destination.parent.iterdir()))
            self.assertEqual(original, source.read_bytes())

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
