"""Always-on-top floating Cursor usage widget (personal / portable)."""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import font as tkfont

from cursor_auth import AuthError
from cursor_usage import PlanUsage, UsageError, budget_from_plan, fetch_current_period_usage
from paths import resource_path
from pace_history import (
    active_pace_history_path,
    load_history,
    record_usage_point,
    reset_today_baseline,
    save_history,
)
from pacing import (
    PaceResult,
    compute_pace,
    format_compact,
    format_units,
)
from settings import (
    AppSettings,
    effective_click_through,
    effective_pill_metric,
    ensure_usage_section_visible,
    format_usage_percent,
    load_settings,
    resolve_minimized_percent,
    save_settings,
)
from settings_ui import SettingsWindow, open_settings
from theme import (
    BAR_BG,
    BG,
    BORDER,
    CARD,
    CRITICAL,
    DOT_ERR,
    DOT_OK,
    DOT_PULSE,
    DOT_UNKNOWN,
    HOVER,
    MARKER_80,
    MUTED,
    PACE_WARN_BG,
    PACE_WARN_FG,
    STALE_BG,
    STALE_FG,
    TEXT,
    USAGE_MARK,
    WARN,
    bar_color_for_percent,
    frame_border_for_state,
    pace_accent,
    pace_badge_colors,
    pill_border_for_state,
    pill_chrome,
)
from win_app_icon import apply_tk_icon, set_app_user_model_id
from win_clickthrough import (
    TRANSPARENT_KEY,
    clear_window_region,
    get_window_pos,
    set_click_through,
    set_color_key,
    set_layered_attrs,
    set_rounded_corners,
    set_window_pos,
    toplevel_hwnd,
)
from win_taskbar import apply_taskbar_button
from win_tray import TrayIcon
from win_hotkey import GlobalHotkey
from win_startup import set_start_with_windows
from window_state import (
    WindowState,
    clamp_position,
    load_window_state,
    save_window_state,
    virtual_screen_bounds,
)

POLL_MS = 3 * 60 * 1000
STALE_MS = 2 * POLL_MS
WINDOW_WIDTH = 300
PILL_WIDTH = 110
PILL_WIDTH_PACE = 168
PILL_HEIGHT = 36
PILL_PAD_L = 8
PILL_PAD_R = 10
PILL_GAP = 6
PILL_RING = 20
PILL_BORDER_PX = 2
PILL_NUM_FONT = ("Segoe UI", 11, "bold")
PILL_BADGE_FONT = ("Segoe UI", 8, "bold")
CORNER_RADIUS = 18
PILL_CORNER_RADIUS = 22  # unused in pill mode; radius = height
GEAR_ICON = "\uE713"
FADE_OUT_MS = 90
FADE_IN_MS = 110
FADE_FRAME_MS = 12
APP_ICON = resource_path("assets", "app.ico")


