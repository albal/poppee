"""Small cross-platform helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def subprocess_env() -> dict[str, str]:
    """Environment for child processes.

    PyInstaller's Linux bootloader points LD_LIBRARY_PATH at the bundled libraries;
    system tools like notify-send and xdg-open must not inherit that.
    """
    env = dict(os.environ)
    if is_frozen() and sys.platform.startswith("linux"):
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is not None:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def self_command(*args: str, gui: bool = False) -> list[str]:
    """Command line that runs Poppee itself with ``args``."""
    if is_frozen():
        exe = Path(sys.executable)
        if gui and sys.platform == "win32":
            tray = exe.with_name("poppee-tray.exe")
            if tray.exists():
                exe = tray
        return [str(exe), *args]
    python = Path(sys.executable)
    if gui and sys.platform == "win32":
        pythonw = python.with_name("pythonw.exe")
        if pythonw.exists():
            python = pythonw
    return [str(python), "-m", "poppee", *args]


def spawn(cmd: list[str]) -> None:
    """Start a detached background process."""
    kwargs: dict = {
        "env": subprocess_env(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def open_url(url: str) -> None:
    if sys.platform.startswith("linux") and shutil.which("xdg-open"):
        spawn(["xdg-open", url])
    else:
        webbrowser.open(url)


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        spawn(["open", str(path)])
    else:
        spawn(["xdg-open", str(path)])


class SingleInstance:
    """Advisory lock file so only one Poppee checks the accounts at a time."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")  # noqa: SIM115 - held open for the process lifetime
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True
