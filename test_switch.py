#!/usr/bin/python3
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import install as installer


SOURCE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("claude_switch", SOURCE / "claude-switch.py")
switch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(switch)
# Listed here, not read from the program, so dropping an entry fails the tests.
PRIVATE = (".claude.json", ".claude/.credentials.json", ".claude/daemon.log", ".claude/stats-cache.json",
           ".claude/daemon", ".claude/jobs", ".claude/telemetry", ".claude/cache", ".claude/backups")
SHARED = (".claude/projects", ".claude/sessions", ".claude/settings.json", ".claude/history.jsonl")
FAKE = '''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
if sys.argv[1:3] == ["auth", "status"]:
    logged_in = (Path.home() / ".claude/.credentials.json").exists()
    print(json.dumps({"loggedIn": logged_in, "email": "private@example.test"}))
    sys.exit(0 if logged_in else 1)
print(json.dumps({"args": sys.argv[1:], "config": os.environ.get("CLAUDE_CONFIG_DIR")}))
'''
# Stands in for /usr/bin/security so that no test touches the real keychain.
FAKE_SECURITY = '''#!/usr/bin/python3
import json, shlex, sys
from pathlib import Path
store = Path.home() / "fake-keychain.json"
if (Path.home() / "fake-keychain-locked").exists():
    sys.exit(36)
items = json.loads(store.read_text()) if store.exists() else {}
def run(command, *rest):
    rest = [argument for argument in rest if argument not in ("-U", "-w")]
    options = dict(zip(rest[::2], rest[1::2]))
    key = options["-a"] + "/" + options["-s"]
    if command == "find-generic-password":
        if key not in items:
            sys.exit(44)
        print(bytes.fromhex(items[key]).decode())
    elif command == "add-generic-password":
        items[key] = options["-X"]
    elif items.pop(key, None) is None:
        sys.exit(44)
    store.write_text(json.dumps(items))
if sys.argv[1] == "-i":
    for line in sys.stdin:
        run(*shlex.split(line))
else:
    run(*sys.argv[1:])
'''


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.bin = self.home / ".local/bin"
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "LANG": "C.UTF-8"}
        self.bin.mkdir(parents=True)
        native = self.bin / "claude"
        native.write_text(FAKE)
        native.chmod(0o700)
        security = self.bin / "security"
        security.write_text(FAKE_SECURITY)
        security.chmod(0o700)
        for relative in PRIVATE + SHARED:
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if "." in path.name:
                path.write_text("account one " + path.name)
            else:
                path.mkdir()
                (path / "item").write_text("account one " + path.name)
        self.install_result = self.run_install()
        self.accounts = self.home / ".claude-accounts"

    def run_install(self, success=True):
        result = subprocess.run([sys.executable, str(SOURCE / "install.py")],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def command(self, *arguments, **kwargs):
        return subprocess.run([str(self.bin / "claude-switch.py"), *arguments], env=self.env,
                              text=True, capture_output=True, **kwargs)

    def in_home(self, function, *arguments, tty=True, answers=(), pids=()):
        output = io.StringIO()
        with patch.dict(os.environ, {"HOME": str(self.home), "PATH": self.env["PATH"]}), \
                patch.object(sys.stdin, "isatty", return_value=tty), \
                patch("builtins.input", side_effect=list(answers)), \
                patch.object(switch, "running_claude_pids", return_value=list(pids)), \
                contextlib.redirect_stdout(output):
            result = function(*arguments)
        return result, output.getvalue()

    def keychain_key(self):
        with patch.dict(os.environ, {"HOME": str(self.home)}):
            return f"{switch.keychain_account()}/{switch.KEYCHAIN_SERVICE}"

    def set_keychain(self, login):
        (self.home / "fake-keychain.json").write_text(json.dumps({self.keychain_key(): login.encode().hex()}))

    def keychain(self):
        store = self.home / "fake-keychain.json"
        items = json.loads(store.read_text()) if store.exists() else {}
        login = items.get(self.keychain_key())
        return None if login is None else bytes.fromhex(login).decode()

    def assert_linked_to(self, account):
        for relative in PRIVATE:
            name = Path(relative).name
            self.assertEqual(os.readlink(self.home / relative), str(self.accounts / f"account-{account}" / name))

    def test_install_moves_private_entries_into_account_one(self):
        self.assertEqual((self.bin / "claude-switch.py").read_bytes(), (SOURCE / "claude-switch.py").read_bytes())
        self.assertEqual((self.bin / "claude-switch.py").stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.accounts / "current").read_text(), "1\n")
        self.assertEqual(self.accounts.stat().st_mode & 0o777, 0o700)
        self.assert_linked_to("1")
        self.assertEqual((self.home / ".claude/.credentials.json").read_text(), "account one .credentials.json")
        self.assertEqual((self.home / ".claude/daemon/item").read_text(), "account one daemon")
        for relative in SHARED:
            self.assertFalse((self.home / relative).is_symlink())
        self.assertIn("当前账号 1", self.install_result.stdout)

    def test_use_switches_links_and_takes_back_replaced_files(self):
        self.assertEqual(self.command("add", "2").returncode, 0)
        (self.accounts / "account-2/.credentials.json").write_text("account two login")
        live = self.home / ".claude/.credentials.json"
        # Claude replaces the credentials link with a regular file when it writes a refreshed token.
        live.unlink()
        live.write_text("account one refreshed")
        result = self.command("use", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_linked_to("2")
        self.assertEqual(live.read_text(), "account two login")
        self.assertEqual((self.accounts / "account-1/.credentials.json").read_text(), "account one refreshed")
        self.assertTrue((self.accounts / "account-2/daemon").is_dir())
        self.assertEqual((self.accounts / "current").read_text(), "2\n")
        self.assertEqual((self.home / ".claude/projects/item").read_text(), "account one projects")
        self.assertEqual(self.command("use", "1").returncode, 0)
        self.assertEqual(live.read_text(), "account one refreshed")

    def test_use_takes_back_replaced_directory(self):
        self.assertEqual(self.command("add", "2").returncode, 0)
        live = self.home / ".claude/cache"
        live.unlink()
        live.mkdir()
        (live / "fresh").write_text("new cache")
        self.assertEqual(self.command("use", "2").returncode, 0)
        self.assertEqual(sorted(p.name for p in (self.accounts / "account-1/cache").iterdir()), ["fresh"])
        self.assert_linked_to("2")

    def test_use_rejects_missing_account_and_foreign_link(self):
        result = self.command("use", "3")
        self.assertIn("claude-switch.py add 3", result.stderr)
        self.assertEqual(self.command("add", "3").returncode, 0)
        foreign = self.home / ".claude/jobs"
        foreign.unlink()
        foreign.symlink_to(self.home / "elsewhere")
        result = self.command("use", "3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不是本工具建立的链接", result.stderr)
        self.assertEqual(os.readlink(foreign), str(self.home / "elsewhere"))
        self.assertEqual((self.accounts / "current").read_text(), "1\n")

    def test_use_with_running_claude_needs_terminal_confirmation(self):
        self.assertEqual(self.command("add", "2").returncode, 0)
        with self.assertRaisesRegex(ValueError, "正在运行的 Claude 进程（42）"):
            self.in_home(switch.switch_account, "2", tty=False, pids=[42])
        for answer in ("y", EOFError()):
            switched, output = self.in_home(switch.switch_account, "2", answers=[answer], pids=[42])
            self.assertFalse(switched)
            self.assertIn("已取消", output)
            self.assert_linked_to("1")
        switched, output = self.in_home(switch.switch_account, "2", answers=["2"], pids=[42])
        self.assertTrue(switched)
        self.assertIn("可能把原账号的配置和令牌写进账号 2", output)
        self.assert_linked_to("2")

    def test_running_claude_pids_finds_native_versions(self):
        version = self.home / ".local/share/claude/versions/1.0"
        version.parent.mkdir(parents=True)
        shutil.copy("/bin/sleep", version)
        if sys.platform == "darwin":
            # macOS kills a copied system binary until it is signed again.
            subprocess.run(["codesign", "--force", "--sign", "-", str(version)], check=True, capture_output=True)
        (self.bin / "claude").unlink()
        (self.bin / "claude").symlink_to(version)
        running = subprocess.Popen([str(self.bin / "claude"), "30"])
        self.addCleanup(running.wait)
        self.addCleanup(running.kill)
        with patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertEqual(switch.running_claude_pids(), [running.pid])

    def test_use_on_macos_swaps_keychain_login(self):
        self.assertEqual(self.command("add", "2").returncode, 0)
        (self.accounts / "account-2/.credentials.json").write_text("account two login")
        self.set_keychain("account one keychain")
        with patch.object(switch, "USES_KEYCHAIN", True):
            self.in_home(switch.switch_account, "2")
            self.assertEqual(self.keychain(), "account two login")
            self.assertEqual((self.accounts / "account-1/.credentials.json").read_text(), "account one keychain")
            # Claude refreshes the token in the keychain while account 2 is active.
            self.set_keychain("account two refreshed")
            self.in_home(switch.switch_account, "1")
        self.assertEqual(self.keychain(), "account one keychain")
        stored = self.accounts / "account-2/.credentials.json"
        self.assertEqual(stored.read_text(), "account two refreshed")
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)

    def test_use_on_macos_clears_keychain_for_account_without_login(self):
        self.assertEqual(self.command("add", "3").returncode, 0)
        self.set_keychain("account one keychain")
        with patch.object(switch, "USES_KEYCHAIN", True):
            self.in_home(switch.switch_account, "3")
        self.assertIsNone(self.keychain())
        self.assertEqual((self.accounts / "account-1/.credentials.json").read_text(), "account one keychain")

    def test_use_on_macos_stops_when_keychain_fails(self):
        self.assertEqual(self.command("add", "2").returncode, 0)
        (self.home / "fake-keychain-locked").touch()
        with patch.object(switch, "USES_KEYCHAIN", True):
            with self.assertRaisesRegex(ValueError, "读取钥匙串登录信息失败：钥匙串已锁定.*security unlock-keychain"):
                self.in_home(switch.switch_account, "2")
        (self.home / "fake-keychain-locked").unlink()
        (self.accounts / "account-2/.credentials.json").write_text("x" * 3000)
        with patch.object(switch, "USES_KEYCHAIN", True):
            with self.assertRaisesRegex(ValueError, "登录信息过长"):
                self.in_home(switch.switch_account, "2")
        self.assertIsNone(self.keychain())
        self.assertEqual((self.accounts / "current").read_text(), "1\n")

    def test_add_creates_private_empty_directory_and_rejects_existing(self):
        result = self.command("add", "4")
        self.assertEqual(result.returncode, 0, result.stderr)
        directory = self.accounts / "account-4"
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(directory.iterdir()), [])
        self.assertIn("目标已存在", self.command("add", "4").stderr)
        for account in ("0", "10", "a"):
            self.assertNotEqual(self.command("add", account).returncode, 0)

    def test_remove_needs_confirmation_and_keeps_current_account(self):
        self.assertEqual(self.command("add", "2").returncode, 0)
        directory = self.accounts / "account-2"
        (directory / ".credentials.json").write_text("account two login")
        self.assertIn("当前账号", self.command("remove", "1").stderr)
        self.assertIn("删除需要在终端中确认", self.command("remove", "2", input="2\n").stderr)
        self.assertIn("已取消", self.in_home(switch.remove_account, "2", answers=["n"])[1])
        self.assertTrue(directory.is_dir())
        self.assertIn("已删除账号 2", self.in_home(switch.remove_account, "2", answers=["2"])[1])
        self.assertFalse(directory.exists())
        self.assertIn("未添加", self.command("remove", "3").stderr)

    def test_login_switches_then_runs_native_login(self):
        self.assertEqual(self.command("add", "2").returncode, 0)
        result = self.command("login", "2", "--email", "user@example.test", "--sso")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(data, {"args": ["auth", "login", "--claudeai", "--email", "user@example.test", "--sso"],
                                "config": None})
        self.assert_linked_to("2")

    def test_status_reports_current_login_and_saved_credentials(self):
        for account in ("2", "3"):
            self.assertEqual(self.command("add", account).returncode, 0)
        (self.accounts / "account-3/.credentials.json").write_text("account three login")
        live = self.home / ".claude/stats-cache.json"
        live.unlink()
        live.write_text("{}")
        result = self.command("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "当前账号：1", "账号 1：已登录（当前）", f"账号 1：下次切换时收回 {live}",
            "账号 2：无凭据", "账号 3：已保存凭据"])
        self.assertNotIn("private", result.stdout + result.stderr)

    def test_reinstall_keeps_selection_and_repairs_links(self):
        self.assertEqual(self.command("add", "2").returncode, 0)
        self.assertEqual(self.command("use", "2").returncode, 0)
        live = self.home / ".claude/.credentials.json"
        live.unlink()
        live.write_text("account two refreshed")
        (self.bin / "claude-switch.py").write_text("old version")
        result = self.run_install()
        self.assertIn("当前账号 2", result.stdout)
        self.assertEqual((self.bin / "claude-switch.py").read_bytes(), (SOURCE / "claude-switch.py").read_bytes())
        self.assertEqual((self.accounts / "account-2/.credentials.json").read_text(), "account two refreshed")
        self.assert_linked_to("2")

    def test_install_migrates_old_accounts_and_removes_old_wrapper(self):
        old = self.home / ".claude-account3"
        old.mkdir()
        (old / "projects").symlink_to(self.home / ".claude/projects")
        (old / ".credentials.json").write_text("account three login")
        (old / ".claude.json").write_text("account three metadata")
        wrapper = self.home / ".local/share/claude-switch"
        (wrapper / "bin").mkdir(parents=True)
        (wrapper / "bin/claude").symlink_to("../launcher.py")
        (wrapper / "launcher.py").write_text("old")
        (self.home / ".config/claude-switch").mkdir(parents=True)
        (self.home / ".config/claude-switch/current").write_text("3\n")
        zshrc = 'export PATH="$HOME/.local/share/claude-switch/bin:$PATH"\n'
        (self.home / ".zshrc").write_text(zshrc)
        (self.home / ".bashrc").write_text("# " + zshrc)
        result = self.run_install()
        migrated = self.accounts / "account-3"
        self.assertEqual((migrated / ".credentials.json").read_text(), "account three login")
        self.assertEqual((migrated / ".claude.json").read_text(), "account three metadata")
        self.assertFalse((migrated / "projects").exists())
        self.assertTrue(old.is_dir())
        self.assertFalse(wrapper.exists())
        self.assertFalse((self.home / ".config/claude-switch").exists())
        self.assertIn("迁移账号 3", result.stdout)
        self.assertIn("~/.zshrc 中仍有旧包装器的 PATH 段", result.stdout)
        self.assertNotIn("~/.bashrc", result.stdout)
        self.assertEqual((self.home / ".zshrc").read_text(), zshrc)
        self.assertEqual((self.accounts / "current").read_text(), "1\n")

    def test_old_wrapper_directory_with_other_files_is_kept(self):
        wrapper = self.home / ".local/share/claude-switch"
        wrapper.mkdir(parents=True)
        (wrapper / "README.md").write_text("old")
        (wrapper / "notes.txt").write_text("user notes")
        result = self.run_install()
        self.assertEqual(list(wrapper.iterdir()), [wrapper / "notes.txt"])
        self.assertIn("旧包装器目录中还有其他文件", result.stdout)

    def test_failed_update_keeps_old_program(self):
        installed = self.bin / "claude-switch.py"
        installed.write_text("old version")
        real_replace = os.replace

        def failing_replace(source, destination):
            if Path(destination).name == "claude-switch.py":
                raise OSError("injected replace failure")
            return real_replace(source, destination)

        with patch.dict(os.environ, {"HOME": str(self.home)}), patch.object(installer.os, "replace", failing_replace):
            with self.assertRaisesRegex(OSError, "injected replace failure"):
                installer.install()
        self.assertEqual(installed.read_text(), "old version")
        self.assertEqual(list(self.bin.glob(".claude-switch.py-*")), [])

    def test_install_refuses_symlinked_accounts_directory(self):
        saved = self.home / "saved-accounts"
        self.accounts.rename(saved)
        self.accounts.symlink_to(saved)
        self.assertIn("账号目录是符号链接", self.run_install(success=False).stderr)

    def test_install_requires_native_claude(self):
        (self.bin / "claude").unlink()
        self.assertIn("官方 Claude 未安装", self.run_install(success=False).stderr)


if __name__ == "__main__":
    unittest.main()
