import io
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPTS))
import copilot_hook as copilot


def attrs(span):
    return {item["key"]: item["value"] for item in span["attributes"]}


def io_value(span, key):
    value = attrs(span).get("langfuse.observation." + key)
    return json.loads(value["stringValue"]) if value else None


class CopilotHookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config_path = self.root / ".vscode/langfuse.json"
        self.config_path.parent.mkdir()
        self.config = {"enabled": True, "mode": "messages", "public_key": "pk-lf-stu-20250001",
                       "secret_key": "sk-lf-token-" + "a" * 40, "base_url": "https://gateway.example:8443", "user_id": "UNTRUSTED_ID"}
        self.save_config()
        self.source = self.root / "copilot-source.jsonl"
        self.records = []
        self.add("session.start", {"sessionId": "session", "version": 1, "producer": "copilot-agent", "context": {"cwd": str(self.root)}})
        self.sender = mock.Mock(return_value=True)
        self.archive = self.root / ".agent-sessions/vscode-copilot/session.md"
        patcher = mock.patch.object(copilot.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def save_config(self, mode=None):
        if mode:
            self.config["mode"] = mode
        self.config_path.write_text(json.dumps(self.config))

    def add(self, kind, data):
        index = len(self.records)
        self.records.append({"id": f"record-{index}", "parentId": f"record-{index - 1}" if index else None,
                             "timestamp": (datetime(2026, 9, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=index)).isoformat(), "type": kind, "data": data})
        self.flush()

    def flush(self):
        self.source.write_text("".join(json.dumps(record) + "\n" for record in self.records))

    def message(self, text, requests=None, reasoning=None):
        data = {"messageId": f"message-{len(self.records)}", "content": text, "toolRequests": requests or []}
        if reasoning:
            data["reasoningText"] = reasoning
        self.add("assistant.message", data)

    def event(self, name="Stop", **fields):
        payload = {"hook_event_name": name, "session_id": "session", "transcript_path": str(self.source),
                   "cwd": str(self.root), "timestamp": "2026-09-06T13:00:00+00:00", **fields}
        copilot.handle(payload, self.root, self.sender)
        return payload

    def add_turn(self, prompt="USER_INPUT", reply="FINAL_REPLY", tool=True):
        self.add("user.message", {"content": prompt, "attachments": []})
        self.add("assistant.turn_start", {"turnId": "0"})
        if tool:
            self.message("INTERMEDIATE_TEXT", [{"toolCallId": "call-1", "name": "run_in_terminal", "arguments": '{"command":"printf COMMAND_TEXT"}', "type": "function"}], "THINKING_TEXT")
            self.add("tool.execution_start", {"toolCallId": "call-1", "toolName": "run_in_terminal", "arguments": {"command": "printf COMMAND_TEXT"}})
            self.add("tool.execution_complete", {"toolCallId": "call-1", "success": True, "result": {"content": "OUTPUT_TEXT\nnext line"}})
            self.add("assistant.turn_end", {"turnId": "0"})
            self.add("assistant.turn_start", {"turnId": "1"})
        self.message(reply)
        self.add("assistant.turn_end", {"turnId": "1" if tool else "0"})

    def spans(self):
        return [span for call in self.sender.call_args_list for span in call.args[1]]

    def test_messages_only_on_disk_but_uploads_all_available_content(self):
        self.add_turn()
        original = self.source.read_bytes()
        self.event()
        text = self.archive.read_text()
        self.assertIn("USER_INPUT", text)
        self.assertIn("FINAL_REPLY", text)
        for value in ("INTERMEDIATE_TEXT", "THINKING_TEXT", "COMMAND_TEXT", "OUTPUT_TEXT"):
            for path in (self.root / ".agent-sessions").rglob("*"):
                if path.is_file():
                    self.assertNotIn(value.encode(), path.read_bytes(), str(path))
        self.assertEqual([], list((self.root / ".agent-sessions").rglob("*.json*")))
        self.assertEqual(original, self.source.read_bytes())
        spans = self.spans()
        roots = [span for span in spans if "parentSpanId" not in span]
        self.assertEqual(1, len(roots))
        self.assertEqual([{"role": "user", "content": "USER_INPUT"}], io_value(roots[0], "input"))
        self.assertEqual([{"role": "assistant", "content": "FINAL_REPLY"}], io_value(roots[0], "output"))
        for value in ("INTERMEDIATE_TEXT", "THINKING_TEXT", "COMMAND_TEXT", "OUTPUT_TEXT"):
            self.assertIn(value, json.dumps(spans))
        self.assertTrue(all(span.get("parentSpanId", roots[0]["spanId"]) == roots[0]["spanId"] for span in spans))
        self.assertEqual(1, len({span["traceId"] for span in spans}))
        self.assertNotIn("UNTRUSTED_ID", json.dumps(spans))
        self.assertNotIn("user.id", json.dumps(spans))
        self.assertNotIn(self.config["secret_key"], json.dumps(spans))
        self.assertEqual(0o600, self.archive.stat().st_mode & 0o777)

    def test_tool_calls_and_full_modes(self):
        self.add_turn()
        self.save_config("tool-calls")
        self.event()
        text = self.archive.read_text()
        self.assertIn("```bash\nprintf COMMAND_TEXT", text)
        self.assertEqual(1, text.count("### 工具调用：run_in_terminal"))
        self.assertNotIn("OUTPUT_TEXT", text)
        self.assertNotIn("INTERMEDIATE_TEXT", text)
        self.save_config("full")
        self.event()
        text = self.archive.read_text()
        for value in ("INTERMEDIATE_TEXT", "THINKING_TEXT", "COMMAND_TEXT", "OUTPUT_TEXT"):
            self.assertIn(value, text)
        self.assertEqual(1, text.count("### 工具调用：run_in_terminal"))
        self.assertEqual(1, text.count("### 工具输出：run_in_terminal"))
        self.save_config("messages")
        self.event()
        self.assertNotIn("OUTPUT_TEXT", self.archive.read_text())
        self.assertNotIn("COMMAND_TEXT", self.archive.read_text())

    def test_stop_and_duplicate_transcript_entries_do_not_reupload(self):
        self.add_turn()
        self.event()
        first = self.archive.read_bytes()
        calls = self.sender.call_count
        self.event()
        self.records.append(self.records[-1])
        self.flush()
        self.event()
        self.assertEqual(first, self.archive.read_bytes())
        self.assertEqual(calls, self.sender.call_count)

    def test_multiple_llm_rounds_are_one_user_turn_and_identical_user_turns_stay_distinct(self):
        self.add_turn()
        self.event()
        self.add_turn()
        self.event()
        text = self.archive.read_text()
        self.assertEqual(2, text.count("USER_INPUT"))
        self.assertEqual(2, text.count("FINAL_REPLY"))
        self.assertEqual(2, text.count("## 第 "))
        self.assertEqual(2, len({span["traceId"] for span in self.spans()}))
        self.assertEqual(1, len({attrs(span)["langfuse.session.id"]["stringValue"] for span in self.spans()}))

    def test_recreated_history_with_new_uuids_does_not_duplicate(self):
        self.add_turn()
        self.event()
        before = self.archive.read_bytes()
        self.sender.reset_mock()
        for index, record in enumerate(self.records):
            record["id"] = f"replayed-{index}"
            record["parentId"] = f"replayed-{index-1}" if index else None
            if record["type"] == "assistant.message":
                record["data"]["messageId"] = f"new-message-id-{index}"
        self.flush()
        self.event()
        self.assertEqual(before, self.archive.read_bytes())
        self.sender.assert_not_called()

    def test_official_history_replay_without_tool_results_retains_archive_and_accepts_new_turn(self):
        self.save_config("full")
        self.add_turn()
        self.event()
        original = self.archive.read_bytes()
        self.sender.reset_mock()
        # Official _replayHistory emits assistant rounds and toolRequests, not
        # tool.execution_* entries. Every entry is assigned a new UUID.
        self.records = [record for record in self.records if not record["type"].startswith("tool.execution_")]
        for index, record in enumerate(self.records):
            record["id"] = f"history-{index}"
            record["parentId"] = f"history-{index - 1}" if index else None
            if record["type"] in {"assistant.turn_start", "assistant.turn_end"}:
                record["data"]["turnId"] = "0." + record["data"]["turnId"]
        self.flush()
        self.event(timestamp="2026-09-06T14:00:00Z")
        self.assertEqual(original, self.archive.read_bytes())
        self.sender.assert_not_called()
        self.add_turn("NEW_PROMPT", "NEW_REPLY", tool=False)
        self.event(timestamp="2026-09-06T15:00:00Z")
        self.assertIn("OUTPUT_TEXT", self.archive.read_text())
        self.assertIn("NEW_REPLY", self.archive.read_text())
        self.assertEqual(2, self.archive.read_text().count("## 第 "))
        self.assertEqual(1, len(self.spans()))

    def test_enabling_on_an_existing_conversation_does_not_import_old_turns(self):
        self.add_turn("OLD_PRIVATE_PROMPT", "OLD_PRIVATE_REPLY", tool=False)
        self.add_turn("NEW_PROMPT", "NEW_REPLY", tool=False)
        self.event()
        text = self.archive.read_text()
        self.assertNotIn("OLD_PRIVATE", text)
        self.assertNotIn("OLD_PRIVATE", json.dumps(self.spans()))
        self.assertIn("NEW_REPLY", text)
        self.add_turn("THIRD_PROMPT", "THIRD_REPLY", tool=False)
        self.event()
        self.assertNotIn("OLD_PRIVATE", self.archive.read_text())
        self.assertEqual(2, self.archive.read_text().count("## 第 "))

    def test_session_start_and_empty_stop_create_no_archive_or_trace(self):
        self.event("SessionStart")
        self.event()
        self.assertFalse((self.root / ".agent-sessions").exists())
        self.sender.assert_not_called()

    def test_user_prompt_must_be_the_current_transcript_prompt(self):
        self.add_turn("old", "old reply", tool=False)
        with self.assertRaisesRegex(copilot.TranscriptError, "最新用户输入"):
            self.event("UserPromptSubmit", prompt="not flushed new prompt")
        self.assertFalse(self.archive.exists())
        self.sender.assert_not_called()

    def test_new_reply_updates_same_root_id_and_source_timestamps(self):
        self.add("user.message", {"content": "question"})
        self.event("UserPromptSubmit", prompt="question")
        first = [span for span in self.spans() if "parentSpanId" not in span][0]
        self.add("assistant.turn_start", {"turnId": "0"})
        self.message("LATEST_REPLY")
        self.add("assistant.turn_end", {"turnId": "0"})
        self.event()
        last = [span for span in self.spans() if "parentSpanId" not in span][-1]
        self.assertEqual(first["spanId"], last["spanId"])
        self.assertEqual(first["traceId"], last["traceId"])
        self.assertEqual(first["startTimeUnixNano"], last["startTimeUnixNano"])
        self.assertGreater(int(last["endTimeUnixNano"]), int(first["endTimeUnixNano"]))
        self.assertIn("LATEST_REPLY", self.archive.read_text())

    def test_hook_tool_result_fills_a_not_yet_flushed_transcript(self):
        self.save_config("full")
        self.add("user.message", {"content": "question"})
        self.add("assistant.turn_start", {"turnId": "0"})
        self.message("running", [{"toolCallId": "call", "name": "run_in_terminal", "arguments": '{"command":"pwd"}', "type": "function"}])
        self.event("PreToolUse", tool_name="run_in_terminal", tool_use_id="call__vscode-3", tool_input={"command": "pwd"})
        self.event("PostToolUse", tool_name="run_in_terminal", tool_use_id="call__vscode-3", tool_input={"command": "pwd"}, tool_response="RESULT_FROM_HOOK")
        self.assertIn("RESULT_FROM_HOOK", self.archive.read_text())
        tool_spans = [span for span in self.spans() if span["name"] == "Bash"]
        self.assertEqual(1, len({span["spanId"] for span in tool_spans}))
        self.add("tool.execution_start", {"toolCallId": "call", "toolName": "run_in_terminal", "arguments": {"command": "pwd"}})
        self.add("tool.execution_complete", {"toolCallId": "call", "success": True, "result": {"content": "RESULT_FROM_HOOK"}})
        self.add("assistant.turn_end", {"turnId": "0"})
        self.event()
        self.assertEqual(1, self.archive.read_text().count("RESULT_FROM_HOOK"))
        self.assertEqual(1, self.archive.read_text().count("### 工具调用：run_in_terminal"))

    def test_tool_errors_are_retained(self):
        self.add_turn()
        for record in self.records:
            if record["type"] == "tool.execution_complete":
                record["data"]["success"] = False
        self.flush()
        self.event()
        self.assertEqual(2, next(span for span in self.spans() if span["name"] == "Bash")["status"]["code"])

    def test_missing_final_reply_does_not_use_intermediate_text_as_final(self):
        self.add_turn()
        self.records = self.records[:7]
        self.flush()
        self.event()
        self.assertNotIn("INTERMEDIATE_TEXT", self.archive.read_text())
        root = next(span for span in self.spans() if "parentSpanId" not in span)
        self.assertEqual([], io_value(root, "output"))

    def test_delayed_final_flush_is_retried(self):
        self.add("user.message", {"content": "question"})
        self.add("assistant.turn_start", {"turnId": "0"})
        def flush_later(_delay):
            self.message("DELAYED_FINAL")
            self.add("assistant.turn_end", {"turnId": "0"})
        self.sleep.side_effect = flush_later
        self.event()
        self.assertIn("DELAYED_FINAL", self.archive.read_text())
        self.assertEqual(1, self.sleep.call_count)

    def test_corrupt_or_unsupported_source_does_not_overwrite_archive(self):
        self.add_turn()
        self.event()
        original = self.archive.read_bytes()
        source = self.source.read_bytes()
        variants = [source + b'{"partial":', b'not-json\n', source.replace(b'"version": 1', b'"version": 2'), source.replace(b'"sessionId": "session"', b'"sessionId": "another-session"')]
        for content in variants:
            self.source.write_bytes(content)
            with self.assertRaises(copilot.TranscriptError):
                self.event()
            self.assertEqual(original, self.archive.read_bytes())

    def test_stale_hook_cannot_roll_back_newer_markdown(self):
        self.add_turn()
        self.event(timestamp="2026-09-06T14:00:00Z")
        original = self.archive.read_bytes()
        self.records = self.records[:7]
        self.flush()
        self.event(timestamp="2026-09-06T13:00:00Z")
        self.assertEqual(original, self.archive.read_bytes())

    def test_newer_hook_with_truncated_source_reports_error_without_overwrite(self):
        self.add_turn()
        self.event()
        original = self.archive.read_bytes()
        self.records = self.records[:7]
        self.flush()
        with self.assertRaisesRegex(copilot.TranscriptError, "截断"):
            self.event(timestamp="2026-09-06T14:00:00Z")
        self.assertEqual(original, self.archive.read_bytes())

    def test_changed_user_order_is_detected_instead_of_overwriting_a_turn(self):
        self.add_turn()
        self.event()
        original = self.archive.read_bytes()
        self.records[1]["data"]["content"] = "changed earlier prompt"
        self.flush()
        with self.assertRaisesRegex(copilot.TranscriptError, "重排"):
            self.event()
        self.assertEqual(original, self.archive.read_bytes())

    def test_network_failure_retries_from_source_without_json_outbox(self):
        self.add_turn()
        self.sender.return_value = False
        self.event()
        before = self.spans()
        self.assertIn("FINAL_REPLY", self.archive.read_text())
        self.sender.return_value = True
        self.sender.reset_mock()
        self.event()
        self.assertEqual(before, self.spans())
        self.sender.reset_mock()
        self.event()
        self.sender.assert_not_called()
        self.assertEqual([], list(self.archive.parent.rglob("*.json*")))

    def test_credentials_missing_still_saves_markdown(self):
        self.config.pop("secret_key")
        self.save_config()
        self.add_turn()
        with redirect_stderr(io.StringIO()):
            self.event()
        self.assertIn("FINAL_REPLY", self.archive.read_text())
        self.sender.assert_not_called()

    def test_scope_disabled_and_other_agent_configs_do_not_activate(self):
        self.add_turn()
        self.event(cwd="/other-project")
        self.event(cwd="relative-project")
        self.config["enabled"] = False
        self.save_config()
        self.event()
        self.config_path.unlink()
        (self.root / ".cursor").mkdir()
        (self.root / ".cursor/langfuse.json").write_text('{"enabled":true,"mode":"full"}')
        self.event()
        self.assertFalse(self.archive.exists())
        self.sender.assert_not_called()

    def test_concurrent_identical_callbacks_keep_one_copy(self):
        self.add_turn()
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: self.event(), range(8)))
        self.assertEqual(1, self.archive.read_text().count("FINAL_REPLY"))
        roots = [span for span in self.spans() if "parentSpanId" not in span]
        self.assertEqual(1, len({span["spanId"] for span in roots}))

    def test_real_cli_fails_open_without_printing_source_content(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "copilot_hook.py")], input='{"secret":"DO_NOT_LOG",', text=True, capture_output=True)
        self.assertEqual(0, result.returncode)
        self.assertEqual({}, json.loads(result.stdout))
        self.assertNotIn("DO_NOT_LOG", result.stderr)


