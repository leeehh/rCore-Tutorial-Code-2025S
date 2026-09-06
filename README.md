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

本仓库提供环境准备脚本，支持 Codex、Claude Code、Cursor 和 VS Code GitHub Copilot
的 Langfuse 会话上传与本地 Markdown 留档。Codex / Claude Code 的插件全局关闭、项目内
启用；Cursor / VS Code 使用项目原生 hooks，不安装全局 hooks。凭据只保存在项目内。

#### 1. 前置条件

- 已安装并能够正常运行 Codex CLI、Claude Code 或支持项目 hooks 的新版 Cursor。
- 已安装 Git 和 Python 3.9 或更高版本。
- 使用 Codex 时需要 Node.js 22 或更高版本。
- 使用 Claude Code 时需要 `uv`；或者 Python 3.10 及
  `langfuse>=4.7,<5`。
- Cursor 适配器只使用 Python 标准库，不需要 Node.js、`uv` 或额外 Langfuse SDK；
  本次接入面向 Cursor 编辑器的 Agent 会话，不包含 Tab 自动补全。
- VS Code 适配器也只使用 Python 标准库；需安装支持项目 hooks 和 v1 transcript 的新版
  VS Code / GitHub Copilot，并登录可使用 Copilot Agent 的账户。这里支持本地 Copilot
  Agent 会话，不包含行内补全、后台/云端 Agent，或 VS Code 中运行的 Codex / Claude。
- 准备脚本使用 Bash。Linux / macOS 可直接运行；Windows 建议在 WSL 中准备环境，并用
  VS Code 的 WSL 窗口打开项目。Remote SSH 同样需在项目所在环境运行脚本。

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

# 自动配置能够检测到 CLI 的 Agent
./scripts/setup-agent-plugins.sh auto /path/to/rcore-agent-token-<学号>.json
```

也可以只配置指定 Agent：

```bash
# 仅 Codex
./scripts/setup-agent-plugins.sh codex /path/to/rcore-agent-token-<学号>.json

# 仅 Claude Code
./scripts/setup-agent-plugins.sh claude /path/to/rcore-agent-token-<学号>.json

# 仅 Cursor；即使没有安装 cursor 命令也可以配置
./scripts/setup-agent-plugins.sh cursor /path/to/rcore-agent-token-<学号>.json

# 仅 VS Code GitHub Copilot；无需 code 命令，也可用 copilot 别名
./scripts/setup-agent-plugins.sh vscode /path/to/rcore-agent-token-<学号>.json

