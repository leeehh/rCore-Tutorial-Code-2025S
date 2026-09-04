# rCore-Tutorial-Code-2025S

### Code
- [Soure Code of labs for 2025S](https://github.com/LearningOS/rCore-Tutorial-Code-2025S)
### Documents

- Concise Manual: [rCore-Tutorial-Guide-2025S](https://LearningOS.github.io/rCore-Tutorial-Guide-2025S/)

- Detail Book [rCore-Tutorial-Book-v3](https://rcore-os.github.io/rCore-Tutorial-Book-v3/)


### OS API docs of rCore Tutorial Code 2025S
- [OS API docs of ch1](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch1/os/index.html)
  AND [OS API docs of ch2](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch2/os/index.html)
- [OS API docs of ch3](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch3/os/index.html)
  AND [OS API docs of ch4](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch4/os/index.html)
- [OS API docs of ch5](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch5/os/index.html)
  AND [OS API docs of ch6](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch6/os/index.html)
- [OS API docs of ch7](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch7/os/index.html)
  AND [OS API docs of ch8](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch8/os/index.html)
- [OS API docs of ch9](https://learningos.github.io/rCore-Tutorial-Code-2025S/ch9/os/index.html)

### Related Resources
- [Learning Resource](https://github.com/LearningOS/rust-based-os-comp2022/blob/main/relatedinfo.md)


### Build & Run

```bash
# setup build&run environment first
$ git clone https://github.com/leeehh/rCore-Tutorial-Code-2025S.git
$ cd rCore-Tutorial-Code-2025S
$ git clone https://github.com/LearningOS/rCore-Tutorial-Test-2025S.git user
$ git checkout ch$ID
$ cd os
# run OS in ch$ID
$ make run
```
Notice: $ID is from [1-9]

### Code Agent 会话上传与本地留档

本仓库提供环境准备脚本，可为 Codex、Claude Code 安装 Langfuse 会话上传插件和
rCore 本地留档插件。插件在用户全局配置中保持关闭，只由本仓库中的项目配置启用，
因此只有从本仓库目录（或其子目录）启动的 Agent 才会上传和保存会话。

#### 1. 前置条件

- 已安装并能够正常运行 Codex CLI 或 Claude Code。
- 已安装 Git 和 Python 3.9 或更高版本。
- 使用 Codex 时需要 Node.js 22 或更高版本。
- 使用 Claude Code 时需要 `uv`；或者 Python 3.10 及
  `langfuse>=4.7,<5`。

#### 2. 注册并下载个人凭据

打开[学生注册页面](https://lihh18-nuc.tail6722a8.ts.net:10000/register)，填写真实
姓名和学号并下载 `rcore-agent-token-<学号>.json`。每个学号只能注册一次。

凭据 JSON 中的 token 对应学生身份，服务器会根据 token 确定上传者，不需要也不允许
自行填写 `user_id`。不要将该文件发给他人或提交到 Git；如果丢失凭据或学号已被占用，
请联系助教撤销后重新注册。

#### 3. 安装插件并写入项目配置

请先停留在 `main` 分支并拉取最新代码，然后把下载的凭据路径传给准备脚本：

```bash
git switch main
git pull --ff-only

# 自动配置本机已经安装的 Codex 和/或 Claude Code（推荐）
./scripts/setup-agent-plugins.sh auto /path/to/rcore-agent-token-<学号>.json
```

也可以只配置指定 Agent：

```bash
# 仅 Codex
./scripts/setup-agent-plugins.sh codex /path/to/rcore-agent-token-<学号>.json

# 仅 Claude Code
./scripts/setup-agent-plugins.sh claude /path/to/rcore-agent-token-<学号>.json

# 同时要求配置两者；缺少任一 Agent 时脚本会报错
./scripts/setup-agent-plugins.sh all /path/to/rcore-agent-token-<学号>.json
```

脚本会安装或更新以下两个插件：

- Langfuse 官方插件：把本仓库内的 Agent 会话上传到课程服务器。
- `rcore-session-archive`：把会话保存到本仓库的 `.agent-sessions/`。

脚本还会生成下列本地配置：

| 文件 | 用途 | 是否提交 Git |
| --- | --- | --- |
| `.codex/config.toml` | 在本仓库启用 Codex hooks 和两个插件 | 是 |
| `.codex/langfuse.json` | Codex 的个人 Langfuse 凭据 | 否 |
| `.claude/settings.json` | 在本仓库启用 Claude Code 的两个插件 | 是 |
| `.claude/settings.local.json` | Claude Code 的个人 Langfuse 凭据 | 否 |
| `.agents/session-archive.json` | 选择本地留档等级 | 否 |
| `.agent-sessions/` | 实际会话留档目录 | 否 |

凭据只写入当前项目目录，不会写入用户主目录。上述个人配置、下载的 token JSON 和
会话留档均已加入 `.gitignore`，不要使用 `git add -f` 强制提交。

#### 4. 首次启用与检查

安装完成后必须从本仓库目录启动一个新会话；已经运行的 Agent 不会自动加载刚安装或
刚更新的插件。

Codex：

```bash
cd /path/to/rCore-Tutorial-Code-2025S
codex
```

在 Codex 中使用 `/plugins` 检查两个插件是否启用，并使用 `/hooks` 审阅、信任
Langfuse 和 archive hooks。脚本不会绕过 hook 信任确认。

Claude Code：

```bash
cd /path/to/rCore-Tutorial-Code-2025S
claude
```

若安装时 Claude Code 已经在运行，请执行 `/reload-plugins`，或者退出后重新启动。
Claude Code 会直接读取 `.claude/settings.local.json`，无需运行
`/plugin configure`。

完成一次对话后，可检查本地是否生成了留档：

```bash
find .agent-sessions -type f -name '*.jsonl'
```

切换到 `ch1` 至 `ch8` 等实验分支后仍使用同一套安装结果；请始终从该仓库目录启动
Agent。在其他目录启动时，项目配置不会生效，也不会上传或本地留档。

#### 5. 配置本地留档等级

准备脚本默认创建以下配置：

```json
{
  "mode": "messages"
}
```

编辑 `.agents/session-archive.json` 中的 `mode` 可选择留档内容：

| `mode` | 保存内容 |
| --- | --- |
| `messages` | 只保存学生输入和每轮 Agent 最终回答；默认值。 |
| `tool-calls` | 在 `messages` 基础上增加工具名称、调用 ID 和命令/工具输入，不保存工具输出。 |
| `full` | 保存 Agent 的完整原始 transcript，包括中间消息、推理记录、工具调用和工具输出。 |

配置缺失、JSON 格式错误或 `mode` 不受支持时，插件会回退到 `messages`。修改等级只会
影响之后的 hook 刷新，不会重新处理已经结束的旧会话。即使使用 `messages`，输入和
回答中也可能包含源码或隐私信息，因此不要分享 `.agent-sessions/`。
