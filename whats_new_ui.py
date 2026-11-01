"""Simple What's New window (CHANGELOG + Got it)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext

from app_version import load_changelog_text, load_release_info
from paths import resource_path
from settings import AppSettings, save_settings
from theme import BG, BORDER, CARD, MUTED, TEXT
from win_app_icon import apply_tk_icon

APP_ICON = resource_path("assets", "app.ico")


class WhatsNewWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        settings: AppSettings,
        on_seen: Callable[[AppSettings], None] | None = None,
    ) -> None:
        super().__init__(parent)
        release = load_release_info()
        self.title(f"What's New — v{release.version}")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(360, 320)
        self.settings = settings
        self._on_seen = on_seen

        self.transient(parent)
        apply_tk_icon(self, APP_ICON)

        outer = tk.Frame(self, bg=BG, padx=18, pady=18)
        outer.pack(fill="both", expand=True)

        tk.Label(
            outer,
            text=f"v{release.version}",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 14),
            anchor="w",
        ).pack(fill="x")
        if release.title:
            tk.Label(
                outer,
                text=release.title,
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 9),
                anchor="w",
                wraplength=420,
                justify="left",
            ).pack(fill="x", pady=(4, 12))

        body = tk.Frame(
            outer,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        body.pack(fill="both", expand=True)

        text = scrolledtext.ScrolledText(
            body,
            wrap="word",
            font=("Segoe UI", 9),
            bg=CARD,
            fg=TEXT,
            relief="flat",
            padx=10,
            pady=10,
            height=16,
        )
        text.pack(fill="both", expand=True, padx=1, pady=1)
        text.insert("1.0", load_changelog_text())
        text.configure(state="disabled")

        btn_row = tk.Frame(outer, bg=BG)
        btn_row.pack(fill="x", pady=(12, 0))
        tk.Button(
            btn_row,
            text="Got it",
            command=self._on_got_it,
            font=("Segoe UI", 9),
            padx=16,
            pady=4,
        ).pack(side="right")

        self.geometry("440x420")

    def _on_got_it(self) -> None:
        release = load_release_info()
        self.settings.last_seen_version = release.version
        save_settings(self.settings)
        if self._on_seen is not None:
            self._on_seen(self.settings)
        self.destroy()


_open_window: WhatsNewWindow | None = None


def open_whats_new(
    parent: tk.Misc,
    settings: AppSettings,
    on_seen: Callable[[AppSettings], None] | None = None,
) -> WhatsNewWindow:
    global _open_window
    if _open_window is not None and _open_window.winfo_exists():
        _open_window.lift()
        _open_window.focus_force()
        return _open_window

    win = WhatsNewWindow(parent, settings, on_seen=on_seen)

    def _clear(event: object) -> None:
        global _open_window
        if getattr(event, "widget", None) is win:
            _open_window = None

    win.bind("<Destroy>", _clear)
    _open_window = win
    return win
