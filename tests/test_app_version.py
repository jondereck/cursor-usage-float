"""Tests for version.json and What's New unread state."""

from __future__ import annotations

from pathlib import Path

from app_version import (
    ReleaseInfo,
    format_version_footer,
    load_changelog_text,
    load_release_info,
    whats_new_unread,
)


def test_load_release_info_from_version_json() -> None:
    release = load_release_info()
    assert release.version == "1.2.1"
    assert release.date == "2026-11-02"
    assert release.title


def test_whats_new_unread_when_never_seen() -> None:
    release = load_release_info()
    assert whats_new_unread("", release) is True
    assert whats_new_unread("0.9.0", release) is True


def test_whats_new_read_after_ack() -> None:
    release = load_release_info()
    assert whats_new_unread(release.version, release) is False


def test_load_release_info_missing_file(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "version.json"
    monkeypatch.setattr(
        "app_version.version_json_path",
        lambda: missing,
    )
    release = load_release_info()
    assert release.version == "0.0.0"
    assert whats_new_unread("", release) is False


def test_load_changelog_text(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Test\n\nHello", encoding="utf-8")
    monkeypatch.setattr("app_version.changelog_path", lambda: path)
    assert "Hello" in load_changelog_text()


def test_format_version_footer() -> None:
    assert format_version_footer(
        ReleaseInfo(version="1.2.3", date="2026-01-01", title="x")
    ) == "v1.2.3 · 2026-01-01"


def test_last_seen_version_round_trip(tmp_path: Path) -> None:
    from settings import AppSettings, load_settings, save_settings

    path = tmp_path / "settings.json"
    save_settings(AppSettings(last_seen_version="1.0.0"), path)
    assert load_settings(path).last_seen_version == "1.0.0"
