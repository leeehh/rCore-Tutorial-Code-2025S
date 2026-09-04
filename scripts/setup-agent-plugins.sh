#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPOSITORY_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd -P)
RCORE_MARKETPLACE_NAME="rcore-tutorial-2025s"
RCORE_PLUGIN_ID="rcore-session-archive@${RCORE_MARKETPLACE_NAME}"
CODEX_LANGFUSE_MARKETPLACE_NAME="codex-observability-plugin"
CODEX_LANGFUSE_MARKETPLACE_SOURCE="langfuse/codex-observability-plugin"
CODEX_LANGFUSE_PLUGIN_ID="tracing@${CODEX_LANGFUSE_MARKETPLACE_NAME}"
CLAUDE_LANGFUSE_MARKETPLACE_NAME="langfuse-observability"
CLAUDE_LANGFUSE_MARKETPLACE_SOURCE="langfuse/Claude-Observability-Plugin"
CLAUDE_LANGFUSE_PLUGIN_ID="langfuse-observability@${CLAUDE_LANGFUSE_MARKETPLACE_NAME}"
MARKETPLACE_SOURCE=""

usage() {
    cat <<'EOF'
Usage: ./scripts/setup-agent-plugins.sh [auto|codex|claude|all]

  auto    Install plugins for every supported agent found (default).
  codex   Install the Codex upload and local archive plugins only.
  claude  Install the Claude Code upload and local archive plugins only.
  all     Require and configure both Codex and Claude Code.

Plugins are disabled in the user configuration and enabled by this repository's
tracked project configuration. Private credential files are created in this
repository from tracked templates and are excluded from Git.
EOF
}

prepare_private_config() {
    local template_path="$1"
    local config_path="$2"
    local agent_name="$3"

    if [[ ! -e "${config_path}" ]]; then
        (umask 077; cp "${template_path}" "${config_path}")
        echo "Created ${agent_name} credential file: ${config_path}"
    else
        echo "Keeping existing ${agent_name} credential file: ${config_path}"
    fi
    chmod 600 "${config_path}"
}

require_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "error: Python 3 is required by the local session archive hook" >&2
        exit 1
    fi
    if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
        echo "error: Python 3.9 or newer is required" >&2
        exit 1
    fi
}

require_node_22() {
    if ! command -v node >/dev/null 2>&1; then
        echo "error: Node.js 22 or newer is required by the Langfuse Codex plugin" >&2
        return 1
    fi
    if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
        echo "error: Node.js 22 or newer is required by the Langfuse Codex plugin" >&2
        return 1
    fi
}

require_claude_langfuse_runtime() {
    if command -v uv >/dev/null 2>&1; then
        return
    fi
    if python3 -c '
import importlib.metadata
import re
import sys

if sys.version_info < (3, 10):
    raise SystemExit(1)
match = re.match(r"^(\d+)\.(\d+)", importlib.metadata.version("langfuse"))
raise SystemExit(
    0 if match and (int(match.group(1)), int(match.group(2))) >= (4, 7)
    and int(match.group(1)) < 5 else 1
)
' >/dev/null 2>&1; then
        return
    fi

    echo "error: the Langfuse Claude Code plugin requires uv, or Python 3.10+" >&2
    echo "       with langfuse>=4.7,<5 installed" >&2
    echo "       see https://docs.astral.sh/uv/getting-started/installation/" >&2
    return 1
}

resolve_marketplace_source() {
    if [[ -n "${RCORE_PLUGIN_MARKETPLACE_SOURCE:-}" ]]; then
        MARKETPLACE_SOURCE="${RCORE_PLUGIN_MARKETPLACE_SOURCE}"
        return
    fi

    MARKETPLACE_SOURCE=$(git -C "${REPOSITORY_ROOT}" remote get-url origin 2>/dev/null || true)
    if [[ -z "${MARKETPLACE_SOURCE}" ]]; then
        echo "error: cannot determine the Git origin for the rCore plugin marketplace" >&2
        echo "set RCORE_PLUGIN_MARKETPLACE_SOURCE to a Git URL or marketplace directory" >&2
        exit 1
    fi
}

codex_marketplace_exists() {
    local marketplace_name="$1"
    codex plugin marketplace list --json | python3 -c '
import json, sys
name = sys.argv[1]
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("name") == name for item in data.get("marketplaces", [])) else 1)
' "${marketplace_name}"
}

