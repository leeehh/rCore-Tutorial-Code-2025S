# rCore Session Archive

This repository-local plugin keeps a raw local copy of Codex and Claude Code
transcripts. It does not upload data and does not contain Langfuse credentials.

The `Stop` hook refreshes the session file after every agent response. The
`SessionEnd` hook performs one final refresh when the session closes. Both hooks
atomically replace the same file, so repeated hook calls do not create duplicate
archives.

Archives are written to:

```text
.agent-sessions/codex/<session-id>.jsonl
.agent-sessions/claude-code/<session-id>.jsonl
```

The archive directory is excluded from Git because transcripts may contain
prompts, source snippets, tool output, or secrets.
