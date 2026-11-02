# Multi-account usage (Cursor + Grok app) with auto refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or implement task-by-task in Agent). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show **separate usage bars** for Jon’s real accounts (e.g. Cursor `jonnifas@gmail.com`, Cursor `jonderecknifas@gmail.com`, Grok app Premium ~38%) and **refresh the UI automatically** when the active login on each platform changes—without manual “Save token” every time where we can avoid it.

**Architecture:** Introduce a small **account-slot** layer (like Codex’s `~/.codex/auth.json`): each slot has a **source** (live Cursor DB, token file, Grok app store TBD) and a **fetcher**. A **login watcher** detects Cursor token changes (and Grok when discovered), triggers `refresh_async`, and updates row labels from JWT email. Split **“Grok Bot (Cursor allowance)”** from **“Grok app / Premium”** in UI copy and code. Phase 0 is a **spike**; no Grok-app row until we have a stable read-only auth + usage endpoint.

**Tech Stack:** Python 3.10+, Tkinter, existing `cursor_auth` / `cursor_usage`, new `grok_app_usage.py` (after spike), `account_slots.py`, `login_watch.py`, pytest.

## Global Constraints

- Windows-first (current product); fail-soft on optional providers.
- **Never** sync bearer tokens to Google Drive shared `settings.json` (extend `LOCAL_ONLY_SETTINGS`).
- Tokens stay on disk only in user-chosen local paths or `%APPDATA%\cursor-usage-float\`—document in README.
- No breaking rename of existing settings keys in v1.1; add new keys with defaults.
- Bump `version.json` + `CHANGELOG.md` when shipping user-visible behavior.
- Follow existing patterns: background thread fetch, `after(0, …)` UI apply, adaptive polling.

---

## Jon’s target layout (acceptance sketch)

| Row label (example) | Account | Source |
|---------------------|---------|--------|
| Cursor · jonnifas@… | Cursor IDE daily | Live `state.vscdb` |
| Cursor · jondereck@… | Second Cursor sub | Token file **or** auto-snapshot on switch |
| Grok Bot (Cursor) · jonnifas@… | Cursor bundled weekly | `GetSandUsageStatus` with **live** Cursor token |
| Grok Premium · jondereck@… | Grok.com / app | **New** — Grok app auth + usage API (spike) |

Pill can stay on one metric; expanded view shows all enabled rows.

---

## File map (planned)

| File | Responsibility |
|------|----------------|
| `account_slots.py` | Slot config, resolve token per slot, JWT email for labels |
| `login_watch.py` | Poll/watch Cursor DB token fingerprint; optional Grok path |
| `grok_app_usage.py` | Parse + fetch Grok **app** premium usage (after spike) |
| `cursor_auth.py` | Extend: `token_fingerprint`, `jwt_email_claim` (no verify) |
| `cursor_usage.py` | Optional: fetch grok bot per arbitrary token |
| `settings.py` | Slot settings, local-only paths, rename labels |
| `settings_ui.py` | Accounts UI: slots, auto-snapshot toggle, test connection |
| `main.py` | Wire rows, watcher, apply labels on refresh |
| `tests/test_account_slots.py` | Slot + local-only sync |
| `tests/test_login_watch.py` | Fingerprint change detection |
| `tests/test_grok_app_usage.py` | Parsers (fixture JSON from spike) |
| `docs/superpowers/specs/2026-11-02-grok-app-usage-spike.md` | Spike notes (endpoints, paths) |

---

## Phase 0 — Grok app spike (blocker for Grok Premium row)

**Outcome:** A short spec with **yes/no** on read-only usage + exact Windows paths.

- [ ] **0.1** Document Jon’s Grok client: desktop app vs browser-only; where Premium % is shown (screenshot → which product).
- [ ] **0.2** On Windows, search `%APPDATA%`, `%LOCALAPPDATA%`, Electron stores for Grok/x.ai (Process Explorer / dir listing)—record paths **without** pasting secrets into git.
- [ ] **0.3** With devtools or mitmproxy (local only), capture **one** HTTPS call that returns premium usage % when Grok app loads; save **redacted** request shape to `docs/superpowers/specs/2026-11-02-grok-app-usage-spike.md`.
- [ ] **0.4** Decision in spec: **A)** implement `grok_app_usage.py` fetcher, **B)** defer Grok Premium row and ship Cursor-only auto-switch first, **C)** impossible without official API → keep manual % or deep link only.

**Stop gate:** Do not implement Grok Premium row until 0.4 is **A**.

---

## Phase 1 — Account slots + labels (Cursor only, shippable)

**Outcome:** Main/Second bars show **email labels**; second slot uses token file; clearer copy.

- [ ] **1.1** Add `jwt_email_claim(token) -> str | None` in `cursor_auth.py` (base64 payload only, no signature verify). Tests with fixture JWT.
- [ ] **1.2** Add `account_slots.py`: `CursorSlot(kind="live"|"file", path?, label_override?)` → `resolve_token()` + `display_label()`.
- [ ] **1.3** Settings: `cursor_secondary_label` kept; add `auto_label_from_email: bool = True` (default on). Map existing `show_dual_cursor` + `secondary_cursor_token_file` to slot B.
- [ ] **1.4** `main.py`: After fetch, set row titles to `Cursor · {email}` or custom label; subtext unchanged.
- [ ] **1.5** Rename UI string **“Grok Bot”** → **“Grok Bot (Cursor)”** in `settings_ui.py` / row title (tooltip or subtext: “Not Grok.com Premium”).
- [ ] **1.6** Tests + bump patch version; update README “Two Cursor accounts” with jonnifas/jondereck example.

---

## Phase 2 — Auto refresh when Cursor login changes

**Outcome:** Sign out / sign in sa Cursor → within ~30s bars update **without** manual Save (primary always; secondary optional auto-snapshot).

- [ ] **2.1** Add `login_watch.py`: `cursor_token_fingerprint(db_path) -> str` (hash of resolved access token or last 8 chars + exp from JWT).
- [ ] **2.2** On poll tick (or dedicated 10s timer), if fingerprint ≠ last → call `refresh_async()` and update status “Account changed · refreshing…”.
- [ ] **2.3** Settings toggle: **“Remember previous Cursor login as second bar”** (default off). When on and fingerprint changes A→B: write **previous** token to `secondary_cursor_token_file` before UI shows B (one-time export on switch). Document security tradeoff.
- [ ] **2.4** When fingerprint changes, refresh primary + grok bot (cursor) + secondary file fetch in one worker (existing thread).
- [ ] **2.5** Tests: mock fingerprint change triggers refresh flag; auto-snapshot writes file with fake token in tmp_path.

---

## Phase 3 — Grok Premium row (after Phase 0 = A)

**Outcome:** Separate bar for Grok app account (jondereck 38%) independent of Cursor login.

- [ ] **3.1** Implement `grok_app_usage.py`: read auth from spike path; `fetch_grok_app_usage() -> GrokAppUsage(percent, reset?, email?)`.
- [ ] **3.2** Settings: `show_grok_app`, `grok_app_token_file` or `grok_app_auth_path` (local-only list in `LOCAL_ONLY_SETTINGS`).
- [ ] **3.3** UI row **“Grok Premium”** + optional second token file + **“Save current Grok login to file”** (mirror Cursor flow) until Grok live watch exists.
- [ ] **3.4** `login_watch.py`: add Grok auth fingerprint when path known; auto `refresh_async` on change.
- [ ] **3.5** Pill/icon: optional small Grok premium segment (settings off by default).
- [ ] **3.6** Tests with recorded fixtures only; bump minor version; CHANGELOG.

---

## Phase 4 — Polish (Cursor-like feel)

- [ ] **4.1** Settings **Accounts** summary: “Signed in: jonnifas@… · Second file: jondereck@… (ok/stale)” from last successful fetch.
- [ ] **4.2** Stale second slot: if JWT `exp` passed, subtext “Token expired · sign in to that account in Cursor and re-save (or enable auto-remember)”.
- [ ] **4.3** DEVLOG + README diagram (mermaid) of slots vs products.

---

## What we cannot promise (set expectations)

- **Two simultaneous live Cursor logins** in one IDE: impossible; live + file/snapshot remains the model.
- **Grok Premium without Phase 0**: no ETA until spike finds auth + API.
- **100% instant** on login: file watchers on `state.vscdb` may lag SQLite lock; 10–30s is realistic.

---

## Suggested implementation order for Jon

1. Ship **Phase 1 + 2** first → solves auto-update on Cursor switch + clear labels for jonnifas/jondereck **Cursor** usage.
2. Run **Phase 0 spike** in parallel (1–2 hours manual).
3. Ship **Phase 3** when spike is green.

---

## Verification checklist

- [ ] Cursor login switch jonnifas ↔ jondereck: primary email label and % change without opening Settings.
- [ ] With token file for jondereck + live jonnifas: two **different** percents when dashboards differ.
- [ ] Grok Bot (Cursor) row tracks **live** Cursor account, not token file.
- [ ] After Phase 3: Grok Premium row tracks jondereck file/login, shows ~38% when app does.
- [ ] Shared Drive `settings.json` contains **no** token file contents or JWT strings.
- [ ] `pytest tests -q` green.

---

## Task 1 kickoff (first coding session)

Start with **1.1** `jwt_email_claim` + tests, then **1.2–1.4** labels on existing dual bar—smallest visible win before watcher work.