# 配置四者；缺少 Codex / Claude Code CLI 时会报错
./scripts/setup-agent-plugins.sh all /path/to/rcore-agent-token-<学号>.json
```

如果只安装了图形界面，请显式使用 `cursor` 或 `vscode`，不要依赖 `auto` 的 CLI 检测。
脚本不安装 Agent 客户端本身。

Codex / Claude Code 会安装或更新以下两个插件：

- Langfuse 官方插件：把本仓库内的 Agent 会话上传到课程服务器。
- `rcore-session-archive`：把会话以 Markdown 保存到本仓库的 `.agent-sessions/`。

Cursor 使用本仓库提供的适配脚本，经 [Cursor 官方 hooks 接口](https://cursor.com/docs/hooks)
采集事件，并通过 [Langfuse OTLP 接口](https://langfuse.com/integrations/native/opentelemetry)
上传到课程身份网关；不是安装或改写 Codex / Claude Code 的官方 Langfuse 插件。
脚本合并 `.cursor/hooks.json`，保留其他 hooks，重复运行不会重复添加。

VS Code 同样使用本仓库的适配器，通过 [VS Code 官方 hooks 接口](https://code.visualstudio.com/docs/agent-customization/hooks)
读取 Copilot 提供的 transcript，再上传与留档；不启用应用级 OTel，也不安装全局扩展。
脚本将专用 hooks 注册到项目 `.vscode/settings.json`，保留已有设置和 JSONC 注释，
不重复添加，也不修改其他 Agent 的插件缓存。

脚本还会生成下列本地配置：

| 文件 | 用途 | 是否提交 Git |
| --- | --- | --- |
| `.codex/config.toml` | 在本仓库启用 Codex hooks 和两个插件 | 是 |
| `.codex/langfuse.json` | Codex 的个人 Langfuse 凭据与本地留档等级 `mode` | 否 |
| `.claude/settings.json` | 在本仓库启用 Claude Code 的两个插件 | 是 |
| `.claude/settings.local.json` | Claude Code 的个人 Langfuse 凭据与本地留档等级 `env.RCORE_SESSION_ARCHIVE_MODE` | 否 |
| `.cursor/hooks.example.json` | Cursor hooks 的共享示例 | 是 |
| `.cursor/hooks.json` | 准备脚本生成的 Cursor 项目 hooks | 否 |
| `.cursor/rcore-hooks/` | 准备脚本安装的 Cursor 运行脚本，切分支后仍保留 | 否 |
| `.cursor/langfuse.json` | Cursor 的开关 `enabled`、个人凭据与本地留档等级 `mode` | 否 |
| `.vscode/copilot-hooks.example.json` | VS Code Copilot hooks 的共享示例 | 是 |
| `.vscode/settings.json` | 启用项目 hooks，并注册专用 hooks 文件，保留其他编辑器设置 | 否 |
| `.vscode/rcore-hooks/` | Copilot 的 `hooks.json` 与 Python 运行脚本，切分支后仍保留 | 否 |
| `.vscode/langfuse.json` | Copilot 的开关 `enabled`、个人凭据与本地留档等级 `mode` | 否 |
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

Cursor：

使用 **Open Folder** 打开本仓库根目录并信任工作区，再新建 Agent 会话。无需进入 Cursor
运行插件配置命令；在 **Customize → Hooks** 检查 hooks，在 **Output → Hooks** 查看异常。
如果未加载配置，重启 Cursor。使用 Remote SSH / WSL 时，应在项目所在的远程 / WSL
环境运行准备脚本，并确保该环境有 `python3`。

Cursor 只读取当前仓库的 `.cursor/langfuse.json`；没有这个文件或 `enabled` 不是 `true`
时，上传和本地归档都不会启用。不往用户主目录写 Cursor 配置，也不会关闭用户自己安装的
其他全局 hooks。为避免混入其他项目，不采集包含仓库外文件夹的多根工作区；请单独打开本仓库。
本适配器不需要开启第三方 Claude hooks 兼容。如果以前装过其他 Cursor 会话上传 hooks，
请检查是否仍在运行，避免同时启用两套上传；Cursor 会执行各来源匹配的 hooks，项目配置不会
自动屏蔽全局配置。参见 [第三方 hooks 说明](https://cursor.com/docs/reference/third-party-hooks)。

VS Code GitHub Copilot：

使用 **Open Folder** 单独打开并信任本仓库根目录，新建本地 **Copilot Agent** 会话。
不要用包含其他项目的多根工作区。若编辑器已开着，可执行 **Developer: Reload Window**
后新建会话；在 **Output → Copilot Chat Hooks** 查看执行情况。组织策略禁用 hooks 时，
需要联系管理员，准备脚本不会绕过策略或工作区信任。

适配器只读取本仓库 `.vscode/langfuse.json`；缺失、无效或 `enabled` 不是 `true` 时，
上传与归档都不启用。脚本不写入主目录，不关闭用户已有的其他全局 hooks；若此前配置过
其他 Copilot 会话导出或 OTel 上传，请确认未重复启用。SSH / WSL 窗口的 hook 在远程 / WSL
环境执行，该环境需能运行 `python3` 并访问课程服务器。

完成一次对话后，可检查本地是否生成了留档：

```bash
find .agent-sessions -type f -name '*.md'
```

每个会话保存为一个 Markdown 文件，可直接使用 VS Code 的 Markdown 预览阅读：

```text
.agent-sessions/codex/<session-id>.md
.agent-sessions/claude-code/<session-id>.md
.agent-sessions/cursor/<conversation-id>.md
.agent-sessions/vscode-copilot/<session-id>.md
```

文件按轮次展示用户输入和 Agent 回答，保留消息中的代码块、列表与表格；工具命令使用
代码块展示，参数按键值展示。较长的中间输出和工具结果放入可展开的折叠区，文本不会截断。
所有等级都只生成 Markdown，不另存原始 JSON/JSONL 备份，也不复制图片等二进制附件，
附件仅记录描述或引用。Agent 自己维护的源会话文件不受影响。

Codex / Claude Code 切换实验分支后继续使用原有安装结果。Cursor / VS Code 的 hooks、凭据
和运行脚本由准备脚本放入项目内被 Git 忽略的 `.cursor` / `.vscode` 路径，切到 `ch*` 后仍
保留，实验分支不需要重复携带 `plugins` 源码。不要执行会清理这些本地配置的 `git clean -fdx`。
请始终从本仓库目录启动 Agent；在其他项目中，本仓库的配置不生效。

#### 5. 配置本地留档等级

四个 Agent 使用各自的项目配置，归档等级互不影响。准备脚本默认设置为 `messages`，
重新运行时保留已有选择。

Codex：编辑 `.codex/langfuse.json` 的顶层 `mode` 字段，和 `enabled`、
`public_key`、`secret_key` 等 Langfuse 配置放在同一个 JSON 对象中：

```json
{
  "mode": "messages"
}
```

Claude Code：编辑 `.claude/settings.local.json` 中的
`env.RCORE_SESSION_ARCHIVE_MODE`，Langfuse 凭据继续使用同一个 `env` 中的
`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`：

```json
{
  "env": {
    "RCORE_SESSION_ARCHIVE_MODE": "messages"
  }
}
```

以上片段只展示归档字段；编辑已有文件时保留其他字段和环境变量。完整示例见
[`.codex/langfuse.example.json`](.codex/langfuse.example.json) 和
[`.claude/settings.local.example.json`](.claude/settings.local.example.json)。
`RCORE_SESSION_ARCHIVE_MODE` 由本仓库的归档插件读取，不是 Langfuse 官方插件的配置项；
它放在官方支持的 `env` 中，不添加自定义顶层设置，不修改官方上传插件。
Claude Code 不需要单独的 `.claude/langfuse.json`，仅安装 Claude Code 也不会生成
`.codex/langfuse.json`。

Cursor：编辑 `.cursor/langfuse.json` 的顶层 `mode`，其余凭据字段保持不变，示例见
[`.cursor/langfuse.example.json`](.cursor/langfuse.example.json)。将 `enabled` 改为 `false`
会同时暂停 Cursor 的上传与归档；改回 `true` 后从后续 hook 事件继续，不回填停用期间的内容。

VS Code Copilot：编辑 `.vscode/langfuse.json` 的顶层 `mode`，示例见
[`.vscode/langfuse.example.json`](.vscode/langfuse.example.json)。将 `enabled` 改为 `false`
同时暂停上传与归档。此配置由本仓库适配器读取，不是 VS Code 或 Langfuse 官方的配置文件。

| `mode` | 保存内容 |
| --- | --- |
| `messages` | 只保存学生输入和每轮 Agent 最终回答；默认值。 |
| `tool-calls` | 在 `messages` 基础上增加工具名称、调用 ID 和命令/工具输入，不保存工具输出。 |
| `full` | 增加中间输出、可读的推理摘要和完整工具输出，较长内容折叠展示。 |

`full` 保存的是可读的会话内容，不重复保存内部传输事件、token 计数、加密字段等运行元数据。
hook 更新同一会话的 `.md` 文件，不会重复追加历史内容。Codex / Claude Code 升级后，同一会话
成功写入 Markdown 时会清理对应的旧 `.jsonl` 留档；其他历史会话文件不会自动转换或删除。
Claude Code 的 `Stop` 归档会同时读取 hook 携带的最终回复，避免原始会话文件尚未落盘时
漏掉最新回答。已保存的本轮回复不会重复写入，不同轮内容相同的回答仍分别保留。

升级已有安装时，重新运行 `./scripts/setup-agent-plugins.sh claude` 即可更新插件并迁移
配置。Claude 尚未设置 `RCORE_SESSION_ARCHIVE_MODE` 时，脚本会沿用此前
`.codex/langfuse.json` 中的归档等级；保存后独立使用 Claude 的配置，不再随 Codex 的
等级变化。只迁移归档等级，不复制或覆盖两个 Agent 各自的凭据。

旧的 `.agents/session-archive.json` 已停用。Codex / Claude Code 准备脚本仍支持迁移其中的等级，
在所选 Agent 的新配置成功写入后删除旧文件；新位置已有等级时优先保留。
Cursor / VS Code 不读取旧配置。`.agents/plugins/` 中的插件源配置仍需保留。

归档插件每次只读取当前 Agent 对应的项目配置文件，不使用另一个 Agent 的等级或进程中
缓存的归档环境变量。Codex / Claude Code 的配置缺失或无效时回退到 `messages`；
Cursor / VS Code 则需要有效且启用的配置才采集，其 `mode` 缺失或无效时使用 `messages`。
准备脚本遇到无效配置则会报错，要求修正后再安装。
等级只控制本地 Markdown 留档，Langfuse 上传内容仍由上传插件决定。更新插件后需要
重新打开 Agent；之后修改归档等级会在下一次 hook 刷新时生效，无需重新安装插件，也不会
重新处理已经结束的旧会话。修改 Claude 的 Langfuse 凭据后则应重启 Claude Code，以加载
新的环境变量。即使使用 `messages`，输入和
回答中也可能包含源码或隐私信息，因此不要分享 `.agent-sessions/`。

#### 6. Cursor 的记录与排查

Cursor 在提交输入、完成回复、工具调用等事件发生时刷新 Markdown，不读取它的内部会话
数据库，也不复制源 transcript。最终回复直接取自 `afterAgentResponse`，无需等待源文件落盘。
`full` 仅包含 hooks 实际提供的正文、思考摘要、工具输入/输出；不能取得的系统提示、完整
模型请求或隐藏推理不会伪造或补全。Langfuse 上传不受本地 `mode` 限制。

每个 conversation 对应一个本地文件和一个 Langfuse session，每个 generation 对应一轮 trace。
工具开始和结束使用同一个 observation ID；相同回调重试不会新建一条完整历史，空 `stop`
不会创建空 trace。`.agent-sessions/cursor/.state/` 的 SQLite 索引只保存 ID、时间和摘要，
不保存消息、工具内容或凭据；请和 Markdown 一起保留，不要单独删除活动会话的索引。

降低 `mode` 会在下一次事件时删去本会话 Markdown 中不再允许的内容；提高等级只影响后续
收到的事件，无法恢复以前未留档的工具信息。更新时回到 `main` 拉取代码，再重新运行
`cursor` 准备命令，刷新项目内的运行脚本；不会修改其他分支或其他 Agent 的缓存。

网络上传失败时，本地 Markdown 仍保存。短暂网络错误会立即重试一次，当前轮的用户输入与
最终回复还会在 `stop` 时重试；为避免在 `messages` 模式暗中存下全部工具输出，**不保存
原始上传队列**，持续断网期间的工具事件不能保证之后自动补传。请在 Output → Hooks 检查
`HTTP 401`（凭据无效）、`HTTP 403`（访问被拒绝）及连接错误；不要把 token 发到日志里。

文件采用原子替换，终端实时观察应使用 `tail -F`（按文件名跟随），而不是 `tail -f`：

```bash
tail -F .agent-sessions/cursor/<conversation-id>.md
```

开始正式实验前，先在 Cursor 发一条测试消息，让 Agent 执行一个简单命令并回复，确认本地
Markdown 和 Langfuse 均收到本轮记录。也可运行适配器的自动化测试（使用模拟事件，不上传真实会话）：

```bash
python3 -m unittest discover -s plugins/rcore-session-archive/tests
```

#### 7. VS Code Copilot 的记录与排查

适配器在提交输入、工具调用和停止等 hooks 中读取该会话的 transcript，再按 `mode` 生成
Markdown。`Stop` 不直接提供最终回复，因此会短暂等待源文件写完；超时或格式不支持时
输出提示，保留已有留档，不把中间消息冒充最终回答。若强制结束进程且之后没有 hook，
不能保证补齐尚未写入源文件的最后一段回复。

每个会话对应一个文件和一个 Langfuse session，每次用户提交对应一轮稳定 ID 的 trace。
模型内部多次调用、工具开始/结束及 hook 重试不会新建重复轮次；启用时只接入当前轮，
不会批量上传此前未采集的旧轮次。上传包含源文件实际提供的中间文本、推理摘要和工具
输入/输出，不受本地 `mode` 限制；源文件没有提供的模型完整输入和内部信息无法记录。

与 Cursor 不同，只要 Copilot 源文件仍有内容，提高 `mode` 可以恢复本会话已接入轮次的
相应内容；降低等级会在下一次 hook 清理该会话中不再允许的 Markdown 内容。
`.agent-sessions/vscode-copilot/.state/` 只保存去重/重试所需的 ID、哈希和时间，不存正文
或 token；请和 Markdown 一起保留。不会生成原始 JSON 备份或上传队列。

网络失败不影响已写好的 Markdown；后续 hook 会从仍存在的 Copilot 源文件重试未成功的
上传。源文件被 Copilot 清理后，或会话不再触发 hook 时，不能保证自动补传。
在 **Output → Copilot Chat Hooks** 查看凭据、网络或 transcript 版本错误，不要将 token
复制进日志。当前支持官方实现的 **v1 transcript**，其格式尚不是稳定 API；参见
[官方 hooks 说明](https://code.visualstudio.com/docs/agent-customization/hooks) 和
[适配器说明](plugins/rcore-session-archive/README.md#vs-code-github-copilot-native-project-hooks)。

更新时回到 `main` 拉取代码，重新运行 `./scripts/setup-agent-plugins.sh vscode`，再新建
Copilot 会话。凭据和已有 `mode` 会保留。正式实验前先发一条无敏感信息的测试消息，
让 Agent 执行一个简单命令并回复，确认 Markdown 和 Langfuse 都有记录。
文件使用原子替换，终端查看更新请使用：

```bash
tail -F .agent-sessions/vscode-copilot/<session-id>.md
```
