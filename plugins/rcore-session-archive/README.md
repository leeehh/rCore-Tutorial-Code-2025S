# rCore Session Archive

This repository-local plugin keeps a configurable Markdown archive of Codex and
Claude Code sessions. It does not upload data and does not contain Langfuse
credentials.

## Configuration

Each agent reads its own project configuration, alongside its Langfuse credentials.
The setup script preserves existing credentials and mode choices; both files are
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
