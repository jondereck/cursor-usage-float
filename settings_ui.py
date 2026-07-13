"""LAYOUT settings window for the Cursor usage floater."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from settings import (
    DENSITY_OPTIONS,
    METRIC_OPTIONS,
    AppSettings,
    save_settings,
)
from theme import ACCENT, BG, BORDER, CARD, MUTED, TEXT

DENSITY_LABELS = {
    "full": "Full (Total + Auto + API)",
    "compact": "Compact (Total only)",
    "minimal": "Minimal (pill — percentage only)",
}

METRIC_LABELS = {
    "total": "Total",
    "auto": "Auto + Composer",
    "api": "API",
    "worst": "Worst (highest %)",
}


class SettingsWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        settings: AppSettings,
        on_change: Callable[[AppSettings], None],
    ) -> None:
        super().__init__(parent)
        self.title("Cursor Usage Widget")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.settings = settings
        self._on_change = on_change
        self._updating = False

        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        outer = tk.Frame(self, bg=BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        title = tk.Label(
            outer,
            text="Cursor Usage Widget",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        )
        title.pack(fill="x")

        subtitle = tk.Label(
            outer,
            text="Cosmetic and behavior options. Changes apply live.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        subtitle.pack(fill="x", pady=(4, 14))

        card = tk.Frame(outer, bg=CARD, padx=14, pady=14, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x")

        section = tk.Label(
            card,
            text="LAYOUT",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        section.pack(fill="x", pady=(0, 10))

        self._density_var = tk.StringVar(value=settings.density)
        self._metric_var = tk.StringVar(value=settings.minimized_metric)

        self._add_dropdown(
            card,
            "Density",
            self._density_var,
            [(k, DENSITY_LABELS[k]) for k in DENSITY_OPTIONS],
            self._on_density,
        )
        self._add_dropdown(
            card,
            "Minimized %",
            self._metric_var,
            [(k, METRIC_LABELS[k]) for k in METRIC_OPTIONS],
            self._on_metric,
        )

        toggles = [
            ("always_on_top", "Always on top"),
            ("click_through", "Click-through"),
            ("show_header", "Show header"),
            ("show_reset_countdown", "Show reset countdown"),
            ("show_stale_badge", "Show stale-data badge"),
            ("start_minimized", "Start minimized"),
        ]
        self._bool_vars: dict[str, tk.BooleanVar] = {}
        for attr, label in toggles:
            var = tk.BooleanVar(value=bool(getattr(settings, attr)))
            self._bool_vars[attr] = var
            self._add_toggle(card, label, var, attr)

        self.update_idletasks()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")

    def _add_dropdown(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.StringVar,
        choices: list[tuple[str, str]],
        command: Callable[[], None],
    ) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(0, 10))
        tk.Label(
            row,
            text=label,
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x")

        display_to_key = {label_text: key for key, label_text in choices}
        key_to_display = {key: label_text for key, label_text in choices}
        display_var = tk.StringVar(value=key_to_display.get(variable.get(), choices[0][1]))

        combo = ttk.Combobox(
            row,
            textvariable=display_var,
            values=[label_text for _, label_text in choices],
            state="readonly",
            font=("Segoe UI", 9),
        )
        combo.pack(fill="x", pady=(4, 0))

        def on_select(_event: object | None = None) -> None:
            if self._updating:
                return
            key = display_to_key.get(display_var.get())
            if key is None:
                return
            variable.set(key)
            command()

        combo.bind("<<ComboboxSelected>>", on_select)

    def _add_toggle(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.BooleanVar,
        attr: str,
    ) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=4)
        tk.Label(
            row,
            text=label,
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side="left")

        def on_toggle() -> None:
            if self._updating:
                return
            setattr(self.settings, attr, bool(variable.get()))
            self._persist()

        # Simple custom toggle using Checkbutton styled as switch-ish
        chk = tk.Checkbutton(
            row,
            variable=variable,
            command=on_toggle,
            bg=CARD,
            activebackground=CARD,
            selectcolor=CARD,
            fg=ACCENT,
            activeforeground=ACCENT,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        chk.pack(side="right")

    def _on_density(self) -> None:
        self.settings.density = self._density_var.get()
        self._persist()

    def _on_metric(self) -> None:
        self.settings.minimized_metric = self._metric_var.get()
        self._persist()

    def _persist(self) -> None:
        save_settings(self.settings)
        self._on_change(self.settings)

    def sync_from_settings(self, settings: AppSettings) -> None:
        """Refresh controls if settings changed externally."""
        self.settings = settings
        self._updating = True
        try:
            self._density_var.set(settings.density)
            self._metric_var.set(settings.minimized_metric)
            for attr, var in self._bool_vars.items():
                var.set(bool(getattr(settings, attr)))
        finally:
            self._updating = False

    def _on_close(self) -> None:
        self.destroy()


_open_window: SettingsWindow | None = None


def open_settings(
    parent: tk.Misc,
    settings: AppSettings,
    on_change: Callable[[AppSettings], None],
) -> SettingsWindow:
    global _open_window
    if _open_window is not None and _open_window.winfo_exists():
        _open_window.sync_from_settings(settings)
        _open_window.lift()
        _open_window.focus_force()
        return _open_window

    win = SettingsWindow(parent, settings, on_change)

    def _clear(event: object) -> None:
        global _open_window
        if getattr(event, "widget", None) is win:
            _open_window = None

    win.bind("<Destroy>", _clear)
    _open_window = win
    return win
