from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from poppee.gmail import GmailError, Message


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Never touch the real user config/data directories."""
    monkeypatch.setenv("POPPEE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("POPPEE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def make_message(msg_id: str, ts: float = 1000.0, sender="Forum", subject=None) -> Message:
    return Message(
        id=msg_id,
        thread_id=f"t{msg_id}",
        sender=sender,
        sender_email="noreply@forum.example",
        subject=subject or f"Subject {msg_id}",
        snippet=f"Snippet {msg_id}",
        timestamp=ts,
    )


@dataclass
class FakeClient:
    """Stands in for GmailClient: ``inbox`` is a list of messages, newest first."""

    inbox: list[Message] = field(default_factory=list)
    more: bool = False
    error: Exception | None = None
    fetched: list[str] = field(default_factory=list)

    def unread_ids(self, query, limit=100):
        if self.error:
            raise self.error
        return [m.id for m in self.inbox][:limit], self.more

    def message(self, msg_id):
        self.fetched.append(msg_id)
        for m in self.inbox:
            if m.id == msg_id:
                return m
        raise GmailError("HTTP 404: not found")


class RecordingNotifier:
    name = "recording"

    def __init__(self):
        self.sent = []

    def send(self, n):
        self.sent.append(n)
        return True
