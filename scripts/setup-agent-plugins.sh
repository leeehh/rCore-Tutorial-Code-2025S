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
CREDENTIAL_FILE=""
ARCHIVE_MODE=""
CODEX_ARCHIVE_MODE=""
CLAUDE_ARCHIVE_MODE=""
CURSOR_ARCHIVE_MODE=""
SECTION_NUMBER=0
CURRENT_SECTION="启动检查"
CURRENT_STEP="读取命令参数"
CURRENT_COMMAND=""
WARNING_COUNT=0
COMPLETED_AGENTS=()

UI_RESET=""
UI_BOLD=""
UI_DIM=""
UI_BLUE=""
UI_GREEN=""
UI_YELLOW=""
UI_RED=""

init_output() {
    # Keep redirected output readable, and respect the standard NO_COLOR opt-out.
    if [[ -t 1 && -t 2 && "${TERM:-}" != "dumb" && -z "${NO_COLOR:-}" ]]; then
        UI_RESET=$'\033[0m'
        UI_BOLD=$'\033[1m'
        UI_DIM=$'\033[2m'
        UI_BLUE=$'\033[36m'
        UI_GREEN=$'\033[32m'
        UI_YELLOW=$'\033[33m'
        UI_RED=$'\033[31m'
    fi
}

log_info() {
    printf '  %s[信息]%s %s\n' "${UI_BLUE}" "${UI_RESET}" "$*"
}

log_success() {
    printf '  %s[成功]%s %s\n' "${UI_GREEN}" "${UI_RESET}" "$*"
}

log_warning() {
    WARNING_COUNT=$((WARNING_COUNT + 1))
    printf '  %s[警告]%s %s\n' "${UI_YELLOW}" "${UI_RESET}" "$*" >&2
}

log_error() {
    printf '  %s[失败]%s %s\n' "${UI_RED}" "${UI_RESET}" "$*" >&2
}

log_detail() {
    printf '         %s\n' "$*"
}

begin_section() {
    SECTION_NUMBER=$((SECTION_NUMBER + 1))
    CURRENT_SECTION="$1"
    printf '\n%s[%s] %s%s\n' "${UI_BOLD}${UI_BLUE}" "${SECTION_NUMBER}" "$1" "${UI_RESET}"
}

begin_step() {
    CURRENT_STEP="$1"
    CURRENT_COMMAND=""
    printf '  %s[执行]%s %s\n' "${UI_BLUE}" "${UI_RESET}" "${CURRENT_STEP}"
}

complete_step() {
    log_success "${CURRENT_STEP}"
}

indent_output() {
    local line
    while IFS= read -r line || [[ -n "${line}" ]]; do
        printf '      %s│%s %s\n' "${UI_DIM}" "${UI_RESET}" "${line}"
    done
}

run_command() {
    local description="$1"
    local status
    shift
    begin_step "${description}"
    printf -v CURRENT_COMMAND '%q ' "$@"
    printf '      %s$ %s%s\n' "${UI_DIM}" "${CURRENT_COMMAND% }" "${UI_RESET}"

    # Only wrap external commands here. Wrapping a shell function in an `if`
    # would disable errexit inside that function and could hide installation errors.
    if "$@" 2>&1 | indent_output; then
        complete_step
    else
        status=$?
        return "${status}"
    fi
}

report_exit() {
    local status="$1"
    if [[ "${status}" -eq 0 ]]; then
        return
    fi
    printf '\n%s配置未完成%s\n' "${UI_BOLD}${UI_RED}" "${UI_RESET}" >&2
    log_error "${CURRENT_SECTION} → ${CURRENT_STEP}（退出码：${status}）"
    if [[ -n "${CURRENT_COMMAND}" ]]; then
        log_detail "失败命令：${CURRENT_COMMAND% }" >&2
    fi
    if [[ "${#COMPLETED_AGENTS[@]}" -gt 0 ]]; then
        log_detail "已完成：${COMPLETED_AGENTS[*]}" >&2
    fi
    log_detail "请查看上方错误信息，处理后重新运行配置脚本。" >&2
}

