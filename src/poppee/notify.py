"""Native desktop notifications without extra dependencies.

* Linux (GNOME, KDE, ...): ``notify-send``, falling back to ``gdbus`` (freedesktop D-Bus)
* macOS: ``terminal-notifier`` when installed (clickable), otherwise ``osascript``
* Windows 10/11: toast notifications through PowerShell's WinRT bridge
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from html import escape

from . import APP_NAME
from .util import open_url, subprocess_env

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    url: str | None = None


class Notifier:
    name = "base"

    def send(self, n: Notification) -> bool:
        raise NotImplementedError


class LogNotifier(Notifier):
    name = "log"

    def send(self, n: Notification) -> bool:
        log.info("NOTIFY %s: %s", n.title, n.body)
        return True


class _CommandNotifier(Notifier):
    def __init__(self, which=shutil.which, run=subprocess.run, popen=subprocess.Popen):
        self.which = which
        self.run = run
        self.popen = popen

    def _run(self, cmd: list[str], **kwargs) -> bool:
        try:
            result = self.run(
                cmd,
                env=kwargs.pop("env", subprocess_env()),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
                **kwargs,
            )
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("%s failed: %s", cmd[0], e)
            return False
        if result.returncode != 0:
            log.warning("%s exited with %s: %s", cmd[0], result.returncode, result.stderr)
        return result.returncode == 0


class LinuxNotifier(_CommandNotifier):
    name = "linux"
    MAX_WAITING = 10  # notify-send processes kept alive waiting for a click

    def __init__(self, click_to_open: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.click_to_open = click_to_open
        self._supports_actions: bool | None = None
        self._waiting = threading.BoundedSemaphore(self.MAX_WAITING)

    def send(self, n: Notification) -> bool:
        if self.which("notify-send"):
            return self._notify_send(n)
        if self.which("gdbus"):
            return self._gdbus(n)
        log.warning("Neither notify-send nor gdbus found; install libnotify-bin")
        return False

    def _base_cmd(self) -> list[str]:
        return [
            "notify-send",
            f"--app-name={APP_NAME}",
            "--icon=mail-unread",
            "--category=email.arrived",
        ]

    def actions_supported(self) -> bool:
        if self._supports_actions is None:
            try:
                out = self.run(
                    ["notify-send", "--help"],
                    env=subprocess_env(),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self._supports_actions = "--action" in (out.stdout or "")
            except (OSError, subprocess.SubprocessError):
                self._supports_actions = False
        return self._supports_actions

    def _notify_send(self, n: Notification) -> bool:
        # The body is interpreted as markup by most notification servers.
        body = escape(n.body, quote=False)
        if (
            n.url
            and self.click_to_open
            and self.actions_supported()
            and self._waiting.acquire(blocking=False)
        ):
            cmd = [*self._base_cmd(), "--action=default=Open", "--wait", "--", n.title, body]
            try:
                proc = self.popen(
                    cmd,
                    env=subprocess_env(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            except OSError as e:
                self._waiting.release()
                log.warning("notify-send failed: %s", e)
                return False
            threading.Thread(target=self._await_click, args=(proc, n.url), daemon=True).start()
            return True
        return self._run([*self._base_cmd(), "--", n.title, body])

    def _await_click(self, proc, url: str) -> None:
        try:
            out, _ = proc.communicate()
            if (out or "").strip() == "default":
                open_url(url)
        finally:
            self._waiting.release()

    def _gdbus(self, n: Notification) -> bool:
        # gdbus parses each argument as GVariant text; JSON strings are valid GVariant strings.
        return self._run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.Notifications",
                "--object-path",
                "/org/freedesktop/Notifications",
                "--method",
                "org.freedesktop.Notifications.Notify",
                json.dumps(APP_NAME),
                "0",
                json.dumps("mail-unread"),
                json.dumps(n.title),
                json.dumps(escape(n.body, quote=False)),
                "[]",
                "{}",
                "-1",
            ]  # fmt: skip
        )


class MacNotifier(_CommandNotifier):
    name = "macos"

    _APPLESCRIPT = [
        "on run argv",
        'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"',
        "end run",
    ]

    def __init__(self, click_to_open: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.click_to_open = click_to_open

    def send(self, n: Notification) -> bool:
        if self.which("terminal-notifier"):
            # Prefix to stop terminal-notifier treating a leading "-" or "[" specially.
            cmd = ["terminal-notifier", "-title", n.title, "-message", "​" + n.body]
            cmd += ["-sound", "Glass"]
            if n.url and self.click_to_open:
                cmd += ["-open", n.url]
            return self._run(cmd)
        cmd = ["osascript"]
        for line in self._APPLESCRIPT:
            cmd += ["-e", line]
        # Arguments are passed as argv, so nothing needs escaping.
        return self._run([*cmd, n.title, n.body])


class WindowsNotifier(_CommandNotifier):
    name = "windows"

    # Toasts must be attributed to a registered app; PowerShell's AppUserModelID always is.
    APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    SCRIPT = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType = WindowsRuntime] | Out-Null;"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$xml.LoadXml($env:POPPEE_TOAST_XML);"
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml;"
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        "CreateToastNotifier($env:POPPEE_TOAST_APP).Show($toast)"
    )

    def __init__(self, click_to_open: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.click_to_open = click_to_open

    def toast_xml(self, n: Notification) -> str:
        launch = ""
        if n.url and self.click_to_open:
            launch = f' activationType="protocol" launch="{escape(n.url)}"'
        return (
            f'<toast{launch}><visual><binding template="ToastGeneric">'
            f"<text>{escape(n.title)}</text><text>{escape(n.body)}</text>"
            f'<text placement="attribution">{APP_NAME}</text>'
            '</binding></visual><audio src="ms-winsoundevent:Notification.Mail"/></toast>'
        )

    def send(self, n: Notification) -> bool:
        env = subprocess_env()
        # Passing data through the environment avoids PowerShell quoting pitfalls.
        env["POPPEE_TOAST_XML"] = self.toast_xml(n)
        env["POPPEE_TOAST_APP"] = self.APP_ID
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
        kwargs = {"env": env}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return self._run([*cmd, "-Command", self.SCRIPT], **kwargs)


def get_notifier(click_to_open: bool = True, platform: str = sys.platform) -> Notifier:
    if platform == "win32":
        return WindowsNotifier(click_to_open=click_to_open)
    if platform == "darwin":
        return MacNotifier(click_to_open=click_to_open)
    if platform.startswith(("linux", "freebsd", "openbsd")):
        return LinuxNotifier(click_to_open=click_to_open)
    return LogNotifier()
