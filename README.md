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
$ git clone https://github.com/LearningOS/rCore-Tutorial-Code-2025S.git
$ cd rCore-Tutorial-Code-2025S
$ ./scripts/setup-agent-plugins.sh auto ~/Downloads/rcore-agent-token-你的学号.json
$ git clone https://github.com/LearningOS/rCore-Tutorial-Test-2025S.git user
$ git checkout ch$ID
$ cd os
# run OS in ch$ID
$ make run
```
Notice: $ID is from [1-9]

The agent setup script installs both the official Langfuse upload plugin and the
rCore local session archive plugin for Codex and/or Claude Code. Run it from the
`main` branch before checking out a lab branch. Use
`./scripts/setup-agent-plugins.sh codex` or
`./scripts/setup-agent-plugins.sh claude` to configure only one agent. Both
plugins are disabled in the user's global configuration and enabled by this
repository's project configuration, including the `ch1` through `ch8` branches.
Consequently, sessions are uploaded and archived only when the agent is started
inside this repository. The script installs the rCore marketplace from this
repository's `origin/main`, so it remains available after switching branches.

先打开
[`https://lihh18-nuc.tail6722a8.ts.net:10000/register`](https://lihh18-nuc.tail6722a8.ts.net:10000/register)，
填写真实姓名和学号并下载凭据 JSON；每个学号只能注册一次。把 JSON 路径作为
脚本的第二个参数，脚本会自动生成所需的项目级配置：

- Codex: `.codex/langfuse.json`
- Claude Code: `.claude/settings.local.json`

Both files and downloaded `rcore-agent-token*.json` files are excluded from
Git; do not force-add them. The JSON contains a secret: do not share it, and
delete extra copies after setup. Identity is derived by the server from this
token; no `user_id` needs to be entered. If the token is lost or the student ID
is already registered, contact a TA to revoke it and register again.

Claude Code reads the local settings file directly, so `/plugin configure` is not required. Codex
users must trust the repository and review the Langfuse/archive hooks with
`/hooks` on first use; hook trust is intentionally not bypassed. Claude Code
users should restart it or run `/reload-plugins`.
The Codex plugin requires Node.js 22 or newer; the Claude Code plugin requires
`uv`, or Python 3.10+ with `langfuse>=4.7,<5`. Local transcripts are stored in
`.agent-sessions/`, which is excluded from Git.

### Grading

```bash
# setup build&run environment first
$ git clone https://github.com/LearningOS/rCore-Tutorial-Code-2025S.git
$ cd rCore-Tutorial-Code-2025S
$ rm -rf ci-user
$ git clone https://github.com/LearningOS/rCore-Tutorial-Checker-2025S.git ci-user
$ git clone https://github.com/LearningOS/rCore-Tutorial-Test-2025S.git ci-user/user
$ git checkout ch$ID
# check&grade OS in ch$ID with more tests
$ cd ci-user && make test CHAPTER=$ID
```
Notice: $ID is from [3,4,5,6,8]