def _rounded_rect_coords(
    x1: float, y1: float, x2: float, y2: float, radius: float
) -> list[float]:
    """Polygon points for a rounded rectangle (smooth=True)."""
    if x2 <= x1 or y2 <= y1:
        return [x1, y1, x2, y1, x2, y2, x1, y2]
    r = min(radius, (x2 - x1) / 2.0, (y2 - y1) / 2.0)
    return [
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


class ProgressRow(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        title: str,
        *,
        hero: bool = False,
        compact: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(master, bg=master.cget("bg"), **kwargs)
        self._value = 0.0
        self._hero = hero
        self._compact = compact

        header = tk.Frame(self, bg=self.cget("bg"))
        header.pack(fill="x")

        title_size = 12 if hero else (9 if compact else 10)
        pct_size = 13 if hero else (9 if compact else 10)

        self.title_label = tk.Label(
            header,
            text=title,
            bg=self.cget("bg"),
            fg=TEXT if hero else MUTED,
            font=("Segoe UI Semibold" if hero else "Segoe UI", title_size, "bold" if hero else "normal"),
            anchor="w",
        )
        self.title_label.pack(side="left")

        self.pct_label = tk.Label(
            header,
            text="—%",
            bg=self.cget("bg"),
            fg=TEXT,
            font=("Segoe UI Semibold", pct_size),
            anchor="e",
        )
        self.pct_label.pack(side="right")

        bar_h = 14 if hero else (6 if compact else 8)
        self._bar_h = bar_h
        self._bar_radius = bar_h / 2.0
        self._seg_ids: list[int] = []
        # Canvas matches card so the track can be a true rounded pill (no square edges).
        self.bar_outer = tk.Canvas(
            self,
            height=bar_h,
            bg=self.cget("bg"),
            highlightthickness=0,
            bd=0,
        )
        self.bar_outer.pack(fill="x", pady=(8 if hero else 5, 0))
        self._track = self.bar_outer.create_polygon(
            0, 0, 0, 0, fill=BAR_BG, outline="", smooth=True
        )
        self._mark = self.bar_outer.create_line(
            0, 0, 0, 0, fill=MARKER_80, width=1
        )
        self.bar_outer.bind("<Configure>", self._redraw_bar)

        self.sub_label: tk.Label | None = None
        if hero:
            self.sub_label = tk.Label(
                self,
                text="",
                bg=self.cget("bg"),
                fg=MUTED,
                font=("Segoe UI", 8),
                wraplength=WINDOW_WIDTH - 48,
                justify="left",
                anchor="w",
            )

    def set_percent(self, value: float) -> None:
        self._value = max(0.0, min(100.0, float(value)))
        tip = bar_color_for_percent(self._value)
        self.pct_label.configure(
            text=format_usage_percent(self._value),
            fg=tip if self._value >= 40.0 else TEXT,
        )
        self._redraw_bar()

    def set_subtext(self, text: str) -> None:
        if self.sub_label is None:
            return
        text = (text or "").strip()
        if not text:
            self.sub_label.pack_forget()
            return
        self.sub_label.configure(text=text)
        if not self.sub_label.winfo_ismapped():
            self.sub_label.pack(fill="x", pady=(6, 0))

    def _clear_segments(self) -> None:
        for item in self._seg_ids:
            self.bar_outer.delete(item)
        self._seg_ids.clear()

    def _redraw_bar(self, _event: object | None = None) -> None:
        width = max(self.bar_outer.winfo_width(), 1)
        height = max(self.bar_outer.winfo_height(), 1)
        r = min(self._bar_radius, height / 2.0, width / 2.0)

        self.bar_outer.coords(
            self._track, *_rounded_rect_coords(0, 0, width, height, r)
        )
        self._clear_segments()

        fill_w = width * (self._value / 100.0)
        if fill_w > 0.5:
            # Gradient by absolute position on the bar (green → amber → red toward 100%).
            # More segments = smoother blend.
            segments = max(8, min(48, int(fill_w)))
            for i in range(segments):
                x0 = fill_w * (i / segments)
                x1 = fill_w * ((i + 1) / segments)
                # Color at this point along the full 0–100% scale
                pos_pct = (x1 / width) * 100.0
                color = bar_color_for_percent(pos_pct)
                # Round the outer caps; middle strips are flat rects.
                if i == 0 or i == segments - 1:
                    item = self.bar_outer.create_polygon(
                        *_rounded_rect_coords(x0, 0, max(x1, x0 + 0.5), height, r),
                        fill=color,
                        outline="",
                        smooth=True,
                    )
                else:
                    item = self.bar_outer.create_rectangle(
                        x0, 0, x1, height, fill=color, outline=""
                    )
                self._seg_ids.append(item)

        # 80% warning mark on top
        mx = width * (USAGE_MARK / 100.0)
        inset = max(1.0, height * 0.12)
        self.bar_outer.coords(self._mark, mx, inset, mx, height - inset)
        mark_color = CRITICAL if self._value >= USAGE_MARK else MARKER_80
        self.bar_outer.itemconfigure(self._mark, fill=mark_color)
        self.bar_outer.tag_raise(self._mark)


class UsageFloater(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Cursor Usage")
        self.configure(bg=BG)
        self.overrideredirect(True)
        self.resizable(False, False)
        apply_tk_icon(self, APP_ICON)

        self.settings = load_settings()
        # Ensure shared settings.json exists once Sync folder is configured.
        if self.settings.pace_sync_folder.strip():
            save_settings(self.settings)
        if self.settings.start_with_windows:
            set_start_with_windows(True)
        self._drag_x = 0
        self._drag_y = 0
        self._refreshing = False
        self._connection_ok: bool | None = None
        self._last_success_at: datetime | None = None
        self._last_usage: PlanUsage | None = None
        self._last_pace: PaceResult | None = None
        self._window_state = load_window_state()
        if self._window_state is not None:
            self._minimized = bool(self._window_state.minimized)
            # Minimal density is always pill unless force-expanded.
            self._force_expanded = (
                not self._window_state.minimized and self.settings.density == "minimal"
            )
        else:
            self._minimized = bool(self.settings.start_minimized)
            self._force_expanded = False
        self._placed = False
        self._animating = False
        self._anim_job: str | None = None
        self._pulse_job: str | None = None
        self._pulse_on = False
        self._header_buttons: list[tk.Button] = []
        self._was_pill = bool(self._minimized or self.settings.density == "minimal")
        if self._force_expanded:
            self._was_pill = False
        self._settings_open = False
        self._settings_win: SettingsWindow | None = None
        self._click_through_hotkey: GlobalHotkey | None = None
        self._tray: TrayIcon | None = None

        self.attributes("-topmost", bool(self.settings.always_on_top))

        self._build_ui()
        self._tray = TrayIcon(
            self,
            tip="Cursor Usage",
            icon_path=APP_ICON,
            on_show=self._on_tray_show,
            on_settings=self._open_settings,
            on_quit=self.destroy,
            is_start_with_windows=lambda: bool(self.settings.start_with_windows),
            is_start_minimized=lambda: bool(self.settings.start_minimized),
            set_start_with_windows=self._tray_set_start_with_windows,
            set_start_minimized=self._tray_set_start_minimized,
        )
        self._apply_settings_side_effects()
        self._apply_layout(animate=False)
        self._restore_or_place_default()
        # Re-apply after Tk finishes mapping — first geometry can snap to primary.
        self.after(150, self._restore_or_place_default)
        self.after(400, self._restore_or_place_default)
        self._register_click_through_hotkey()
        # Tray only — never a taskbar button for this borderless floater.
        self.after(100, self._hide_from_taskbar)
        if self._tray is not None:
            self.after(150, self._tray.show)
        self.after(200, self.refresh_async)
        self.after(POLL_MS, self._schedule_poll)
        self.after(30_000, self._schedule_stale_check)

    def _build_ui(self) -> None:
        self.outer = tk.Frame(self, bg=BORDER, bd=0)
        self.outer.pack(fill="both", expand=True)

        self.card = tk.Frame(self.outer, bg=CARD, padx=14, pady=12)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        self.expanded = tk.Frame(self.card, bg=CARD)
        self.expanded.pack(fill="both", expand=True)

        self.header = tk.Frame(self.expanded, bg=CARD)
        self.header.pack(fill="x")
        self.header.bind("<ButtonPress-1>", self._start_drag)
        self.header.bind("<B1-Motion>", self._on_drag)
        self.header.bind("<ButtonRelease-1>", self._end_drag)

        status_wrap = tk.Frame(self.header, bg=CARD)
        status_wrap.pack(side="left", padx=(0, 6))

        self.status_dot = tk.Canvas(
            status_wrap,
            width=12,
            height=12,
            bg=CARD,
            highlightthickness=0,
            bd=0,
        )
        self.status_dot.pack(side="left")
        self._dot_item = self.status_dot.create_oval(
            2, 2, 10, 10, fill=DOT_UNKNOWN, outline=""
        )

        self.status_cue = tk.Label(
            status_wrap,
            text="",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 7, "bold"),
            anchor="w",
        )
        # Only packed when there is an error cue (never "OK")

        title = tk.Label(
            self.header,
            text="Cursor Usage",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI Semibold", 11),
            anchor="w",
        )
        title.pack(side="left")
        title.bind("<ButtonPress-1>", self._start_drag)
        title.bind("<B1-Motion>", self._on_drag)
        title.bind("<ButtonRelease-1>", self._end_drag)

        self.refresh_btn = self._header_btn("↻", self.refresh_async)
        self._header_btn("✕", self.destroy).pack(side="right")
        self.refresh_btn.pack(side="right", padx=(0, 2))
        self._header_btn(GEAR_ICON, self._open_settings, icon_font=True).pack(
            side="right", padx=(0, 2)
        )
        self._header_btn("−", self._toggle_minimized).pack(side="right", padx=(0, 2))

        self.total_row = ProgressRow(self.expanded, "Cursor Models", hero=True)
        self.total_row.configure(bg=CARD)
        self.total_row.pack(fill="x", pady=(14, 0))

        # Daily pace / soft-stop (hero visual)
        self.pace_panel = tk.Frame(self.expanded, bg=CARD)
        self.pace_panel.pack(fill="x", pady=(12, 0))

        pace_header = tk.Frame(self.pace_panel, bg=CARD)
        pace_header.pack(fill="x")

        # WARN/STOP chip only — hidden while OK
        self.pace_badge = tk.Label(
            pace_header,
            text="",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI Semibold", 8),
            padx=8,
            pady=3,
        )

        self.pace_reset_btn = tk.Button(
            pace_header,
            text="Reset today",
            command=self._reset_pace_today,
            bg=CARD,
            fg=MUTED,
            activebackground=HOVER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=6,
            pady=1,
        )
        self.pace_reset_btn.pack(side="right")
        self.pace_reset_btn.bind("<Enter>", lambda _e: self.pace_reset_btn.configure(fg=TEXT))
        self.pace_reset_btn.bind("<Leave>", lambda _e: self.pace_reset_btn.configure(fg=MUTED))

        self.pace_row = ProgressRow(self.pace_panel, "Today's pace", hero=True)
        self.pace_row.configure(bg=CARD)
        self.pace_row.pack(fill="x", pady=(6, 0))

        self.pace_msg = tk.Label(
            self.pace_panel,
            text="",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
            wraplength=WINDOW_WIDTH - 48,
            justify="left",
            anchor="w",
        )
        # Only packed on WARN/STOP

        self.pace_meta = tk.Label(
            self.pace_panel,
            text="",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
            wraplength=WINDOW_WIDTH - 48,
            justify="left",
            anchor="w",
        )
        self.pace_meta.pack(fill="x", pady=(6, 0))

        # Detail: Auto / API
        self.detail = tk.Frame(self.expanded, bg=CARD)
        self.detail.pack(fill="x", pady=(14, 0))

        self.auto_row = ProgressRow(self.detail, "Cursor Models", compact=True)
        self.auto_row.configure(bg=CARD)

        self.api_row = ProgressRow(self.detail, "Other Models", compact=True)
        self.api_row.configure(bg=CARD)
        self.api_row.pack(fill="x")

        self.reset_label = tk.Label(
            self.expanded,
            text="",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )

        self.stale_badge = tk.Label(
            self.expanded,
            text="Stale data",
            bg=STALE_BG,
            fg=STALE_FG,
            font=("Segoe UI", 8, "bold"),
            padx=6,
            pady=2,
        )

        self.status_label = tk.Label(
            self.expanded,
            text="Starting…",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 7),
            anchor="w",
            justify="left",
            wraplength=WINDOW_WIDTH - 36,
        )
        self.status_label.pack(fill="x", pady=(10, 0))

        # --- Pill: single Canvas face (exact CSS capsule; widgets can't cover the ring) ---
        self.pill = tk.Frame(self.card, bg=CARD)
        self.pill_face = tk.Canvas(
            self.pill,
            width=120,
            height=PILL_HEIGHT,
            bg=CARD,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        # Exact pixel size only — fill/expand left a magenta (transparent) strip
        # under the capsule so the bottom border looked cut off.
        self.pill_face.pack()
        self.pill.pack_propagate(True)
        self._pill_border_color = CARD
        self._pill_view: dict[str, object] = {
            "text": "—%",
            "number_color": TEXT,
            "ring_color": BAR_BG,
            "ring_extent": 0.0,
            "dot_color": DOT_UNKNOWN,
            "badge_text": "",
            "badge_bg": PACE_WARN_BG,
            "badge_fg": PACE_WARN_FG,
            "show_badge": False,
            "cue": "",
        }
        self.pill_face.bind("<Configure>", self._on_pill_configure)
        self.pill_face.bind("<ButtonPress-1>", self._start_drag)
        self.pill_face.bind("<B1-Motion>", self._on_drag)
        self.pill_face.bind("<Double-Button-1>", lambda _e: self._expand_from_pill())
        self.pill_face.bind("<ButtonRelease-1>", self._end_drag)
        self.pill.bind("<ButtonPress-1>", self._start_drag)
        self.pill.bind("<B1-Motion>", self._on_drag)
        self.pill.bind("<Double-Button-1>", lambda _e: self._expand_from_pill())
        self.pill.bind("<ButtonRelease-1>", self._end_drag)

        self._pill_press_xy: tuple[int, int] | None = None

        # Legacy names kept so older bind loops / updates don't crash if referenced.
        self.pill_inner = self.pill
        self.pill_canvas = self.pill_face
        self.pill_pct = self.pill_face
        self.pill_state = self.pill_face
        self.pill_cue = self.pill_face
        self.pill_border_canvas = self.pill_face
        self._pill_dot_item = None
        self._pill_arc = None
        self._pill_arc_bg = None

        for child in self.expanded.winfo_children():
            if isinstance(child, tk.Label):
                child.bind("<ButtonPress-1>", self._start_drag)
                child.bind("<B1-Motion>", self._on_drag)
                child.bind("<ButtonRelease-1>", self._end_drag)

        self.card.bind("<Button-3>", lambda _e: self._open_settings())
        self.pill.bind("<Button-3>", lambda _e: self._open_settings())
        self.pill_face.bind("<Button-3>", lambda _e: self._open_settings())
        self.expanded.bind("<Button-3>", lambda _e: self._open_settings())
        self.bind("<Escape>", lambda _e: self._collapse_to_pill())

    def _header_btn(
        self, text: str, command: object, *, icon_font: bool = False
    ) -> tk.Button:
        if icon_font:
            font = ("Segoe MDL2 Assets", 10)
        elif text == "✕":
            font = ("Segoe UI", 9)
        else:
            font = ("Segoe UI", 10)
        btn = tk.Button(
            self.header,
            text=text,
            command=command,
            bg=CARD,
            fg=MUTED,
            activebackground=HOVER,
            activeforeground=TEXT,
            bd=0,
            relief="flat",
            font=font,
            cursor="hand2",
            padx=5,
            pady=1,
        )
        btn.bind("<Enter>", lambda _e, b=btn: b.configure(bg=HOVER, fg=TEXT))
        btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=CARD, fg=MUTED))
        self._header_buttons.append(btn)
        return btn

    def _open_settings(self) -> None:
        hint = ""
        if self._click_through_hotkey is not None:
            hint = self._click_through_hotkey.shortcut_label
        self._settings_win = open_settings(
            self,
            self.settings,
            self._on_settings_changed,
            on_visibility=self._on_settings_visibility,
            hotkey_hint=hint,
        )

    def _on_settings_visibility(self, open_: bool) -> None:
        self._settings_open = bool(open_)
        self._apply_settings_side_effects()

    def _on_settings_changed(self, settings: AppSettings) -> None:
        ensure_usage_section_visible(settings)
        self.settings = settings
        if settings.density != "minimal":
            self._force_expanded = False
        self._apply_settings_side_effects()
        self._apply_layout(animate=True)
        if self._last_usage is not None:
            self._update_pace_from_usage(self._last_usage)
        self._refresh_status_text()
        self._update_pill_percent()
        self._update_section_visibility()
        self._resize_to_content()

    def _apply_settings_side_effects(self) -> None:
        try:
            self.attributes("-topmost", bool(self.settings.always_on_top))
        except tk.TclError:
            pass
        hwnd = toplevel_hwnd(self)
        set_click_through(
            hwnd,
            effective_click_through(self.settings.click_through, self._settings_open),
        )

    def _register_click_through_hotkey(self) -> None:
        hotkey = GlobalHotkey(self, callback=self._hotkey_open_settings)
        if hotkey.register():
            self._click_through_hotkey = hotkey

    def _hotkey_open_settings(self) -> None:
        """Escape hatch: open Settings (soft-unlocks click-through while open)."""
        self._open_settings()

    def destroy(self) -> None:
        self._persist_window_state()
        if self._click_through_hotkey is not None:
            self._click_through_hotkey.unregister()
            self._click_through_hotkey = None
        if self._tray is not None:
            self._tray.destroy()
            self._tray = None
        super().destroy()

    def _hide_from_taskbar(self) -> None:
        """Keep presence in the system tray only — no taskbar button."""
        apply_taskbar_button(toplevel_hwnd(self), show=False)

    def _on_tray_show(self) -> None:
        """Tray left-click / Show: bring float back (expand pill if needed)."""
        try:
            self.deiconify()
        except tk.TclError:
            pass
        if self._show_pill_mode():
            self._expand_from_pill()
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass
        self._hide_from_taskbar()

    def _tray_set_start_with_windows(self, enabled: bool) -> None:
        self.settings.start_with_windows = bool(enabled)
        set_start_with_windows(self.settings.start_with_windows)
        save_settings(self.settings)

    def _tray_set_start_minimized(self, enabled: bool) -> None:
        self.settings.start_minimized = bool(enabled)
        save_settings(self.settings)

    def _toggle_minimized(self) -> None:
        if self._animating:
            return
        if self.settings.density == "minimal":
            self._force_expanded = not self._force_expanded
            self._minimized = False
        else:
            self._force_expanded = False
            self._minimized = not self._minimized
        self._apply_layout(animate=True)
        self._persist_window_state()

    def _collapse_to_pill(self) -> None:
        if self._animating or self._show_pill_mode():
            return
        self._force_expanded = False
        self._minimized = True
        self._apply_layout(animate=True)
        self._persist_window_state()

    def _expand_from_pill(self) -> None:
        if self._animating or not self._show_pill_mode():
            return
        self._minimized = False
        if self.settings.density == "minimal":
            self._force_expanded = True
        self._apply_layout(animate=True)
        self._persist_window_state()

    def _pill_click(self, event: tk.Event) -> None:
        if self._pill_press_xy is None:
            return
        dx = abs(event.x_root - self._pill_press_xy[0])
        dy = abs(event.y_root - self._pill_press_xy[1])
        self._pill_press_xy = None
        if dx < 4 and dy < 4:
            self._expand_from_pill()

    def _show_pill_mode(self) -> bool:
        if self._force_expanded:
            return False
        return self._minimized or self.settings.density == "minimal"

    def _apply_layout(self, *, animate: bool = False) -> None:
        want_pill = self._show_pill_mode()
        was_pill = self._was_pill

        self._paint_status()
        self._update_pill_percent()

        if not animate or was_pill == want_pill:
            self._cancel_animation()
            self._set_chrome(want_pill)
            # Keep top-left fixed so expand/collapse doesn't jump.
            self._resize_to_content(pin_right=False)
            self._was_pill = want_pill
            self._set_alpha(1.0)
            return

        # Alpha crossfade beats size-morph on Windows (no SetWindowRgn stutter).
        pos = get_window_pos(toplevel_hwnd(self))
        if pos is not None:
            anchor_x, anchor_y = pos[0], pos[1]
        else:
            anchor_x, anchor_y = int(self.winfo_x()), int(self.winfo_y())
        self._was_pill = want_pill
        self._animating = True

        def after_fade_out() -> None:
            self._set_chrome(want_pill)
            self.update_idletasks()
            end_w, end_h = self._target_size()
            self.geometry(f"{end_w}x{end_h}")
            hwnd = toplevel_hwnd(self)
            # Same top-left as before the toggle (do not pin-right / slide).
            if not set_window_pos(hwnd, anchor_x, anchor_y):
                self.geometry(f"{end_w}x{end_h}+{anchor_x}+{anchor_y}")
            self._apply_rounded_corners(end_w, end_h)
            self._paint_status()
            self._update_pill_percent()
            self._fade_alpha(0.0, 1.0, FADE_IN_MS, on_done=self._clear_animating)

        self._fade_alpha(1.0, 0.0, FADE_OUT_MS, on_done=after_fade_out)

    def _clear_animating(self) -> None:
        self._animating = False
        self._set_alpha(1.0)
        if self._show_pill_mode():
            # Re-assert color-key after fade (Tk alpha can clear it).
            self._apply_rounded_corners(*self._target_size())

    def _set_chrome(self, show_pill: bool) -> None:
        if show_pill:
            self.expanded.pack_forget()
            if not self.pill.winfo_ismapped():
                self.pill.pack()
            # Zero padding: any card padx/pady eats the capsule bottom into the
            # window clip (border looks cut off / "putol").
            self.card.configure(padx=0, pady=0)
            self.card.pack_configure(padx=0, pady=0)
            self.outer.configure(bg=CARD)
            self.after_idle(self._redraw_pill_face)
            return

        self.pill.pack_forget()
        self.card.configure(padx=14, pady=12, bg=CARD)
        self.card.pack_configure(padx=1, pady=1)
        self.outer.configure(bg=BORDER)
        self.pill.configure(bg=CARD)
        try:
            self.configure(bg=BG)
        except tk.TclError:
            pass
        # Expanded must not keep pill color-key (magenta would show as pink).
        try:
            hwnd = toplevel_hwnd(self)
            set_color_key(hwnd, None)
        except Exception:
            pass

        for child in (
            self.header,
            self.total_row,
            self.pace_panel,
            self.detail,
            self.reset_label,
            self.stale_badge,
            self.status_label,
        ):
            child.pack_forget()

        if not self.expanded.winfo_ismapped():
            self.expanded.pack(fill="both", expand=True)

        if self.settings.show_header:
            self.header.pack(fill="x")

        first_section = True
        if self.settings.show_total:
            self.total_row.pack(
                fill="x",
                pady=(14 if self.settings.show_header or first_section else 0, 0),
            )
            first_section = False

        if self.settings.show_pace:
            self.pace_panel.pack(
                fill="x",
                pady=(12 if not first_section else (14 if self.settings.show_header else 0), 0),
            )
            first_section = False

        show_detail = self.settings.density == "full" or (
            self.settings.density == "minimal" and self._force_expanded
        )
        if show_detail:
            self.detail.pack(
                fill="x",
                pady=(14 if not first_section else (14 if self.settings.show_header else 0), 0),
            )

        self.status_label.pack(fill="x", pady=(10, 0))
        self._update_reset_countdown()
        self._update_stale_badge()

    def _update_section_visibility(self) -> None:
        """Apply Total / Today's pace on-off without full chrome rebuild."""
        if self._show_pill_mode():
            return
        if self.settings.show_total:
            if not self.total_row.winfo_ismapped():
                self.total_row.pack(fill="x", pady=(14, 0), after=self.header)
        else:
            self.total_row.pack_forget()
        self._update_pace_visibility()

    def _update_pace_visibility(self) -> None:
        if not hasattr(self, "pace_panel"):
            return
        show = bool(self.settings.show_pace) and not self._show_pill_mode()
        if show:
            if not self.pace_panel.winfo_ismapped():
                if self.total_row.winfo_ismapped():
                    self.pace_panel.pack(fill="x", pady=(12, 0), after=self.total_row)
                elif self.header.winfo_ismapped():
                    self.pace_panel.pack(fill="x", pady=(14, 0), after=self.header)
                else:
                    self.pace_panel.pack(fill="x", pady=(0, 0))
        else:
            self.pace_panel.pack_forget()

    def _pace_accent(self, state: str) -> str:
        return pace_accent(state)

    def _paint_status(self) -> None:
        if self._refreshing:
            color = DOT_PULSE if self._pulse_on else DOT_UNKNOWN
            cue = ""
        elif self._connection_ok is True:
            color = DOT_OK
            cue = ""
        elif self._connection_ok is False:
            color = DOT_ERR
            cue = self._error_cue_label()
        else:
            color = DOT_UNKNOWN
            cue = ""

        self.status_dot.itemconfigure(self._dot_item, fill=color)
        self._pill_view["dot_color"] = color
        self._pill_view["cue"] = cue if cue else ""
        if cue:
            self.status_cue.configure(text=cue, fg=DOT_ERR)
            if not self.status_cue.winfo_ismapped():
                self.status_cue.pack(side="left", padx=(4, 0))
        else:
            self.status_cue.pack_forget()
        if self._show_pill_mode():
            self._redraw_pill_face()

    def _error_cue_label(self) -> str:
        msg = (self.status_label.cget("text") or "").lower()
        if "auth" in msg or "token" in msg or "sign" in msg:
            return "Auth"
        if "network" in msg or "url" in msg or "timed" in msg:
            return "Offline"
        return "Error"

    def _on_pill_configure(self, event: object = None) -> None:
        # Ignore noise while we lock geometry; only redraw on real size changes.
        if event is not None and hasattr(event, "width") and hasattr(event, "height"):
            w, h, _, _ = self._pill_metrics()
            if int(event.width) == w and int(event.height) == h:
                return
        self._redraw_pill_face()

    def _draw_capsule(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        fill: str,
        *,
        tag: str = "face",
    ) -> None:
        diam = y2 - y1
        if diam < 2 or x2 - x1 < diam:
            return
        r = diam / 2.0
        canvas.create_oval(x1, y1, x1 + diam, y2, fill=fill, outline="", tags=tag)
        canvas.create_oval(x2 - diam, y1, x2, y2, fill=fill, outline="", tags=tag)
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="", tags=tag)

    def _draw_capsule_stroke(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str,
        *,
        width: int = 2,
        tag: str = "face",
    ) -> None:
        """Uniform capsule outline (balanced — no thick crescent ends)."""
        diam = y2 - y1
        if diam < 4 or x2 - x1 < diam:
            return
        r = diam / 2.0
        canvas.create_arc(
            x1, y1, x1 + diam, y2,
            start=90, extent=180, style="arc",
            outline=color, width=width, tags=tag,
        )
        canvas.create_arc(
            x2 - diam, y1, x2, y2,
            start=270, extent=180, style="arc",
            outline=color, width=width, tags=tag,
        )
        canvas.create_line(x1 + r, y1, x2 - r, y1, fill=color, width=width, tags=tag)
        canvas.create_line(x1 + r, y2, x2 - r, y2, fill=color, width=width, tags=tag)

    def _pill_metrics(self) -> tuple[int, int, int, int]:
        """Return (width, height, text_w, badge_w) for compact capsule."""
        view = self._pill_view
        text = str(view.get("text") or "—%")
        font_nums = tkfont.Font(family=PILL_NUM_FONT[0], size=PILL_NUM_FONT[1], weight="bold")
        font_badge = tkfont.Font(family=PILL_BADGE_FONT[0], size=PILL_BADGE_FONT[1], weight="bold")
        text_w = font_nums.measure(text)
        badge_w = 0
        if view.get("show_badge"):
            badge_w = font_badge.measure(str(view.get("badge_text") or "")) + 12
        cue_w = 0
        cue = str(view.get("cue") or "")
        if cue:
            font_cue = tkfont.Font(family="Segoe UI", size=7, weight="bold")
            cue_w = font_cue.measure(cue) + 6
        width = (
            PILL_PAD_L
            + PILL_RING
            + PILL_GAP
            + text_w
            + (PILL_GAP + badge_w if badge_w else 0)
            + cue_w
            + PILL_PAD_R
        )
        return max(width, PILL_HEIGHT), PILL_HEIGHT, text_w, badge_w

    def _redraw_pill_face(self) -> None:
        """Compact cream pill + even border via color-key (no HRGN fringe)."""
        c = self.pill_face
        view = self._pill_view
        border = getattr(self, "_pill_border_color", CARD)
        w, h, _text_w, badge_w = self._pill_metrics()
        key = "#%02X%02X%02X" % TRANSPARENT_KEY

        # Lock drawable + toplevel to the same pixel box (prevents cut-off bottom).
        c.configure(width=w, height=h, bg=key)
        try:
            hwnd = toplevel_hwnd(self)
            pos = get_window_pos(hwnd)
            self.geometry(f"{w}x{h}")
            if pos is not None:
                set_window_pos(hwnd, pos[0], pos[1])
        except tk.TclError:
            pass

        c.delete("face")

        for widget in (self, self.outer, self.card, self.pill):
            try:
                widget.configure(bg=key)
            except tk.TclError:
                pass

        # Full-bleed key, then cream body + forced ring (Tk ovals skip the last
        # row when y2 == height; card pady used to clip the same edge).
        c.create_rectangle(0, 0, w + 1, h + 1, fill=key, outline="", tags="face")
        x2, y2 = float(w - 1), float(h - 1)
        if border != CARD:
            bw = float(PILL_BORDER_PX)
            self._draw_capsule(c, 0, 0, x2, y2, str(border))
            self._draw_capsule(c, bw, bw, x2 - bw, y2 - bw, CARD)
            # Solid top/bottom bars — guarantees continuous stroke mid-capsule.
            rad = (y2 - 0) / 2.0
            c.create_rectangle(rad, 0, x2 - rad, bw, fill=str(border), outline="", tags="face")
            c.create_rectangle(
                rad, y2 - bw, x2 - rad, y2, fill=str(border), outline="", tags="face"
            )
        else:
            self._draw_capsule(c, 0, 0, x2, y2, CARD)

        # Ring + center dot
        cx = PILL_PAD_L + PILL_RING / 2
        cy = h / 2
        r_out = PILL_RING / 2 - 2
        c.create_arc(
            cx - r_out, cy - r_out, cx + r_out, cy + r_out,
            start=90, extent=-359.9, style="arc",
            outline=BAR_BG, width=2, tags="face",
        )
        extent = float(view.get("ring_extent") or 0.0)
        if extent:
            c.create_arc(
                cx - r_out, cy - r_out, cx + r_out, cy + r_out,
                start=90, extent=extent, style="arc",
                outline=str(view.get("ring_color") or WARN), width=2, tags="face",
            )
        dot_r = 3.5
        c.create_oval(
            cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r,
            fill=str(view.get("dot_color") or DOT_UNKNOWN), outline="", tags="face",
        )

        # Numbers
        x = PILL_PAD_L + PILL_RING + PILL_GAP
        c.create_text(
            x, cy,
            text=str(view.get("text") or "—%"),
            fill=str(view.get("number_color") or TEXT),
            font=PILL_NUM_FONT,
            anchor="w",
            tags="face",
        )
        font_nums = tkfont.Font(family=PILL_NUM_FONT[0], size=PILL_NUM_FONT[1], weight="bold")
        x += font_nums.measure(str(view.get("text") or "—%"))

        # WARN/STOP chip
        if view.get("show_badge") and badge_w:
            x += PILL_GAP
            bh = 18
            by1 = cy - bh / 2
            by2 = cy + bh / 2
            bx2 = x + badge_w
            rad = 6
            bg = str(view.get("badge_bg") or PACE_WARN_BG)
            c.create_oval(x, by1, x + rad * 2, by2, fill=bg, outline="", tags="face")
            c.create_oval(bx2 - rad * 2, by1, bx2, by2, fill=bg, outline="", tags="face")
            c.create_rectangle(x + rad, by1, bx2 - rad, by2, fill=bg, outline="", tags="face")
            c.create_text(
                x + badge_w / 2, cy,
                text=str(view.get("badge_text") or ""),
                fill=str(view.get("badge_fg") or PACE_WARN_FG),
                font=PILL_BADGE_FONT,
                anchor="center",
                tags="face",
            )
            x = bx2

        cue = str(view.get("cue") or "")
        if cue:
            x += PILL_GAP
            c.create_text(
                x, cy,
                text=cue,
                fill=DOT_ERR,
                font=("Segoe UI", 7, "bold"),
                anchor="w",
                tags="face",
            )

        # Re-assert color-key after geometry (click-through / layout can clear it).
        try:
            hwnd = toplevel_hwnd(self)
            clear_window_region(hwnd)
            set_color_key(hwnd, TRANSPARENT_KEY)
        except Exception:
            pass

    def _apply_pill_border(self, border: str) -> None:
        """OK = seamless cream; WARN/STOP = even capsule border."""
        self._pill_border_color = border
        if self._show_pill_mode():
            self.card.configure(padx=0, pady=0)
            self.card.pack_configure(padx=0, pady=0)
            self._redraw_pill_face()
            self._apply_rounded_corners(*self._target_size())
        elif border != CARD:
            self.outer.configure(bg=border)
            self.card.configure(bg=CARD)
            self.card.pack_configure(padx=2, pady=2)
        else:
            self.card.pack_configure(padx=0, pady=0)
    def _apply_rounded_corners(self, width: int, height: int) -> None:
        hwnd = toplevel_hwnd(self)
        if self._show_pill_mode():
            # Color-key shape — drawn capsule IS the visible shape (balanced border).
            clear_window_region(hwnd)
            set_color_key(hwnd, TRANSPARENT_KEY)
            return

        set_color_key(hwnd, None)
        set_rounded_corners(hwnd, width, height, CORNER_RADIUS)

    def _update_pill_percent(self) -> None:
        view = self._pill_view
        if self._last_usage is None:
            view.update(
                {
                    "text": "—%",
                    "number_color": TEXT,
                    "ring_extent": 0.0,
                    "show_badge": False,
                    "badge_text": "",
                }
            )
            self._apply_pill_border(CARD)
            return

        metric = effective_pill_metric(self.settings)
        if metric == "pace" and self._last_pace is not None:
            pace = self._last_pace
            pct = min(150.0, pace.percent_of_fair * 100.0)
            chrome = pill_chrome(
                pace.state,
                used_label=format_units(pace.used_today),
                fair_label=format_units(pace.fair_today),
                fill_pct=pct,
            )
            extent = -max(1.0, min(359.9, min(pct, 100.0) / 100.0 * 359.9))
            view.update(
                {
                    "text": chrome.text,
                    "number_color": chrome.number_color,
                    "ring_color": chrome.ring_color,
                    "ring_extent": extent,
                    "show_badge": chrome.show_badge,
                    "badge_text": chrome.badge_text,
                    "badge_bg": chrome.badge_bg,
                    "badge_fg": chrome.badge_fg,
                }
            )
            self._apply_pill_border(chrome.border_color)
            return

        if metric == "pace":
            view.update(
                {
                    "text": "—%",
                    "number_color": TEXT,
                    "ring_extent": 0.0,
                    "show_badge": False,
                }
            )
            self._apply_pill_border(CARD)
            return

        value = resolve_minimized_percent(self._last_usage, metric)
        extent = -max(1.0, min(359.9, value / 100.0 * 359.9))
        view.update(
            {
                "text": format_usage_percent(value),
                "number_color": TEXT,
                "ring_color": bar_color_for_percent(value),
                "ring_extent": extent,
                "show_badge": False,
            }
        )
        self._apply_pill_border(CARD)

    def _update_reset_countdown(self) -> None:
        if self._show_pill_mode() or not self.settings.show_reset_countdown:
            self.reset_label.pack_forget()
            return
        text = self._format_reset_countdown()
        if not text:
            self.reset_label.pack_forget()
            return
        self.reset_label.configure(text=text)
        self.reset_label.pack(fill="x", pady=(8, 0), before=self.status_label)

    def _format_reset_countdown(self) -> str:
        if self._last_usage is None or not self._last_usage.billing_cycle_end:
            return ""
        raw = self._last_usage.billing_cycle_end.strip()
        end = _parse_billing_end(raw)
        if end is None:
            return f"Cycle ends: {raw}"
        now = datetime.now(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta = end - now
        secs = int(delta.total_seconds())
        if secs <= 0:
            return "Resets soon"
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days > 0:
            return f"Resets in {days}d {hours}h"
        if hours > 0:
            return f"Resets in {hours}h {minutes}m"
        return f"Resets in {minutes}m"

    def _update_stale_badge(self) -> None:
        if self._show_pill_mode():
            self.stale_badge.pack_forget()
            return
        stale = False
        if self.settings.show_stale_badge and self._last_success_at is not None:
            age_ms = (datetime.now() - self._last_success_at).total_seconds() * 1000
            stale = age_ms > STALE_MS
        if stale:
            self.stale_badge.pack(fill="x", pady=(8, 0), before=self.status_label)
        else:
            self.stale_badge.pack_forget()

    def _refresh_status_text(self) -> None:
        if self._show_pill_mode():
            return
        if self._connection_ok is False and self.status_label.cget("text"):
            return
        if self._last_success_at is not None:
            stamp = self._last_success_at.strftime("%H:%M:%S")
            self.status_label.configure(text=f"Updated {stamp}")

    def _target_size(self) -> tuple[int, int]:
        self.update_idletasks()
        if self._show_pill_mode():
            w, h, _, _ = self._pill_metrics()
            return w, h
        return WINDOW_WIDTH, max(self.winfo_reqheight(), 1)

    def _place_top_right(self) -> None:
        width, height = self._target_size()
        screen_w = self.winfo_screenwidth()
        x = max(screen_w - width - 24, 0)
        y = 24
        self.geometry(f"{width}x{height}+{x}+{y}")
        self._placed = True
        self._apply_rounded_corners(width, height)

    def _restore_or_place_default(self) -> None:
        """Restore last position/mode, or top-right on first run."""
        state = self._window_state
        if state is None:
            self._place_top_right()
            return
        width, height = self._target_size()
        ox, oy, vw, vh = virtual_screen_bounds(
            self.winfo_screenwidth(), self.winfo_screenheight()
        )
        x, y = clamp_position(
            state.x,
            state.y,
            width=width,
            height=height,
            screen_w=vw,
            screen_h=vh,
            origin_x=ox,
            origin_y=oy,
        )
        # Size via Tk, position via Win32 (Tk winfo/geometry mishandles 2nd monitor).
        self.geometry(f"{width}x{height}")
        hwnd = toplevel_hwnd(self)
        if not set_window_pos(hwnd, x, y):
            self.geometry(f"{width}x{height}+{x}+{y}")
        self._placed = True
        self._apply_rounded_corners(width, height)

    def _persist_window_state(self) -> None:
        try:
            self.update_idletasks()
            width = max(self.winfo_width(), 1)
            height = max(self.winfo_height(), 1)
            hwnd = toplevel_hwnd(self)
            pos = get_window_pos(hwnd)
            if pos is None:
                pos = (int(self.winfo_x()), int(self.winfo_y()))
            ox, oy, vw, vh = virtual_screen_bounds(
                self.winfo_screenwidth(), self.winfo_screenheight()
            )
            x, y = clamp_position(
                pos[0],
                pos[1],
                width=width,
                height=height,
                screen_w=vw,
                screen_h=vh,
                origin_x=ox,
                origin_y=oy,
            )
            state = WindowState(x=x, y=y, minimized=bool(self._show_pill_mode()))
            save_window_state(state)
            self._window_state = state
        except Exception:
            pass

    def _resize_to_content(self, *, pin_right: bool = False) -> None:
        width, height = self._target_size()
        hwnd = toplevel_hwnd(self)
        pos = get_window_pos(hwnd)
        cur_x = pos[0] if pos is not None else int(self.winfo_x())
        cur_y = pos[1] if pos is not None else int(self.winfo_y())
        cur_w = max(self.winfo_width(), 1)
        if pin_right:
            x = cur_x + cur_w - width
            y = cur_y
        else:
            x, y = cur_x, cur_y
        self.geometry(f"{width}x{height}")
        if not set_window_pos(hwnd, x, y):
            self.geometry(f"{width}x{height}+{x}+{y}")
        self._apply_rounded_corners(width, height)

    def _set_alpha(self, value: float) -> None:
        """Fade opacity without dropping pill color-key (avoids pink edges)."""
        alpha = max(0.0, min(1.0, value))
        hwnd = toplevel_hwnd(self)
        try:
            pill_up = bool(self.pill.winfo_ismapped())
        except tk.TclError:
            pill_up = False
        if hwnd and pill_up:
            # Tk -alpha uses LWA_ALPHA alone and clears LWA_COLORKEY → magenta shows.
            set_layered_attrs(
                hwnd,
                color_key=TRANSPARENT_KEY,
                alpha=int(round(alpha * 255)),
            )
            return
        try:
            self.attributes("-alpha", alpha)
        except tk.TclError:
            pass

    def _cancel_animation(self) -> None:
        if self._anim_job is not None:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None
        self._animating = False

    def _fade_alpha(
        self,
        start: float,
        end: float,
        duration_ms: int,
        *,
        on_done: object | None = None,
    ) -> None:
        if self._anim_job is not None:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

        frames = max(1, duration_ms // FADE_FRAME_MS)

        def ease(t: float) -> float:
            # ease-in-out quad
            return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2

        def step(i: int) -> None:
            t = min(1.0, i / frames)
            self._set_alpha(start + (end - start) * ease(t))
            if i >= frames:
                self._anim_job = None
                self._set_alpha(end)
                if callable(on_done):
                    on_done()
                return
            self._anim_job = self.after(FADE_FRAME_MS, lambda: step(i + 1))

        self._set_alpha(start)
        step(1)

    def _start_drag(self, event: tk.Event) -> None:
        pos = get_window_pos(toplevel_hwnd(self))
        if pos is not None:
            self._drag_x = event.x_root - pos[0]
            self._drag_y = event.y_root - pos[1]
        else:
            self._drag_x = event.x_root - self.winfo_x()
            self._drag_y = event.y_root - self.winfo_y()
        self._pill_press_xy = (event.x_root, event.y_root)

    def _on_drag(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        hwnd = toplevel_hwnd(self)
        if not set_window_pos(hwnd, x, y):
            self.geometry(f"+{x}+{y}")

    def _end_drag(self, event: tk.Event) -> None:
        self._persist_window_state()
        # Pill single-click-to-expand still uses the same release.
        if self._show_pill_mode():
            self._pill_click(event)

    def _schedule_poll(self) -> None:
        self.refresh_async()
        self.after(POLL_MS, self._schedule_poll)

    def _schedule_stale_check(self) -> None:
        if not self._show_pill_mode():
            self._update_stale_badge()
        self.after(30_000, self._schedule_stale_check)

    def _start_pulse(self) -> None:
        self._stop_pulse()
        self._pulse_on = False

        def tick() -> None:
            if not self._refreshing:
                self._pulse_job = None
                self._paint_status()
                return
            self._pulse_on = not self._pulse_on
            self._paint_status()
            angle = 0 if not hasattr(self, "_refresh_spin") else self._refresh_spin
            self._refresh_spin = (angle + 45) % 360
            # Subtle refresh glyph cue via fg flash
            try:
                self.refresh_btn.configure(fg=TEXT if self._pulse_on else MUTED)
            except tk.TclError:
                pass
            self._pulse_job = self.after(180, tick)

        tick()

    def _stop_pulse(self) -> None:
        if self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
        self._pulse_on = False
        try:
            self.refresh_btn.configure(fg=MUTED, bg=CARD)
        except tk.TclError:
            pass

    def refresh_async(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        self._start_pulse()
        if not self._show_pill_mode():
            self.status_label.configure(text="Refreshing…")

        def worker() -> None:
            try:
                usage = fetch_current_period_usage()
                self.after(0, lambda: self._apply_usage(usage))
            except (AuthError, UsageError) as exc:
                msg = str(exc)
                self.after(0, lambda: self._apply_error(msg))
            except Exception as exc:  # noqa: BLE001
                msg = f"Unexpected error: {exc}"
                self.after(0, lambda: self._apply_error(msg))
            finally:
                self.after(0, self._clear_refreshing)

        threading.Thread(target=worker, daemon=True).start()

    def _clear_refreshing(self) -> None:
        self._refreshing = False
        self._stop_pulse()
        self._paint_status()

    def _apply_usage(self, usage: PlanUsage) -> None:
        self._last_usage = usage
        self._connection_ok = True
        self._last_success_at = datetime.now()
        self.total_row.set_percent(usage.auto_percent)
        self.total_row.set_subtext("Includes Grok and Composer")
        self.auto_row.set_percent(usage.auto_percent)
        self.api_row.set_percent(usage.api_percent)
        self._update_pace_from_usage(usage)
        self._paint_status()
        self._update_pill_percent()
        if not self._show_pill_mode():
            stamp = self._last_success_at.strftime("%H:%M:%S")
            self.status_label.configure(text=f"Updated {stamp}")
            self._update_reset_countdown()
            self._update_stale_badge()
            self._update_section_visibility()
        self._resize_to_content()

    def _pace_history_path(self) -> Path:
        return active_pace_history_path(self.settings.pace_sync_folder)

    def _update_pace_from_usage(self, usage: PlanUsage) -> None:
        budget = budget_from_plan(usage)
        path = self._pace_history_path()
        history = load_history(path)
        history, used_today, _weights = record_usage_point(
            history, used=budget.used, unit=budget.unit
        )
        save_history(history, path)

        cycle_end = datetime.now() + timedelta(days=14)
        if usage.billing_cycle_end:
            parsed = _parse_billing_end(usage.billing_cycle_end.strip())
            if parsed is not None:
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone().replace(tzinfo=None)
                cycle_end = parsed

        pace = compute_pace(
            remaining=budget.remaining,
            billing_cycle_end=cycle_end,
            now=datetime.now(),
            weights=_weights,
            used_today=used_today,
        )
        self._last_pace = pace

        # Pace bar fills by % of today's fair budget; label shows used%/fair
        pace_pct = min(100.0, pace.percent_of_fair * 100.0)
        self.pace_row.set_percent(pace_pct)
        used_lbl = format_units(pace.used_today)
        fair_lbl = format_units(pace.fair_today)
        self.pace_row.pct_label.configure(
            text=f"{used_lbl}%/{fair_lbl}%",
            fg=self._pace_accent(pace.state) if pace.state != "OK" else TEXT,
        )
        self.pace_row.title_label.configure(text="Today's pace", fg=TEXT)

        unit = "%" if budget.unit == "percent" else "¢"
        if budget.remaining <= 0.01:
            meta = "Cycle allowance used up"
        else:
            meta = (
                f"{pace.days_left} days incl. today"
                f"  ·  {format_units(budget.remaining)}{unit} left in cycle"
            )
        self.pace_meta.configure(text=meta, fg=MUTED)

        # Badge + warning only when near/over today's pace
        if pace.state == "OK":
            self.pace_badge.pack_forget()
            self.pace_msg.pack_forget()
        else:
            bg, fg = pace_badge_colors(pace.state)
            self.pace_badge.configure(text=pace.state, bg=bg, fg=fg)
            if not self.pace_badge.winfo_ismapped():
                self.pace_badge.pack(side="right", before=self.pace_reset_btn)
            self.pace_msg.configure(text=pace.message, fg=self._pace_accent(pace.state))
            if not self.pace_msg.winfo_ismapped():
                self.pace_msg.pack(fill="x", pady=(4, 0), before=self.pace_meta)

        if self._show_pill_mode():
            self._apply_pill_border(pill_border_for_state(pace.state))
        else:
            self.outer.configure(bg=frame_border_for_state(pace.state))
            self.card.pack_configure(padx=1, pady=1)

    def _reset_pace_today(self) -> None:
        """Re-baseline local used-today counter (does not change Cursor usage)."""
        if self._last_usage is None:
            self.status_label.configure(text="No usage data yet — refresh first")
            return
        budget = budget_from_plan(self._last_usage)
        path = self._pace_history_path()
        history = load_history(path)
        history = reset_today_baseline(history, used=budget.used, unit=budget.unit)
        save_history(history, path)
        self._update_pace_from_usage(self._last_usage)
        self._update_pill_percent()
        if not self._show_pill_mode():
            self.status_label.configure(text="Pace reset — today's count starts at 0")
            self._update_section_visibility()
        self._resize_to_content()

    def _apply_error(self, message: str) -> None:
        self._connection_ok = False
        if not self._show_pill_mode():
            self.status_label.configure(text=message)
            self._update_stale_badge()
        self._paint_status()
        self._resize_to_content()


def _parse_billing_end(raw: str) -> datetime | None:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        num = float(raw)
        if num > 1e12:
            num /= 1000.0
        return datetime.fromtimestamp(num, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def main() -> None:
    set_app_user_model_id()
    app = UsageFloater()
    try:
        tkfont.nametofont("TkDefaultFont").configure(family="Segoe UI", size=9)
    except tk.TclError:
        pass
    app.after(100, app._apply_settings_side_effects)
    # Re-apply icon after the HWND is fully realized (taskbar / alt-tab).
    app.after(100, lambda: apply_tk_icon(app, APP_ICON))
    app.after(150, app._hide_from_taskbar)
    app.mainloop()


if __name__ == "__main__":
    main()
