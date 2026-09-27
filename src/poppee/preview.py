"""PopPeeper-style preview window listing recent unread mail for every account.

It runs as its own process and reads ``state.json``, so it never interferes with
the tray icon's event loop (which must own the main thread on macOS).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import APP_NAME
from .gmail import Message, inbox_url
from .state import State
from .util import open_url


@dataclass
class Section:
    name: str
    email: str
    unread: int
    more: bool
    error: str | None
    messages: list[Message] = field(default_factory=list)


def load_sections(state_path: Path) -> list[Section]:
    sections = []
    for key, st in State(state_path, readonly=True).data["accounts"].items():
        sections.append(
            Section(
                name=st.get("name") or key,
                email=st.get("email") or key,
                unread=st.get("unread", 0),
                more=st.get("more", False),
                error=st.get("error"),
                messages=[Message.from_dict(m) for m in st.get("recent", [])],
            )
        )
    return sections


def format_age(timestamp: float, now: float | None = None) -> str:
    delta = max(0, (now if now is not None else time.time()) - timestamp)
    if delta < 60:
        return "now"
    for size, unit in ((86400 * 7, "w"), (86400, "d"), (3600, "h"), (60, "m")):
        if delta >= size:
            return f"{int(delta // size)}{unit}"
    return "now"


def as_text(sections: list[Section]) -> str:
    if not sections:
        return "No mail checked yet. Is `poppee run` running?"
    out = []
    for s in sections:
        count = f"{s.unread}{'+' if s.more else ''}"
        out.append(
            f"== {s.name} <{s.email}> - {count} unread" + (f" [{s.error}]" if s.error else "")
        )
        for m in s.messages:
            out.append(f"  {format_age(m.timestamp):>4}  {m.sender}: {m.subject}")
    return "\n".join(out)


def show(state_path: Path) -> None:
    try:
        import tkinter as tk
    except ImportError:
        print(as_text(load_sections(state_path)))
        return
    PreviewWindow(tk, state_path).run()


class PreviewWindow:
    WIDTH, HEIGHT = 440, 560
    REFRESH_MS = 15000

    def __init__(self, tk, state_path: Path):
        self.tk = tk
        self.state_path = state_path
        self._mtime = None
        root = self.root = tk.Tk()
        root.title(f"{APP_NAME} - recent mail")
        root.configure(bg="white")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = sw - self.WIDTH - 24, sh - self.HEIGHT - 72
        root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{max(0, x)}+{max(0, y)}")
        root.bind("<Escape>", lambda e: root.destroy())

        bar = tk.Frame(root, bg="#f1f3f4")
        bar.pack(side="bottom", fill="x")
        tk.Button(bar, text="Close", command=root.destroy).pack(side="right", padx=6, pady=6)
        tk.Button(bar, text="Refresh", command=self.render).pack(side="right", pady=6)
        self.status = tk.Label(bar, bg="#f1f3f4", fg="#5f6368", anchor="w")
        self.status.pack(side="left", padx=8)

        self.canvas = tk.Canvas(root, bg="white", highlightthickness=0)
        scroll = tk.Scrollbar(root, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg="white")
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width)
        )
        root.bind_all("<MouseWheel>", self._on_wheel)
        root.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        root.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

    def _on_wheel(self, event) -> None:
        step = -1 * (event.delta // 120 if abs(event.delta) >= 120 else event.delta)
        self.canvas.yview_scroll(int(step), "units")

    def _clickable(self, widgets, url: str) -> None:
        for w in widgets:
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda e, u=url: open_url(u))

    def render(self) -> None:
        tk = self.tk
        for child in self.inner.winfo_children():
            child.destroy()
        sections = load_sections(self.state_path)
        now = time.time()
        if not sections:
            tk.Label(self.inner, text=as_text([]), bg="white", fg="#5f6368", pady=40).pack()
        for s in sections:
            head = tk.Frame(self.inner, bg="#e8f0fe")
            head.pack(fill="x", pady=(8, 0))
            count = f"{s.unread}{'+' if s.more else ''} unread"
            title = tk.Label(
                head,
                text=f"{s.name}   {count}",
                bg="#e8f0fe",
                fg="#174ea6",
                font=("TkDefaultFont", 11, "bold"),
                anchor="w",
                padx=8,
                pady=4,
            )
            title.pack(side="left", fill="x", expand=True)
            self._clickable([head, title], inbox_url(s.email))
            if s.error:
                tk.Label(
                    self.inner,
                    text=s.error,
                    fg="#d93025",
                    bg="white",
                    anchor="w",
                    wraplength=self.WIDTH - 40,
                    justify="left",
                    padx=8,
                ).pack(fill="x")
            for m in s.messages:
                row = tk.Frame(self.inner, bg="white", padx=8, pady=4)
                row.pack(fill="x")
                top = tk.Frame(row, bg="white")
                top.pack(fill="x")
                sender = tk.Label(
                    top, text=m.sender, bg="white", anchor="w", font=("TkDefaultFont", 10, "bold")
                )
                sender.pack(side="left")
                age = tk.Label(top, text=format_age(m.timestamp, now), bg="white", fg="#5f6368")
                age.pack(side="right")
                subject = tk.Label(
                    row,
                    text=m.subject,
                    bg="white",
                    anchor="w",
                    justify="left",
                    wraplength=self.WIDTH - 40,
                )
                subject.pack(fill="x")
                snippet = tk.Label(
                    row,
                    text=m.snippet[:160],
                    bg="white",
                    fg="#5f6368",
                    anchor="w",
                    justify="left",
                    wraplength=self.WIDTH - 40,
                )
                snippet.pack(fill="x")
                self._clickable([row, top, sender, age, subject, snippet], m.url(s.email))
            if not s.messages and not s.error:
                tk.Label(
                    self.inner, text="No unread mail", bg="white", fg="#5f6368", anchor="w", padx=8
                ).pack(fill="x")
        total = sum(s.unread for s in sections)
        self.status.configure(text=f"{total} unread · updated {time.strftime('%H:%M')}")

    def _poll(self) -> None:
        try:
            mtime = self.state_path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self._mtime:
            self._mtime = mtime
            self.render()
        self.root.after(self.REFRESH_MS, self._poll)

    def run(self) -> None:
        self._poll()
        self.root.lift()
        self.root.focus_force()
        self.root.mainloop()
