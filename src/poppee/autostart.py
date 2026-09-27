"""Start Poppee automatically at login (per user, no admin rights needed)."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import APP_NAME
from .util import self_command

LABEL = "io.github.poppee"


class LinuxAutostart:
    """XDG autostart entry, honoured by GNOME, KDE, Xfce, Cinnamon, ..."""

    def __init__(self, config_home: Path | None = None):
        base = config_home or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        self.path = base / "autostart" / "poppee.desktop"

    @staticmethod
    def _quote(arg: str) -> str:
        if not any(c in arg for c in " \t\n\"'\\><~|&;$*?#()`"):
            return arg
        escaped = "".join("\\" + c if c in '"`$\\' else c for c in arg)
        return f'"{escaped}"'

    def entry(self, cmd: list[str]) -> str:
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            "Comment=Gmail notifier\n"
            f"Exec={' '.join(self._quote(a) for a in cmd)}\n"
            "Icon=mail-unread\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            "X-GNOME-Autostart-Delay=10\n"
        )

    def enable(self, cmd: list[str]) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.entry(cmd), encoding="utf-8")
        return str(self.path)

    def disable(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False

    def is_enabled(self) -> bool:
        return self.path.exists()


class MacAutostart:
    """launchd LaunchAgent in ~/Library/LaunchAgents."""

    def __init__(self, home: Path | None = None):
        self.path = (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"

    def plist(self, cmd: list[str]) -> bytes:
        return plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": cmd,
                "RunAtLoad": True,
                "ProcessType": "Interactive",
            }
        )

    def enable(self, cmd: list[str]) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self.plist(cmd))
        return str(self.path)

    def disable(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False

    def is_enabled(self) -> bool:
        return self.path.exists()


class WindowsAutostart:
    """HKCU ...\\CurrentVersion\\Run registry value."""

    KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self, winreg=None):
        if winreg is None:
            import winreg as _winreg

            winreg = _winreg
        self.winreg = winreg

    def enable(self, cmd: list[str]) -> str:
        w = self.winreg
        with w.CreateKey(w.HKEY_CURRENT_USER, self.KEY) as key:
            w.SetValueEx(key, APP_NAME, 0, w.REG_SZ, subprocess.list2cmdline(cmd))
        return f"HKCU\\{self.KEY}\\{APP_NAME}"

    def disable(self) -> bool:
        w = self.winreg
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, self.KEY, 0, w.KEY_SET_VALUE) as key:
                w.DeleteValue(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False

    def is_enabled(self) -> bool:
        w = self.winreg
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, self.KEY) as key:
                w.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False


def get_autostart(platform: str = sys.platform):
    if platform == "win32":
        return WindowsAutostart()
    if platform == "darwin":
        return MacAutostart()
    return LinuxAutostart()


def launch_command() -> list[str]:
    return self_command("run", gui=True)
