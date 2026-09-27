"""Command-line interface. Running ``poppee`` with no arguments starts the tray app."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import shutil
import sys
import threading
from pathlib import Path

from . import APP_NAME, __version__, auth, autostart, config, paths
from .checker import Checker
from .notify import Notification, get_notifier
from .state import State
from .util import SingleInstance, open_path

log = logging.getLogger("poppee")

NEXT_STEPS = """\
Next steps:
  1. In Google Cloud Console create a project, enable the Gmail API and create an
     OAuth client of type "Desktop app" (full walkthrough in the README).
  2. poppee init --client-secret ~/Downloads/client_secret_XXXX.json
  3. poppee add-account          (repeat for each Gmail account)
  4. poppee autostart enable     (optional: start at login)
  5. poppee run
"""


def _setup_logging(verbose: bool, to_file: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        log_path = paths.log_file()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
        )
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    if not verbose:
        for noisy in ("urllib3", "google", "PIL"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _config_path(args) -> Path:
    return Path(args.config).expanduser() if args.config else paths.config_file()


def _load_config(args) -> config.Config:
    try:
        return config.load(_config_path(args))
    except config.ConfigError as e:
        raise SystemExit(f"error: {e}") from e


# Commands ---------------------------------------------------------------------


def cmd_init(args) -> int:
    path = _config_path(args)
    if config.write_template(path):
        print(f"Created {path}")
    else:
        print(f"Config already exists: {path}")
    if args.client_secret:
        src = Path(args.client_secret).expanduser()
        if not src.is_file():
            raise SystemExit(f"error: {src} does not exist")
        dest = config.load(path).client_secret_file
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        os.chmod(dest, 0o600)
        print(f"Installed OAuth client file as {dest}")
        print("Now run `poppee add-account` for each Gmail account.")
    else:
        print()
        print(NEXT_STEPS)
    return 0


def cmd_add_account(args) -> int:
    from google.auth.transport.requests import AuthorizedSession

    from .gmail import GmailClient

    path = _config_path(args)
    config.write_template(path)
    cfg = _load_config(args)
    try:
        creds = auth.authorize(cfg.client_secret_file, login_hint=args.email)
    except auth.AuthSetupError as e:
        raise SystemExit(f"error: {e}") from e
    email = GmailClient(AuthorizedSession(creds)).email_address()
    if args.email and args.email.lower() != email.lower():
        print(f"note: you signed in as {email}, not {args.email}")
    auth.save_credentials(email, creds)
    if cfg.find_account(email):
        print(f"Signed in to {email} again (account was already configured).")
    else:
        config.append_account(path, email, name=args.name, query=args.query)
        print(f"Added {email}. It will be checked from the next poll (or 'Reload config').")
    return 0


def cmd_remove_account(args) -> int:
    path = _config_path(args)
    removed = path.exists() and config.remove_account(path, args.email)
    token = auth.delete_credentials(args.email)
    if not (removed or token):
        print(f"{args.email} was not configured.")
        return 1
    print(f"Removed {args.email}" + (" (sign-in token deleted)" if token else ""))
    return 0


def cmd_list(args) -> int:
    cfg = _load_config(args)
    if not cfg.accounts:
        print("No accounts yet. Run `poppee add-account`.")
    for a in cfg.accounts:
        flags = [] if a.enabled else ["disabled"]
        if not a.notify:
            flags.append("no pop-ups")
        if not auth.has_token(a.email):
            flags.append("NOT SIGNED IN")
        extra = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{a.name} <{a.email}>  query: {a.query}{extra}")
    return 0


def cmd_check(args) -> int:
    cfg = _load_config(args)
    # Read-only state: a manual check must not swallow notifications the daemon would show.
    checker = Checker(
        cfg, State(paths.state_file(), readonly=True), get_notifier(cfg.click_to_open)
    )
    results = checker.check_all(notify=args.notify)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "name": r.account.name,
                        "email": r.account.email,
                        "unread": r.unread,
                        "more": r.more,
                        "error": r.error,
                        "recent": [m.to_dict() for m in r.recent],
                    }
                    for r in results
                ],
                indent=2,
            )
        )
    else:
        for r in results:
            status = f"ERROR: {r.error}" if r.error else f"{r.count_label} unread"
            print(f"{r.account.name} <{r.account.email}>: {status}")
            for m in r.recent[: args.show]:
                print(f"    {m.sender}: {m.subject}")
    return 1 if any(r.error for r in results) else 0


def _headless_loop(checker: Checker) -> None:
    stop = threading.Event()
    log.info("Running without a tray icon; press Ctrl+C to stop")
    try:
        while not stop.is_set():
            results = checker.check_all()
            log.info(
                "Checked %d account(s): %d unread", len(results), sum(r.unread for r in results)
            )
            stop.wait(checker.config.poll_interval)
    except KeyboardInterrupt:
        pass


def cmd_run(args) -> int:
    _setup_logging(args.verbose, to_file=True)
    path = _config_path(args)
    if config.write_template(path):
        log.info("Created default config at %s", path)
    cfg = _load_config(args)

    lock = SingleInstance(paths.lock_file())
    if not lock.acquire():
        log.error("%s is already running", APP_NAME)
        return 1

    checker = Checker(cfg, State(paths.state_file()), get_notifier(cfg.click_to_open))
    if not cfg.accounts:
        log.warning("No accounts configured yet - run `poppee add-account`")
    if not args.no_tray:
        from .tray import TrayApp, TrayUnavailable

        try:
            TrayApp(checker, path).run()
            return 0
        except TrayUnavailable as e:
            log.warning("Tray icon unavailable (%s); continuing without it", e)
    _headless_loop(checker)
    return 0


def cmd_preview(args) -> int:
    from . import preview

    if args.text:
        print(preview.as_text(preview.load_sections(paths.state_file())))
    else:
        preview.show(paths.state_file())
    return 0


def cmd_test_notify(args) -> int:
    cfg_path = _config_path(args)
    click = config.load(cfg_path).click_to_open if cfg_path.exists() else True
    notifier = get_notifier(click)
    ok = notifier.send(
        Notification(
            f"{APP_NAME} test",
            "Notifications are working. Click to open Gmail.",
            url="https://mail.google.com/",
        )
    )
    print(f"Sent via {notifier.name} backend" if ok else "Sending the notification failed")
    return 0 if ok else 1


def cmd_config(args) -> int:
    path = _config_path(args)
    if args.edit:
        config.write_template(path)
        open_path(path)
    print(path)
    if args.all:
        print(f"data:   {paths.data_dir()}")
        print(f"tokens: {paths.tokens_dir()}")
        print(f"log:    {paths.log_file()}")
    return 0


def cmd_autostart(args) -> int:
    target = autostart.get_autostart()
    if args.action == "enable":
        where = target.enable(autostart.launch_command())
        print(f"{APP_NAME} will start at login ({where})")
    elif args.action == "disable":
        print("Autostart disabled" if target.disable() else "Autostart was not enabled")
    else:
        print("enabled" if target.is_enabled() else "disabled")
    return 0


# Entry points -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="poppee", description=f"{APP_NAME}: a free multi-account Gmail notifier."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", help="path to config.toml (default: per-user config)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("init", help="create the config file and install the OAuth client file")
    p.add_argument("--client-secret", metavar="FILE", help="client_secret JSON from Google Cloud")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add-account", help="sign in to a Gmail account and add it")
    p.add_argument("--email", help="pre-select this Google account on the sign-in page")
    p.add_argument("--name", help="label shown in notifications (default: the address)")
    p.add_argument("--query", help="Gmail search to watch (default: 'is:unread in:inbox')")
    p.set_defaults(func=cmd_add_account)

    p = sub.add_parser("remove-account", help="remove an account and delete its sign-in token")
    p.add_argument("email")
    p.set_defaults(func=cmd_remove_account)

    p = sub.add_parser("list", help="list configured accounts")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("check", help="check all accounts once and print the result")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--notify", action="store_true", help="also show notifications for new mail")
    p.add_argument("--show", type=int, default=3, metavar="N", help="messages to list per account")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="run in the background with a tray icon (default)")
    p.add_argument("--no-tray", action="store_true", help="no tray icon, notifications only")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("preview", help="show the recent-mail window")
    p.add_argument("--text", action="store_true", help="print to the terminal instead")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("test-notify", help="show a test notification")
    p.set_defaults(func=cmd_test_notify)

    p = sub.add_parser("config", help="print (or --edit) the config file location")
    p.add_argument("--edit", action="store_true", help="open the config file in your editor")
    p.add_argument("--all", action="store_true", help="also print data, token and log paths")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("autostart", help="start Poppee when you log in")
    p.add_argument("action", choices=["enable", "disable", "status"])
    p.set_defaults(func=cmd_autostart)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windowed builds (pythonw, PyInstaller --windowed) have no console streams.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115

    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command is None:
        args = parser.parse_args([*(sys.argv[1:] if argv is None else argv), "run"])
    if args.command != "run":
        _setup_logging(args.verbose)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


def main_tray() -> int:
    return main()