class CopilotSetupTests(unittest.TestCase):
    def test_jsonc_edits_preserve_comments_settings_strings_and_are_idempotent(self):
        source = '''{
  // keep this editor preference
  "editor.fontSize": 16,
  "example": "text,} https://example.test/*not a comment*/",
  "chat.useHooks": false, // local override
  "chat.hookFilesLocations": {
    "custom/hooks": true, /* retain this */
  },
}
'''
        updated = copilot.set_jsonc(source, ["chat.useHooks"], True)
        updated = copilot.set_jsonc(updated, ["chat.hookFilesLocations", copilot.HOOK_LOCATION], True)
        config = copilot.jsonc_object(updated)[0]
        self.assertTrue(config["chat.useHooks"])
        self.assertTrue(config["chat.hookFilesLocations"][copilot.HOOK_LOCATION])
        self.assertTrue(config["chat.hookFilesLocations"]["custom/hooks"])
        self.assertEqual(16, config["editor.fontSize"])
        for value in ("// keep this editor preference", "// local override", "/* retain this */", '"example": "text,} https://example.test/*not a comment*/"'):
            self.assertIn(value, updated)
        self.assertEqual(updated, copilot.set_jsonc(updated, ["chat.hookFilesLocations", copilot.HOOK_LOCATION], True))

    def test_jsonc_insertion_handles_empty_comments_bom_and_no_trailing_comma(self):
        for source in ('{}', '{/* only comment */}', '\ufeff{\n"other":42 // end comment\n}', '{"other": {"inner":[1,2,],},}'):
            with self.subTest(source=source):
                updated = copilot.set_jsonc(source, ["chat.useHooks"], True)
                self.assertTrue(copilot.jsonc_object(updated)[0]["chat.useHooks"])

    def test_invalid_config_is_not_replaced_and_installer_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".vscode").mkdir()
            path = root / ".vscode/settings.json"
            for source in ('{"broken":', '{"duplicate":1,"duplicate":2}', '[]', '{"chat.hookFilesLocations": false}'):
                path.write_text(source)
                result = subprocess.run([sys.executable, str(SCRIPTS / "copilot_hook.py"), "--install", str(root)], text=True, capture_output=True)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(source, path.read_text())
                self.assertFalse((root / ".vscode/rcore-hooks").exists())

    def test_installer_matches_template_and_preserves_unrelated_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            copilot.install_hooks(root)
            settings = (root / ".vscode/settings.json").read_bytes()
            path = root / copilot.HOOK_LOCATION
            expected = json.loads((REPOSITORY / ".vscode/copilot-hooks.example.json").read_text())
            self.assertEqual(expected, json.loads(path.read_text()))
            config = json.loads(path.read_text())
            config["hooks"]["Stop"].insert(0, {"type": "command", "command": "unrelated"})
            path.write_text(json.dumps(config))
            copilot.install_hooks(root)
            once = path.read_bytes()
            copilot.install_hooks(root)
            self.assertEqual(once, path.read_bytes())
            self.assertEqual(settings, (root / ".vscode/settings.json").read_bytes())
            self.assertEqual("unrelated", json.loads(once)["hooks"]["Stop"][0]["command"])
            self.assertNotIn("otel", settings.decode())
            for name in ("archive_session.py", "cursor_hook.py", "copilot_hook.py"):
                self.assertEqual((SCRIPTS / name).read_bytes(), (root / ".vscode/rcore-hooks" / name).read_bytes())

    def test_setup_imports_token_and_preserves_independent_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project with spaces"
            (root / ".vscode").mkdir(parents=True)
            (root / ".vscode/langfuse.example.json").write_bytes((REPOSITORY / ".vscode/langfuse.example.json").read_bytes())
            path = root / ".vscode/langfuse.json"
            path.write_text('{"mode":"tool-calls","user_id":"not-trusted"}')
            credential = Path(temp) / "token.json"
            token = {"student_id": "20250001", "public_key": "pk-lf-stu-20250001", "secret_key": "sk-lf-token-" + "z" * 40, "base_url": "https://gateway.example:8443"}
            credential.write_text(json.dumps(token))
            for _ in range(2):
                result = subprocess.run(["bash", "-c", 'source "$1"\nREPOSITORY_ROOT="$2"\nCREDENTIAL_FILE="$3"\nsetup_vscode\nprint_summary',
                                         "copilot-test", str(REPOSITORY / "scripts/setup-agent-plugins.sh"), str(root), str(credential)], text=True, capture_output=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("VS Code Copilot 留档等级：tool-calls", result.stdout)
                self.assertNotIn(token["secret_key"], result.stdout + result.stderr)
            config = json.loads(path.read_text())
            self.assertEqual("tool-calls", config["mode"])
            self.assertEqual(token["secret_key"], config["secret_key"])
            self.assertNotIn("user_id", config)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            for name in (".codex", ".claude", ".cursor", ".agents"):
                self.assertFalse((root / name).exists())

    def test_cached_script_runs_with_no_plugin_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            copilot.install_hooks(root)
            (root / ".vscode/langfuse.json").write_text('{"enabled":true,"mode":"messages"}')
            source = root / "source.jsonl"
            data = [
                ("session.start", {"sessionId": "cached", "version": 1, "producer": "copilot-agent"}),
                ("user.message", {"content": "CACHED_PROMPT"}),
                ("assistant.turn_start", {"turnId": "0"}),
                ("assistant.message", {"content": "CACHED_REPLY", "toolRequests": []}),
                ("assistant.turn_end", {"turnId": "0"}),
            ]
            stamp = "2026-09-06T13:00:00Z"
            source.write_text("".join(json.dumps({"type": kind, "data": value, "id": str(index), "timestamp": stamp}) + "\n"
                                      for index, (kind, value) in enumerate(data)))
            payload = {"hook_event_name": "Stop", "session_id": "cached", "transcript_path": str(source), "cwd": str(root), "timestamp": stamp}
            result = subprocess.run(["bash", "-c", copilot.COMMAND], cwd=root, input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(0, result.returncode)
            self.assertEqual({}, json.loads(result.stdout))
            self.assertFalse((root / "plugins").exists())
            archive = (root / ".agent-sessions/vscode-copilot/cached.md").read_text()
            self.assertIn("CACHED_PROMPT", archive)
            self.assertIn("CACHED_REPLY", archive)

    def test_private_files_ignored_and_template_is_not(self):
        result = subprocess.run(["git", "check-ignore", ".vscode/settings.json", ".vscode/langfuse.json", ".vscode/rcore-hooks/hooks.json", ".agent-sessions/vscode-copilot/session.md"], cwd=REPOSITORY, text=True, capture_output=True)
        self.assertEqual(4, len(result.stdout.splitlines()))
        result = subprocess.run(["git", "check-ignore", ".vscode/langfuse.example.json", ".vscode/copilot-hooks.example.json"], cwd=REPOSITORY, capture_output=True)
        self.assertEqual(1, result.returncode)


if __name__ == "__main__":
    unittest.main()
