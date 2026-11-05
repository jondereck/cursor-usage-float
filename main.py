"""Always-on-top floating Cursor usage widget (personal / portable)."""

from __future__ import annotations

import json
import math
import os
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import font as tkfont

from account_slots import cursor_slot_label, short_email_display
from cursor_auth import AuthError, get_access_token, read_access_token_from_file, token_fingerprint
from cursor_identity import get_cursor_account_info
from grok_app_usage import (
    GrokAppError,
    GrokAppUsage,
    fetch_grok_app_usage,
    format_grok_app_error,
    format_grok_plan_label,
    grok_error_needs_login_action,
    resolve_grok_auth_path,
)
from grok_cli_setup import ensure_grok_auth_for_usage, grok_auth_ready
from grok_login_launcher import launch_grok_login_terminal
from login_watch import file_stamp, live_cursor_fingerprint
from cursor_usage import (
    GrokBotUsage,
    PlanUsage,
    TokenUsage,
    UsageError,
    budget_from_plan,
    fetch_current_period_usage,
    fetch_grok_bot_usage,
    fetch_token_usage,
)
from antigravity_usage import AntigravityUsage, fetch_antigravity_usage
from codex_usage import CodexUsage, fetch_codex_usage
from opencode_usage import (
    OpenCodeUsage,
    apply_budget,
    fetch_opencode_usage,
    format_token_count,
)
from paths import resource_path
from pill_icons import load_pill_icons
from polling import POLL_TICK_MS, SLOW_POLL_MS, poll_interval_ms
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
from app_version import format_version_footer, whats_new_unread
from settings import (
    AppSettings,
    cursor_primary_bar_label,
    cursor_secondary_bar_label,
    default_settings_path,
    effective_click_through,
    effective_pill_metric,
    ensure_usage_section_visible,
    format_cursor_usage_percent,
    format_usage_percent,
    load_settings,
    resolve_minimized_percent,
    save_settings,
)
from settings_ui import SettingsWindow, open_settings
from whats_new_ui import open_whats_new
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
from spin_button import SpinButton
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
from win_idle import seconds_since_last_input
from win_startup import set_start_with_windows
from window_state import (
    WindowState,
    clamp_position,
    load_window_state,
    save_window_state,
    virtual_screen_bounds,
)

POLL_MS = SLOW_POLL_MS  # slowest cadence (also drives the stale badge)
STALE_MS = 2 * POLL_MS
# GetAggregatedUsageEvents is a heavier query; a couple of minutes of lag is
# fine for a cumulative token counter.
TOKEN_USAGE_TTL_S = 120.0
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
PILL_DUAL_NUM_FONT = ("Segoe UI", 10, "bold")
PILL_BADGE_FONT = ("Segoe UI", 8, "bold")
PILL_DUAL_PAD_X = 10
PILL_DUAL_ITEM_GAP = 5
PILL_DUAL_SECTION_GAP = 8
PILL_DUAL_DIVIDER_H = 16
PILL_ICON = 20
CORNER_RADIUS = 18
PILL_CORNER_RADIUS = 22  # unused in pill mode; radius = height
GEAR_ICON = "\uE713"
FADE_OUT_MS = 90
FADE_IN_MS = 110
FADE_FRAME_MS = 12
APP_ICON = resource_path("assets", "app.ico")


def _usage_moved(previous: PlanUsage, current: PlanUsage) -> bool:
    """True when headline percentages moved (covers background agent usage)."""
    return (
        round(previous.auto_percent, 1) != round(current.auto_percent, 1)
        or round(previous.api_percent, 1) != round(current.api_percent, 1)
    )


def _antigravity_cache_path() -> Path:
    return default_settings_path().with_name("antigravity-usage.json")


def _load_antigravity_cache() -> tuple[AntigravityUsage, datetime] | None:
    try:
        payload = json.loads(_antigravity_cache_path().read_text(encoding="utf-8"))
        usage = payload["usage"]
        updated_at = datetime.fromisoformat(payload["updated_at"])

        def percent(value: object) -> float | None:
            if value is None:
                return None
            number = float(value)
            return number if math.isfinite(number) and 0 <= number <= 100 else None

        usage_percent = percent(usage["usage_percent"])
        if usage_percent is None:
            return None
        next_reset = usage.get("next_reset")
        if next_reset is not None and not isinstance(next_reset, str):
            return None
        if updated_at.tzinfo is not None:
            updated_at = updated_at.astimezone().replace(tzinfo=None)
        return (
            AntigravityUsage(
                usage_percent=usage_percent,
                gemini_percent=percent(usage.get("gemini_percent")),
                claude_gpt_percent=percent(usage.get("claude_gpt_percent")),
                next_reset=next_reset,
                plan_name=None,
                is_eligible=True,
            ),
            updated_at,
        )
    except (OSError, KeyError, TypeError, ValueError, OverflowError):
        return None


