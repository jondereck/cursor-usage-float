# Sync Status Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show shared-folder backup state and last successful write time in Settings → Sync.

**Architecture:** Add a pure `sync_status.py` inspector that derives state from
the configured folder, file mtimes, and the latest in-process write result.
Settings renders that status and refreshes it every 10 seconds. Shared settings
writes report success/failure to the inspector.

**Tech Stack:** Python stdlib, Tkinter, pytest

## Global Constraints

- Indicator appears only in Settings → Sync.
- “Last backup” means successful write to the shared folder, not confirmed cloud upload.
- Existing local fallback must continue when Drive is unavailable.

---

### Task 1: Sync status model and inspector

**Files:**
- Create: `sync_status.py`
- Create: `tests/test_sync_status.py`

**Interfaces:**
- Produces: `SyncStatus(state, label, last_backup, detail)`
- Produces: `inspect_sync_status(folder: str) -> SyncStatus`
- Produces: `record_sync_success()` and `record_sync_error(message: str)`

- [ ] Write tests for local-only, unavailable, synced mtime, and write-error states.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests\test_sync_status.py -q`; expect failures because the module does not exist.
- [ ] Implement the dataclass, process-memory error state, folder inspection, and newest shared-file timestamp.
- [ ] Re-run the targeted tests; expect all to pass.

### Task 2: Record shared settings writes

**Files:**
- Modify: `settings.py`
- Modify: `tests/test_settings.py`

**Interfaces:**
- Consumes: `record_sync_success()` / `record_sync_error(message)`

- [ ] Add tests proving shared write success clears errors and shared write failure records an error while preserving local settings.
- [ ] Run the new tests; expect failures before wiring.
- [ ] Report success/error around the existing best-effort shared settings write.
- [ ] Re-run targeted tests; expect all to pass.

### Task 3: Settings UI indicator

**Files:**
- Modify: `settings_ui.py`
- Modify: `theme.py` only if an existing status color is insufficient.

**Interfaces:**
- Consumes: `inspect_sync_status(folder)`

- [ ] Add a colored status label and last-backup label under the Sync path.
- [ ] Refresh immediately and every 10 seconds while Settings is open.
- [ ] Cancel the scheduled refresh when Settings closes.
- [ ] Run the full test suite and manually open Settings to verify rendering.
