"""Always-on-top floating Cursor usage widget (personal / portable)."""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import font as tkfont

from cursor_auth import AuthError
from cursor_usage import PlanUsage, UsageError, fetch_current_period_usage
from settings import (
    AppSettings,
    format_percent,
    load_settings,
    resolve_minimized_percent,
)
from settings_ui import open_settings
from theme import (
    BAR_BG,
    BAR_FG,
    BG,
    BORDER,
    CARD,
    DOT_ERR,
    DOT_OK,
    DOT_UNKNOWN,
    INNER,
    MUTED,
    TEXT,
)
from win_clickthrough import set_click_through, set_rounded_corners, toplevel_hwnd

# Poll every 3 minutes
POLL_MS = 3 * 60 * 1000
STALE_MS = 2 * POLL_MS
WINDOW_WIDTH = 300
PILL_WIDTH = 96
CORNER_RADIUS = 16
PILL_CORNER_RADIUS = 14
GEAR_ICON = "\uE713"  # Segoe MDL2 Assets settings gear


class ProgressRow(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        title: str,
        *,
        subtext: str | None = None,
        compact: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(master, bg=master.cget("bg"), **kwargs)
        self._title = title
        self._value = 0.0

        header = tk.Frame(self, bg=self.cget("bg"))
        header.pack(fill="x")

        self.title_label = tk.Label(
            header,
            text=title,
            bg=self.cget("bg"),
            fg=TEXT,
            font=("Segoe UI", 9 if compact else 10, "bold"),
            anchor="w",
        )
        self.title_label.pack(side="left")

        self.pct_label = tk.Label(
            header,
            text="—%",
            bg=self.cget("bg"),
            fg=TEXT,
            font=("Segoe UI", 9 if compact else 10, "bold"),
            anchor="e",
        )
        self.pct_label.pack(side="right")

        self.bar_outer = tk.Canvas(
            self,
            height=8 if compact else 10,
            bg=BAR_BG,
            highlightthickness=0,
            bd=0,
        )
        self.bar_outer.pack(fill="x", pady=(6, 0))
        self.bar_fill = self.bar_outer.create_rectangle(
            0, 0, 0, 12, fill=BAR_FG, width=0
        )
        self.bar_outer.bind("<Configure>", self._redraw_bar)

        self.sub_label: tk.Label | None = None
        if subtext is not None:
            self.sub_label = tk.Label(
                self,
                text=subtext,
                bg=self.cget("bg"),
                fg=MUTED,
                font=("Segoe UI", 8),
                wraplength=WINDOW_WIDTH - 48,
                justify="left",
                anchor="w",
            )
            self.sub_label.pack(fill="x", pady=(6, 0))

    def set_percent(self, value: float) -> None:
        self._value = max(0.0, min(100.0, float(value)))
        self.pct_label.configure(text=format_percent(self._value))
        self._redraw_bar()

    def set_subtext(self, text: str) -> None:
        if self.sub_label is not None:
            self.sub_label.configure(text=text)

    def _redraw_bar(self, _event: object | None = None) -> None:
        width = max(self.bar_outer.winfo_width(), 1)
        height = max(self.bar_outer.winfo_height(), 1)
        fill_w = int(width * (self._value / 100.0))
        self.bar_outer.coords(self.bar_fill, 0, 0, fill_w, height)


class UsageFloater(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Cursor Usage")
        self.configure(bg=BG)
        self.overrideredirect(True)
        self.resizable(False, False)

        self.settings = load_settings()
        self._drag_x = 0
        self._drag_y = 0
        self._refreshing = False
        self._connection_ok: bool | None = None
        self._last_success_at: datetime | None = None
        self._last_usage: PlanUsage | None = None
        self._minimized = bool(self.settings.start_minimized)
        self._force_expanded = False
        self._placed = False

        self.attributes("-topmost", bool(self.settings.always_on_top))

        self._build_ui()
        self._apply_settings_side_effects()
        self._apply_layout()
        self._place_top_right()
        self.after(200, self.refresh_async)
        self.after(POLL_MS, self._schedule_poll)
        self.after(30_000, self._schedule_stale_check)

    def _build_ui(self) -> None:
        self.outer = tk.Frame(self, bg=BORDER, bd=0)
        self.outer.pack(fill="both", expand=True)

        self.card = tk.Frame(self.outer, bg=CARD, padx=14, pady=12)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        # --- Expanded content ---
        self.expanded = tk.Frame(self.card, bg=CARD)
        self.expanded.pack(fill="both", expand=True)

        self.header = tk.Frame(self.expanded, bg=CARD)
        self.header.pack(fill="x")
        self.header.bind("<ButtonPress-1>", self._start_drag)
        self.header.bind("<B1-Motion>", self._on_drag)

        self.status_dot = tk.Canvas(
            self.header,
            width=12,
            height=12,
            bg=CARD,
            highlightthickness=0,
            bd=0,
        )
        self.status_dot.pack(side="left", padx=(0, 6))
        self._dot_item = self.status_dot.create_oval(2, 2, 10, 10, fill=DOT_UNKNOWN, outline="")

        title = tk.Label(
            self.header,
            text="Cursor Usage",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        title.pack(side="left")
        title.bind("<ButtonPress-1>", self._start_drag)
        title.bind("<B1-Motion>", self._on_drag)

        self._header_btn("✕", self.destroy).pack(side="right")
        self._header_btn("↻", self.refresh_async).pack(side="right", padx=(0, 2))
        self._header_btn(GEAR_ICON, self._open_settings, icon_font=True).pack(
            side="right", padx=(0, 2)
        )
        self._header_btn("−", self._toggle_minimized).pack(side="right", padx=(0, 2))

        self.total_row = ProgressRow(
            self.expanded,
            "Total",
            subtext="Loading…",
        )
        self.total_row.configure(bg=CARD)
        self.total_row.pack(fill="x", pady=(12, 0))

        self.detail = tk.Frame(self.expanded, bg=INNER, padx=10, pady=10)
        self.detail.pack(fill="x", pady=(10, 0))

        self.auto_row = ProgressRow(
            self.detail,
            "Auto + Composer",
            subtext="Additional usage beyond limits consumes API quota or on-demand spend.",
            compact=True,
        )
        self.auto_row.configure(bg=INNER)
        self.auto_row.pack(fill="x")

        self.api_row = ProgressRow(
            self.detail,
            "API",
            subtext="Additional usage beyond limits consumes on-demand spend.",
            compact=True,
        )
        self.api_row.configure(bg=INNER)
        self.api_row.pack(fill="x", pady=(12, 0))

        self.reset_label = tk.Label(
            self.expanded,
            text="",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.reset_label.pack(fill="x", pady=(8, 0))

        self.stale_badge = tk.Label(
            self.expanded,
            text="Stale data",
            bg="#FEF3C7",
            fg="#92400E",
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

        # --- Pill (minimized / minimal density) ---
        self.pill = tk.Frame(self.card, bg=CARD)
        self.pill_inner = tk.Frame(self.pill, bg=CARD)
        self.pill_inner.pack(padx=8, pady=6)

        self.pill_dot = tk.Canvas(
            self.pill_inner,
            width=12,
            height=12,
            bg=CARD,
            highlightthickness=0,
            bd=0,
        )
        self.pill_dot.pack(side="left", padx=(0, 6))
        self._pill_dot_item = self.pill_dot.create_oval(
            2, 2, 10, 10, fill=DOT_UNKNOWN, outline=""
        )

        self.pill_pct = tk.Label(
            self.pill_inner,
            text="—%",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
        )
        self.pill_pct.pack(side="left")

        for w in (self.pill, self.pill_inner, self.pill_pct, self.pill_dot):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<Double-Button-1>", lambda _e: self._expand_from_pill())
            w.bind("<ButtonRelease-1>", self._pill_click)

        self._pill_press_xy: tuple[int, int] | None = None

        for child in self.expanded.winfo_children():
            if isinstance(child, tk.Label):
                child.bind("<ButtonPress-1>", self._start_drag)
                child.bind("<B1-Motion>", self._on_drag)

        self.card.bind("<Button-3>", lambda _e: self._open_settings())
        self.pill.bind("<Button-3>", lambda _e: self._open_settings())
        self.expanded.bind("<Button-3>", lambda _e: self._open_settings())

    def _header_btn(
        self, text: str, command: object, *, icon_font: bool = False
    ) -> tk.Button:
        if icon_font:
            font = ("Segoe MDL2 Assets", 10)
        elif text == "✕":
            font = ("Segoe UI", 9)
        else:
            font = ("Segoe UI", 10)
        return tk.Button(
            self.header,
            text=text,
            command=command,
            bg=CARD,
            fg=MUTED,
            activebackground=CARD,
            activeforeground=TEXT,
            bd=0,
            relief="flat",
            font=font,
            cursor="hand2",
            padx=4,
        )

    def _open_settings(self) -> None:
        open_settings(self, self.settings, self._on_settings_changed)

    def _on_settings_changed(self, settings: AppSettings) -> None:
        self.settings = settings
        if settings.density != "minimal":
            self._force_expanded = False
        self._apply_settings_side_effects()
        self._apply_layout()
        self._refresh_status_text()
        self._update_pill_percent()
        self._resize_to_content()

    def _apply_settings_side_effects(self) -> None:
        try:
            self.attributes("-topmost", bool(self.settings.always_on_top))
        except tk.TclError:
            pass
        hwnd = toplevel_hwnd(self)
        set_click_through(hwnd, bool(self.settings.click_through))

    def _toggle_minimized(self) -> None:
        if self.settings.density == "minimal":
            self._force_expanded = not self._force_expanded
            self._minimized = False
        else:
            self._force_expanded = False
            self._minimized = not self._minimized
        self._apply_layout()
        self._resize_to_content()

    def _expand_from_pill(self) -> None:
        self._minimized = False
        if self.settings.density == "minimal":
            self._force_expanded = True
        self._apply_layout()
        self._resize_to_content()

    def _pill_click(self, event: tk.Event) -> None:
        # Treat as expand if it wasn't a drag.
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

    def _apply_layout(self) -> None:
        show_pill = self._show_pill_mode()

        if show_pill:
            self.expanded.pack_forget()
            if not self.pill.winfo_ismapped():
                self.pill.pack(fill="both", expand=True)
            self.card.configure(padx=4, pady=2)
        else:
            self.pill.pack_forget()
            self.card.configure(padx=14, pady=12)

            # Re-pack expanded children in a stable order.
            for child in (
                self.header,
                self.total_row,
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

            self.total_row.pack(fill="x", pady=(12, 0) if self.settings.show_header else (0, 0))

            # Temporary expand from minimal uses full detail layout.
            show_detail = self.settings.density == "full" or (
                self.settings.density == "minimal" and self._force_expanded
            )
            if show_detail:
                self.detail.pack(fill="x", pady=(10, 0))

            self.status_label.pack(fill="x", pady=(10, 0))
            self._update_reset_countdown()
            self._update_stale_badge()

        self._paint_status_dots()
        self._update_pill_percent()

    def _paint_status_dots(self) -> None:
        if self._connection_ok is True:
            color = DOT_OK
        elif self._connection_ok is False:
            color = DOT_ERR
        else:
            color = DOT_UNKNOWN
        self.status_dot.itemconfigure(self._dot_item, fill=color)
        self.pill_dot.itemconfigure(self._pill_dot_item, fill=color)

    def _update_pill_percent(self) -> None:
        if self._last_usage is None:
            self.pill_pct.configure(text="—%")
            return
        value = resolve_minimized_percent(
            self._last_usage, self.settings.minimized_metric
        )
        self.pill_pct.configure(text=format_percent(value))

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
            # Keep last error message if red
            return
        if self._last_success_at is not None:
            stamp = self._last_success_at.strftime("%H:%M:%S")
            self.status_label.configure(text=f"Updated {stamp}")

    def _place_top_right(self) -> None:
        self.update_idletasks()
        width = PILL_WIDTH if self._show_pill_mode() else WINDOW_WIDTH
        height = self.winfo_reqheight()
        screen_w = self.winfo_screenwidth()
        x = max(screen_w - width - 24, 0)
        y = 24
        self.geometry(f"{width}x{height}+{x}+{y}")
        self._placed = True
        self._apply_rounded_corners(width, height)

    def _resize_to_content(self) -> None:
        self.update_idletasks()
        width = PILL_WIDTH if self._show_pill_mode() else WINDOW_WIDTH
        height = max(self.winfo_reqheight(), 1)
        x = self.winfo_x()
        y = self.winfo_y()
        self.geometry(f"{width}x{height}+{x}+{y}")
        self._apply_rounded_corners(width, height)

    def _apply_rounded_corners(self, width: int, height: int) -> None:
        radius = PILL_CORNER_RADIUS if self._show_pill_mode() else CORNER_RADIUS
        set_rounded_corners(toplevel_hwnd(self), width, height, radius)

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()
        self._pill_press_xy = (event.x_root, event.y_root)

    def _on_drag(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.geometry(f"+{x}+{y}")

    def _schedule_poll(self) -> None:
        self.refresh_async()
        self.after(POLL_MS, self._schedule_poll)

    def _schedule_stale_check(self) -> None:
        if not self._show_pill_mode():
            self._update_stale_badge()
        self.after(30_000, self._schedule_stale_check)

    def refresh_async(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        if not self._show_pill_mode():
            self.status_label.configure(text="Refreshing…")

        def worker() -> None:
            try:
                usage = fetch_current_period_usage()
                self.after(0, lambda: self._apply_usage(usage))
            except (AuthError, UsageError) as exc:
                msg = str(exc)
                self.after(0, lambda: self._apply_error(msg))
            except Exception as exc:  # noqa: BLE001 — surface unexpected errors in UI
                msg = f"Unexpected error: {exc}"
                self.after(0, lambda: self._apply_error(msg))
            finally:
                self.after(0, self._clear_refreshing)

        threading.Thread(target=worker, daemon=True).start()

    def _clear_refreshing(self) -> None:
        self._refreshing = False

    def _apply_usage(self, usage: PlanUsage) -> None:
        self._last_usage = usage
        self._connection_ok = True
        self._last_success_at = datetime.now()
        self.total_row.set_percent(usage.total_percent)
        self.total_row.set_subtext(usage.summary_line)
        self.auto_row.set_percent(usage.auto_percent)
        self.api_row.set_percent(usage.api_percent)
        self._paint_status_dots()
        self._update_pill_percent()
        if not self._show_pill_mode():
            stamp = self._last_success_at.strftime("%H:%M:%S")
            self.status_label.configure(text=f"Updated {stamp}")
            self._update_reset_countdown()
            self._update_stale_badge()
        self._resize_to_content()

    def _apply_error(self, message: str) -> None:
        self._connection_ok = False
        self._paint_status_dots()
        if not self._show_pill_mode():
            self.status_label.configure(text=message)
            self._update_stale_badge()
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
    # Epoch ms / seconds
    try:
        num = float(raw)
        if num > 1e12:
            num /= 1000.0
        return datetime.fromtimestamp(num, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def main() -> None:
    app = UsageFloater()
    try:
        tkfont.nametofont("TkDefaultFont").configure(family="Segoe UI", size=9)
    except tk.TclError:
        pass
    # Re-apply click-through after window is mapped
    app.after(100, app._apply_settings_side_effects)
    app.mainloop()


if __name__ == "__main__":
    main()
