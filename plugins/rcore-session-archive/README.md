# rCore Session Archive

This repository-local plugin keeps a configurable local archive of Codex and
Claude Code sessions. It does not upload data and does not contain Langfuse
credentials.

## Configuration

The repository-local configuration is `.agents/session-archive.json`. The
setup script creates it from `.agents/session-archive.example.json` without
overwriting an existing choice. The file is ignored by Git so each student can
choose a policy independently.

```json
{
  "mode": "messages"
}
```

Supported modes are:

| Mode | Archived data |
| --- | --- |
| `messages` | User-authored input and each agent final answer only. This is the default. |
| `tool-calls` | Everything in `messages`, plus tool names, command/tool inputs, and call IDs. Tool outputs and results are discarded. |
| `full` | The complete raw agent transcript, including intermediate messages, reasoning records, tool calls, and tool outputs. |

If the configuration is missing, malformed, or contains an unsupported mode,
the plugin uses the privacy-preserving `messages` mode. Filtered modes write a
small normalized JSONL stream instead of copying agent-internal transcript
metadata. In `tool-calls` mode, remember that command arguments and other tool
inputs can themselves contain sensitive information even though outputs are
excluded.

The `Stop` hook refreshes the session file after every agent response. The
`SessionEnd` hook performs one final refresh when the session closes. Both hooks
atomically replace the same file, so repeated hook calls do not create duplicate
archives.

Archives are written to:

```text
.agent-sessions/codex/<session-id>.jsonl
.agent-sessions/claude-code/<session-id>.jsonl
```

The archive directory is excluded from Git because every mode can contain
sensitive prompts or source snippets, and `full` mode can additionally contain
reasoning records, tool output, or secrets. Changing the mode affects future
hook refreshes; older archive files are not rewritten automatically.
