"""App release metadata (JonOS-style version.json + CHANGELOG)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from paths import resource_path


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    date: str
    title: str


_FALLBACK = ReleaseInfo(version="0.0.0", date="", title="Cursor Usage Float")


def version_json_path() -> Path:
    return resource_path("version.json")


def changelog_path() -> Path:
    return resource_path("CHANGELOG.md")


def load_release_info() -> ReleaseInfo:
    path = version_json_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return _FALLBACK
    if not isinstance(raw, dict):
        return _FALLBACK
    version = str(raw.get("version") or "").strip() or _FALLBACK.version
    date = str(raw.get("date") or "").strip()
    title = str(raw.get("title") or "").strip()
    return ReleaseInfo(version=version, date=date, title=title)


def load_changelog_text() -> str:
    path = changelog_path()
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        release = load_release_info()
        return f"# Changelog\n\n## {release.version}\n\n{release.title}\n"


def whats_new_unread(last_seen_version: str, release: ReleaseInfo | None = None) -> bool:
    """True when the user has not acknowledged the current release."""
    release = release or load_release_info()
    seen = (last_seen_version or "").strip()
    current = (release.version or "").strip()
    if not current or current == "0.0.0":
        return False
    return seen != current


def format_version_footer(release: ReleaseInfo | None = None) -> str:
    release = release or load_release_info()
    if release.date:
        return f"v{release.version} · {release.date}"
    return f"v{release.version}"