print_summary() {
    printf '\n%s配置结果%s\n' "${UI_BOLD}" "${UI_RESET}"
    if [[ "${WARNING_COUNT}" -gt 0 ]]; then
        printf '  %s[注意]%s 安装步骤已完成，有 %s 条警告需要查看。\n' \
            "${UI_YELLOW}" "${UI_RESET}" "${WARNING_COUNT}"
    else
        log_success "配置完成"
    fi
    log_detail "已配置 Agent：${COMPLETED_AGENTS[*]}"
    log_detail "生效范围：本仓库（全局关闭）"
    log_detail "本地留档：.agent-sessions/<agent>/<session-id>.md（不生成 JSON 备份）"
    if [[ -n "${CODEX_ARCHIVE_MODE}" ]]; then
        log_detail "Codex 留档等级：${CODEX_ARCHIVE_MODE}（.codex/langfuse.json → mode）"
    fi
    if [[ -n "${CLAUDE_ARCHIVE_MODE}" ]]; then
        log_detail "Claude Code 留档等级：${CLAUDE_ARCHIVE_MODE}（.claude/settings.local.json → env.RCORE_SESSION_ARCHIVE_MODE）"
    fi
    if [[ -n "${CURSOR_ARCHIVE_MODE}" ]]; then
        log_detail "Cursor 留档等级：${CURSOR_ARCHIVE_MODE}（.cursor/langfuse.json → mode）"
    fi
    log_detail "个人凭据：仅保存在项目配置目录，已忽略 Git 提交"

    printf '\n%s接下来%s\n' "${UI_BOLD}" "${UI_RESET}"
    local agent_name
    for agent_name in "${COMPLETED_AGENTS[@]}"; do
        case "${agent_name}" in
            Codex)
                log_info "Codex：从本仓库打开新会话；首次使用请通过 /hooks 审阅并信任 hooks。"
                ;;
            "Claude Code")
                log_info "Claude Code：从本仓库重新启动，或在已有会话执行 /reload-plugins。"
                ;;
            Cursor)
                log_info "Cursor：打开并信任本仓库文件夹，再新建 Agent 会话；在 Output → Hooks 查看异常。"
                ;;
        esac
    done
}

usage() {
    cat <<'EOF'
用法：./scripts/setup-agent-plugins.sh [auto|codex|claude|cursor|all] [credential.json]

  auto    配置本机已安装的 Agent（默认）
  codex   仅配置 Codex 的上传和本地归档插件
  claude  仅配置 Claude Code 的上传和本地归档插件
  cursor  仅配置 Cursor 项目 hooks；无需 Cursor 命令行、Node.js 或 uv
  all     配置三者；Codex / Claude Code CLI 缺失时会报错

auto 通过 CLI 检测 Agent；只安装 Cursor 图形界面时，请显式使用 cursor。

插件全局关闭，仅在本仓库启用。请先注册并下载个人凭据 JSON：
  https://lihh18-nuc.tail6722a8.ts.net:10000/register
然后将 JSON 路径作为第二个参数传入。凭据只保存到项目目录，不提交 Git。

输出标记：[执行] 正在处理  [成功] 已完成  [警告] 需要留意  [失败] 已停止
终端中自动使用颜色；重定向输出或设置 NO_COLOR=1 时使用纯文本。
EOF
}

prepare_private_config() {
    local template_path="$1"
    local config_path="$2"
    local agent_name="$3"

    if [[ -n "${CREDENTIAL_FILE}" ]]; then
        python3 - "${CREDENTIAL_FILE}" "${config_path}" "${agent_name}" <<'PY'
import json
import os
import re
import sys
import tempfile
from pathlib import Path

credential_path = Path(sys.argv[1]).expanduser().resolve()
config_path = Path(sys.argv[2])
agent_name = sys.argv[3]

try:
    credential = json.loads(credential_path.read_text(encoding="utf-8"))
except FileNotFoundError:
    raise SystemExit(f"error: credential JSON not found: {credential_path}")
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"error: cannot read credential JSON: {error}")

student_id = credential.get("student_id")
public_key = credential.get("public_key")
secret_key = credential.get("secret_key")
base_url = credential.get("base_url")
if not isinstance(student_id, str) or not re.fullmatch(r"[0-9]{6,20}", student_id):
    raise SystemExit("error: credential JSON contains an invalid student_id")
if public_key != f"pk-lf-stu-{student_id}":
    raise SystemExit("error: credential JSON public_key does not match student_id")
if not isinstance(secret_key, str) or not secret_key.startswith("sk-lf-token-") or len(secret_key) < 32:
    raise SystemExit("error: credential JSON contains an invalid secret_key")
