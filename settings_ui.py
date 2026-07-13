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
from theme import (
    BG,
    BORDER,
    CARD,
    MUTED,
    SWITCH_OFF,
    SWITCH_ON,
    TEXT,
)

DENSITY_LABELS = {
    "full": "Full",
    "compact": "Compact",
    "minimal": "Pill",
}

METRIC_LABELS = {
    "total": "Total",
    "auto": "Auto + Composer",
    "api": "API",
    "worst": "Worst",
}


class ToggleSwitch(tk.Canvas):
    """Minimal pill switch control."""

    def __init__(
        self,
        master: tk.Misc,
        variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            width=40,
            height=22,
            bg=CARD,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            **kwargs,
        )
        self._var = variable
        self._command = command
        self._track = self.create_round_rect(1, 1, 39, 21, 11, fill=SWITCH_OFF, outline="")
        self._knob = self.create_oval(3, 3, 19, 19, fill="#FFFFFF", outline="")
        self.bind("<Button-1>", self._toggle)
        self._var.trace_add("write", lambda *_: self._redraw())
        self._redraw()

    def create_round_rect(
        self, x1: int, y1: int, x2: int, y2: int, r: int, **kwargs: object
    ) -> int:
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _toggle(self, _event: object | None = None) -> None:
        self._var.set(not bool(self._var.get()))
        if self._command:
            self._command()

    def _redraw(self) -> None:
        on = bool(self._var.get())
        self.itemconfigure(self._track, fill=SWITCH_ON if on else SWITCH_OFF)
        if on:
            self.coords(self._knob, 21, 3, 37, 19)
        else:
            self.coords(self._knob, 3, 3, 19, 19)


class SettingsWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        settings: AppSettings,
        on_change: Callable[[AppSettings], None],
    ) -> None:
        super().__init__(parent)
        self.title("Cursor Usage")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.settings = settings
        self._on_change = on_change
        self._updating = False

        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        outer = tk.Frame(self, bg=BG, padx=18, pady=18)
        outer.pack(fill="both", expand=True)

        title = tk.Label(
            outer,
            text="Cursor Usage",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 15),
            anchor="w",
        )
        title.pack(fill="x")

        subtitle = tk.Label(
            outer,
            text="Changes apply live.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        subtitle.pack(fill="x", pady=(2, 14))

        self._density_var = tk.StringVar(value=settings.density)
        self._metric_var = tk.StringVar(value=settings.minimized_metric)
        self._bool_vars: dict[str, tk.BooleanVar] = {}

        appearance = self._section(outer, "Appearance")
        self._add_dropdown(
            appearance,
            "Density",
            self._density_var,
            [(k, DENSITY_LABELS[k]) for k in DENSITY_OPTIONS],
            self._on_density,
        )
        self._add_dropdown(
            appearance,
            "Pill metric",
            self._metric_var,
            [(k, METRIC_LABELS[k]) for k in METRIC_OPTIONS],
            self._on_metric,
        )
        for attr, label in (
            ("show_header", "Show header"),
            ("show_reset_countdown", "Reset countdown"),
            ("show_stale_badge", "Stale-data badge"),
        ):
            self._add_switch(appearance, label, attr)

        behavior = self._section(outer, "Behavior")
        for attr, label in (
            ("always_on_top", "Always on top"),
            ("click_through", "Click-through"),
            ("start_minimized", "Start as pill"),
        ):
            self._add_switch(behavior, label, attr)

        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 300)
        h = self.winfo_reqheight()
        self.geometry(f"{w}x{h}")

    def _section(self, parent: tk.Misc, title: str) -> tk.Frame:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x", pady=(0, 12))
        card = tk.Frame(
            wrap,
            bg=CARD,
            padx=14,
            pady=12,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        card.pack(fill="x")
        tk.Label(
            card,
            text=title.upper(),
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 10))
        return card

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

    def _add_switch(self, parent: tk.Misc, label: str, attr: str) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=5)
        tk.Label(
            row,
            text=label,
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side="left")

        var = tk.BooleanVar(value=bool(getattr(self.settings, attr)))
        self._bool_vars[attr] = var

        def on_toggle() -> None:
            if self._updating:
                return
            setattr(self.settings, attr, bool(var.get()))
            self._persist()

        ToggleSwitch(row, var, command=on_toggle).pack(side="right")

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
