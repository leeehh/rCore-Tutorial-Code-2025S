import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPTS))
import cursor_hook as cursor


def attributes(span):
    return {item["key"]: item["value"] for item in span["attributes"]}


def span_text(span, key):
    value = attributes(span).get("langfuse.observation." + key)
    return json.loads(value["stringValue"]) if value else None


class CursorHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / ".cursor/langfuse.json"
        self.config.parent.mkdir()
        self.settings = {
            "enabled": True, "mode": "messages", "public_key": "pk-lf-stu-20250001",
            "secret_key": "sk-lf-token-" + "a" * 40, "base_url": "https://gateway.example:8443",
            "tags": ["os-lab", "rcore"], "user_id": "do-not-trust-this",
        }
        self.save_config()
        self.sender = mock.Mock(return_value=True)
        self.archive = self.root / ".agent-sessions/cursor/conversation.md"

    def save_config(self, mode=None):
        if mode:
            self.settings["mode"] = mode
        self.config.write_text(json.dumps(self.settings))

    def event(self, name, generation="generation-1", **fields):
        payload = {
            "hook_event_name": name, "conversation_id": "conversation",
            "generation_id": generation, "workspace_roots": [str(self.root)],
            "model": "cursor-test-model", "user_email": "private@example.test",
            "transcript_path": "/must/not/be/read/nonexistent.jsonl", **fields,
        }
        cursor.handle(payload, self.root, self.sender)
        return payload

    def trace(self, repeat=False):
        sequence = [
            ("beforeSubmitPrompt", {"prompt": "USER_MESSAGE", "attachments": [{"type": "file", "file_path": "os/src/main.rs"}]}),
            ("afterAgentThought", {"text": "THINKING_DETAIL", "duration_ms": 30}),
            ("preToolUse", {"tool_name": "Shell", "tool_use_id": "tool-1", "tool_input": {"command": "printf COMMAND_ONLY"}, "agent_message": "INTERMEDIATE_DETAIL"}),
            ("postToolUse", {"tool_name": "Shell", "tool_use_id": "tool-1", "tool_input": {"command": "printf COMMAND_ONLY"}, "tool_output": json.dumps({"stdout": "OUTPUT_DETAIL\nnext line", "stderr": "", "exitCode": 0}), "duration": 2}),
            ("afterAgentResponse", {"text": "FINAL_REPLY\n\n```rust\nfn main() {}\n```"}),
            ("stop", {"status": "completed", "loop_count": 0}),
        ]
        for name, fields in sequence:
            self.event(name, **fields)
            if repeat:
                self.event(name, **fields)

    def spans(self):
        return [span for call in self.sender.call_args_list for span in call.args[1]]

    def test_messages_mode_excludes_all_intermediate_content_on_disk(self):
        self.trace()
        text = self.archive.read_text()
        self.assertIn("USER_MESSAGE", text)
        self.assertIn("FINAL_REPLY", text)
        self.assertIn("os/src/main.rs", text)
        self.assertIn("```rust\nfn main() {}", text)
        for secret in ("THINKING_DETAIL", "INTERMEDIATE_DETAIL", "COMMAND_ONLY", "OUTPUT_DETAIL"):
            for path in (self.root / ".agent-sessions").rglob("*"):
                if path.is_file():
                    self.assertNotIn(secret.encode(), path.read_bytes(), str(path))
        self.assertEqual([], list((self.root / ".agent-sessions").rglob("*.json*")))
        self.assertEqual(0o600, self.archive.stat().st_mode & 0o777)
        self.assertEqual(0o700, self.archive.parent.stat().st_mode & 0o777)

    def test_tool_calls_mode_has_commands_without_outputs_or_thoughts(self):
        self.save_config("tool-calls")
        self.event("beforeSubmitPrompt", prompt="USER_MESSAGE")
        self.event("preToolUse", tool_name="Shell", tool_use_id="tool-1", tool_input={"command": "printf COMMAND_ONLY"})
        self.assertIn("COMMAND_ONLY", self.archive.read_text())
        self.trace()
        text = self.archive.read_text()
        self.assertIn("### 工具调用：Shell", text)
        self.assertIn("```bash\nprintf COMMAND_ONLY", text)
        self.assertNotIn("OUTPUT_DETAIL", text)
        self.assertNotIn("THINKING_DETAIL", text)
        self.assertNotIn("INTERMEDIATE_DETAIL", text)

    def test_full_mode_retains_readable_results_and_thoughts(self):
        self.save_config("full")
        self.trace()
        text = self.archive.read_text()
        for expected in ("THINKING_DETAIL", "INTERMEDIATE_DETAIL", "COMMAND_ONLY", "OUTPUT_DETAIL", "exitCode: 0"):
            self.assertIn(expected, text)
        self.assertNotIn('\\"stdout\\"', text)
        self.assertEqual(1, text.count("### 工具调用：Shell"))
        self.assertEqual(1, text.count("### 工具输出：Shell"))

    def test_mode_downgrade_prunes_existing_output_then_commands(self):
        self.save_config("full")
        self.trace()
        self.save_config("tool-calls")
        self.event("stop", status="completed")
        text = self.archive.read_text()
        self.assertIn("COMMAND_ONLY", text)
        self.assertNotIn("OUTPUT_DETAIL", text)
        self.assertNotIn("THINKING_DETAIL", text)
        self.save_config("messages")
        self.event("stop", status="completed")
        self.assertNotIn("COMMAND_ONLY", self.archive.read_text())
        self.assertIn("FINAL_REPLY", self.archive.read_text())

    def test_mode_downgrade_also_clears_a_tool_only_archive(self):
        self.save_config("full")
        self.event("postToolUse", tool_name="Shell", tool_use_id="only-tool", tool_input={"command": "ONLY_COMMAND"}, tool_output="ONLY_OUTPUT")
        self.save_config("messages")
        self.event("stop", status="completed")
        self.assertNotIn("ONLY_COMMAND", self.archive.read_text())
        self.assertNotIn("ONLY_OUTPUT", self.archive.read_text())
        self.event("afterAgentResponse", text="New final answer")
        self.assertIn("New final answer", self.archive.read_text())

    def test_mode_does_not_filter_uploaded_tool_results_and_thoughts(self):
        self.trace()
        spans = self.spans()
        self.assertTrue(any(span["name"] == "Bash" and "OUTPUT_DETAIL" in (span_text(span, "output") or "") for span in spans))
        self.assertTrue(any(span["name"] == "Bash" and "COMMAND_ONLY" in (span_text(span, "input") or "") for span in spans))
        self.assertTrue(any(span_text(span, "output") == "THINKING_DETAIL" for span in spans))
        roots = [span for span in spans if "parentSpanId" not in span]
        self.assertEqual(1, len(roots))
        self.assertIn("USER_MESSAGE", span_text(roots[0], "input")[0]["content"])
        self.assertIn("FINAL_REPLY", span_text(roots[0], "output")[0]["content"])
        self.assertTrue(all(span.get("parentSpanId", roots[0]["spanId"]) == roots[0]["spanId"] for span in spans))
        self.assertEqual(1, len({span["traceId"] for span in spans}))
        encoded = json.dumps(spans)
        for forbidden in ("user.id", "do-not-trust-this", "private@example.test", self.settings["secret_key"]):
            self.assertNotIn(forbidden, encoded)

    def test_repeated_callbacks_do_not_duplicate_or_reupload_completed_events(self):
        self.save_config("full")
        self.trace(repeat=True)
        text = self.archive.read_text()
        for value in ("USER_MESSAGE", "FINAL_REPLY", "COMMAND_ONLY", "OUTPUT_DETAIL", "THINKING_DETAIL"):
            self.assertEqual(1, text.count(value), value)
        spans = self.spans()
        roots = [span for span in spans if span["name"] == "Cursor Turn"]
        self.assertEqual(1, len(roots))
        tool_spans = [span for span in spans if span["name"] == "Bash"]
        self.assertEqual(2, len(tool_spans))  # start and completed result update the same observation
        self.assertEqual(tool_spans[0]["spanId"], tool_spans[1]["spanId"])
        self.assertEqual(tool_spans[0]["startTimeUnixNano"], tool_spans[1]["startTimeUnixNano"])

    def test_identical_messages_in_different_turns_are_retained(self):
        for generation in ("one", "two"):
            self.event("beforeSubmitPrompt", generation, prompt="same question")
            self.event("afterAgentResponse", generation, text="same answer")
            self.event("stop", generation, status="completed")
        text = self.archive.read_text()
        self.assertEqual(2, text.count("same question"))
        self.assertEqual(2, text.count("same answer"))
        spans = self.spans()
        self.assertEqual(2, len({span["traceId"] for span in spans}))
        self.assertEqual(1, len({attributes(span)["langfuse.session.id"]["stringValue"] for span in spans}))

    def test_nonconsecutive_repeated_text_is_not_mistaken_for_a_retry(self):
        self.save_config("full")
        for text in ("THOUGHT_A", "THOUGHT_B", "THOUGHT_A"):
            self.event("afterAgentThought", text=text)
            self.event("afterAgentThought", text=text)
        self.assertEqual(2, self.archive.read_text().count("THOUGHT_A"))
        self.assertEqual(3, len(self.spans()))
        for text in ("RESPONSE_A", "RESPONSE_B", "RESPONSE_A"):
            self.event("afterAgentResponse", text=text)
            self.event("afterAgentResponse", text=text)
        self.assertEqual(2, self.archive.read_text().count("RESPONSE_A"))

    def test_tools_with_identical_commands_but_different_ids_are_retained(self):
        self.save_config("full")
        for tool_id in ("first", "second"):
            self.event("postToolUse", tool_name="Shell", tool_use_id=tool_id, tool_input={"command": "pwd"}, tool_output="cwd")
        self.assertEqual(2, self.archive.read_text().count("### 工具调用：Shell"))
        self.assertEqual(2, len({span["spanId"] for span in self.spans()}))

    def test_commentary_followed_by_tool_is_not_a_final_answer(self):
        self.event("beforeSubmitPrompt", prompt="test")
        self.event("afterAgentResponse", text="I will inspect the file")
        self.event("preToolUse", tool_name="Read", tool_use_id="read-1", tool_input={"path": "README.md"})
        self.assertNotIn("I will inspect", self.archive.read_text())
        self.event("afterAgentResponse", text="The final answer")
        self.assertIn("The final answer", self.archive.read_text())
        self.assertTrue(any(span_text(span, "output") == "I will inspect the file" for span in self.spans()))

    def test_empty_stop_and_response_do_not_create_empty_root_traces(self):
        self.event("stop", status="completed")
        self.assertFalse((self.root / ".agent-sessions").exists())
        self.event("afterAgentResponse", text=" ")
        self.event("stop", status="completed")
        self.assertFalse(self.archive.exists())
        self.sender.assert_not_called()

    def test_aborted_turn_keeps_prompt_without_inventing_a_reply(self):
        self.event("beforeSubmitPrompt", prompt="unfinished question")
        self.event("stop", status="aborted")
        text = self.archive.read_text()
        self.assertIn("unfinished question", text)
        self.assertNotIn("### Cursor", text)
        self.assertEqual([], span_text(self.spans()[0], "output"))
        self.assertEqual(2, self.spans()[0]["status"]["code"])

    def test_tool_failure_is_preserved_without_blocking(self):
        self.save_config("full")
        self.event("postToolUseFailure", tool_name="Shell", tool_use_id="failed", tool_input={"command": "false"}, error_message="Process exited 1", failure_type="error")
        self.assertIn("Process exited 1", self.archive.read_text())
        self.assertEqual(2, self.spans()[0]["status"]["code"])

    def test_failed_root_upload_is_retried_at_stop_with_identical_ids(self):
        self.sender.return_value = False
        self.event("beforeSubmitPrompt", prompt="question")
        self.event("afterAgentResponse", text="reply")
        self.assertIn("reply", self.archive.read_text())
        self.sender.return_value = True
        self.event("stop", status="completed")
        self.assertEqual(self.spans()[0], self.spans()[1])
        self.event("stop", status="completed")
        self.assertEqual(2, self.sender.call_count)

    def test_scope_gate_ignores_other_projects_multiroot_and_missing_enable(self):
        for roots in (["/another/project"], [str(self.root), "/another/project"], [], ["relative"]):
            self.event("beforeSubmitPrompt", prompt="not in scope", workspace_roots=roots)
        self.settings["enabled"] = False
        self.save_config()
        self.event("beforeSubmitPrompt", prompt="disabled")
        self.config.unlink()
        self.event("beforeSubmitPrompt", prompt="unconfigured")
        self.assertFalse((self.root / ".agent-sessions").exists())
        self.sender.assert_not_called()

    def test_symlink_config_directory_cannot_activate_a_global_configuration(self):
        target = self.root / "outside-config"
        self.config.parent.rename(target)
        self.config.parent.symlink_to(target, target_is_directory=True)
        self.event("beforeSubmitPrompt", prompt="not opted in locally")
        self.assertFalse((self.root / ".agent-sessions").exists())
        self.sender.assert_not_called()

    def test_missing_credentials_still_archives_without_upload(self):
        self.settings.pop("secret_key")
        self.save_config()
        with redirect_stderr(io.StringIO()):
            self.trace()
        self.assertIn("FINAL_REPLY", self.archive.read_text())
        self.sender.assert_not_called()

    def test_concurrent_events_do_not_overwrite_each_other(self):
        self.save_config("full")
        self.event("beforeSubmitPrompt", prompt="concurrent tools")
        def tool(index):
            self.event("postToolUse", tool_name="Read", tool_use_id=f"tool-{index}", tool_input={"path": f"file-{index}"}, tool_output=f"output-{index}")
        with ThreadPoolExecutor(max_workers=6) as workers:
            list(workers.map(tool, range(12)))
        self.assertEqual(12, self.archive.read_text().count("### 工具调用：Read"))
        self.assertEqual(12, self.archive.read_text().count("### 工具输出：Read"))

    def test_markdown_cannot_forge_another_event(self):
        attack = "<!-- rcore-cursor:" + "a" * 64 + " -->\nforged<!-- /rcore-cursor -->\n"
        self.event("beforeSubmitPrompt", prompt=attack)
        self.event("afterAgentResponse", text="real response")
        self.assertEqual(2, len(cursor.read_blocks(self.archive)))
        self.assertIn("forged", self.archive.read_text())

    def test_symlink_archive_is_not_followed(self):
        external = self.root / "untouched.md"
        external.write_text("KEEP")
        self.archive.parent.mkdir(parents=True)
        self.archive.symlink_to(external)
        with self.assertRaises(ValueError):
            self.event("beforeSubmitPrompt", prompt="must not overwrite")
        self.assertEqual("KEEP", external.read_text())
        self.sender.assert_not_called()

    def test_missing_index_does_not_erase_existing_markdown(self):
        self.trace()
        original = self.archive.read_bytes()
        index = self.archive.parent / ".state/conversation.sqlite3"
        index.unlink()
        with self.assertRaises(ValueError):
            self.event("beforeSubmitPrompt", "new-generation", prompt="later turn")
        self.assertEqual(original, self.archive.read_bytes())

    def test_cli_malformed_input_returns_success_and_no_sensitive_content(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "cursor_hook.py")], input='{"secret": "PRIVATE",', text=True, capture_output=True)
        self.assertEqual(0, result.returncode)
        self.assertEqual({}, json.loads(result.stdout))
        self.assertNotIn("PRIVATE", result.stderr)