if not isinstance(base_url, str) or not re.fullmatch(r"https://[^/?#:]+:8443", base_url):
    raise SystemExit("error: credential JSON contains an invalid gateway base_url")

output = {}
if config_path.is_file():
    try:
        existing = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"error: cannot preserve existing {agent_name} config: {error}")
    if not isinstance(existing, dict):
        raise SystemExit(f"error: existing {agent_name} config must be a JSON object")
    output.update(existing)

if agent_name in {"Codex", "Cursor"}:
    output.update({
        "enabled": True,
        "public_key": public_key,
        "secret_key": secret_key,
        "base_url": base_url,
        "tags": ["os-lab", "rcore"],
    })
    output.pop("user_id", None)
elif agent_name == "Claude Code":
    output.setdefault("$schema", "https://json.schemastore.org/claude-code-settings.json")
    environment = output.setdefault("env", {})
    if not isinstance(environment, dict):
        raise SystemExit("error: existing Claude Code env config must be a JSON object")
    environment.update({
        "LANGFUSE_PUBLIC_KEY": public_key,
        "LANGFUSE_SECRET_KEY": secret_key,
        "LANGFUSE_BASE_URL": base_url,
        "CC_LANGFUSE_CAPTURE_IMAGES": "false",
    })
    environment.pop("LANGFUSE_USER_ID", None)
else:
    raise SystemExit(f"error: unsupported agent: {agent_name}")

config_path.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary_name = tempfile.mkstemp(
    dir=config_path.parent, prefix=f".{config_path.name}.", suffix=".tmp"
)
temporary_path = Path(temporary_name)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
        json.dump(output, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
        destination.flush()
        os.fsync(destination.fileno())
    temporary_path.chmod(0o600)
    os.replace(temporary_path, config_path)
except BaseException:
    try:
        temporary_path.unlink()
    except OSError:
        pass
    raise
PY
        log_info "已写入 ${agent_name} 个人凭据：${config_path}"
    elif [[ ! -e "${config_path}" || "${agent_name}" == "Codex" || "${agent_name}" == "Cursor" ]]; then
        local config_status
        # Older Claude-only setups may have created a mode-only Codex config.
        # Fill missing fields from the template while preserving existing values.
        config_status=$(python3 - "${template_path}" "${config_path}" "${agent_name}" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

template_path, config_path = map(Path, sys.argv[1:3])
try:
    template = json.loads(template_path.read_text(encoding="utf-8"))
    existing = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    raise SystemExit(f"error: cannot prepare project configuration: {error}")
if not isinstance(existing, dict):
    raise SystemExit("error: project configuration must be a JSON object")
output = {**template, **existing}
if output != existing or not config_path.exists():
    config_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=config_path.parent, suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            json.dump(output, destination, ensure_ascii=False, indent=2)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, config_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
needs_credentials = sys.argv[3] not in {"Codex", "Cursor"} or not output.get("base_url") or any(
    not output.get(key) or output[key] == template[key]
    for key in ("public_key", "secret_key")
)
print("placeholder" if needs_credentials else "preserved")
PY
        )
        if [[ "${config_status}" == "placeholder" ]]; then
            log_warning "未提供 ${agent_name} 个人凭据，当前只有占位配置，尚不能上传会话。"
            log_detail "配置文件：${config_path}" >&2
            log_detail "请注册并下载凭据 JSON，再将其路径作为第二个参数重新运行脚本。" >&2
        else
            log_info "保留 ${agent_name} 现有凭据：${config_path}"
        fi
    else
        log_info "保留 ${agent_name} 现有凭据：${config_path}"
    fi
    chmod 600 "${config_path}"
}

require_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        log_error "未找到 Python 3；本地归档插件需要 Python 3.9 或更高版本。"
        exit 1
    fi
    if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
        log_error "Python 版本过低；请安装 Python 3.9 或更高版本。"
        exit 1
    fi
}

