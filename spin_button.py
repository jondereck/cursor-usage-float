"""Header refresh button that actually spins while a refresh is running.

A ``tk.Button`` can only flash its foreground, so the glyph stays put and the
"is it working?" cue is easy to miss. This Canvas draws the same ↻ glyph at rest
and swaps to a rotating arc while busy.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from theme import CARD, HOVER, MUTED, TEXT

SPIN_INTERVAL_MS = 60
SPIN_STEP_DEG = 30
ARC_SWEEP_DEG = 280
ARC_WIDTH = 2


class SpinButton(tk.Canvas):
    """A flat header icon button with a spinner state."""

    def __init__(
        self,
        master: tk.Misc,
        command: Callable[[], None],
        *,
        glyph: str = "↻",
        font: tuple[str, int] = ("Segoe UI", 10),
        padx: int = 5,
        pady: int = 1,
        bg: str = CARD,
        fg: str = MUTED,
        hover_bg: str = HOVER,
        hover_fg: str = TEXT,
    ) -> None:
        # Measure a real tk.Button with the header's options so swapping in a
        # Canvas does not change the header height by a pixel.
        probe = tk.Button(
            master,
            text=glyph,
            font=font,
            bg=bg,
            fg=fg,
            bd=0,
            relief="flat",
            padx=padx,
            pady=pady,
        )
        probe.update_idletasks()
        width = max(int(probe.winfo_reqwidth()), 18)
        height = max(int(probe.winfo_reqheight()), 16)
        probe.destroy()

        super().__init__(
            master,
            width=width,
            height=height,
            bg=bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            takefocus=0,
        )
        self._width = width
        self._height = height
        self._command = command
        self._glyph = glyph
        self._font = font
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg
        self._hover_fg = hover_fg
        self._hovering = False
        self._angle = 90.0
        self._job: str | None = None

        self._draw_idle()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    @property
    def spinning(self) -> bool:
        return self._job is not None

    def start(self) -> None:
        """Begin the spin animation (idempotent)."""
        if self._job is not None or not self.winfo_exists():
            return
        self._angle = 90.0
        self._draw_spinner()
        self._job = self.after(SPIN_INTERVAL_MS, self._tick)

    def stop(self) -> None:
        """Cancel the animation and return to the static glyph."""
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        if self.winfo_exists():
            self._draw_idle()

    def _color(self) -> str:
        if self._hovering:
            return self._hover_fg
        return self._fg

    def _draw_idle(self) -> None:
        self.delete("all")
        self.configure(bg=self._hover_bg if self._hovering else self._bg)
        self.create_text(
            self._width / 2,
            self._height / 2,
            text=self._glyph,
            font=self._font,
            fill=self._color(),
        )

    def _draw_spinner(self) -> None:
        self.delete("all")
        self.configure(bg=self._hover_bg if self._hovering else self._bg)
        radius = max(min(self._width, self._height) / 2 - ARC_WIDTH - 1, 3)
        cx = self._width / 2
        cy = self._height / 2
        self.create_arc(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            start=self._angle,
            extent=ARC_SWEEP_DEG,
            style="arc",
            outline=self._color(),
            width=ARC_WIDTH,
        )

    def _tick(self) -> None:
        self._job = None
        if not self.winfo_exists():
            return
        self._angle = (self._angle - SPIN_STEP_DEG) % 360
        self._draw_spinner()
        self._job = self.after(SPIN_INTERVAL_MS, self._tick)

    def _on_enter(self, _event: tk.Event | None = None) -> None:
        self._hovering = True
        if self._job is None:
            self._draw_idle()
        else:
            self._draw_spinner()

    def _on_leave(self, _event: tk.Event | None = None) -> None:
        self._hovering = False
        if self._job is None:
            self._draw_idle()
        else:
            self._draw_spinner()

    def _on_click(self, _event: tk.Event | None = None) -> None:
        self._command()


__all__ = ["SpinButton"]
