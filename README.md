# Claude 多账号切换

Linux 本机工具。所有账号共用一个 `~/.claude`，只有登录身份和账号绑定的状态按账号保存在
`~/.claude-accounts/account-<N>/`。切换账号就是把这些私有条目的符号链接改指到另一个账号。
`claude` 始终是官方程序，不经过包装器，Kander 和脚本无需任何配置。
Python 3 使用系统 `/usr/bin/python3`，无第三方依赖。

```sh
claude-switch.py add 2       # 添加空的账号 2
claude-switch.py login 2     # 切换到账号 2 并在浏览器登录
claude-switch.py status
claude-switch.py use 1       # 切回账号 1
claude-switch.py remove 2    # 删除账号 2 及其凭据，需在终端确认
```

最多支持 9 个账号，编号 `1`–`9`。当前账号保存在 `~/.claude-accounts/current`，原子更新。

## 私有条目与共享

每个账号私有，保存在 `account-<N>/` 中、在原位置以符号链接指向当前账号：

- `~/.claude.json`：账号身份、`userID`、组织与模型缓存、项目信任状态、用户级 MCP 等。
- `~/.claude/` 下的 `.credentials.json`、`daemon.log`、`stats-cache.json`，以及目录
  `daemon`、`jobs`、`telemetry`、`cache`、`backups`。

清单见 `claude-switch.py` 的 `PRIVATE_FILES` 与 `PRIVATE_DIRECTORIES`。`~/.claude` 中的
其他内容（`projects`、`sessions`、`session-env`、`tasks`、`plans`、`settings.json`、
`history.jsonl`、`CLAUDE.md`、`rules`、`hooks`、`skills`、`plugins` 等）所有账号共用，
包括会话记录和正在运行的会话登记。同一时刻只有一个账号生效，不能多个会话同时使用不同账号。

Claude 写 `.claude.json` 时跟随符号链接；写 `.credentials.json` 时会把链接替换为普通文件。
因此 `use` 先把被替换成普通文件或目录的私有条目移回当前账号（覆盖其中的旧副本），再改链接，
刷新后的令牌不会丢失。`status` 列出等待收回的条目。不是本工具建立的符号链接一律拒绝处理，
保留现场。各命令之间以 `~/.claude-accounts/.lock` 互斥。

## 命令

- `use <N>`：切换到已添加的账号。检测到正在运行的 Claude 进程（含 daemon）时列出 pid，
  说明继续的后果：这些进程会在下次刷新令牌或写配置时改用新账号，并可能把原账号的配置和令牌
  写进新账号。需在终端输入账号编号确认，输入不符即取消；stdin 不是终端时拒绝。
  建议先退出所有 Claude 再切换。
- `add <N>`：创建空的 `account-<N>`，目标已存在时拒绝。
- `login <N> [--email <邮箱>] [--sso]`：先按 `use` 切换，再运行官方
  `claude auth login --claudeai`，选项原样传入。登录会改变当前账号。
- `status`：当前账号调用官方 `claude auth status` 显示是否已登录；其他账号只显示是否保存了凭据，
  不切换、不联网，不输出邮箱或令牌。
- `remove <N>`：删除整个 `account-<N>`，包括凭据，不可恢复。拒绝当前账号；需在终端输入账号编号确认，
  stdin 不是终端时拒绝。

## 安装与更新

在源码目录运行 `python3 install.py`，可重复运行：

1. 把 `claude-switch.py` 原子替换到 `~/.local/bin/claude-switch.py`（0700），不触碰官方程序。
   `~/.local/bin` 需在 PATH 中，安装器发现不在时提示。
2. 首次安装时创建 `account-1`，把现有私有条目移入并换成链接，当前账号为 1。
   再次安装时保留当前账号，只收回被替换的条目并修复链接。
3. 迁移旧版布局：每个 `~/.claude-account<N>` 若没有对应的 `account-<N>`，复制其
   `.credentials.json` 与 `.claude.json` 到新目录。旧目录保留，核对后手动删除；
   旧目录中独立保存的 `sessions`、`tasks` 等不迁移。
4. 删除旧包装器自己的文件：`~/.local/share/claude-switch` 下的 `bin/claude`、`bin/claude-account`、
   `launcher.py`、`install.py`、`test_switch.py`、`README.md`，以及 `~/.config/claude-switch/current`，
   随后删除空目录；目录中还有其他文件时保留并提示。安装器不修改 shell 启动文件，
   只列出仍含旧 PATH 段（`Claude account switcher`）的文件，由用户删除。

`~/.claude-accounts` 是符号链接时拒绝安装。程序文件替换失败时保留旧版。

撤销：先 `use` 回要保留的账号，再把 `~/.claude.json` 与各私有条目的链接替换为
`account-<N>/` 中对应的文件或目录，最后删除 `~/.local/bin/claude-switch.py`。

测试：`python3 -B -m unittest -v test_switch.py`，使用临时 HOME 和假的官方 CLI，
不读取真实 token，不触发真实登录或模型调用。