disable_codex_plugin_globally() {
    local plugin_id="$1"
    python3 - "${plugin_id}" <<'PY'
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
    local marketplace_name="$1"
    claude plugin marketplace list --json | python3 -c '
import json, sys
name = sys.argv[1]
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("name") == name for item in data) else 1)
' "${marketplace_name}"
}

setup_codex() {
    if ! command -v codex >/dev/null 2>&1; then
        echo "error: Codex CLI is not installed" >&2
        return 1
    fi
    require_node_22

    if codex_marketplace_exists "${CODEX_LANGFUSE_MARKETPLACE_NAME}"; then
        if ! codex plugin marketplace upgrade "${CODEX_LANGFUSE_MARKETPLACE_NAME}"; then
            echo "warning: could not update the Codex Langfuse marketplace; using its cache" >&2
        fi
    else
        codex plugin marketplace add "${CODEX_LANGFUSE_MARKETPLACE_SOURCE}"
    fi
    codex plugin add "${CODEX_LANGFUSE_PLUGIN_ID}"
    disable_codex_plugin_globally "${CODEX_LANGFUSE_PLUGIN_ID}"

    if codex_marketplace_exists "${RCORE_MARKETPLACE_NAME}"; then
        if ! codex plugin marketplace upgrade "${RCORE_MARKETPLACE_NAME}"; then
            echo "warning: could not update the rCore Codex marketplace; using its cache" >&2
        fi
    elif [[ -d "${MARKETPLACE_SOURCE}" ]]; then
        codex plugin marketplace add "${MARKETPLACE_SOURCE}"
    else
        codex plugin marketplace add "${MARKETPLACE_SOURCE}" --ref main
    fi
    codex plugin add "${RCORE_PLUGIN_ID}"
    disable_codex_plugin_globally "${RCORE_PLUGIN_ID}"
    prepare_private_config \
        "${REPOSITORY_ROOT}/.codex/langfuse.example.json" \
        "${REPOSITORY_ROOT}/.codex/langfuse.json" \
        "Codex"

    echo "Codex Langfuse upload and local archive plugins installed."
    echo "Both are disabled globally and enabled by this repository."
}

setup_claude() {
    if ! command -v claude >/dev/null 2>&1; then
        echo "error: Claude Code CLI is not installed" >&2
        return 1
    fi
    require_claude_langfuse_runtime

    if claude_marketplace_exists "${CLAUDE_LANGFUSE_MARKETPLACE_NAME}"; then
        if ! claude plugin marketplace update "${CLAUDE_LANGFUSE_MARKETPLACE_NAME}"; then
            echo "warning: could not update the Claude Langfuse marketplace; using its cache" >&2
        fi
    else
        claude plugin marketplace add --scope user "${CLAUDE_LANGFUSE_MARKETPLACE_SOURCE}"
    fi
    claude plugin install --scope user "${CLAUDE_LANGFUSE_PLUGIN_ID}"
    claude plugin disable --scope user "${CLAUDE_LANGFUSE_PLUGIN_ID}"

    if claude_marketplace_exists "${RCORE_MARKETPLACE_NAME}"; then
        if ! claude plugin marketplace update "${RCORE_MARKETPLACE_NAME}"; then
            echo "warning: could not update the rCore Claude marketplace; using its cache" >&2
        fi
    elif [[ -d "${MARKETPLACE_SOURCE}" ]]; then
        claude plugin marketplace add --scope user "${MARKETPLACE_SOURCE}"
    else
        claude plugin marketplace add --scope user "${MARKETPLACE_SOURCE}#main"
    fi
    claude plugin install --scope user "${RCORE_PLUGIN_ID}"
    claude plugin disable --scope user "${RCORE_PLUGIN_ID}"
    prepare_private_config \
        "${REPOSITORY_ROOT}/.claude/settings.local.example.json" \
        "${REPOSITORY_ROOT}/.claude/settings.local.json" \
        "Claude Code"

    echo "Claude Code Langfuse upload and local archive plugins installed."
    echo "Both are disabled globally and enabled by this repository."
}

main() {
    local target="${1:-auto}"
    local configured=0

    if [[ "${target}" == "-h" || "${target}" == "--help" ]]; then
        usage
        return
    fi

    require_python
    resolve_marketplace_source

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
        *)
            usage >&2
            exit 2
            ;;
    esac

    cat <<'EOF'

Local transcripts will be stored under .agent-sessions/ and will not be committed.
Replace the placeholders in the generated project-local credential file(s).
Codex users must trust this repository and review its hooks with /hooks on first use.
Claude Code users should restart Claude Code or run /reload-plugins.
EOF
}

main "$@"
