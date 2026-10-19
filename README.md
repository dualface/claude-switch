# claude-switch：Claude 多账号切换

在一台 MacOS/Linux 电脑上保存多个 Claude 账号，用一条命令切换。

切换账号后，你的设置、规则、技能和聊天记录都保持不变，只有登录的账号变了。

---

## 安装

在本项目目录中运行：

```sh
python3 install.py
```

安装完成后，你现在登录的账号就是 **账号 1**。

> 如果安装后提示找不到 `claude-switch.py`，请把 `~/.local/bin` 加入 PATH，然后重新打开终端。

---

## 添加账号

账号用数字 1 到 9 编号。要添加账号 2：

```sh
claude-switch.py add 2
```

---

## 登录账号

要登录账号 2：

```sh
claude-switch.py login 2
```

浏览器会打开 Claude 的登录页面。登录完成后，你就在使用账号 2。

每个账号只需登录一次。

---

## 切换账号

要切换回账号 1：

```sh
claude-switch.py use 1
```

切换后，再打开的 Claude 使用账号 1。

> **切换前，请先关闭所有正在运行的 Claude。**
> 如果还有 Claude 在运行，程序会提醒你，并要求你输入账号编号确认。不确认就不会切换。

---

## 查看账号状态

```sh
claude-switch.py status
```

显示示例：

```
当前账号：1
账号 1：已登录（当前）
账号 2：已保存凭据
账号 3：无凭据
```

- **当前账号**：现在正在使用的账号。
- **已登录**：当前账号可以正常使用。
- **未登录**：当前账号需要用 `login` 重新登录。
- **已保存凭据**：这个账号登录过，切换过去就能用。
- **无凭据**：这个账号还没有登录，请用 `login` 登录。

---

## 删除账号

要删除账号 3：

```sh
claude-switch.py remove 3
```

程序会要求你输入账号编号确认。删除后，这个账号的登录信息无法恢复。

正在使用的账号不能删除，请先切换到其他账号。

---

## 常用命令一览

| 你想做什么       | 命令                        |
| ---------------- | --------------------------- |
| 添加账号 2       | `claude-switch.py add 2`    |
| 登录账号 2       | `claude-switch.py login 2`  |
| 切换到账号 1     | `claude-switch.py use 1`    |
| 查看所有账号状态 | `claude-switch.py status`   |
| 删除账号 3       | `claude-switch.py remove 3` |

---

## 许可证

基于 MIT 协议开源。详见 [LICENSE](LICENSE)。

---

## 作者的其他项目

欢迎体验作者 [dualface](https://github.com/dualface) 的其他项目：

- [Kander](https://github.com/dualface/kander)：规则驱动的多 Agent 看板调度工具，内置独立审核与自动化交付门禁。
- [ste-zh](https://github.com/dualface/ste-zh)：让 AI Agent 用清晰、严密、无歧义的中文汇报工作结果的 skill。
- [Ullage](https://github.com/dualface/ullage-cli)：本地守护进程与 CLI 工具，查看 Claude、ChatGPT、Grok、Cursor 等订阅的用量。
- [QuickTUI](https://quicktui.ai/)：适用于各类编码 Agent 的手机端完整终端，支持自托管直连，单台主机免费。
