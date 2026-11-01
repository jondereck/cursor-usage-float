# Cursor Usage Float — changelog

Bump `version.json` when you add a section (newest first).

## 1.0.0 — 2026-11-01

### Added
- **What's New** — reads this file; unread dot until you tap **Got it** (saved in settings).
- **Version label** in Settings footer (`version.json` is the single source of truth).
- Grok Bot weekly bar, Antigravity / Codex / OpenCode rows, dual-icon pill layout.
- Adaptive polling and grant-based Cursor usage when the dashboard API shape changes.
- Cursor one-decimal % for the Models pool (e.g. 15.1%).

### Fixed
- Cursor **401** when the access token is stored as `cursor-safe-storage:v1:` (Windows decrypt).
