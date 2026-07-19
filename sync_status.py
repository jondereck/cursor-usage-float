"""Inspect shared-folder backup state for the Settings UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

SyncState = Literal["local", "synced", "unavailable", "error"]

_last_write_error: str | None = None


@dataclass(frozen=True)
class SyncStatus:
    state: SyncState
    label: str
    last_backup: datetime | None = None
    detail: str = ""


def format_last_backup(stamp: datetime | None) -> str:
    """Format a compact, Windows-compatible last-backup label."""
    if stamp is None:
        return "Last backup: —"
    day = stamp.strftime("%a, %b %d").replace(" 0", " ")
    time = stamp.strftime("%I:%M %p").lstrip("0")
    return f"Last backup: {day} · {time}"


def record_sync_success() -> None:
    """Clear the latest in-process shared-write error."""
    global _last_write_error
    _last_write_error = None


def record_sync_error(message: str) -> None:
    """Remember the latest shared-write error for the Settings UI."""
    global _last_write_error
    _last_write_error = str(message).strip() or "Unknown write error"


def inspect_sync_status(sync_folder: str) -> SyncStatus:
    """Derive sync state and newest backup time from the shared folder."""
    folder = (sync_folder or "").strip().strip('"')
    if not folder:
        return SyncStatus(state="local", label="Local only")

    shared = Path(folder).expanduser()
    try:
        if not shared.is_dir():
            return SyncStatus(
                state="unavailable",
                label="Drive unavailable — using local backup",
            )
    except OSError:
        return SyncStatus(
            state="unavailable",
            label="Drive unavailable — using local backup",
        )

    if _last_write_error is not None:
        return SyncStatus(
            state="error",
            label="Sync error",
            detail=_last_write_error,
        )

    modified: list[float] = []
    for name in ("settings.json", "pace-history.json"):
        try:
            candidate = shared / name
            if candidate.is_file():
                modified.append(candidate.stat().st_mtime)
        except OSError:
            continue

    last_backup = datetime.fromtimestamp(max(modified)) if modified else None
    return SyncStatus(
        state="synced",
        label="Synced",
        last_backup=last_backup,
    )
