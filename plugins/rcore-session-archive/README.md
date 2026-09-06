# rCore Session Archive

This repository-local plugin keeps configurable Markdown archives of Codex and
Claude Code sessions. Their `archive_session.py` hook does not upload data. The
companion `cursor_hook.py` handles both project-local Cursor archives and OTLP
upload through the course identity gateway. No credentials are included in the plugin.

## Configuration

Each agent reads its own project configuration, alongside its Langfuse credentials.
The setup script preserves existing credentials and mode choices; private files are
ignored by Git so each student can choose a policy independently.

For Codex, set the top-level `mode` in `.codex/langfuse.json`:

```json
{
  "mode": "messages"
}
```

For Claude Code, set `env.RCORE_SESSION_ARCHIVE_MODE` in `.claude/settings.local.json`:

```json
{
  "env": {
    "RCORE_SESSION_ARCHIVE_MODE": "messages"
  }
}
```

These snippets show only archive fields; retain other fields when editing existing
files. The complete templates are `.codex/langfuse.example.json` and
`.claude/settings.local.example.json`. Claude's `LANGFUSE_*` and `CC_LANGFUSE_*`
variables remain in that same `env` block, as supported by the unmodified official
upload plugin. `RCORE_SESSION_ARCHIVE_MODE` is consumed only by this archive plugin.
There is no `.claude/langfuse.json`, and a Claude-only setup no longer creates a
Codex configuration file.

The hook reads only the current agent's file on every invocation, never the other
agent's policy or a stale process environment value. When upgrading an older
installation, run `./scripts/setup-agent-plugins.sh claude`: if Claude has no mode
yet, setup copies the previously shared Codex mode once, without copying credentials
or changing Codex's configuration. The two modes are independent after setup.
Setup also migrates the retired `.agents/session-archive.json` choice, then removes
that old file after the selected agent's new configuration is safely saved. An
explicit per-agent mode takes precedence. The `.agents/plugins/` marketplace is retained.
This setting controls local Markdown archives; the Langfuse
upload plugin determines what is uploaded separately.

Supported modes are:

| Mode | Archived data |
| --- | --- |
| `messages` | User-authored input and each agent final answer only. This is the default. |
| `tool-calls` | Everything in `messages`, plus tool names, command/tool inputs, and call IDs. Tool outputs and results are discarded. |
| `full` | Conversation text including intermediate messages, readable reasoning summaries, tool calls, and complete tool outputs. Long intermediate text and outputs are collapsible. |

If the current agent's file or its mode is missing, or the configuration is malformed or
contains an unsupported mode, the hook uses `messages`. The setup script instead
rejects invalid configuration so it can be corrected before installation.
Every mode writes one
Markdown document, with user/agent sections grouped into conversation turns.
Message code blocks, lists, tables and line breaks are retained. Shell commands
get their own code blocks; structured tool arguments are shown as readable
key/value text. Long intermediate messages and tool outputs use HTML
`details` sections without truncating the text. Open the file in VS Code's
Markdown preview to expand these sections.

No raw JSON/JSONL backup is generated. Duplicate transport events, token counters,
encrypted fields, and other agent-internal metadata are not conversation content
and are omitted even in `full` mode. Binary attachments are described or referenced,
not copied or embedded as base64. The agent's own source transcript is never deleted.

In `tool-calls` mode, remember that command arguments and other tool
inputs can themselves contain sensitive information even though outputs are
excluded.

The `Stop` hook refreshes the session file after every agent response. The
`SessionEnd` hook performs one final refresh when the session closes. Both hooks
atomically replace the same file, so repeated hook calls do not create duplicate
archives.

