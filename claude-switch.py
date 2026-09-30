#!/usr/bin/python3
"""Switch the Claude login by pointing the account-private entries of ~/.claude at a saved account."""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ACCOUNTS = tuple(str(number) for number in range(1, 10))
# Login identity and account-bound state inside ~/.claude; every other entry is shared.
PRIVATE_FILES = (".credentials.json", "daemon.log", "stats-cache.json")
PRIVATE_DIRECTORIES = ("daemon", "jobs", "telemetry", "cache", "backups")
# Account metadata lives at ~/.claude.json, not inside ~/.claude.
METADATA = ".claude.json"


def accounts_directory():
    return Path.home() / ".claude-accounts"


def account_directory(account):
    return accounts_directory() / f"account-{account}"


def selection_file():
    return accounts_directory() / "current"


def native_cli():
    return Path.home() / ".local/bin/claude"


def private_entries():
    """Yield (live path, stored name, is directory) for every account-private entry."""
    yield Path.home() / METADATA, METADATA, False
    config = Path.home() / ".claude"
    for name in PRIVATE_FILES:
        yield config / name, name, False
    for name in PRIVATE_DIRECTORIES:
        yield config / name, name, True


@contextlib.contextmanager
def locked():
    directory = accounts_directory()
    # Writing through a symlinked directory would move credentials outside the store.
    if directory.is_symlink():
        raise ValueError(f"账号目录是符号链接，保留现场：{directory}")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    with open(directory / ".lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def selected_account():
    try:
        account = selection_file().read_text().strip()
    except FileNotFoundError:
        raise ValueError("账号选择文件缺失；请先运行 python3 install.py") from None
    if account not in ACCOUNTS:
        raise ValueError(f"账号选择文件无效：{selection_file()}")
    return account


def write_selection(account):
    target = selection_file()
    # Readers see either complete selection.
    fd, temporary = tempfile.mkstemp(prefix=".current-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(account + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def existing_account_directory(account):
    directory = account_directory(account)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"账号 {account} 未添加或不是独立目录；先运行 claude-switch.py add {account}")
    return directory


def is_own_link(path, name):
    return os.readlink(path) in {str(account_directory(account) / name) for account in ACCOUNTS}


def store_live_entries(account):
    """Move entries Claude replaced with real files back into the account that owns them."""
    stored = account_directory(account)
    if stored.is_symlink() or not stored.is_dir():
        raise ValueError(f"当前账号 {account} 的目录缺失，无法收回其登录信息：{stored}")
    for live, name, _ in private_entries():
        if live.is_symlink():
            if not is_own_link(live, name):
                raise ValueError(f"不是本工具建立的链接，保留现场：{live}")
            continue
        if not live.exists():
            continue
        target = stored / name
        # The live entry is what Claude last wrote, so it supersedes the stored copy.
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        os.replace(live, target)


def link_account(account):
    stored = account_directory(account)
    for live, name, is_directory in private_entries():
        target = stored / name
        # A dangling directory link would make Claude's mkdir fail.
        if is_directory:
            target.mkdir(mode=0o700, exist_ok=True)
        live.parent.mkdir(mode=0o700, exist_ok=True)
        temporary = live.with_name(f".{name}.claude-switch-{os.getpid()}")
        temporary.symlink_to(target)
        try:
            os.replace(temporary, live)
        finally:
            if temporary.is_symlink():
                temporary.unlink()


def running_claude_pids():
    # The native launcher points at versions/<version>; every running Claude executes one of them.
    versions = native_cli().resolve().parent
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            executable = Path(os.readlink(entry / "exe"))
        except OSError:
            continue
        if executable.parent == versions:
            pids.append(int(entry.name))
    return sorted(pids)


def confirmed_in_terminal(message, expected, refusal):
    # A person must confirm; scripts and agents cannot answer for them.
    if not sys.stdin.isatty():
        raise ValueError(refusal)
    print(message)
    try:
        answer = input(f"输入账号编号 {expected} 确认：")
    except EOFError:
        answer = ""
    return answer.strip() == expected


def confirmed_despite_running_claude(account):
    pids = running_claude_pids()
    if not pids:
        return True
    message = (f"有正在运行的 Claude 进程：{', '.join(map(str, pids))}。\n"
               f"继续切换后，它们会在下次刷新令牌或写配置时改用账号 {account}，"
               f"并可能把原账号的配置和令牌写进账号 {account}。建议先退出这些进程。")
    refusal = f"有正在运行的 Claude 进程（{', '.join(map(str, pids))}）；请退出后重试，或在终端中运行以确认"
    return confirmed_in_terminal(message, account, refusal)


def switch_account(account):
    """Return False when the person cancels; otherwise the account is active afterwards."""
    with locked():
        existing_account_directory(account)
        if not confirmed_despite_running_claude(account):
            print("已取消，未切换账号。")
            return False
        store_live_entries(selected_account())
        link_account(account)
        write_selection(account)
    print(f"已切换到账号 {account}。")
    return True


def initialize():
    """Create account 1 from the current login on first run; repair the links on later runs."""
    with locked():
        if selection_file().exists():
            account = selected_account()
            existing_account_directory(account)
        else:
            account = "1"
            account_directory(account).mkdir(mode=0o700, exist_ok=True)
        store_live_entries(account)
        link_account(account)
        if not selection_file().exists():
            write_selection(account)
    return account


def add_account(account):
    with locked():
        directory = account_directory(account)
        if directory.exists() or directory.is_symlink():
            raise ValueError(f"目标已存在，保留现场：{directory}")
        directory.mkdir(mode=0o700)
    print(f"已添加账号 {account}；切换并登录：claude-switch.py login {account}")


def remove_account(account):
    with locked():
        if account == selected_account():
            raise ValueError(f"账号 {account} 是当前账号；先运行 claude-switch.py use <其他编号>")
        directory = existing_account_directory(account)
        message = f"将删除 {directory}，包括账号 {account} 的凭据，不可恢复。"
        refusal = f"删除需要在终端中确认；请手动运行 claude-switch.py remove {account}"
        if not confirmed_in_terminal(message, account, refusal):
            print("已取消，未删除任何文件。")
            return
        shutil.rmtree(directory)
    print(f"已删除账号 {account}。")


def configured_accounts():
    return [account for account in ACCOUNTS
            if account_directory(account).exists() or account_directory(account).is_symlink()]


def current_login_state():
    result = subprocess.run([str(native_cli()), "auth", "status", "--json"],
                            capture_output=True, text=True, timeout=20)
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError(f"无法检查登录状态（退出码 {result.returncode}）") from None
    if not isinstance(data, dict) or not isinstance(data.get("loggedIn"), bool):
        raise ValueError("登录状态格式异常")
    if result.returncode not in (0, 1) or (data["loggedIn"] and result.returncode):
        raise ValueError(f"检查登录状态失败（退出码 {result.returncode}）")
    return "已登录" if data["loggedIn"] else "未登录"


def show_status():
    current = selected_account()
    print(f"当前账号：{current}")
    failed = False
    for account in configured_accounts():
        try:
            if account == current:
                pending = [str(live) for live, _, _ in private_entries()
                           if live.exists() and not live.is_symlink()]
                print(f"账号 {account}：{current_login_state()}（当前）")
                if pending:
                    print(f"账号 {account}：下次切换时收回 " + ", ".join(pending))
            else:
                saved = (existing_account_directory(account) / ".credentials.json").exists()
                print(f"账号 {account}：{'已保存凭据' if saved else '无凭据'}")
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            print(f"账号 {account}：检查失败（{error}）", file=sys.stderr)
            failed = True
    return 1 if failed else 0


def login(account, email, sso):
    if not switch_account(account):
        return
    native = str(native_cli())
    arguments = [native, "auth", "login", "--claudeai"]
    if email:
        arguments.extend(["--email", email])
    if sso:
        arguments.append("--sso")
    os.execv(native, arguments)


def main():
    parser = argparse.ArgumentParser(description="切换 ~/.claude 使用的 Claude 登录；共享其他所有资料。")
    commands = parser.add_subparsers(dest="command", required=True)
    use = commands.add_parser("use", help="切换到指定账号")
    use.add_argument("account", choices=ACCOUNTS)
    add = commands.add_parser("add", help="添加空的账号目录")
    add.add_argument("account", choices=ACCOUNTS)
    remove = commands.add_parser("remove", help="删除账号目录及其凭据，需在终端确认")
    remove.add_argument("account", choices=ACCOUNTS)
    commands.add_parser("status", help="显示当前账号及各账号的登录状态")
    login_parser = commands.add_parser("login", help="切换到指定账号并登录")
    login_parser.add_argument("account", choices=ACCOUNTS)
    login_parser.add_argument("--email", help="预填登录邮箱")
    login_parser.add_argument("--sso", action="store_true", help="使用 SSO 登录")
    args = parser.parse_args()
    if args.command == "use":
        switch_account(args.account)
    elif args.command == "add":
        add_account(args.account)
    elif args.command == "remove":
        remove_account(args.account)
    elif args.command == "status":
        sys.exit(show_status())
    else:
        login(args.account, args.email, args.sso)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"{Path(sys.argv[0]).name}: {error}", file=sys.stderr)
        sys.exit(1)
