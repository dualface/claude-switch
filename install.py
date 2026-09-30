#!/usr/bin/python3
"""Install or update claude-switch.py, set up account 1 and retire the old PATH wrapper."""

import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile


SOURCE = Path(__file__).resolve().parent
PROGRAM = "claude-switch.py"
# Files the old PATH wrapper installed; only these are removed, nothing it did not create.
OLD_INSTALL_FILES = ("bin/claude", "bin/claude-account", "launcher.py", "install.py",
                     "test_switch.py", "README.md")
OLD_WRAPPER_DIRECTORY = "/.local/share/claude-switch/bin"
STARTUP_FILES = (".zshenv", ".zprofile", ".zshrc", ".profile", ".bashrc", ".bash_profile",
                 ".bash_login", ".config/fish/config.fish")


def load_switch():
    # The program name has a hyphen, so it cannot be imported by name.
    spec = importlib.util.spec_from_file_location("claude_switch", SOURCE / PROGRAM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_file(source, destination, mode):
    # The installed program is either the old or the new version, never a partial file.
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(source.read_bytes())
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def migrate_old_accounts(switch):
    """Copy the login of each old ~/.claude-account<N> into a new account-N; leave the old one."""
    migrated = []
    for account in switch.ACCOUNTS[1:]:
        old = Path.home() / f".claude-account{account}"
        new = switch.account_directory(account)
        if old.is_symlink() or not old.is_dir() or new.exists() or new.is_symlink():
            continue
        new.mkdir(mode=0o700)
        for name in (".credentials.json", ".claude.json"):
            path = old / name
            if path.is_file() and not path.is_symlink():
                shutil.copy2(path, new / name)
        migrated.append(account)
    return migrated


def remove_old_wrapper():
    """Delete the old wrapper's own files, so a stale PATH entry no longer shadows claude."""
    installed = Path.home() / ".local/share/claude-switch"
    selection = Path.home() / ".config/claude-switch"
    leftovers = []
    for path in [installed / name for name in OLD_INSTALL_FILES] + [selection / "current"]:
        if path.is_symlink() or path.is_file():
            path.unlink()
    for directory in (installed / "bin", installed, selection):
        if directory.is_symlink() or not directory.exists():
            continue
        try:
            directory.rmdir()
        except OSError:
            leftovers.append(directory)
    return leftovers


def startup_files_with_old_path():
    found = []
    for name in STARTUP_FILES:
        try:
            text = (Path.home() / name).read_text()
        except (OSError, ValueError):
            continue
        if any(OLD_WRAPPER_DIRECTORY in line and not line.strip().startswith("#")
               for line in text.splitlines()):
            found.append(name)
    return found


def install():
    switch = load_switch()
    binary_directory = Path.home() / ".local/bin"
    native = switch.native_cli()
    if not native.is_file() or not os.access(native, os.X_OK):
        raise ValueError("官方 Claude 未安装在 ~/.local/bin/claude")
    replace_file(SOURCE / PROGRAM, binary_directory / PROGRAM, 0o700)
    account = switch.initialize()
    print(f"已安装 ~/.local/bin/{PROGRAM}；当前账号 {account}。")
    migrated = migrate_old_accounts(switch)
    if migrated:
        print(f"已从旧目录迁移账号 {', '.join(migrated)} 的登录信息；"
              "核对无误后可删除对应的 ~/.claude-account<N>。")
    for directory in remove_old_wrapper():
        print(f"旧包装器目录中还有其他文件，保留：{directory}")
    for name in startup_files_with_old_path():
        print(f"~/{name} 中仍有旧包装器的 PATH 段（Claude account switcher），可以删除。")
    if str(binary_directory) not in os.environ.get("PATH", "").split(os.pathsep):
        print("~/.local/bin 不在 PATH 中；请把它加入 PATH 后再运行 claude-switch.py。")


if __name__ == "__main__":
    try:
        install()
    except (OSError, ValueError) as error:
        print(f"安装失败：{error}；可重新运行 python3 install.py 完成更新", file=sys.stderr)
        sys.exit(1)