read_archive_config() {
    local agent_name="${1:-codex}"
    # Read before credential setup fills template defaults. Claude migrates the
    # previously shared Codex mode only until its own project mode is saved.
    ARCHIVE_MODE=$(python3 - "${REPOSITORY_ROOT}" "${agent_name}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
agent_name = sys.argv[2]
allowed_modes = {"messages", "tool-calls", "full"}
mode = "messages"
paths = [".codex/langfuse.json", ".agents/session-archive.json"]
if agent_name == "claude":
    paths.insert(0, ".claude/settings.local.json")
elif agent_name == "cursor":
    paths = [".cursor/langfuse.json"]
elif agent_name != "codex":
    raise SystemExit(f"error: unsupported agent: {agent_name}")
for relative_path in paths:
    config_path = root / relative_path
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        continue
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"error: cannot read archive configuration {config_path}: {error}")
    if not isinstance(config, dict):
        raise SystemExit(f"error: archive configuration must be a JSON object: {config_path}")
    mode_key = "mode"
    if relative_path == ".claude/settings.local.json":
        config = config.get("env", {})
        if not isinstance(config, dict):
            raise SystemExit(f"error: Claude Code env config must be a JSON object: {config_path}")
        mode_key = "RCORE_SESSION_ARCHIVE_MODE"
    if mode_key not in config:
        continue
    mode = config[mode_key]
    if not isinstance(mode, str) or mode not in allowed_modes:
        choices = ", ".join(sorted(allowed_modes))
        raise SystemExit(f"error: archive mode must be one of {choices}: {config_path}")
    break
print(mode)
PY
    )
    log_info "${agent_name} 当前本地留档等级：${ARCHIVE_MODE}"
}

prepare_archive_config() {
    local agent_name="${1:-codex}"
    local config_path="${REPOSITORY_ROOT}/.codex/langfuse.json"
    case "${agent_name}" in
        codex) ;;
        claude) config_path="${REPOSITORY_ROOT}/.claude/settings.local.json" ;;
        cursor) config_path="${REPOSITORY_ROOT}/.cursor/langfuse.json" ;;
        *) log_error "不支持的配置目标：${agent_name}"; return 1 ;;
    esac
    local legacy_path="${REPOSITORY_ROOT}/.agents/session-archive.json"
    # Cursor has never used the retired shared policy. Leave it for Codex/Claude migration.
    if [[ "${agent_name}" == "cursor" ]]; then
        legacy_path=""
    fi
    local legacy_existed=0
    if [[ -e "${legacy_path}" || -L "${legacy_path}" ]]; then
        legacy_existed=1
    fi
    python3 - "${config_path}" "${ARCHIVE_MODE}" "${legacy_path}" "${agent_name}" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

config_path = Path(sys.argv[1])
try:
    config = json.loads(config_path.read_text(encoding="utf-8"))
except FileNotFoundError:
    config = {}
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    raise SystemExit(f"error: cannot preserve Langfuse configuration: {error}")
if not isinstance(config, dict):
    raise SystemExit("error: Langfuse configuration must be a JSON object")
if sys.argv[4] == "claude":
    environment = config.setdefault("env", {})
    if not isinstance(environment, dict):
        raise SystemExit("error: Claude Code env config must be a JSON object")
    environment["RCORE_SESSION_ARCHIVE_MODE"] = sys.argv[2]
else:
    config["mode"] = sys.argv[2]
config_path.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary_name = tempfile.mkstemp(
    dir=config_path.parent, prefix=f".{config_path.name}.", suffix=".tmp"
)
temporary_path = Path(temporary_name)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
        json.dump(config, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
        destination.flush()
        os.fsync(destination.fileno())
    temporary_path.chmod(0o600)
    os.replace(temporary_path, config_path)
except BaseException:
    temporary_path.unlink(missing_ok=True)
    raise

# Only remove the superseded file after the new mode and credentials were
# atomically saved. The .agents/plugins marketplace remains in place.
legacy_path = Path(sys.argv[3]) if sys.argv[3] else None
try:
    if legacy_path is not None and (legacy_path.exists() or legacy_path.is_symlink()):
        legacy_path.unlink()
except OSError as error:
    raise SystemExit(f"error: mode was saved, but cannot remove legacy configuration {legacy_path}: {error}")
PY
    if [[ "${agent_name}" == "claude" ]]; then
        CLAUDE_ARCHIVE_MODE="${ARCHIVE_MODE}"
    elif [[ "${agent_name}" == "cursor" ]]; then
        CURSOR_ARCHIVE_MODE="${ARCHIVE_MODE}"
    else
        CODEX_ARCHIVE_MODE="${ARCHIVE_MODE}"
    fi
    log_info "本地留档等级已保存到：${config_path}"
    if [[ "${legacy_existed}" -eq 1 ]]; then
        log_info "旧归档配置已迁移并删除：${legacy_path}"
    fi
}

