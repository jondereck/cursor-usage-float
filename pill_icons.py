"""Load pill PNG marks (dev + PyInstaller); keep references alive for Tk."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from paths import resource_path

PILL_ICON_FILES: dict[str, str] = {
    "cursor": "cursor-mark.png",
    "grok": "grok-mark.png",
    "xai": "xai-mark.png",
    "antigravity": "antigravity-mark.png",
    "codex": "codex-mark.png",
    "opencode": "opencode-mark.png",
}


def load_pill_icons(master: tk.Misc) -> tuple[dict[str, tk.PhotoImage | None], list[tk.PhotoImage]]:
    """Load each icon independently; return (name→image, refs to prevent GC)."""
    icons: dict[str, tk.PhotoImage | None] = {}
    refs: list[tk.PhotoImage] = []
    for key, filename in PILL_ICON_FILES.items():
        icons[key] = _load_one(master, filename)
        if icons[key] is not None:
            refs.append(icons[key])
    return icons, refs


def _load_one(master: tk.Misc, filename: str) -> tk.PhotoImage | None:
    path: Path = resource_path("assets", filename)
    if not path.is_file():
        return None
    # Forward slashes avoid rare Tcl path issues on Windows.
    file_arg = path.as_posix()
    try:
        return tk.PhotoImage(master=master, file=file_arg)
    except tk.TclError:
        pass
    try:
        return tk.PhotoImage(master=master, file=str(path))
    except tk.TclError:
        return None
