"""System tray icon (pystray). pystray is imported lazily so headless use never needs it."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from . import APP_NAME, config
from .checker import AccountResult, Checker
from .gmail import inbox_url
from .icon import render_icon
from .notify import Notification
from .util import open_path, open_url, self_command, spawn

log = logging.getLogger(__name__)


class TrayUnavailable(Exception):
    pass


def total_unread(results: list[AccountResult]) -> int:
    return sum(r.unread for r in results)


def tooltip(results: list[AccountResult]) -> str:
    total = total_unread(results)
    errors = sum(1 for r in results if r.error)
    text = f"{APP_NAME}: {total} unread" if results else f"{APP_NAME}: no accounts"
    if errors:
        text += f", {errors} with problems"
    return text[:63]  # Windows limits tray tooltips


def account_label(result: AccountResult) -> str:
    if result.error:
        return f"⚠ {result.account.name}: {result.error[:40]}"
    return f"{result.account.name}: {result.count_label} unread"


class TrayApp:
    def __init__(self, checker: Checker, config_path: Path):
        self.checker = checker
        self.config_path = config_path
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.icon = None

    def run(self) -> None:
        try:
            import pystray
        except Exception as e:  # e.g. no display, missing backend
            raise TrayUnavailable(str(e)) from e
        self._pystray = pystray
        self.icon = pystray.Icon(
            "poppee", render_icon(0), APP_NAME, menu=pystray.Menu(self._menu_items)
        )
        # pystray must own the main thread (required on macOS); polling runs in a worker.
        self.icon.run(setup=self._setup)

    def _setup(self, icon) -> None:
        icon.visible = True
        threading.Thread(target=self._loop, name="poller", daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.checker.check_all()
            except Exception:
                log.exception("Check failed")
            self._refresh()
            self._wake.wait(self.checker.config.poll_interval)
            self._wake.clear()

    def _refresh(self) -> None:
        results = self.checker.results
        all_failed = bool(results) and all(r.error for r in results)
        self.icon.icon = render_icon(total_unread(results), error=all_failed)
        self.icon.title = tooltip(results)
        self.icon.update_menu()

    # Menu -------------------------------------------------------------------

    def _menu_items(self):
        item, menu = self._pystray.MenuItem, self._pystray.Menu
        items = [item("Show recent mail", self._show_preview, default=True), menu.SEPARATOR]
        results = self.checker.results
        if results:
            items += [item(account_label(r), _opener(inbox_url(r.account.email))) for r in results]
        elif not self.checker.config.accounts:
            items.append(item("No accounts - run `poppee add-account`", None, enabled=False))
        else:
            items.append(item("Checking…", None, enabled=False))
        items += [
            menu.SEPARATOR,
            item("Check now", self._check_now),
            item("Open config file", self._open_config),
            item("Reload config", self._reload_config),
            menu.SEPARATOR,
            item("Quit", self._quit),
        ]
        yield from items

    def _show_preview(self, icon, item) -> None:
        spawn(self_command("preview", gui=True))

    def _check_now(self, icon, item) -> None:
        self._wake.set()

    def _open_config(self, icon, item) -> None:
        open_path(self.config_path)

    def _reload_config(self, icon, item) -> None:
        try:
            self.checker.config = config.load(self.config_path)
        except config.ConfigError as e:
            log.error("Reload failed: %s", e)
            self.checker.notifier.send(Notification(f"{APP_NAME}: config error", str(e)))
            return
        self._wake.set()

    def _quit(self, icon, item) -> None:
        self._stop.set()
        self._wake.set()
        icon.stop()


def _opener(url: str):
    def action(icon, item):
        open_url(url)

    return action
