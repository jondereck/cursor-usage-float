"""LAYOUT settings window for the Cursor usage floater."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, ttk

from pace_history import apply_pace_sync_folder
from paths import resource_path
from settings import (
    DENSITY_OPTIONS,
    METRIC_OPTIONS,
    AppSettings,
    ensure_usage_section_visible,
    save_settings,
)
from sync_status import format_last_backup, inspect_sync_status
from theme import (
    BG,
    BORDER,
    CARD,
    DOT_ERR,
    DOT_OK,
    DOT_UNKNOWN,
    MUTED,
    SWITCH_OFF,
    SWITCH_ON,
    TEXT,
    WARN,
)
from win_app_icon import apply_tk_icon
from win_startup import set_start_with_windows

APP_ICON = resource_path("assets", "app.ico")

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
    "pace": "Today's pace",
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
        on_visibility: Callable[[bool], None] | None = None,
        hotkey_hint: str = "",
    ) -> None:
        super().__init__(parent)
        self.title("Cursor Usage")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.settings = settings
        self._on_change = on_change
        self._on_visibility = on_visibility
        self._updating = False
        self._sync_refresh_job: str | None = None

        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        apply_tk_icon(self, APP_ICON)
        self.after(50, lambda: apply_tk_icon(self, APP_ICON))

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

        hint = f"Changes apply live. Hotkey: {hotkey_hint}" if hotkey_hint else "Changes apply live."
        subtitle = tk.Label(
            outer,
            text=hint,
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
            ("show_total", "Total"),
            ("show_pace", "Today's pace"),
            ("show_reset_countdown", "Reset countdown"),
            ("show_stale_badge", "Stale-data badge"),
        ):
            self._add_switch(appearance, label, attr)

        behavior = self._section(outer, "Behavior")
        for attr, label in (
            ("always_on_top", "Always on top"),
            ("click_through", "Click-through"),
        ):
            self._add_switch(behavior, label, attr)

        sync = self._section(outer, "Sync")
        self._add_pace_sync_row(sync)

        startup = self._section(outer, "Startup")
        for attr, label in (
            ("start_with_windows", "Start with Windows"),
            ("start_minimized", "Open hidden (pill)"),
        ):
            self._add_switch(startup, label, attr)

        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 300)
        h = self.winfo_reqheight()
        self.geometry(f"{w}x{h}")
        if self._on_visibility is not None:
            self._on_visibility(True)

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
            enabled = bool(var.get())
            setattr(self.settings, attr, enabled)
            if attr in ("show_total", "show_pace"):
                if not self.settings.show_total and not self.settings.show_pace:
                    # Keep at least one usage section visible.
                    var.set(True)
                    setattr(self.settings, attr, True)
                    return
                ensure_usage_section_visible(self.settings)
                self._metric_var.set(self.settings.minimized_metric)
            if attr == "start_with_windows":
                set_start_with_windows(enabled)
            self._persist()

        ToggleSwitch(row, var, command=on_toggle).pack(side="right")

    def _add_pace_sync_row(self, parent: tk.Misc) -> None:
        tk.Label(
            parent,
            text="Sync folder (Google Drive / OneDrive)",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            parent,
            text="Same folder on both PCs syncs Today's pace and settings. Leave empty for this PC only.",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
            wraplength=280,
            justify="left",
        ).pack(fill="x", pady=(2, 6))

        self._sync_path_var = tk.StringVar(
            value=self._sync_display(self.settings.pace_sync_folder)
        )
        path_lbl = tk.Label(
            parent,
            textvariable=self._sync_path_var,
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
            wraplength=280,
            justify="left",
        )
        path_lbl.pack(fill="x", pady=(0, 6))

        self._sync_status_label = tk.Label(
            parent,
            text="",
            bg=CARD,
            fg=DOT_UNKNOWN,
            font=("Segoe UI Semibold", 9),
            anchor="w",
            wraplength=280,
            justify="left",
        )
        self._sync_status_label.pack(fill="x", pady=(2, 0))

        self._sync_backup_label = tk.Label(
            parent,
            text="Last backup: —",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self._sync_backup_label.pack(fill="x", pady=(2, 8))

        btns = tk.Frame(parent, bg=CARD)
        btns.pack(fill="x")

        browse = tk.Button(
            btns,
            text="Browse…",
            command=self._browse_pace_sync,
            bg=CARD,
            fg=TEXT,
            activebackground=BORDER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9),
        )
        browse.pack(side="left")

        clear = tk.Button(
            btns,
            text="Use local",
            command=self._clear_pace_sync,
            bg=CARD,
            fg=MUTED,
            activebackground=BORDER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9),
        )
        clear.pack(side="left", padx=(6, 0))
        self._refresh_sync_status()

    @staticmethod
    def _sync_display(folder: str) -> str:
        folder = (folder or "").strip()
        return folder if folder else "Local (this PC only)"

    def _set_pace_sync_folder(self, folder: str) -> None:
        if self._updating:
            return
        self.settings.pace_sync_folder = apply_pace_sync_folder(
            self.settings.pace_sync_folder, folder
        )
        self._sync_path_var.set(self._sync_display(self.settings.pace_sync_folder))
        self._persist()
        self._refresh_sync_status()

    def _refresh_sync_status(self) -> None:
        if self._sync_refresh_job is not None:
            try:
                self.after_cancel(self._sync_refresh_job)
            except tk.TclError:
                pass
            self._sync_refresh_job = None

        status = inspect_sync_status(self.settings.pace_sync_folder)
        colors = {
            "local": DOT_UNKNOWN,
            "synced": DOT_OK,
            "unavailable": WARN,
            "error": DOT_ERR,
        }
        text = f"●  {status.label}"
        if status.state == "error" and status.detail:
            text = f"{text} — {status.detail}"
        self._sync_status_label.configure(
            text=text,
            fg=colors[status.state],
        )
        self._sync_backup_label.configure(
            text=format_last_backup(status.last_backup)
        )
        try:
            self._sync_refresh_job = self.after(
                10_000, self._refresh_sync_status
            )
        except tk.TclError:
            self._sync_refresh_job = None

    def _browse_pace_sync(self) -> None:
        initial = self.settings.pace_sync_folder.strip() or None
        chosen = filedialog.askdirectory(
            parent=self,
            title="Choose shared sync folder",
            initialdir=initial,
            mustexist=True,
        )
        if chosen:
            self._set_pace_sync_folder(chosen)

    def _clear_pace_sync(self) -> None:
        self._set_pace_sync_folder("")

    def _on_density(self) -> None:
        self.settings.density = self._density_var.get()
        self._persist()

    def _on_metric(self) -> None:
        self.settings.minimized_metric = self._metric_var.get()
        if self.settings.minimized_metric == "pace":
            self.settings.show_pace = True
        else:
            self.settings.show_total = True
        ensure_usage_section_visible(self.settings)
        self._metric_var.set(self.settings.minimized_metric)
        self._sync_bool_vars()
        self._persist()

    def _sync_bool_vars(self) -> None:
        for attr, var in self._bool_vars.items():
            var.set(bool(getattr(self.settings, attr)))

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
            if hasattr(self, "_sync_path_var"):
                self._sync_path_var.set(self._sync_display(settings.pace_sync_folder))
        finally:
            self._updating = False
        if hasattr(self, "_sync_status_label"):
            self._refresh_sync_status()

    def _on_close(self) -> None:
        if self._sync_refresh_job is not None:
            try:
                self.after_cancel(self._sync_refresh_job)
            except tk.TclError:
                pass
            self._sync_refresh_job = None
        self.destroy()


_open_window: SettingsWindow | None = None


def open_settings(
    parent: tk.Misc,
    settings: AppSettings,
    on_change: Callable[[AppSettings], None],
    on_visibility: Callable[[bool], None] | None = None,
    hotkey_hint: str = "",
) -> SettingsWindow:
    global _open_window
    if _open_window is not None and _open_window.winfo_exists():
        _open_window.sync_from_settings(settings)
        _open_window.lift()
        _open_window.focus_force()
        if on_visibility is not None:
            on_visibility(True)
        return _open_window

    win = SettingsWindow(
        parent,
        settings,
        on_change,
        on_visibility=on_visibility,
        hotkey_hint=hotkey_hint,
    )

    def _clear(event: object) -> None:
        global _open_window
        if getattr(event, "widget", None) is win:
            _open_window = None
            if on_visibility is not None:
                on_visibility(False)

    win.bind("<Destroy>", _clear)
    _open_window = win
    return win