require_node_22() {
    if ! command -v node >/dev/null 2>&1; then
        log_error "未找到 Node.js；Codex 的 Langfuse 插件需要 Node.js 22 或更高版本。"
        return 1
    fi
    if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
        log_error "Node.js 版本过低；Codex 的 Langfuse 插件需要 Node.js 22 或更高版本。"
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

    log_error "Claude Code 的 Langfuse 插件缺少运行环境。"
    log_detail "请安装 uv；或使用 Python 3.10+ 并安装 langfuse>=4.7,<5。" >&2
    log_detail "uv 安装说明：https://docs.astral.sh/uv/getting-started/installation/" >&2
    return 1
}

resolve_marketplace_source() {
    if [[ -n "${RCORE_PLUGIN_MARKETPLACE_SOURCE:-}" ]]; then
        MARKETPLACE_SOURCE="${RCORE_PLUGIN_MARKETPLACE_SOURCE}"
        return
    fi

    # Install the archive plugin from the checkout whose setup script is being
    # run.  This avoids a stale marketplace clone serving an older plugin after
    # students update or switch branches in the experiment repository.
    MARKETPLACE_SOURCE="${REPOSITORY_ROOT}"
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

codex_plugin_is_installed() {
    local plugin_id="$1"
    codex plugin list --json | python3 -c '
import json, sys
plugin_id = sys.argv[1]
data = json.load(sys.stdin)
raise SystemExit(
    0 if any(item.get("pluginId") == plugin_id for item in data.get("installed", [])) else 1
)
' "${plugin_id}"
}

refresh_codex_rcore_plugin() {
    # `marketplace upgrade` cannot repair a marketplace that was previously
    # registered against a copied local cache. Remove both layers so Codex
    # installs the plugin advertised by MARKETPLACE_SOURCE on every setup run.
    if codex_plugin_is_installed "${RCORE_PLUGIN_ID}"; then
        run_command "移除 Codex 旧版归档插件缓存" \
            codex plugin remove "${RCORE_PLUGIN_ID}"
    fi
    if codex_marketplace_exists "${RCORE_MARKETPLACE_NAME}"; then
        run_command "移除 Codex 旧归档插件源" \
            codex plugin marketplace remove "${RCORE_MARKETPLACE_NAME}"
    fi

    if [[ -d "${MARKETPLACE_SOURCE}" ]]; then
        run_command "注册 Codex 归档插件源" \
            codex plugin marketplace add "${MARKETPLACE_SOURCE}"
    else
        run_command "注册 Codex 归档插件源" \
            codex plugin marketplace add "${MARKETPLACE_SOURCE}" --ref main
    fi
    run_command "安装 Codex 本地归档插件" \
        codex plugin add "${RCORE_PLUGIN_ID}"
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

claude_plugin_is_installed() {
    local plugin_id="$1"
    claude plugin list --json | python3 -c '
import json, sys
plugin_id = sys.argv[1]
data = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("id") == plugin_id for item in data) else 1)
' "${plugin_id}"
}

claude_project_plugin_is_enabled() {
    local plugin_id="$1"
    python3 - "${REPOSITORY_ROOT}/.claude/settings.json" "${plugin_id}" <<'PY'
import json
import sys
from pathlib import Path

settings_path = Path(sys.argv[1])
plugin_id = sys.argv[2]
try:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
enabled_plugins = settings.get("enabledPlugins")
raise SystemExit(
    0 if isinstance(enabled_plugins, dict) and enabled_plugins.get(plugin_id) is True else 1
)
PY
}

enable_claude_plugin_for_project() {
    local plugin_id="$1"
    if ! claude_project_plugin_is_enabled "${plugin_id}"; then
        run_command "在本仓库启用 Claude Code 插件：${plugin_id}" \
            claude plugin enable --scope project "${plugin_id}"
    else
        log_info "本仓库已启用 Claude Code 插件：${plugin_id}"
    fi
}