def _save_antigravity_cache(usage: AntigravityUsage, updated_at: datetime) -> None:
    path = _antigravity_cache_path()
    temporary = path.with_suffix(".tmp")
    payload = {
        "updated_at": updated_at.isoformat(),
        "usage": {
            "usage_percent": usage.usage_percent,
            "gemini_percent": usage.gemini_percent,
            "claude_gpt_percent": usage.claude_gpt_percent,
            "next_reset": usage.next_reset,
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


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
        precise: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(master, bg=master.cget("bg"), **kwargs)
        self._value = 0.0
        self._hero = hero
        self._compact = compact
        self._precise = precise

        header = tk.Frame(self, bg=self.cget("bg"))
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)

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
        self.title_label.grid(row=0, column=0, sticky="w")

        self.pct_label = tk.Label(
            header,
            text="—%",
            bg=self.cget("bg"),
            fg=TEXT,
            font=("Segoe UI Semibold", pct_size),
            anchor="e",
        )
        self.pct_label.grid(row=0, column=1, sticky="e", padx=(6, 0))

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
        label = (
            format_cursor_usage_percent(self._value)
            if self._precise
            else format_usage_percent(self._value)
        )
        self.pct_label.configure(
            text=label,
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

    def set_title(self, title: str) -> None:
        text = (title or "").strip()
        max_len = 22 if self._hero else 18
        if len(text) > max_len:
            text = text[: max_len - 1].rstrip() + "…"
        self.title_label.configure(text=text)

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
        self._last_poll_at = 0.0
        self._last_usage_change_at = 0.0
        self._antigravity_retry_job: str | None = None
        self._antigravity_retrying = False
        self._connection_ok: bool | None = None
        self._last_success_at: datetime | None = None
        self._last_usage: PlanUsage | None = None
        self._last_token_usage: TokenUsage | None = None
        self._token_usage_at = 0.0
        self._last_usage_secondary: PlanUsage | None = None
        self._secondary_cursor_error: str | None = None
        self._last_grok_bot: GrokBotUsage | None = None
        self._last_grok_app: GrokAppUsage | None = None
        self._grok_app_error: str | None = None
        self._cursor_account = get_cursor_account_info()
        self._cursor_fp: str | None = None
        self._cached_cursor_token: str | None = None
        self._grok_auth_stamp: str | None = None
        self._grok_seen_ok = False
        self._grok_relogin_notified = False
        cached_antigravity = _load_antigravity_cache()
        self._last_antigravity: AntigravityUsage | None = (
            cached_antigravity[0] if cached_antigravity else None
        )
        self._last_antigravity_updated_at: datetime | None = (
            cached_antigravity[1] if cached_antigravity else None
        )
        self._antigravity_error: str | None = (
            "Checking for live usage…" if cached_antigravity else "Waiting for Antigravity usage…"
        )
        self._last_codex: CodexUsage | None = None
        self._last_opencode: OpenCodeUsage | None = None
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
        self._apply_antigravity(self._last_antigravity, self._antigravity_error)
        self._tray = TrayIcon(
            self,
            tip="Cursor Usage",
            icon_path=APP_ICON,
            on_show=self._on_tray_show,
            on_settings=self._open_settings,
            on_whats_new=self._open_whats_new,
            whats_new_unread=lambda: whats_new_unread(self.settings.last_seen_version),
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
        self.after(POLL_TICK_MS, self._poll_tick)
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

        self.refresh_btn = SpinButton(self.header, self.refresh_async)
        self._header_btn("✕", self.destroy).pack(side="right")
        self.refresh_btn.pack(side="right", padx=(0, 2))
        self._header_btn(GEAR_ICON, self._open_settings, icon_font=True).pack(
            side="right", padx=(0, 2)
        )
        self._header_btn("−", self._toggle_minimized).pack(side="right", padx=(0, 2))

        self.total_row = ProgressRow(
            self.expanded, "Cursor Models", hero=True, precise=True
        )
        self.total_row.configure(bg=CARD)
        self.total_row.pack(fill="x", pady=(14, 0))

        self.total_row_secondary = ProgressRow(
            self.expanded, "Cursor Models (2)", hero=True, precise=True
        )
        self.total_row_secondary.configure(bg=CARD)

        self.grok_bot_row = ProgressRow(self.expanded, "Grok Bot (Cursor)", hero=True)
        self.grok_bot_row.configure(bg=CARD)

        self.grok_premium_row = ProgressRow(self.expanded, "Grok", hero=True)
        self.grok_premium_row.configure(bg=CARD)
        self.grok_login_btn_frame = tk.Frame(self.expanded, bg=CARD)
        self.grok_login_btn = tk.Button(
            self.grok_login_btn_frame,
            text="Run grok login",
            command=self._launch_grok_login,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD,
            activeforeground=TEXT,
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
        )
        self.grok_login_btn.pack(anchor="w")
        # Packed only when show_grok_bot and fetch is eligible.

        self.antigravity_row = ProgressRow(self.expanded, "Antigravity", hero=True)
        self.antigravity_row.configure(bg=CARD)
        # Packed only when show_antigravity and fetch is eligible.

        self.codex_row = ProgressRow(self.expanded, "Codex", hero=True)
        self.codex_row.configure(bg=CARD)
        # Packed only when show_codex and fetch is eligible.

        self.opencode_row = ProgressRow(self.expanded, "OpenCode", hero=True)
        self.opencode_row.configure(bg=CARD)
        # Packed only when show_opencode and the local store is readable.

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

        self.auto_row = ProgressRow(
            self.detail, "Cursor Models", compact=True, precise=True
        )
        self.auto_row.configure(bg=CARD)

        self.api_row = ProgressRow(self.detail, "Other Models", compact=True)
        self.api_row.configure(bg=CARD)

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

        self._version_label = format_version_footer()
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
            "layout": "ring",  # ring | icons
            "show_cursor": False,
            "show_grok": False,
            "show_grok_com": False,
            "show_antigravity": False,
            "show_codex": False,
            "show_opencode": False,
            "text": "—%",
            "cursor_text": "—%",
            "grok_text": "—%",
            "grok_com_text": "—%",
            "antigravity_text": "—%",
            "codex_text": "—%",
            "opencode_text": "—%",
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
        self._pill_icon_cursor: tk.PhotoImage | None = None
        self._pill_icon_grok: tk.PhotoImage | None = None
        self._pill_icon_xai: tk.PhotoImage | None = None
        self._pill_icon_antigravity: tk.PhotoImage | None = None
        self._pill_icon_codex: tk.PhotoImage | None = None
        self._pill_icon_opencode: tk.PhotoImage | None = None
        self._pill_image_refs: list[tk.PhotoImage] = []
        pill_icons, self._pill_image_refs = load_pill_icons(self)
        self._pill_icon_cursor = pill_icons.get("cursor")
        self._pill_icon_grok = pill_icons.get("grok")
        self._pill_icon_xai = pill_icons.get("xai")
        self._pill_icon_antigravity = pill_icons.get("antigravity")
        self._pill_icon_codex = pill_icons.get("codex")
        self._pill_icon_opencode = pill_icons.get("opencode")
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
            on_whats_new_seen=self._on_whats_new_seen,
        )

    def _open_whats_new(self) -> None:
        open_whats_new(self, self.settings, on_seen=self._on_whats_new_seen)

    def _on_whats_new_seen(self, settings: AppSettings) -> None:
        self.settings = settings
        if self._tray is not None:
            self._tray._refresh_whats_new_label()
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.sync_from_settings(settings)

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
        if self._last_opencode is not None:
            rescored = apply_budget(
                self._last_opencode, self.settings.opencode_token_budget
            )
            if rescored != self._last_opencode:
                self._last_opencode = rescored
                self._apply_opencode(rescored)
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
            self.total_row_secondary,
            self.grok_bot_row,
            self.grok_premium_row,
            self.antigravity_row,
            self.codex_row,
            self.opencode_row,
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
        self._apply_cursor_bar_labels()
        if self.settings.show_total:
            self.total_row.pack(
                fill="x",
                pady=(14 if self.settings.show_header or first_section else 0, 0),
            )
            first_section = False

        if self._dual_cursor_should_show():
            self.total_row_secondary.pack(
                fill="x",
                pady=(12 if not first_section else 0, 0),
            )
            first_section = False

        if self._grok_bot_should_show():
            self.grok_bot_row.pack(
                fill="x",
                pady=(12 if not first_section else (14 if self.settings.show_header else 0), 0),
            )
            first_section = False

        if self._grok_premium_should_show():
            self.grok_premium_row.pack(
                fill="x",
                pady=(12 if not first_section else (14 if self.settings.show_header else 0), 0),
            )
            first_section = False

        if self._antigravity_should_show():
            self.antigravity_row.pack(
                fill="x",
                pady=(12 if not first_section else (14 if self.settings.show_header else 0), 0),
            )
            first_section = False

        if self._codex_should_show():
            self.codex_row.pack(
                fill="x",
                pady=(12 if not first_section else (14 if self.settings.show_header else 0), 0),
            )
            first_section = False

        if self._opencode_should_show():
            self.opencode_row.pack(
                fill="x",
                pady=(12 if not first_section else (14 if self.settings.show_header else 0), 0),
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

    def _dual_cursor_configured(self) -> bool:
        if not self.settings.show_dual_cursor:
            return False
        path = (self.settings.secondary_cursor_token_file or "").strip()
        return bool(path) and Path(path).expanduser().is_file()

    def _dual_cursor_should_show(self) -> bool:
        if not self.settings.show_dual_cursor:
            return False
        if not self._dual_cursor_configured():
            return False
        if not self.settings.show_total or self._show_pill_mode():
            return False
        if self._last_usage_secondary is None:
            return False
        return True

    def _last_cursor_bar(self) -> tk.Widget | None:
        if (
            hasattr(self, "total_row_secondary")
            and self.total_row_secondary.winfo_ismapped()
        ):
            return self.total_row_secondary
        if self.total_row.winfo_ismapped():
            return self.total_row
        if self.settings.show_header and self.header.winfo_ismapped():
            return self.header
        return None

    def _apply_cursor_bar_labels(self) -> None:
        custom = (self.settings.cursor_primary_label or "").strip()
        if custom:
            self.total_row.set_title(custom)
        else:
            self.total_row.set_title(cursor_primary_bar_label(self.settings))
        if hasattr(self, "total_row_secondary"):
            self.total_row_secondary.set_title(
                cursor_secondary_bar_label(self.settings)
            )

    def _apply_secondary_cursor(
        self,
        usage: PlanUsage | None,
        error: str | None,
    ) -> None:
        if not hasattr(self, "total_row_secondary"):
            return
        if usage is not None:
            self._last_usage_secondary = usage
            self._secondary_cursor_error = None
        else:
            self._last_usage_secondary = None
            self._secondary_cursor_error = error
        if not self._dual_cursor_should_show():
            self.total_row_secondary.pack_forget()
            return
        self.total_row_secondary.set_title(cursor_secondary_bar_label(self.settings))
        self.total_row_secondary.set_percent(usage.auto_percent)
        self.total_row_secondary.set_subtext(
            "Saved login · re-export token file when you switch accounts"
        )

    def _grok_bot_should_show(self) -> bool:
        return (
            bool(self.settings.show_grok_bot)
            and self._last_grok_bot is not None
            and self._last_grok_bot.is_eligible
            and not self._show_pill_mode()
        )

    def _grok_premium_should_show(self) -> bool:
        return bool(self.settings.show_grok_premium) and not self._show_pill_mode()

    def _antigravity_should_show(self) -> bool:
        return (
            bool(self.settings.show_antigravity)
            and (
                (self._last_antigravity is not None and self._last_antigravity.is_eligible)
                or self._antigravity_error is not None
            )
            and not self._show_pill_mode()
        )

    def _codex_should_show(self) -> bool:
        return (
            bool(self.settings.show_codex)
            and self._last_codex is not None
            and self._last_codex.is_eligible
            and not self._show_pill_mode()
        )

    def _opencode_should_show(self) -> bool:
        return (
            bool(self.settings.show_opencode)
            and self._last_opencode is not None
            and self._last_opencode.is_eligible
            and not self._show_pill_mode()
        )

    def _update_section_visibility(self) -> None:
        """Apply Total / Grok Bot / Antigravity / Codex / Today's pace on-off without full chrome rebuild."""
        if self._show_pill_mode():
            return
        if self.settings.show_total:
            if not self.total_row.winfo_ismapped():
                self.total_row.pack(fill="x", pady=(14, 0), after=self.header)
        else:
            self.total_row.pack_forget()
        self._update_dual_cursor_visibility()
        self._update_grok_bot_visibility()
        self._update_grok_premium_visibility()
        self._update_antigravity_visibility()
        self._update_codex_visibility()
        self._update_opencode_visibility()
        self._update_pace_visibility()
        self._update_other_models_visibility()

    def _update_other_models_visibility(self) -> None:
        if not hasattr(self, "api_row"):
            return
        if (
            self.settings.show_other_models
            and not self._show_pill_mode()
            and self.detail.winfo_ismapped()
        ):
            if not self.api_row.winfo_ismapped():
                self.api_row.pack(fill="x")
        else:
            self.api_row.pack_forget()

    def _update_dual_cursor_visibility(self) -> None:
        if not hasattr(self, "total_row_secondary"):
            return
        if self._dual_cursor_should_show():
            if not self.total_row_secondary.winfo_ismapped():
                after = self.total_row if self.total_row.winfo_ismapped() else self.header
                self.total_row_secondary.pack(fill="x", pady=(12, 0), after=after)
            self._apply_secondary_cursor(
                self._last_usage_secondary,
                self._secondary_cursor_error,
            )
        else:
            self.total_row_secondary.pack_forget()

    def _update_grok_bot_visibility(self) -> None:
        if not hasattr(self, "grok_bot_row"):
            return
        show = self._grok_bot_should_show()
        if show:
            if not self.grok_bot_row.winfo_ismapped():
                anchor = self._last_cursor_bar()
                if anchor is not None:
                    self.grok_bot_row.pack(fill="x", pady=(12, 0), after=anchor)
                elif self.header.winfo_ismapped():
                    self.grok_bot_row.pack(fill="x", pady=(14, 0), after=self.header)
                else:
                    self.grok_bot_row.pack(fill="x", pady=(0, 0))
        else:
            self.grok_bot_row.pack_forget()

    def _update_grok_premium_visibility(self) -> None:
        if not hasattr(self, "grok_premium_row"):
            return
        if self._grok_premium_should_show():
            if not self.grok_premium_row.winfo_ismapped():
                if self.grok_bot_row.winfo_ismapped():
                    self.grok_premium_row.pack(fill="x", pady=(12, 0), after=self.grok_bot_row)
                else:
                    anchor = self._last_cursor_bar()
                    if anchor is not None:
                        self.grok_premium_row.pack(fill="x", pady=(12, 0), after=anchor)
                    else:
                        self.grok_premium_row.pack(fill="x")
            self._apply_grok_premium(self._last_grok_app, self._grok_app_error)
        else:
            self.grok_premium_row.pack_forget()
            self._show_grok_login_button(False)

    def _update_antigravity_visibility(self) -> None:
        if not hasattr(self, "antigravity_row"):
            return
        show = self._antigravity_should_show()
        if show:
            if not self.antigravity_row.winfo_ismapped():
                if self.grok_bot_row.winfo_ismapped():
                    self.antigravity_row.pack(fill="x", pady=(12, 0), after=self.grok_bot_row)
                elif (anchor := self._last_cursor_bar()) is not None:
                    self.antigravity_row.pack(fill="x", pady=(12, 0), after=anchor)
                elif self.header.winfo_ismapped():
                    self.antigravity_row.pack(fill="x", pady=(14, 0), after=self.header)
                else:
                    self.antigravity_row.pack(fill="x", pady=(0, 0))
        else:
            self.antigravity_row.pack_forget()

    def _update_codex_visibility(self) -> None:
        if not hasattr(self, "codex_row"):
            return
        show = self._codex_should_show()
        if show:
            if not self.codex_row.winfo_ismapped():
                if self.antigravity_row.winfo_ismapped():
                    self.codex_row.pack(fill="x", pady=(12, 0), after=self.antigravity_row)
                elif self.grok_bot_row.winfo_ismapped():
                    self.codex_row.pack(fill="x", pady=(12, 0), after=self.grok_bot_row)
                elif (anchor := self._last_cursor_bar()) is not None:
                    self.codex_row.pack(fill="x", pady=(12, 0), after=anchor)
                elif self.header.winfo_ismapped():
                    self.codex_row.pack(fill="x", pady=(14, 0), after=self.header)
                else:
                    self.codex_row.pack(fill="x", pady=(0, 0))
        else:
            self.codex_row.pack_forget()

    def _update_opencode_visibility(self) -> None:
        if not hasattr(self, "opencode_row"):
            return
        show = self._opencode_should_show()
        if show:
            if not self.opencode_row.winfo_ismapped():
                if self.codex_row.winfo_ismapped():
                    self.opencode_row.pack(fill="x", pady=(12, 0), after=self.codex_row)
                elif self.antigravity_row.winfo_ismapped():
                    self.opencode_row.pack(fill="x", pady=(12, 0), after=self.antigravity_row)
                elif self.grok_bot_row.winfo_ismapped():
                    self.opencode_row.pack(fill="x", pady=(12, 0), after=self.grok_bot_row)
                elif (anchor := self._last_cursor_bar()) is not None:
                    self.opencode_row.pack(fill="x", pady=(12, 0), after=anchor)
                elif self.header.winfo_ismapped():
                    self.opencode_row.pack(fill="x", pady=(14, 0), after=self.header)
                else:
                    self.opencode_row.pack(fill="x", pady=(0, 0))
        else:
            self.opencode_row.pack_forget()

    def _update_pace_visibility(self) -> None:
        if not hasattr(self, "pace_panel"):
            return
        show = bool(self.settings.show_pace) and not self._show_pill_mode()
        if show:
            if not self.pace_panel.winfo_ismapped():
                if self.opencode_row.winfo_ismapped():
                    self.pace_panel.pack(fill="x", pady=(12, 0), after=self.opencode_row)
                elif self.codex_row.winfo_ismapped():
                    self.pace_panel.pack(fill="x", pady=(12, 0), after=self.codex_row)
                elif self.antigravity_row.winfo_ismapped():
                    self.pace_panel.pack(fill="x", pady=(12, 0), after=self.antigravity_row)
                elif self.grok_bot_row.winfo_ismapped():
                    self.pace_panel.pack(fill="x", pady=(12, 0), after=self.grok_bot_row)
                elif (anchor := self._last_cursor_bar()) is not None:
                    self.pace_panel.pack(fill="x", pady=(12, 0), after=anchor)
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

    def _pill_grok_bot_half(self) -> bool:
        """Grok Bot (Cursor) weekly allowance beside Cursor in the pill."""
        return (
            bool(self.settings.show_grok_bot)
            and self._last_grok_bot is not None
            and self._last_grok_bot.is_eligible
        )

    def _pill_grok_com_half(self) -> bool:
        """Grok.com subscription (grok login) in the pill."""
        return (
            bool(self.settings.show_grok_premium)
            and self._last_grok_app is not None
            and self._last_grok_app.is_eligible
        )

    def _pill_grok_half(self) -> bool:
        return self._pill_grok_bot_half()

    def _pill_antigravity_half(self) -> bool:
        """True when Antigravity usage should appear in the pill."""
        return (
            bool(self.settings.show_antigravity)
            and self._last_antigravity is not None
            and self._last_antigravity.is_eligible
        )

    def _pill_codex_half(self) -> bool:
        """True when Codex usage should appear in the pill."""
        return (
            bool(self.settings.show_codex)
            and self._last_codex is not None
            and self._last_codex.is_eligible
        )

    def _pill_opencode_half(self) -> bool:
        """True when OpenCode usage should appear in the pill."""
        return (
            bool(self.settings.show_opencode)
            and self._last_opencode is not None
            and self._last_opencode.is_eligible
        )

    def _pill_metrics(self) -> tuple[int, int, int, int]:
        """Return (width, height, text_w, badge_w) for compact capsule."""
        view = self._pill_view
        if view.get("layout") == "icons":
            font_nums = tkfont.Font(
                family=PILL_DUAL_NUM_FONT[0],
                size=PILL_DUAL_NUM_FONT[1],
                weight="bold",
            )
            show_cursor = bool(view.get("show_cursor"))
            cursor_w = (
                font_nums.measure(str(view.get("cursor_text") or "—%"))
                if show_cursor
                else 0
            )
            show_grok = bool(view.get("show_grok"))
            grok_w = (
                font_nums.measure(str(view.get("grok_text") or "—%")) if show_grok else 0
            )
            show_grok_com = bool(view.get("show_grok_com"))
            grok_com_w = (
                font_nums.measure(str(view.get("grok_com_text") or "—%"))
                if show_grok_com
                else 0
            )
            show_anti = bool(view.get("show_antigravity"))
            anti_w = (
                font_nums.measure(str(view.get("antigravity_text") or "—%")) if show_anti else 0
            )
            show_codex = bool(view.get("show_codex"))
            codex_w = (
                font_nums.measure(str(view.get("codex_text") or "—%")) if show_codex else 0
            )
            show_opencode = bool(view.get("show_opencode"))
            opencode_w = (
                font_nums.measure(str(view.get("opencode_text") or "—%"))
                if show_opencode
                else 0
            )
            cue_w = 0
            cue = str(view.get("cue") or "")
            if cue:
                font_cue = tkfont.Font(family="Segoe UI", size=7, weight="bold")
                cue_w = font_cue.measure(cue) + PILL_DUAL_SECTION_GAP
            sections = sum(
                1
                for on in (
                    show_cursor,
                    show_grok,
                    show_grok_com,
                    show_anti,
                    show_codex,
                    show_opencode,
                )
                if on
            )
            width = PILL_DUAL_PAD_X
            first = True

            def _add_section(text_w: int) -> None:
                nonlocal width, first
                if not first:
                    width += PILL_DUAL_SECTION_GAP + 1 + PILL_DUAL_SECTION_GAP
                width += PILL_ICON + PILL_DUAL_ITEM_GAP + text_w
                first = False

            if show_cursor:
                _add_section(cursor_w)
            if show_grok:
                _add_section(grok_w)
            if show_grok_com:
                _add_section(grok_com_w)
            if show_anti:
                _add_section(anti_w)
            if show_codex:
                _add_section(codex_w)
            if show_opencode:
                _add_section(opencode_w)
            if sections == 0:
                width += PILL_ICON + PILL_DUAL_ITEM_GAP + font_nums.measure("—%")
            width += cue_w + PILL_DUAL_PAD_X
            return (
                max(width, PILL_HEIGHT),
                PILL_HEIGHT,
                cursor_w + grok_w + grok_com_w + anti_w + codex_w + opencode_w,
                0,
            )

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

        cy = h / 2
        if view.get("layout") == "icons":
            self._redraw_pill_icons(c, w, h, cy)
        else:
            self._redraw_pill_ring(c, h, cy, badge_w)

        # Re-assert color-key after geometry (click-through / layout can clear it).
        try:
            hwnd = toplevel_hwnd(self)
            clear_window_region(hwnd)
            set_color_key(hwnd, TRANSPARENT_KEY)
        except Exception:
            pass

    def _redraw_pill_icons(
        self, c: tk.Canvas, w: int, h: int, cy: float
    ) -> None:
        """Cursor icon+% ; optional | Grok icon+% — compact HTML-style pill."""
        view = self._pill_view
        font_nums = tkfont.Font(
            family=PILL_DUAL_NUM_FONT[0],
            size=PILL_DUAL_NUM_FONT[1],
            weight="bold",
        )
        x = float(PILL_DUAL_PAD_X)
        color = str(view.get("number_color") or TEXT)
        first = True

        def _divider_then_icon_pct(
            icon: tk.PhotoImage | None,
            text: str,
            *,
            fallback: str = "",
        ) -> None:
            nonlocal x, first
            if not first:
                x += PILL_DUAL_SECTION_GAP
                c.create_line(
                    x,
                    cy - PILL_DUAL_DIVIDER_H / 2,
                    x,
                    cy + PILL_DUAL_DIVIDER_H / 2,
                    fill=BORDER,
                    width=1,
                    tags="face",
                )
                x += 1 + PILL_DUAL_SECTION_GAP
            icon_x = x + PILL_ICON / 2
            drawn = False
            if icon is not None:
                try:
                    c.create_image(
                        icon_x,
                        cy,
                        image=icon,
                        anchor="center",
                        tags="face",
                    )
                    drawn = True
                except tk.TclError:
                    drawn = False
            if not drawn and fallback:
                c.create_text(
                    icon_x,
                    cy,
                    text=fallback,
                    fill=TEXT,
                    font=("Segoe UI Semibold", 9),
                    anchor="center",
                    tags="face",
                )
            x += PILL_ICON + PILL_DUAL_ITEM_GAP
            c.create_text(
                x,
                cy,
                text=text,
                fill=color,
                font=PILL_DUAL_NUM_FONT,
                anchor="w",
                tags="face",
            )
            x += font_nums.measure(text)
            first = False

        if view.get("show_cursor"):
            _divider_then_icon_pct(
                self._pill_icon_cursor,
                str(view.get("cursor_text") or "—%"),
                fallback="C",
            )
        if view.get("show_grok"):
            _divider_then_icon_pct(
                self._pill_icon_grok,
                str(view.get("grok_text") or "—%"),
                fallback="G",
            )
        if view.get("show_grok_com"):
            _divider_then_icon_pct(
                self._pill_icon_xai,
                str(view.get("grok_com_text") or "—%"),
                fallback="X",
            )
        if view.get("show_antigravity"):
            _divider_then_icon_pct(
                self._pill_icon_antigravity,
                str(view.get("antigravity_text") or "—%"),
                fallback="A",
            )
        if view.get("show_codex"):
            _divider_then_icon_pct(
                self._pill_icon_codex,
                str(view.get("codex_text") or "—%"),
                fallback="D",
            )
        if view.get("show_opencode"):
            _divider_then_icon_pct(
                self._pill_icon_opencode,
                str(view.get("opencode_text") or "—%"),
                fallback="O",
            )
        if first:
            # Nothing eligible yet — keep a compact placeholder.
            _divider_then_icon_pct(self._pill_icon_cursor, "—%", fallback="C")

        cue = str(view.get("cue") or "")
        if cue:
            x += PILL_DUAL_SECTION_GAP
            c.create_text(
                x,
                cy,
                text=cue,
                fill=DOT_ERR,
                font=("Segoe UI", 7, "bold"),
                anchor="w",
                tags="face",
            )

    def _redraw_pill_ring(
        self, c: tk.Canvas, h: int, cy: float, badge_w: int
    ) -> None:
        """Legacy single-metric ring + percent (+ optional pace badge)."""
        view = self._pill_view
        cx = PILL_PAD_L + PILL_RING / 2
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
            show_anti = self._pill_antigravity_half()
            show_codex = self._pill_codex_half()
            show_opencode = self._pill_opencode_half()
            has_anti = show_anti and self._last_antigravity is not None
            has_codex = show_codex and self._last_codex is not None
            has_opencode = show_opencode and self._last_opencode is not None
            if has_anti or has_codex or has_opencode:
                anti_text = (
                    format_usage_percent(self._last_antigravity.usage_percent)
                    if has_anti
                    else "—%"
                )
                codex_text = (
                    format_usage_percent(self._last_codex.usage_percent)
                    if has_codex
                    else "—%"
                )
                opencode_text = (
                    format_usage_percent(self._last_opencode.usage_percent)
                    if has_opencode
                    else "—%"
                )
                if has_anti:
                    primary_txt = anti_text
                elif has_codex:
                    primary_txt = codex_text
                else:
                    primary_txt = opencode_text
                view.update(
                    {
                        "layout": "icons",
                        "show_cursor": False,
                        "show_grok": False,
                        "show_grok_com": False,
                        "show_antigravity": show_anti,
                        "show_codex": show_codex,
                        "show_opencode": show_opencode,
                        "cursor_text": "—%",
                        "grok_text": "—%",
            "grok_com_text": "—%",
                        "antigravity_text": anti_text,
                        "codex_text": codex_text,
                        "opencode_text": opencode_text,
                        "text": primary_txt,
                        "number_color": TEXT,
                        "ring_extent": 0.0,
                        "show_badge": False,
                        "badge_text": "",
                    }
                )
            else:
                view.update(
                    {
                        "layout": "ring",
                        "show_cursor": False,
                        "show_grok": False,
                        "show_grok_com": False,
                        "show_antigravity": False,
                        "show_codex": False,
                        "show_opencode": False,
                        "text": "—%",
                        "cursor_text": "—%",
                        "grok_text": "—%",
            "grok_com_text": "—%",
                        "antigravity_text": "—%",
                        "codex_text": "—%",
                        "opencode_text": "—%",
                        "number_color": TEXT,
                        "ring_extent": 0.0,
                        "show_badge": False,
                        "badge_text": "",
                    }
                )
            self._apply_pill_border(CARD)
            return

        show_grok = self._pill_grok_bot_half()
        show_grok_com = self._pill_grok_com_half()
        show_anti = self._pill_antigravity_half()
        show_codex = self._pill_codex_half()
        show_opencode = self._pill_opencode_half()
        metric = effective_pill_metric(self.settings)

        # Cursor icon+% when online (Grok / Antigravity / Codex / OpenCode only when on).
        # Pace ring only when pill metric is Today's pace and none is sharing the capsule.
        if show_grok or show_grok_com or show_anti or show_codex or show_opencode or metric != "pace":
            grok_text = "—%"
            if show_grok and self._last_grok_bot is not None:
                grok_text = format_usage_percent(self._last_grok_bot.usage_percent)
            grok_com_text = "—%"
            if show_grok_com and self._last_grok_app is not None:
                grok_com_text = format_usage_percent(self._last_grok_app.usage_percent)
            anti_text = "—%"
            if show_anti and self._last_antigravity is not None:
                anti_text = format_usage_percent(self._last_antigravity.usage_percent)
            codex_text = "—%"
            if show_codex and self._last_codex is not None:
                codex_text = format_usage_percent(self._last_codex.usage_percent)
            opencode_text = "—%"
            if show_opencode and self._last_opencode is not None:
                opencode_text = format_usage_percent(self._last_opencode.usage_percent)
            cursor_txt = format_cursor_usage_percent(self._last_usage.auto_percent)
            view.update(
                {
                    "layout": "icons",
                    "show_cursor": True,
                    "show_grok": show_grok,
                    "show_grok_com": show_grok_com,
                    "show_antigravity": show_anti,
                    "show_codex": show_codex,
                    "show_opencode": show_opencode,
                    "cursor_text": cursor_txt,
                    "grok_text": grok_text,
                    "grok_com_text": grok_com_text,
                    "antigravity_text": anti_text,
                    "codex_text": codex_text,
                    "opencode_text": opencode_text,
                    "text": cursor_txt,
                    "number_color": TEXT,
                    "ring_extent": 0.0,
                    "show_badge": False,
                    "badge_text": "",
                }
            )
            self._apply_pill_border(CARD)
            return

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
                    "layout": "ring",
                    "show_cursor": False,
                    "show_grok": False,
                    "show_antigravity": False,
                    "show_codex": False,
                    "show_opencode": False,
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

        # Pace selected but no pace data yet.
        view.update(
            {
                "layout": "ring",
                "show_cursor": False,
                "show_grok": False,
                "show_antigravity": False,
                "show_codex": False,
                "show_opencode": False,
                "text": "—%",
                "number_color": TEXT,
                "ring_extent": 0.0,
                "show_badge": False,
            }
        )
        self._apply_pill_border(CARD)

    def _update_reset_countdown(self) -> None:
        """Reset hints live on Cursor / Grok row subtexts; hide the old footer line."""
        if hasattr(self, "reset_label"):
            self.reset_label.pack_forget()

    def _format_reset_countdown(self) -> str:
        if self._last_usage is None or not self._last_usage.billing_cycle_end:
            return ""
        hint = format_resets_in_label(self._last_usage.billing_cycle_end)
        return hint or ""

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
            self.status_label.configure(
                text=f"Updated {stamp} · {self._version_label}"
            )
        elif not (self.status_label.cget("text") or "").startswith("Updated"):
            self.status_label.configure(text=self._version_label)

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

    def _poll_interval_ms(self) -> int:
        """Adaptive cadence: fast while you are around, slow while you are away."""
        since_change_s = time.monotonic() - self._last_usage_change_at
        return poll_interval_ms(seconds_since_last_input(), since_change_s)

    def _poll_tick(self) -> None:
        interval_s = self._poll_interval_ms() / 1000.0
        login_changed = False
        try:
            fp = live_cursor_fingerprint()
            if self._cursor_fp is not None and fp != self._cursor_fp:
                login_changed = True
            stamp = file_stamp(
                resolve_grok_auth_path(self.settings.grok_app_token_file)
            )
            if self._grok_auth_stamp is not None and stamp != self._grok_auth_stamp:
                login_changed = True
        except Exception:  # noqa: BLE001
            login_changed = False
        if login_changed or time.monotonic() - self._last_poll_at >= interval_s:
            self.refresh_async()
        self.after(POLL_TICK_MS, self._poll_tick)

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
            self._pulse_job = self.after(180, tick)

        self.refresh_btn.start()
        tick()

    def _stop_pulse(self) -> None:
        if self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
        self._pulse_on = False
        self.refresh_btn.stop()

    def refresh_async(self) -> None:
        if self._refreshing:
            return
        self._last_poll_at = time.monotonic()
        self._cancel_antigravity_retry()
        self._refreshing = True
        self._start_pulse()
        if not self._show_pill_mode():
            self.status_label.configure(text="Refreshing…")
        opencode_budget = int(self.settings.opencode_token_budget)

        def worker() -> None:
            usage: PlanUsage | None = None
            grok: GrokBotUsage | None = None
            grok_ok = False
            anti: AntigravityUsage | None = None
            anti_ok = False
            anti_error: str | None = None
            codex: CodexUsage | None = None
            codex_ok = False
            opencode: OpenCodeUsage | None = None
            opencode_ok = False
            cursor_error: str | None = None
            usage_secondary: PlanUsage | None = None
            usage_secondary_error: str | None = None
            live_token: str | None = None
            primary_label = cursor_primary_bar_label(self.settings)
            secondary_label = cursor_secondary_bar_label(self.settings)
            grok_app: GrokAppUsage | None = None
            grok_app_error: str | None = None

            try:
                live_token = get_access_token()
                fp = token_fingerprint(live_token)
                previous = self._cached_cursor_token
                if (
                    self.settings.remember_previous_cursor_login
                    and previous
                    and token_fingerprint(previous) != fp
                ):
                    dest = (self.settings.secondary_cursor_token_file or "").strip()
                    if not dest:
                        dest = str(
                            Path(os.environ.get("APPDATA") or Path.home())
                            / "cursor-usage-float"
                            / "previous-cursor.txt"
                        )
                        self.settings.secondary_cursor_token_file = dest
                        save_settings(self.settings)
                    Path(dest).expanduser().parent.mkdir(parents=True, exist_ok=True)
                    Path(dest).expanduser().write_text(previous + "\n", encoding="utf-8")
                self._cached_cursor_token = live_token
                self._cursor_fp = fp
                primary_label = cursor_slot_label(
                    prefix="Cursor",
                    token=live_token,
                    override=self.settings.cursor_primary_label,
                    auto_from_email=False,
                    fallback=cursor_primary_bar_label(self.settings),
                )
                info = get_cursor_account_info()
                self._cursor_account = info
            except AuthError:
                live_token = None

            try:
                usage = fetch_current_period_usage(token=live_token)
            except (AuthError, UsageError) as exc:
                cursor_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                cursor_error = f"Unexpected error: {exc}"

            # Cumulative period tokens; cached briefly so a 15s poll doesn't
            # hammer the heavier aggregation endpoint. Failures keep the last
            # good value (None on first failure → row just omits the count).
            token_usage: TokenUsage | None = self._last_token_usage
            if live_token and usage is not None:
                now_mono = time.monotonic()
                if (
                    token_usage is None
                    or now_mono - self._token_usage_at >= TOKEN_USAGE_TTL_S
                ):
                    try:
                        token_usage = fetch_token_usage(token=live_token)
                        self._token_usage_at = now_mono
                    except (AuthError, UsageError):
                        pass
                    except Exception:  # noqa: BLE001
                        pass

            if self.settings.show_dual_cursor:
                token_path = (self.settings.secondary_cursor_token_file or "").strip()
                if token_path:
                    try:
                        token_b = read_access_token_from_file(token_path)
                        secondary_label = cursor_slot_label(
                            prefix="Cursor",
                            token=token_b,
                            override=self.settings.cursor_secondary_label,
                            auto_from_email=self.settings.auto_label_from_email,
                            fallback=cursor_secondary_bar_label(self.settings),
                        )
                        usage_secondary = fetch_current_period_usage(token=token_b)
                    except (AuthError, UsageError) as exc:
                        usage_secondary_error = str(exc)
                        if "401" in usage_secondary_error:
                            usage_secondary_error = (
                                "Second account token expired or wrong account. "
                                "Sign in to that Cursor account, Save token, or clear the path."
                            )
                    except Exception as exc:  # noqa: BLE001
                        usage_secondary_error = f"Unexpected error: {exc}"

            if usage is not None:
                try:
                    grok = fetch_grok_bot_usage()
                    grok_ok = True
                except (AuthError, UsageError):
                    pass
                except Exception:  # noqa: BLE001
                    pass

            if self.settings.show_grok_premium:
                auth_path = resolve_grok_auth_path(self.settings.grok_app_token_file)
                custom_grok = (self.settings.grok_app_token_file or "").strip()
                if grok_auth_ready(auth_path):
                    try:
                        grok_app = fetch_grok_app_usage(
                            auth_path=self.settings.grok_app_token_file
                        )
                    except GrokAppError as exc:
                        grok_app_error = str(exc)
                    except Exception as exc:  # noqa: BLE001
                        grok_app_error = str(exc)
                elif not custom_grok:
                    grok_app_error = ensure_grok_auth_for_usage(
                        self.settings.grok_app_token_file
                    )
                else:
                    try:
                        grok_app = fetch_grok_app_usage(
                            auth_path=self.settings.grok_app_token_file
                        )
                    except GrokAppError as exc:
                        grok_app_error = str(exc)
                    except Exception as exc:  # noqa: BLE001
                        grok_app_error = str(exc)
                # Record the stamp *after* the fetch: a silent token refresh
                # rewrites auth.json and would otherwise trigger a poll loop.
                self._grok_auth_stamp = file_stamp(
                    resolve_grok_auth_path(self.settings.grok_app_token_file)
                )

            try:
                anti = fetch_antigravity_usage()
                anti_ok = True
            except Exception as exc:  # noqa: BLE001
                anti_error = str(exc).strip()[:160] or type(exc).__name__

            try:
                codex = fetch_codex_usage()
                codex_ok = True
            except Exception:  # noqa: BLE001
                pass

            try:
                opencode = fetch_opencode_usage(opencode_budget)
                opencode_ok = True
            except Exception:  # noqa: BLE001
                pass

            if usage is not None:
                self.after(
                    0,
                    lambda u=usage, u2=usage_secondary, u2e=usage_secondary_error, pl=primary_label, sl=secondary_label, g=grok, g_ok=grok_ok, ga=grok_app, gae=grok_app_error, a=anti, a_ok=anti_ok, ae=anti_error, c=codex, c_ok=codex_ok, o=opencode, o_ok=opencode_ok, tu=token_usage: self._apply_usage(
                        u,
                        usage_secondary=u2,
                        usage_secondary_error=u2e,
                        primary_label=pl,
                        secondary_label=sl,
                        grok=g,
                        grok_updated=g_ok,
                        grok_app=ga,
                        grok_app_error=gae,
                        antigravity=a,
                        antigravity_updated=a_ok,
                        antigravity_error=ae,
                        codex=c,
                        codex_updated=c_ok,
                        opencode=o,
                        opencode_updated=o_ok,
                        token_usage=tu,
                    ),
                )
            else:
                self.after(
                    0,
                    lambda m=cursor_error or "Cursor offline", u2=usage_secondary, u2e=usage_secondary_error, pl=primary_label, sl=secondary_label, ga=grok_app, gae=grok_app_error, a=anti, a_ok=anti_ok, ae=anti_error, c=codex, c_ok=codex_ok, o=opencode, o_ok=opencode_ok: self._apply_error(
                        m,
                        usage_secondary=u2,
                        usage_secondary_error=u2e,
                        primary_label=pl,
                        secondary_label=sl,
                        grok_app=ga,
                        grok_app_error=gae,
                        antigravity=a,
                        antigravity_updated=a_ok,
                        antigravity_error=ae,
                        codex=c,
                        codex_updated=c_ok,
                        opencode=o,
                        opencode_updated=o_ok,
                    ),
                )
            self.after(0, self._clear_refreshing)

        threading.Thread(target=worker, daemon=True).start()

    def _clear_refreshing(self) -> None:
        self._refreshing = False
        self._stop_pulse()
        self._paint_status()
        if self._antigravity_error:
            self._schedule_antigravity_retry()

    def _cancel_antigravity_retry(self) -> None:
        if self._antigravity_retry_job is None:
            return
        try:
            self.after_cancel(self._antigravity_retry_job)
        except tk.TclError:
            pass
        self._antigravity_retry_job = None

    def _schedule_antigravity_retry(self) -> None:
        if self._antigravity_retry_job is None and not self._antigravity_retrying:
            self._antigravity_retry_job = self.after(5_000, self._retry_antigravity)

    def _retry_antigravity(self) -> None:
        self._antigravity_retry_job = None
        if not self.settings.show_antigravity:
            return
        if self._refreshing or self._antigravity_retrying:
            self._schedule_antigravity_retry()
            return
        self._antigravity_retrying = True

        def worker() -> None:
            try:
                usage = fetch_antigravity_usage()
                error = None
            except Exception as exc:  # noqa: BLE001
                usage = None
                error = str(exc).strip()[:160] or type(exc).__name__
            self.after(0, lambda u=usage, e=error: self._apply_antigravity_retry(u, e))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_antigravity_retry(
        self,
        usage: AntigravityUsage | None,
        error: str | None,
    ) -> None:
        self._antigravity_retrying = False
        self._record_antigravity(usage, updated=error is None, error=error)
        self._update_pill_percent()
        self._update_section_visibility()
        self._resize_to_content()
        if error:
            self._schedule_antigravity_retry()

    def _apply_usage(
        self,
        usage: PlanUsage,
        *,
        usage_secondary: PlanUsage | None = None,
        usage_secondary_error: str | None = None,
        primary_label: str | None = None,
        secondary_label: str | None = None,
        grok: GrokBotUsage | None = None,
        grok_updated: bool = True,
        grok_app: GrokAppUsage | None = None,
        grok_app_error: str | None = None,
        antigravity: AntigravityUsage | None = None,
        antigravity_updated: bool = True,
        antigravity_error: str | None = None,
        codex: CodexUsage | None = None,
        codex_updated: bool = True,
        opencode: OpenCodeUsage | None = None,
        opencode_updated: bool = True,
        token_usage: TokenUsage | None = None,
    ) -> None:
        if self._last_usage is not None and _usage_moved(self._last_usage, usage):
            self._last_usage_change_at = time.monotonic()
        self._last_usage = usage
        self._last_token_usage = token_usage
        if grok_updated:
            self._last_grok_bot = grok
        self._record_antigravity(
            antigravity,
            updated=antigravity_updated,
            error=antigravity_error,
        )
        if codex_updated:
            self._last_codex = codex
        if opencode_updated:
            self._last_opencode = opencode
        self._connection_ok = True
        self._last_success_at = datetime.now()
        self.total_row.set_percent(usage.auto_percent)
        self.total_row.set_subtext(
            _cursor_subtext(
                usage,
                getattr(self, "_cursor_account", None),
                show_email=self.settings.auto_label_from_email,
                show_reset=self.settings.show_reset_countdown,
                token_usage=token_usage,
                show_tokens=self.settings.show_token_usage,
            )
        )
        if primary_label:
            self.total_row.set_title(primary_label)
        if secondary_label:
            self.total_row_secondary.set_title(secondary_label)
        self._apply_secondary_cursor(usage_secondary, usage_secondary_error)
        self._update_dual_cursor_visibility()
        self._apply_grok_premium(grok_app, grok_app_error)
        self.auto_row.set_percent(usage.auto_percent)
        self.api_row.set_percent(usage.api_percent)
        self._apply_grok_bot(self._last_grok_bot)
        self._apply_codex(self._last_codex)
        self._apply_opencode(self._last_opencode)
        self._update_pace_from_usage(usage)
        self._paint_status()
        self._update_pill_percent()
        if not self._show_pill_mode():
            stamp = self._last_success_at.strftime("%H:%M:%S")
            self.status_label.configure(
                text=f"Updated {stamp} · {self._version_label}"
            )
            self._update_reset_countdown()
            self._update_stale_badge()
            self._update_section_visibility()
        self._resize_to_content()

    def _apply_grok_bot(self, grok: GrokBotUsage | None) -> None:
        if grok is None or not grok.is_eligible:
            return
        self.grok_bot_row.set_title("Grok Bot (Cursor)")
        self.grok_bot_row.set_percent(grok.usage_percent)
        self.grok_bot_row.set_subtext(_format_grok_bot_subtext(grok) + " · Cursor plan, not Grok.com")

    def _apply_grok_premium(
        self,
        usage: GrokAppUsage | None,
        error: str | None,
    ) -> None:
        if not hasattr(self, "grok_premium_row"):
            return
        self._last_grok_app = usage
        self._grok_app_error = error
        ok = usage is not None and usage.is_eligible
        if ok:
            self._grok_seen_ok = True
            self._grok_relogin_notified = False
        elif self.settings.show_grok_premium:
            # Fires even in pill mode so an expired login is never silent.
            self._maybe_notify_grok_relogin(error)
        if not self._grok_premium_should_show():
            return
        if ok:
            self.grok_premium_row.set_title("Grok")
            self.grok_premium_row.set_percent(usage.usage_percent)
            plan = format_grok_plan_label(usage.plan_tier, usage.plan_tier_id)
            parts: list[str] = []
            if plan:
                parts.append(plan)
            elif usage.plan_tier:
                parts.append(usage.plan_tier)
            if usage.email:
                parts.append(short_email_display(usage.email))
            if self.settings.show_reset_countdown and usage.period_end:
                reset_hint = format_resets_in_label(usage.period_end)
                if reset_hint:
                    parts.append(reset_hint)
            if not parts:
                parts.append("grok.com weekly pool")
            self.grok_premium_row.set_subtext(" · ".join(parts))
            self._show_grok_login_button(False)
            return
        self.grok_premium_row.set_percent(0)
        self.grok_premium_row.pct_label.configure(text="—%", fg=MUTED)
        err = format_grok_app_error(
            error or "Installing Grok CLI / waiting for grok login…"
        )
        self.grok_premium_row.set_subtext(err)
        self._show_grok_login_button(grok_error_needs_login_action(error or err))

    def _maybe_notify_grok_relogin(self, error: str | None) -> None:
        """Tray balloon once per expiry episode (click → open grok login)."""
        if self._grok_relogin_notified:
            return
        if not bool(getattr(self.settings, "notify_grok_relogin", True)):
            return
        if self._tray is None or not self._tray.visible:
            return
        if not grok_error_needs_login_action(error):
            return
        if not (self._grok_seen_ok or self._grok_auth_configured()):
            # First run / CLI never set up — the row already explains it.
            return
        shown = self._tray.notify(
            "Grok needs re-login",
            "Grok usage stopped updating. Click to open grok login.",
            on_click=self._grok_relogin_from_notification,
        )
        if shown:
            self._grok_relogin_notified = True

    def _grok_auth_configured(self) -> bool:
        try:
            return resolve_grok_auth_path(self.settings.grok_app_token_file).is_file()
        except Exception:  # noqa: BLE001
            return False

    def _grok_relogin_from_notification(self) -> None:
        self._on_tray_show()
        self._launch_grok_login()

    def _show_grok_login_button(self, visible: bool) -> None:
        if not hasattr(self, "grok_login_btn_frame"):
            return
        if visible and self._grok_premium_should_show():
            if not self.grok_login_btn_frame.winfo_ismapped():
                self.grok_login_btn_frame.pack(
                    fill="x",
                    pady=(4, 0),
                    after=self.grok_premium_row,
                )
        else:
            self.grok_login_btn_frame.pack_forget()

    def _launch_grok_login(self) -> None:
        ok, msg = launch_grok_login_terminal()
        if ok:
            self.status_label.configure(
                text="Terminal opened — finish grok login, then refresh"
            )
        else:
            self.status_label.configure(text=msg[:120])

    def _apply_antigravity(
        self,
        antigravity: AntigravityUsage | None,
        error: str | None = None,
    ) -> None:
        if antigravity is None or not antigravity.is_eligible:
            self.antigravity_row.set_percent(0)
            self.antigravity_row.pct_label.configure(text="—%", fg=MUTED)
            detail = error or "Waiting for Antigravity usage…"
            if error and "language_server" in error.lower():
                detail = "Open Antigravity so its language server is running"
            self.antigravity_row.set_subtext(detail)
            return
        self.antigravity_row.set_percent(antigravity.usage_percent)
        if error and self._last_antigravity_updated_at:
            stamp = self._last_antigravity_updated_at.strftime("%I:%M %p").lstrip("0")
            subtext = f"Saved {stamp} · {error}"
        else:
            subtext = _format_antigravity_subtext(antigravity)
        self.antigravity_row.set_subtext(subtext)

    def _record_antigravity(
        self,
        usage: AntigravityUsage | None,
        *,
        updated: bool,
        error: str | None,
    ) -> None:
        if updated:
            self._last_antigravity = usage
            if usage is not None and usage.is_eligible:
                self._last_antigravity_updated_at = datetime.now()
                _save_antigravity_cache(usage, self._last_antigravity_updated_at)
            else:
                self._last_antigravity_updated_at = None
        self._antigravity_error = error
        self._apply_antigravity(self._last_antigravity, error)
        if error is None:
            self._cancel_antigravity_retry()

    def _apply_codex(self, codex: CodexUsage | None) -> None:
        if codex is None or not codex.is_eligible:
            return
        self.codex_row.set_percent(codex.usage_percent)
        self.codex_row.set_subtext(_format_codex_subtext(codex))

    def _apply_opencode(self, opencode: OpenCodeUsage | None) -> None:
        if opencode is None or not opencode.is_eligible:
            return
        self.opencode_row.set_percent(opencode.usage_percent)
        self.opencode_row.set_subtext(_format_opencode_subtext(opencode))

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

    def _apply_error(
        self,
        message: str,
        *,
        usage_secondary: PlanUsage | None = None,
        usage_secondary_error: str | None = None,
        primary_label: str | None = None,
        secondary_label: str | None = None,
        grok_app: GrokAppUsage | None = None,
        grok_app_error: str | None = None,
        antigravity: AntigravityUsage | None = None,
        antigravity_updated: bool = False,
        antigravity_error: str | None = None,
        codex: CodexUsage | None = None,
        codex_updated: bool = False,
        opencode: OpenCodeUsage | None = None,
        opencode_updated: bool = False,
    ) -> None:
        self._connection_ok = False
        self._record_antigravity(
            antigravity,
            updated=antigravity_updated,
            error=antigravity_error,
        )
        if codex_updated:
            self._last_codex = codex
            self._apply_codex(self._last_codex)
        if opencode_updated:
            self._last_opencode = opencode
            self._apply_opencode(self._last_opencode)
        # Cursor auth/offline — keep prior bars if any, but don't invent a %.
        self.total_row.set_percent(0)
        self.total_row.pct_label.configure(text="—%", fg=MUTED)
        if "auth" in message.lower() or "not logged" in message.lower() or "unauthenticated" in message.lower():
            self.total_row.set_subtext("Sign in to Cursor, then refresh")
        else:
            self.total_row.set_subtext(message[:80])
        self._apply_secondary_cursor(usage_secondary, usage_secondary_error)
        self._update_dual_cursor_visibility()
        if primary_label:
            self.total_row.set_title(primary_label)
        if secondary_label:
            self.total_row_secondary.set_title(secondary_label)
        self._apply_grok_premium(grok_app, grok_app_error)
        if antigravity_updated or codex_updated or opencode_updated:
            self._update_pill_percent()
        if not self._show_pill_mode():
            self.status_label.configure(text=message)
            self._update_stale_badge()
            self._update_section_visibility()
        self._paint_status()
        self._resize_to_content()


def format_resets_in_label(end_raw: str | None) -> str | None:
    """Human countdown e.g. 'Resets in 6d 11h' from an ISO or epoch end time."""
    if not end_raw or not str(end_raw).strip():
        return None
    end = _parse_billing_end(str(end_raw).strip())
    if end is None:
        return f"Resets {end_raw.strip()}"
    now = datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    secs = int((end - now).total_seconds())
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


def _cursor_subtext(
    usage: PlanUsage,
    account: object | None = None,
    *,
    show_email: bool = True,
    show_reset: bool = True,
    token_usage: TokenUsage | None = None,
    show_tokens: bool = True,
) -> str:
    """Row caption: plan · email · pool note · tokens · reset."""
    from cursor_identity import CursorAccountInfo

    parts: list[str] = []
    if isinstance(account, CursorAccountInfo) and account.plan_label:
        parts.append(account.plan_label)
    if show_email and isinstance(account, CursorAccountInfo) and account.email:
        parts.append(short_email_display(account.email))
    if usage.source == "grants":
        parts.append(usage.spend_label or "Included usage this period")
    else:
        parts.append("Includes Composer + Grok")
    if show_tokens and token_usage is not None and token_usage.is_eligible:
        parts.append(f"{format_token_count(token_usage.total_tokens)} tokens")
    if show_reset and usage.billing_cycle_end:
        reset_hint = format_resets_in_label(usage.billing_cycle_end)
        if reset_hint:
            parts.append(reset_hint)
    return " · ".join(parts)


def _format_opencode_subtext(opencode: OpenCodeUsage) -> str:
    """Token-budget label: '15.6M / 20.0M tokens today · 2 sessions'."""
    parts = [
        f"{format_token_count(opencode.tokens_used)} / "
        f"{format_token_count(opencode.budget_tokens)} tokens today"
    ]
    if opencode.sessions:
        noun = "session" if opencode.sessions == 1 else "sessions"
        parts.append(f"{opencode.sessions} {noun}")
    if opencode.cost_usd > 0:
        parts.append(f"${opencode.cost_usd:.2f}")
    return " · ".join(parts)


def _format_codex_subtext(codex: CodexUsage) -> str:
    """Codex allowance label with plan and resets-in hint."""
    plan_name = codex.plan_type.capitalize() if codex.plan_type else "Codex"
    base = f"Plan: {plan_name}"
    if not codex.next_reset:
        return base
    end = _parse_billing_end(str(codex.next_reset).strip())
    if end is None:
        return base
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = end - now
    if delta.total_seconds() <= 0:
        return f"{base} · resets soon"
    days = delta.days
    hours = delta.seconds // 3600
    if days >= 1:
        return f"{base} · resets in {days}d"
    if hours >= 1:
        return f"{base} · resets in {hours}h"
    minutes = max(1, delta.seconds // 60)
    return f"{base} · resets in {minutes}m"


def _format_antigravity_subtext(antigravity: AntigravityUsage) -> str:
    """Antigravity allowance label with models and resets-in hint."""
    if antigravity.gemini_percent is not None and antigravity.claude_gpt_percent is not None:
        base = f"Gemini {int(round(antigravity.gemini_percent))}% · Claude/GPT {int(round(antigravity.claude_gpt_percent))}%"
    else:
        base = "Weekly limit"
    if not antigravity.next_reset:
        return base
    end = _parse_billing_end(str(antigravity.next_reset).strip())
    if end is None:
        return base
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = end - now
    if delta.total_seconds() <= 0:
        return f"{base} · resets soon"
    days = delta.days
    hours = delta.seconds // 3600
    if days >= 1:
        return f"{base} · resets in {days}d"
    if hours >= 1:
        return f"{base} · resets in {hours}h"
    minutes = max(1, delta.seconds // 60)
    return f"{base} · resets in {minutes}m"


def _format_grok_bot_subtext(grok: GrokBotUsage) -> str:
    """Weekly allowance label, with optional resets-in hint."""
    base = "Weekly allowance"
    if not grok.next_reset:
        return base
    end = _parse_billing_end(str(grok.next_reset).strip())
    if end is None:
        return base
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = end - now
    if delta.total_seconds() <= 0:
        return f"{base} · resets soon"
    days = delta.days
    hours = delta.seconds // 3600
    if days >= 1:
        return f"{base} · resets in {days}d"
    if hours >= 1:
        return f"{base} · resets in {hours}h"
    minutes = max(1, delta.seconds // 60)
    return f"{base} · resets in {minutes}m"


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
