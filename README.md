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
- `rcore-session-archive`：把会话以 Markdown 保存到本仓库的 `.agent-sessions/`。

脚本还会生成下列本地配置：

| 文件 | 用途 | 是否提交 Git |
| --- | --- | --- |
| `.codex/config.toml` | 在本仓库启用 Codex hooks 和两个插件 | 是 |
| `.codex/langfuse.json` | Codex 的个人 Langfuse 凭据，以及两个 Agent 共用的本地留档等级 `mode` | 否 |
| `.claude/settings.json` | 在本仓库启用 Claude Code 的两个插件 | 是 |
| `.claude/settings.local.json` | Claude Code 的个人 Langfuse 凭据 | 否 |
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
find .agent-sessions -type f -name '*.md'
```

每个会话保存为一个 Markdown 文件，可直接使用 VS Code 的 Markdown 预览阅读：

```text
.agent-sessions/codex/<session-id>.md
.agent-sessions/claude-code/<session-id>.md
```

文件按轮次展示用户输入和 Agent 回答，保留消息中的代码块、列表与表格；工具命令使用
代码块展示，参数按键值展示。较长的中间输出和工具结果放入可展开的折叠区，文本不会截断。
所有等级都只生成 Markdown，不另存原始 JSON/JSONL 备份，也不复制图片等二进制附件，
附件仅记录描述或引用。Agent 自己维护的源会话文件不受影响。

切换到 `ch1` 至 `ch8` 等实验分支后仍使用同一套安装结果；请始终从该仓库目录启动
Agent。在其他目录启动时，项目配置不会生效，也不会上传或本地留档。

#### 5. 配置本地留档等级

编辑 `.codex/langfuse.json` 的顶层 `mode` 字段，即可选择本地留档内容。
它和 `enabled`、`public_key`、`secret_key` 等 Langfuse 配置放在同一个 JSON 对象中，
准备脚本默认设置为 `messages`：

```json
{
  "mode": "messages"
}
```

上面只展示归档字段；编辑已有文件时保留其他字段。完整示例见
[`.codex/langfuse.example.json`](.codex/langfuse.example.json)。
Codex 和 Claude Code 的本地归档都读取这里的 `mode`；仅安装 Claude Code 时，
脚本也会生成这份配置，其上传凭据仍保存在 `.claude/settings.local.json`。

| `mode` | 保存内容 |
| --- | --- |
| `messages` | 只保存学生输入和每轮 Agent 最终回答；默认值。 |
| `tool-calls` | 在 `messages` 基础上增加工具名称、调用 ID 和命令/工具输入，不保存工具输出。 |
| `full` | 增加中间输出、可读的推理摘要和完整工具输出，较长内容折叠展示。 |

`full` 保存的是可读的会话内容，不重复保存内部传输事件、token 计数、加密字段等运行元数据。
每次 hook 都会完整重写同一会话的 `.md` 文件，不会重复追加历史内容。升级后，同一会话
成功写入 Markdown 时会清理对应的旧 `.jsonl` 留档；其他历史会话文件不会自动转换或删除。

旧的 `.agents/session-archive.json` 已停用。重新运行准备脚本会迁移其中的等级，
保留已有 Langfuse 凭据，并在新配置成功写入后删除旧文件；新位置已有 `mode` 时优先保留。
`.agents/plugins/` 中的插件源配置仍需保留。

归档插件只读取 `.codex/langfuse.json`；文件或 `mode` 缺失、JSON 格式错误、`mode`
不受支持时会回退到 `messages`。准备脚本遇到无效配置则会报错，要求修正后再安装。
`mode` 只控制本地 Markdown 留档，Langfuse 上传内容仍由上传插件决定。修改等级只会
影响之后的 hook 刷新，不会重新处理已经结束的旧会话。即使使用 `messages`，输入和
回答中也可能包含源码或隐私信息，因此不要分享 `.agent-sessions/`。