refresh_claude_rcore_plugin() {
    # Claude Code also caches installed plugin versions. Reinstalling after the
    # marketplace is rebound ensures hooks come from the current checkout.
    if claude_plugin_is_installed "${RCORE_PLUGIN_ID}"; then
        run_command "移除 Claude Code 旧版归档插件缓存" \
            claude plugin uninstall --scope user "${RCORE_PLUGIN_ID}"
    fi
    if claude_marketplace_exists "${RCORE_MARKETPLACE_NAME}"; then
        run_command "移除 Claude Code 旧归档插件源" \
            claude plugin marketplace remove "${RCORE_MARKETPLACE_NAME}"
    fi

    if [[ -d "${MARKETPLACE_SOURCE}" ]]; then
        run_command "注册 Claude Code 归档插件源" \
            claude plugin marketplace add --scope user "${MARKETPLACE_SOURCE}"
    else
        run_command "注册 Claude Code 归档插件源" \
            claude plugin marketplace add --scope user "${MARKETPLACE_SOURCE}#main"
    fi
    run_command "安装 Claude Code 本地归档插件" \
        claude plugin install --scope user "${RCORE_PLUGIN_ID}"
}

setup_codex() {
    begin_section "Codex"
    begin_step "读取 Codex 本地归档等级"
    read_archive_config codex
    complete_step
    begin_step "检查 Codex 运行环境"
    if ! command -v codex >/dev/null 2>&1; then
        log_error "未找到 Codex CLI，请先安装后重新运行脚本。"
        return 1
    fi
    require_node_22
    complete_step

    if codex_marketplace_exists "${CODEX_LANGFUSE_MARKETPLACE_NAME}"; then
        if ! run_command "更新 Codex 的 Langfuse 插件源" \
            codex plugin marketplace upgrade "${CODEX_LANGFUSE_MARKETPLACE_NAME}"; then
            log_warning "Langfuse 插件源更新失败，将继续使用已有缓存；详情见上方命令输出。"
        fi
    else
        run_command "注册 Codex 的 Langfuse 插件源" \
            codex plugin marketplace add "${CODEX_LANGFUSE_MARKETPLACE_SOURCE}"
    fi
    run_command "安装 Codex 的 Langfuse 上传插件" \
        codex plugin add "${CODEX_LANGFUSE_PLUGIN_ID}"
    begin_step "在全局配置中关闭 Codex 上传插件"
    disable_codex_plugin_globally "${CODEX_LANGFUSE_PLUGIN_ID}"
    complete_step

    refresh_codex_rcore_plugin
    begin_step "在全局配置中关闭 Codex 归档插件"
    disable_codex_plugin_globally "${RCORE_PLUGIN_ID}"
    complete_step
    begin_step "准备 Codex 项目凭据配置"
    prepare_private_config \
        "${REPOSITORY_ROOT}/.codex/langfuse.example.json" \
        "${REPOSITORY_ROOT}/.codex/langfuse.json" \
        "Codex"
    prepare_archive_config codex
    complete_step

    COMPLETED_AGENTS+=("Codex")
    log_success "Codex 安装步骤完成"
}

setup_claude() {
    begin_section "Claude Code"
    begin_step "读取 Claude Code 本地归档等级"
    read_archive_config claude
    complete_step
    begin_step "检查 Claude Code 运行环境"
    if ! command -v claude >/dev/null 2>&1; then
        log_error "未找到 Claude Code CLI，请先安装后重新运行脚本。"
        return 1
    fi
    require_claude_langfuse_runtime
    complete_step

    if claude_marketplace_exists "${CLAUDE_LANGFUSE_MARKETPLACE_NAME}"; then
        if ! run_command "更新 Claude Code 的 Langfuse 插件源" \
            claude plugin marketplace update "${CLAUDE_LANGFUSE_MARKETPLACE_NAME}"; then
            log_warning "Langfuse 插件源更新失败，将继续使用已有缓存；详情见上方命令输出。"
        fi
    else
        run_command "注册 Claude Code 的 Langfuse 插件源" \
            claude plugin marketplace add --scope user "${CLAUDE_LANGFUSE_MARKETPLACE_SOURCE}"
    fi
    run_command "安装 Claude Code 的 Langfuse 上传插件" \
        claude plugin install --scope user "${CLAUDE_LANGFUSE_PLUGIN_ID}"
    run_command "在全局配置中关闭 Claude Code 上传插件" \
        claude plugin disable --scope user "${CLAUDE_LANGFUSE_PLUGIN_ID}"
    enable_claude_plugin_for_project "${CLAUDE_LANGFUSE_PLUGIN_ID}"

    refresh_claude_rcore_plugin
    run_command "在全局配置中关闭 Claude Code 归档插件" \
        claude plugin disable --scope user "${RCORE_PLUGIN_ID}"
    enable_claude_plugin_for_project "${RCORE_PLUGIN_ID}"
    begin_step "准备 Claude Code 项目凭据配置"
    prepare_private_config \
        "${REPOSITORY_ROOT}/.claude/settings.local.example.json" \
        "${REPOSITORY_ROOT}/.claude/settings.local.json" \
        "Claude Code"
    prepare_archive_config claude
    complete_step

    COMPLETED_AGENTS+=("Claude Code")
    log_success "Claude Code 安装步骤完成"
}

