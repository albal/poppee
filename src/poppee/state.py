"""Persistent per-account state shared by the checker, tray and preview window."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class State:
    def __init__(self, path: Path, readonly: bool = False):
        self.path = path
        self.readonly = readonly
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
                return data
        except (OSError, ValueError):
            pass
        return {"version": 1, "accounts": {}}

    def account(self, email: str) -> dict:
        with self._lock:
            return self.data["accounts"].setdefault(email.lower(), {})

    def prune(self, keep: set[str]) -> None:
        with self._lock:
            for key in list(self.data["accounts"]):
                if key not in keep:
                    del self.data["accounts"][key]

    def save(self) -> None:
        if self.readonly:
            return
        with self._lock:
            payload = json.dumps(self.data, indent=1, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)
