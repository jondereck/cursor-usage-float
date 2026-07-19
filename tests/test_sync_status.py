"""Tests for shared-folder backup status inspection."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def test_local_only_when_no_sync_folder() -> None:
    from sync_status import inspect_sync_status, record_sync_success

    record_sync_success()
    status = inspect_sync_status("")

    assert status.state == "local"
    assert status.label == "Local only"
    assert status.last_backup is None


def test_unavailable_when_sync_folder_is_missing(tmp_path: Path) -> None:
    from sync_status import inspect_sync_status, record_sync_success

    record_sync_success()
    status = inspect_sync_status(str(tmp_path / "missing"))

    assert status.state == "unavailable"
    assert "unavailable" in status.label.lower()
    assert status.last_backup is None


def test_synced_uses_newest_shared_file_mtime(tmp_path: Path) -> None:
    from sync_status import inspect_sync_status, record_sync_success

    record_sync_success()
    settings = tmp_path / "settings.json"
    history = tmp_path / "pace-history.json"
    settings.write_text("{}", encoding="utf-8")
    history.write_text("{}", encoding="utf-8")
    os.utime(settings, (1000, 1000))
    os.utime(history, (2000, 2000))

    status = inspect_sync_status(str(tmp_path))

    assert status.state == "synced"
    assert status.label == "Synced"
    assert status.last_backup == datetime.fromtimestamp(2000)


def test_recorded_write_error_takes_priority_for_available_folder(
    tmp_path: Path,
) -> None:
    from sync_status import (
        inspect_sync_status,
        record_sync_error,
        record_sync_success,
    )

    record_sync_error("Permission denied")
    status = inspect_sync_status(str(tmp_path))

    assert status.state == "error"
    assert status.label == "Sync error"
    assert status.detail == "Permission denied"

    record_sync_success()


def test_format_last_backup_includes_day_date_and_time() -> None:
    from sync_status import format_last_backup

    stamp = datetime(2026, 7, 19, 20, 24)
    assert format_last_backup(stamp) == "Last backup: Sun, Jul 19 · 8:24 PM"
    assert format_last_backup(None) == "Last backup: —"