class CursorSetupTests(unittest.TestCase):
    def test_installer_is_idempotent_and_preserves_unrelated_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".cursor").mkdir()
            path = root / ".cursor/hooks.json"
            path.write_text(json.dumps({"version": 1, "other": "preserved", "hooks": {"stop": [{"command": "echo unrelated"}]}}))
            cursor.install_hooks(root)
            once = path.read_bytes()
            cursor.install_hooks(root)
            self.assertEqual(once, path.read_bytes())
            hooks = json.loads(once)
            self.assertEqual("preserved", hooks["other"])
            self.assertEqual("echo unrelated", hooks["hooks"]["stop"][0]["command"])
            for event in cursor.EVENTS:
                self.assertEqual(1, sum(entry["command"] == cursor.COMMAND for entry in hooks["hooks"][event]))

    def test_setup_imports_token_project_only_and_preserves_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project with spaces"
            root.mkdir()
            (root / ".cursor").mkdir()
            template = REPOSITORY / ".cursor/langfuse.example.json"
            (root / ".cursor/langfuse.example.json").write_bytes(template.read_bytes())
            path = root / ".cursor/langfuse.json"
            path.write_text(json.dumps({"mode": "tool-calls", "custom": 123, "user_id": "not-allowed"}))
            credential = Path(temp) / "token.json"
            token = {"student_id": "20250001", "public_key": "pk-lf-stu-20250001", "secret_key": "sk-lf-token-" + "z" * 40, "base_url": "https://gateway.example:8443"}
            credential.write_text(json.dumps(token))
            legacy = root / ".agents/session-archive.json"
            legacy.parent.mkdir()
            legacy.write_text('{"mode":"full"}')
            for _ in range(2):
                result = subprocess.run([
                    "bash", "-c", 'source "$1"\nREPOSITORY_ROOT="$2"\nCREDENTIAL_FILE="$3"\nsetup_cursor\nprint_summary',
                    "cursor-setup-test", str(REPOSITORY / "scripts/setup-agent-plugins.sh"), str(root), str(credential),
                ], text=True, capture_output=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("Cursor 留档等级：tool-calls", result.stdout)
                self.assertNotIn(token["secret_key"], result.stdout + result.stderr)
            config = json.loads(path.read_text())
            self.assertEqual("tool-calls", config["mode"])
            self.assertEqual(123, config["custom"])
            self.assertNotIn("user_id", config)
            self.assertTrue(config["enabled"])
            self.assertEqual(token["secret_key"], config["secret_key"])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertTrue(legacy.exists())
            self.assertFalse((root / ".codex").exists())
            self.assertFalse((root / ".claude").exists())

    def test_checked_in_hooks_match_installer_and_ignore_private_files(self):
        checked_in = json.loads((REPOSITORY / ".cursor/hooks.example.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            cursor.install_hooks(Path(temp))
            self.assertEqual(checked_in, json.loads((Path(temp) / ".cursor/hooks.json").read_text()))
        result = subprocess.run(["git", "check-ignore", ".cursor/langfuse.json", ".cursor/hooks.json", ".cursor/rcore-hooks/cursor_hook.py", ".agent-sessions/cursor/session.md", ".agent-sessions/cursor/.state/session.sqlite3"], cwd=REPOSITORY, text=True, capture_output=True)
        self.assertEqual(5, len(result.stdout.splitlines()))

    def test_installed_hook_runs_without_plugin_source_after_branch_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            cursor.install_hooks(root)
            # Simulates a lab checkout that has neither plugins/ nor the setup script.
            config = root / ".cursor/langfuse.json"
            config.write_text('{"enabled":true,"mode":"messages"}')
            for event, extra in (("beforeSubmitPrompt", {"prompt": "branch input"}), ("afterAgentResponse", {"text": "branch reply"})):
                payload = {"hook_event_name": event, "workspace_roots": [str(root)], "conversation_id": "branch-session", "generation_id": "turn", **extra}
                result = subprocess.run(["bash", "-c", cursor.COMMAND], cwd=root, input=json.dumps(payload), text=True, capture_output=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual({}, json.loads(result.stdout))
            text = (root / ".agent-sessions/cursor/branch-session.md").read_text()
            self.assertIn("branch input", text)
            self.assertIn("branch reply", text)
            for filename in ("cursor_hook.py", "archive_session.py"):
                self.assertEqual((SCRIPTS / filename).read_bytes(), (root / ".cursor/rcore-hooks" / filename).read_bytes())


class CursorUploadTests(unittest.TestCase):
    CONFIG = {"base_url": "https://gateway.example:8443", "public_key": "pk-lf-stu-20250001", "secret_key": "sk-lf-token-" + "a" * 40}

    def response(self, body=b"{}"):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = body
        return response

    def test_otlp_endpoint_authentication_and_payload(self):
        with mock.patch.object(cursor.urllib.request, "build_opener") as factory:
            opener = factory.return_value
            opener.open.return_value = self.response()
            self.assertTrue(cursor.upload(self.CONFIG, [{"name": "synthetic"}]))
            request = opener.open.call_args.args[0]
            self.assertEqual("https://gateway.example:8443/api/public/otel/v1/traces", request.full_url)
            auth = base64.b64decode(request.get_header("Authorization").split()[1]).decode()
            self.assertEqual(self.CONFIG["public_key"] + ":" + self.CONFIG["secret_key"], auth)
            self.assertEqual("application/json", request.get_header("Content-type"))
            self.assertEqual("4", request.get_header("X-langfuse-ingestion-version"))
            self.assertEqual([{"name": "synthetic"}], json.loads(request.data)["resourceSpans"][0]["scopeSpans"][0]["spans"])
            self.assertEqual(2, opener.open.call_args.kwargs["timeout"])

    def test_transient_failure_retries_but_auth_failure_does_not_leak(self):
        with mock.patch.object(cursor.urllib.request, "build_opener") as factory:
            opener = factory.return_value
            opener.open.side_effect = [TimeoutError(), self.response()]
            self.assertTrue(cursor.upload(self.CONFIG, []))
            self.assertEqual(2, opener.open.call_count)
            opener.reset_mock()
            opener.open.side_effect = urllib.error.HTTPError("https://example", 401, self.CONFIG["secret_key"], {}, None)
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertFalse(cursor.upload(self.CONFIG, []))
            self.assertEqual(1, opener.open.call_count)
            self.assertIn("401", errors.getvalue())
            self.assertNotIn(self.CONFIG["secret_key"], errors.getvalue())

    def test_otlp_partial_rejection_is_not_marked_success(self):
        with mock.patch.object(cursor.urllib.request, "build_opener") as factory, redirect_stderr(io.StringIO()):
            factory.return_value.open.return_value = self.response(b'{"partialSuccess":{"rejectedSpans":"1"}}')
            self.assertFalse(cursor.upload(self.CONFIG, []))

    def test_authentication_redirects_are_disabled(self):
        self.assertIsNone(cursor.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other-host"))

    def test_real_http_transport_against_local_otlp_receiver(self):
        received = []

        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, self.headers["Authorization"], data))
                body = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Receiver)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Runtime only accepts HTTPS. HTTP here is isolated transport testing;
            # never relax certificate verification or credential validation in handle().
            config = {**self.CONFIG, "base_url": f"http://127.0.0.1:{server.server_port}"}
            with mock.patch.dict(os.environ, {"no_proxy": "127.0.0.1"}):
                self.assertTrue(cursor.upload(config, [{"name": "local-test"}]))
            self.assertFalse(cursor.valid_credentials(config))
            self.assertEqual("/api/public/otel/v1/traces", received[0][0])
            self.assertEqual("local-test", received[0][2]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
