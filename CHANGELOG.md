# Cursor Usage Float — changelog

Bump `version.json` when you add a section (newest first).

## 1.2.1 — 2026-11-02

### Added
- **Grok (grok.com)** row with xAI pill icon, Premium plan label, email + weekly reset in subtitle.
- Cursor Models subtitle shows plan, email, and billing reset countdown.
- Settings toggle **Other Models (API pool)** (off by default).

### Changed
- Grok auth falls back to `~/.grok/auth.json` when a custom token path is invalid or a Cursor export `.txt`.
- Second account bar stays hidden when the saved token fails; login watch no longer forces dual bar on.

## 1.2.0 — 2026-11-02

### Added
- Cursor bars label themselves from the login email when you switch accounts.
- Switching Cursor login refreshes usage and can save the previous login as the second bar.
- **Grok Premium** row reads grok CLI billing (`~/.grok/auth.json` or a token file). This is Grok.com usage, separate from **Grok Bot (Cursor)**.

## 1.1.0 — 2026-11-01

### Added
- **Second Cursor account bar** — top bar = active Cursor login; second bar reads a
  **local token file** (Settings → Cursor accounts). Export while signed into the
  other account, then switch back. Token path stays on this PC (not synced).

## 1.0.0 — 2026-11-01

### Added
- **What's New** — reads this file; unread dot until you tap **Got it** (saved in settings).
- **Version label** in Settings footer (`version.json` is the single source of truth).
- Grok Bot weekly bar, Antigravity / Codex / OpenCode rows, dual-icon pill layout.
- Adaptive polling and grant-based Cursor usage when the dashboard API shape changes.
- Cursor one-decimal % for the Models pool (e.g. 15.1%).

### Fixed
- Cursor **401** when the access token is stored as `cursor-safe-storage:v1:` (Windows decrypt).
