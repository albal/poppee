"""Polls every account and decides what deserves a notification."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import auth
from .config import Account, Config
from .gmail import AuthError, GmailClient, GmailError, Message, inbox_url
from .notify import Notification, Notifier
from .state import State

log = logging.getLogger(__name__)

RECENT_LIMIT = 10  # messages kept per account for the preview window
FETCH_LIMIT = 25  # new messages fetched per account per check
SEEN_LIMIT = 2000  # message ids remembered per account
MAX_WORKERS = 4

ClientFactory = Callable[[Account], GmailClient]


def default_client_factory(account: Account) -> GmailClient:
    return GmailClient(auth.session_for(account.email))


@dataclass
class AccountResult:
    account: Account
    unread: int = 0
    more: bool = False
    new: list[Message] = field(default_factory=list)
    recent: list[Message] = field(default_factory=list)
    error: str | None = None

    @property
    def count_label(self) -> str:
        return f"{self.unread}+" if self.more else str(self.unread)


class Checker:
    def __init__(
        self,
        config: Config,
        state: State,
        notifier: Notifier,
        client_factory: ClientFactory | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.config = config
        self.state = state
        self.notifier = notifier
        self.client_factory = client_factory or default_client_factory
        self.clock = clock
        self.results: list[AccountResult] = []
        self._clients: dict[str, GmailClient] = {}
        self._lock = threading.Lock()

    def check_all(self, notify: bool = True) -> list[AccountResult]:
        with self._lock:
            accounts = [a for a in self.config.accounts if a.enabled]
            if accounts:
                with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(accounts))) as pool:
                    results = list(pool.map(self.check_account, accounts))
            else:
                results = []
            self.state.prune({a.key for a in self.config.accounts})
            self.state.save()
            if notify and self.config.notifications:
                self._notify(results)
            self.results = results
            return results

    def _client(self, account: Account) -> GmailClient:
        client = self._clients.get(account.key)
        if client is None:
            client = self._clients[account.key] = self.client_factory(account)
        return client

    def check_account(self, account: Account) -> AccountResult:
        result = AccountResult(account)
        st = self.state.account(account.email)
        st["name"] = account.name
        st["email"] = account.email
        try:
            client = self._client(account)
            ids, more = client.unread_ids(account.query)
            now = self.clock()
            if st.get("query") != account.query:
                # First check, or the search changed: treat what's there now as already seen.
                st["query"] = account.query
                st["baseline"] = 0.0 if self.config.notify_existing_on_start else now
                seen: set[str] = set() if self.config.notify_existing_on_start else set(ids)
            else:
                seen = set(st.get("seen", []))
            baseline = float(st.get("baseline", 0.0))

            cache = {m["id"]: Message.from_dict(m) for m in st.get("recent", [])}
            candidates = [i for i in ids if i not in seen][:FETCH_LIMIT]
            for msg_id in dict.fromkeys(candidates + ids[:RECENT_LIMIT]):
                if msg_id not in cache:
                    try:
                        cache[msg_id] = client.message(msg_id)
                    except AuthError:
                        raise
                    except GmailError as e:  # e.g. deleted between list and fetch
                        log.debug("%s: skipping message %s: %s", account.email, msg_id, e)

            # Messages older than the baseline were already there before Poppee started
            # watching (e.g. old unread mail scrolling into the first page of results).
            result.new = [
                cache[i] for i in candidates if i in cache and cache[i].timestamp >= baseline
            ]
            result.recent = [cache[i] for i in ids[:RECENT_LIMIT] if i in cache]
            result.unread, result.more = len(ids), more

            st["seen"] = list(dict.fromkeys(ids + st.get("seen", [])))[:SEEN_LIMIT]
            st.update(
                unread=result.unread,
                more=more,
                error=None,
                last_check=now,
                recent=[m.to_dict() for m in result.recent],
            )
        except AuthError as e:
            self._clients.pop(account.key, None)
            result.error = f"Sign-in needed: {e}"
        except GmailError as e:
            result.error = str(e)
        except Exception as e:  # never let one account break the loop
            log.exception("Unexpected error checking %s", account.email)
            self._clients.pop(account.key, None)
            result.error = f"{type(e).__name__}: {e}"

        if result.error:
            log.warning("%s: %s", account.email, result.error)
            st["error"] = result.error
            st["last_check"] = self.clock()
            result.unread, result.more = st.get("unread", 0), st.get("more", False)
            result.recent = [Message.from_dict(m) for m in st.get("recent", [])]
        return result

    def _notify(self, results: list[AccountResult]) -> None:
        for result in results:
            if result.account.notify and result.new:
                for n in build_notifications(result, self.config.max_notifications):
                    self.notifier.send(n)


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_notifications(result: AccountResult, max_individual: int) -> list[Notification]:
    account = result.account
    new = sorted(result.new, key=lambda m: m.timestamp)
    if len(new) <= max_individual:
        return [
            Notification(
                title=_trim(f"{m.sender} · {account.name}", 80),
                body=_trim(f"{m.subject}\n{m.snippet}".strip(), 240),
                url=m.url(account.email),
            )
            for m in new
        ]
    shown = new[-5:][::-1]  # newest first
    lines = [_trim(f"{m.sender}: {m.subject}", 80) for m in shown]
    if len(new) > len(shown):
        lines.append(f"…and {len(new) - len(shown)} more")
    return [
        Notification(
            title=f"{len(new)} new messages · {account.name}",
            body="\n".join(lines),
            url=inbox_url(account.email),
        )
    ]