Claude's `Stop` input supplies `last_assistant_message`: the final response is not
guaranteed to have reached the transcript file when the hook runs. The archive
merges that text into the last response, retaining it once whether the transcript
has no reply yet, has only a partial reply, or already contains the complete reply.
Deduplication is scoped to the latest main-agent API message after the last user
input/tool result, so identical answers to separate prompts are retained. No extra
JSON file is saved, and the agent's source transcript is never modified. An
incomplete final JSONL line is tolerated only when a valid Stop reply is available;
other transcript corruption still fails without replacing an existing archive.
`SessionEnd` and error/interruption events do not inject a stale Stop response.
See the [official Stop input documentation](https://code.claude.com/docs/en/hooks#stop-input).

Archives are written to:

```text
.agent-sessions/codex/<session-id>.md
.agent-sessions/claude-code/<session-id>.md
.agent-sessions/cursor/<conversation-id>.md
```

After a successful Markdown refresh, the hook removes that same session's legacy
`.jsonl` archive, if present. A failed refresh leaves existing archives intact.
Other historical archives are not converted or deleted automatically.

The archive directory is excluded from Git because every mode can contain
sensitive prompts or source snippets, and `full` mode can additionally contain
reasoning records, tool output, or secrets. Restart the agent after updating the
plugin. Subsequent mode edits take effect at the next hook refresh without another
restart; older archive files are not rewritten automatically. Changing Claude's
Langfuse credentials instead requires restarting Claude Code to reload its environment.

## Cursor (native project hooks)

From the checkout, run:

```bash
./scripts/setup-agent-plugins.sh cursor /path/to/rcore-agent-token-<student-id>.json
```

Only Python 3.9+ and Git are required for the adapter. Cursor itself must support the
[documented project hooks](https://cursor.com/docs/hooks). The setup command merges
`.cursor/hooks.json` without removing unrelated hooks or duplicating its handlers.
It writes credentials, `enabled: true` and `mode: "messages"` to the private
`.cursor/langfuse.json`, preserving an existing mode. It does not write user-global
Cursor configuration or install a Codex/Claude upload plugin for Cursor.
The hooks file and installed Python runtime in `.cursor/rcore-hooks/` are ignored by
Git, so they survive switching to lab branches without plugin source. The shared
hook template is `.cursor/hooks.example.json`. After pulling updates on `main`, run
setup again to refresh the project-local runtime; other agents' caches are unchanged.

Open and trust the repository root in Cursor, then start a new Agent chat. Check
Customize → Hooks and the Hooks output channel. Multi-root workspaces containing
folders outside this checkout are excluded. For SSH/WSL, configure the checkout in
that environment and make Python available there. This integration does not capture
Tab completions. Do not remove the ignored runtime/configuration with `git clean -fdx`.

The adapter receives `beforeSubmitPrompt`, `afterAgentResponse`, `afterAgentThought`,
`preToolUse`, `postToolUse`, `postToolUseFailure` and `stop`. It takes the latest reply
directly from the hook, including when `transcript_path` is absent or not flushed.
A reply followed by another tool becomes intermediate output rather than a final
answer. The same three local modes apply; `enabled: false` disables both Cursor
upload and archive. Missing/invalid JSON config disables the adapter, an invalid
mode falls back to `messages`, and each invocation re-reads the project config.

Unlike the Codex/Claude transcript-based writer, this event adapter cannot recover
previously discarded content when a mode is raised. Lowering a mode prunes stored
content for the active conversation at its next callback. Finished conversations
are not automatically rewritten. Markdown is the only conversation-body store.
The private `.state/<conversation-id>.sqlite3` index contains only IDs, hashes and
timestamps for ordering/deduplication; it contains no prompts, responses, tool
contents or credentials. Keep it with the Markdown: if the index is missing, the
adapter refuses to overwrite an existing archive. Generated files are replaced
atomically (`tail -F` follows replacements); archive permissions are owner-only.

Uploads use [Langfuse OTLP/HTTP JSON](https://langfuse.com/integrations/native/opentelemetry)
at `/api/public/otel/v1/traces` with the student's Basic-auth public key/token. No
`user_id` or Cursor email is sent; the gateway assigns the verified student identity.
There is one session per conversation and one stable trace per generation. Tool
start/completion updates share an observation ID, completed event retries are
suppressed, and lifecycle-only empty turns are not exported. Shell observations use
the existing collector's `Bash` input allowlist, with the original Cursor tool name
in metadata. Other tools keep their real names. Remote capture includes the available
intermediate messages and tool outputs regardless of local `mode`; model system
prompts, usage and hidden internals absent from hooks are not fabricated.

Upload attempts have a two-second network timeout and one retry for transient
failures. The current root input/reply is retried on `stop` when necessary. There is
no raw payload disk queue: tool events during persistent outages are not guaranteed
to be backfilled. Local Markdown is saved before network I/O, and hook failures
return an empty response with exit code zero without altering permission decisions.
Redirects are refused so student credentials are never forwarded to another host.

Tests run without a real Cursor process or course-server writes:

```bash
python3 -m unittest discover -s plugins/rcore-session-archive/tests
```
