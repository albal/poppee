"""Minimal Gmail REST API client (just what a notifier needs)."""

from __future__ import annotations

import html
from dataclasses import asdict, dataclass
from email.utils import parseaddr
from typing import Protocol
from urllib.parse import quote

import requests
from google.auth.exceptions import RefreshError, TransportError

API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailError(Exception):
    """A request to Gmail failed."""


class AuthError(GmailError):
    """The account needs to be signed in again."""


class Session(Protocol):
    def get(self, url: str, params=None, timeout: float | None = None): ...


def inbox_url(email: str) -> str:
    return f"https://mail.google.com/mail/?authuser={quote(email)}#inbox"


@dataclass(frozen=True)
class Message:
    id: str
    thread_id: str
    sender: str
    sender_email: str
    subject: str
    snippet: str
    timestamp: float  # seconds since the epoch, when Gmail received it

    def url(self, account_email: str) -> str:
        return f"https://mail.google.com/mail/?authuser={quote(account_email)}#all/{self.thread_id}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Message:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})


class GmailClient:
    def __init__(self, session: Session, timeout: float = 30):
        self.session = session
        self.timeout = timeout

    def _get(self, path: str, params=None) -> dict:
        try:
            resp = self.session.get(API_ROOT + path, params=params, timeout=self.timeout)
        except RefreshError as e:
            raise AuthError(f"sign-in expired or revoked ({e}) - run `poppee add-account`") from e
        except (requests.RequestException, TransportError) as e:
            raise GmailError(f"network error: {e}") from e

        if resp.status_code >= 400:
            try:
                detail = resp.json()["error"]["message"]
            except Exception:
                detail = resp.text[:200] if hasattr(resp, "text") else ""
            if resp.status_code == 401:
                raise AuthError(f"sign-in rejected: {detail}")
            raise GmailError(f"HTTP {resp.status_code}: {detail}")
        return resp.json()

    def email_address(self) -> str:
        return self._get("/profile")["emailAddress"]

    def unread_ids(self, query: str, limit: int = 100) -> tuple[list[str], bool]:
        """Return up to ``limit`` matching message ids (newest first) and whether there are more."""
        data = self._get("/messages", {"q": query, "maxResults": limit})
        ids = [m["id"] for m in data.get("messages", [])]
        return ids, bool(data.get("nextPageToken"))

    def message(self, msg_id: str) -> Message:
        data = self._get(
            f"/messages/{msg_id}",
            [("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject")],
        )
        headers = {
            h.get("name", "").lower(): h.get("value", "")
            for h in data.get("payload", {}).get("headers", [])
        }
        name, address = parseaddr(headers.get("from", ""))
        return Message(
            id=data["id"],
            thread_id=data.get("threadId", data["id"]),
            sender=name or address or "(unknown sender)",
            sender_email=address,
            subject=headers.get("subject", "").strip() or "(no subject)",
            snippet=html.unescape(data.get("snippet", "")).strip(),
            timestamp=int(data.get("internalDate", 0)) / 1000,
        )
