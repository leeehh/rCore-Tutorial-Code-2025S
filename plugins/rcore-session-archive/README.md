# rCore Session Archive

This repository-local plugin keeps a configurable Markdown archive of Codex and
Claude Code sessions. It does not upload data and does not contain Langfuse
credentials.

## Configuration

Set the top-level `mode` field in the repository's `.codex/langfuse.json`, alongside
the Langfuse credentials and other settings. Both Codex and Claude Code archives
read this field. The setup script preserves existing credentials and mode choices;
the file is ignored by Git so each student can choose a policy independently.

```json
{
  "mode": "messages"
}
```

This snippet shows only the archive field; retain the other fields when editing
an existing file. The complete template is `.codex/langfuse.example.json`.
A Claude-only setup also creates `.codex/langfuse.json` for the shared archive
mode; Claude's upload credentials remain in `.claude/settings.local.json`.

The hook reads only `.codex/langfuse.json`. Running the setup script migrates any
retired `.agents/session-archive.json` choice without changing existing credentials,
then removes that old file after the new configuration is safely saved. An explicit
mode in the new file takes precedence. The `.agents/plugins/` marketplace is retained.
This setting controls local Markdown archives; the Langfuse
upload plugin determines what is uploaded separately.

Supported modes are:

| Mode | Archived data |
| --- | --- |
| `messages` | User-authored input and each agent final answer only. This is the default. |
| `tool-calls` | Everything in `messages`, plus tool names, command/tool inputs, and call IDs. Tool outputs and results are discarded. |
| `full` | Conversation text including intermediate messages, readable reasoning summaries, tool calls, and complete tool outputs. Long intermediate text and outputs are collapsible. |

If the Langfuse file or its mode is missing, or the configuration is malformed or
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
reasoning records, tool output, or secrets. Changing the mode affects future
hook refreshes; older archive files are not rewritten automatically.
