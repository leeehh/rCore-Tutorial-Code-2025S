#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPOSITORY_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd -P)
MARKETPLACE_NAME="rcore-tutorial-2025s"
PLUGIN_ID="rcore-session-archive@${MARKETPLACE_NAME}"

usage() {
    cat <<'EOF'
Usage: ./scripts/setup-agent-plugins.sh [auto|codex|claude|all]

  auto    Configure every supported agent found on this machine (default).
  codex   Configure Codex only.
  claude  Configure Claude Code only.
  all     Require and configure both Codex and Claude Code.
EOF
}

require_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "error: Python 3 is required by the local session archive hook" >&2
        exit 1
    fi
}

codex_marketplace_exists() {
    codex plugin marketplace list --json | python3 -c '
import json, sys
name = sys.argv[1]
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("name") == name for item in data.get("marketplaces", [])) else 1)
' "${MARKETPLACE_NAME}"
}

codex_plugin_exists() {
    codex plugin list --json | python3 -c '
import json, sys
plugin_id = sys.argv[1]
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("pluginId") == plugin_id and item.get("installed") for item in data.get("installed", [])) else 1)
' "${PLUGIN_ID}"
}

disable_codex_plugin_globally() {
    python3 - "${PLUGIN_ID}" <<'PY'
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

plugin_id = sys.argv[1]
codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
config_path = codex_root / "config.toml"
if not config_path.exists():
    raise SystemExit("error: Codex did not create its user config")

lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
section = f'[plugins."{plugin_id}"]'
try:
    start = next(index for index, line in enumerate(lines) if line.strip() == section)
except StopIteration:
    raise SystemExit(f"error: Codex did not register {plugin_id} in its user config")

end = next(
    (index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("[")),
    len(lines),
)
enabled_pattern = re.compile(r"^(\s*enabled\s*=\s*)(?:true|false)(\s*(?:#.*)?(?:\n)?)$")
for index in range(start + 1, end):
    match = enabled_pattern.match(lines[index])
    if match:
        lines[index] = f"{match.group(1)}false{match.group(2)}"
        break
else:
    lines.insert(start + 1, "enabled = false\n")

config_path.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary_name = tempfile.mkstemp(
    dir=config_path.parent, prefix=".config.toml.", suffix=".tmp"
)
temporary_path = Path(temporary_name)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.writelines(lines)
        output.flush()
        os.fsync(output.fileno())
    temporary_path.chmod(stat.S_IMODE(config_path.stat().st_mode))
    os.replace(temporary_path, config_path)
except BaseException:
    try:
        temporary_path.unlink()
    except OSError:
        pass
    raise
PY
}

claude_marketplace_exists() {
    claude plugin marketplace list --json | python3 -c '
import json, sys
name = sys.argv[1]
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("name") == name for item in data) else 1)
' "${MARKETPLACE_NAME}"
}

claude_plugin_exists() {
    claude plugin list --json | python3 -c '
import json, sys
plugin_id = sys.argv[1]
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("id") == plugin_id for item in data) else 1)
' "${PLUGIN_ID}"
}

setup_codex() {
    if ! command -v codex >/dev/null 2>&1; then
        echo "error: Codex CLI is not installed" >&2
        return 1
    fi

    if ! codex_marketplace_exists; then
        codex plugin marketplace add "${REPOSITORY_ROOT}"
    fi
    if ! codex_plugin_exists; then
        codex plugin add "${PLUGIN_ID}"
    fi
    disable_codex_plugin_globally

    echo "Codex local session archive configured (enabled only by this repository)."
    if ! codex plugin list --json | python3 -c '
import json, sys
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("pluginId") == "tracing@codex-observability-plugin" and item.get("installed") for item in data.get("installed", [])) else 1)
'; then
        echo "note: the official Langfuse Codex tracing plugin is not installed; follow the course tracing instructions."
    fi
}

setup_claude() {
    if ! command -v claude >/dev/null 2>&1; then
        echo "error: Claude Code CLI is not installed" >&2
        return 1
    fi

    if ! claude_marketplace_exists; then
        claude plugin marketplace add --scope local "${REPOSITORY_ROOT}"
    fi
    if ! claude_plugin_exists; then
        claude plugin install --scope local "${PLUGIN_ID}"
    fi

    echo "Claude Code local session archive configured."
    if ! claude plugin list --json | python3 -c '
import json, sys
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("id") == "langfuse-observability@langfuse-observability" for item in data) else 1)
'; then
        echo "note: the official Langfuse Claude Code plugin is not installed; follow the course tracing instructions."
    fi
}

main() {
    require_python
    local target="${1:-auto}"
    local configured=0

    case "${target}" in
        auto)
            if command -v codex >/dev/null 2>&1; then
                setup_codex
                configured=1
            fi
            if command -v claude >/dev/null 2>&1; then
                setup_claude
                configured=1
            fi
            if [[ "${configured}" -eq 0 ]]; then
                echo "error: neither Codex nor Claude Code was found" >&2
                exit 1
            fi
            ;;
        codex)
            setup_codex
            ;;
        claude)
            setup_claude
            ;;
        all)
            setup_codex
            setup_claude
            ;;
        -h|--help)
            usage
            return
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac

    cat <<'EOF'

Local transcripts will be stored under .agent-sessions/ and will not be committed.
Codex users must review and trust the new hooks with /hooks on first use.
Claude Code users should restart Claude Code or run /reload-plugins.
EOF
}

main "$@"