setup_cursor() {
    begin_section "Cursor"
    begin_step "检查 Cursor 项目配置目录"
    local cursor_path
    for cursor_path in ".cursor" ".cursor/langfuse.json" ".cursor/hooks.json" ".cursor/rcore-hooks"; do
        if [[ -L "${REPOSITORY_ROOT}/${cursor_path}" ]]; then
            log_error "${cursor_path} 是符号链接；为避免写入项目外部，请使用项目内的普通目录或文件。"
            return 1
        fi
    done
    complete_step
    begin_step "读取 Cursor 本地归档等级"
    read_archive_config cursor
    complete_step
    log_info "使用 Cursor 原生项目 hooks；不安装全局 hooks，不需要启动 Cursor 进程。"
    begin_step "准备 Cursor 项目凭据配置"
    prepare_private_config \
        "${REPOSITORY_ROOT}/.cursor/langfuse.example.json" \
        "${REPOSITORY_ROOT}/.cursor/langfuse.json" \
        "Cursor"
    prepare_archive_config cursor
    complete_step
    run_command "配置 Cursor 项目上传与归档 hooks（保留其他 hooks）" \
        python3 "${SCRIPT_DIR}/../plugins/rcore-session-archive/scripts/cursor_hook.py" \
        --install "${REPOSITORY_ROOT}"
    COMPLETED_AGENTS+=("Cursor")
    log_success "Cursor 配置完成"
}

main() {
    local target="${1:-auto}"
    local configured=0

    init_output
    if [[ "${target}" == "-h" || "${target}" == "--help" ]]; then
        usage
        return
    fi

    trap 'report_exit "$?"' EXIT
    printf '\n%srCore · Agent 环境准备%s\n' "${UI_BOLD}" "${UI_RESET}"
    log_detail "项目目录：${REPOSITORY_ROOT}"
    log_detail "配置目标：${target}"
    case "${target}" in
        auto|codex|claude|cursor|all) ;;
        *)
            log_error "不支持的配置目标：${target}"
            usage >&2
            exit 2
            ;;
    esac

    begin_section "基础环境与项目配置"
    begin_step "检查个人凭据路径"
    CREDENTIAL_FILE="${2:-${RCORE_AGENT_CREDENTIAL_FILE:-}}"
    if [[ -n "${CREDENTIAL_FILE}" && ! -f "${CREDENTIAL_FILE}" ]]; then
        log_error "找不到个人凭据 JSON：${CREDENTIAL_FILE}"
        exit 1
    fi
    if [[ -z "${CREDENTIAL_FILE}" ]]; then
        log_info "未传入新的凭据 JSON，将使用项目配置；缺少配置时会提示补充凭据。"
    fi
    complete_step

    begin_step "检查 Python 运行环境"
    require_python
    complete_step
    resolve_marketplace_source

    case "${target}" in
        auto)
            if command -v codex >/dev/null 2>&1; then
                setup_codex
                configured=1
            else
                log_info "跳过 Codex：未检测到 CLI（auto 模式）。"
            fi
            if command -v claude >/dev/null 2>&1; then
                setup_claude
                configured=1
            else
                log_info "跳过 Claude Code：未检测到 CLI（auto 模式）。"
            fi
            if command -v cursor >/dev/null 2>&1 || command -v cursor-agent >/dev/null 2>&1; then
                setup_cursor
                configured=1
            else
                log_info "跳过 Cursor：未检测到 CLI；仅安装图形界面时请使用 cursor 配置目标。"
            fi
            if [[ "${configured}" -eq 0 ]]; then
                CURRENT_STEP="检测可配置的 Agent"
                log_error "未找到 Agent CLI；请先安装 Agent。Cursor 图形界面用户可改用 cursor 配置目标。"
                exit 1
            fi
            ;;
        codex)
            setup_codex
            ;;
        claude)
            setup_claude
            ;;
        cursor)
            setup_cursor
            ;;
        all)
            setup_codex
            setup_claude
            setup_cursor
            ;;
    esac

    print_summary
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
