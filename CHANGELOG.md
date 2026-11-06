# Cursor Usage Float — changelog

Bump `version.json` when you add a section (newest first).

## 1.2.5 — 2026-11-06

### Fixed
- **Pill on the taskbar no longer jumps up.** Position is clamped to the full
  monitor (not the work area), and expand keeps the pill's bottom edge so the
  panel grows upward in place.
- **Hide on true fullscreen** (YouTube / Netflix / F11 / games). Checks every
  400ms, including HTML5 fullscreen windows on the foreground app. Toggle in
  **Settings → Behavior**.

## 1.2.4 — 2026-11-05

### Fixed
- **Pill near the bottom edge now expands upward.** The panel flips away from
  the screen edge (and leftward when the pill is near the right edge) so the
  whole window stays visible above the taskbar. Collapsing puts the pill back
  exactly where you clicked it.

## 1.2.3 — 2026-11-04

### Added
- **Tokens used** in the Cursor Models subtitle (input + output + cache reads,
  cumulative for the month). Toggle in **Settings → Appearance**.
  Cursor only counts token-based calls here, so Composer requests are not included.

## 1.2.2 — 2026-11-04

### Fixed
- **Grok row no longer "expires" every few hours.** The stored `refresh_token` in
  `~/.grok/auth.json` is now used to refresh the access token silently (and once more
  on a 401), so the percentage keeps updating without a manual refresh or `grok login`.
- Grok auth file writes are atomic and skipped when the grok CLI already rotated the token.

### Added
- Tray notification **Grok needs re-login** when a refresh genuinely fails (revoked
  login). Clicking it opens the floater and starts `grok login`. Toggle in
  **Settings → Behavior**.
- The header refresh button now **spins** while a refresh is running.

## 1.2.1 — 2026-11-02

### Added
- **Grok (grok.com)** row with xAI pill icon, Premium plan label, email + weekly reset in subtitle.
- Cursor Models subtitle shows plan, email, and billing reset countdown.
- Settings toggle **Other Models (API pool)** (off by default).

### Changed
- Grok (grok.com): when `~/.grok/auth.json` is missing, auto `npm i -g @xai-official/grok` (once) and open `grok login`.
- Settings **Run grok login** button (install CLI if needed, then browser sign-in).
- PyInstaller build bundles `xai-mark.png` so pill icons no longer all disappear in the `.exe`.
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
