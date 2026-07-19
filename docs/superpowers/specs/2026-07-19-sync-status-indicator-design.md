# Sync Status Indicator — Design

Date: 2026-07-19

## Goal

Show whether the configured shared folder is receiving app backups and when
the last successful shared-folder write occurred.

## UI

Add a status row under **Settings → Sync**:

- Green: `Synced`
- Yellow: `Drive unavailable — using local backup`
- Red: `Sync error`
- Gray: `Local only`

Show `Last backup: Sun, Jul 19 · 8:24 PM` when a successful shared write can
be determined. Refresh every 10 seconds while Settings is open.

## Meaning

“Backup” means the app successfully wrote `settings.json` or
`pace-history.json` into the configured shared folder. Google Drive/OneDrive
uploads that file separately; the app cannot confirm cloud upload completion.

## Data flow

1. Inspect the configured shared folder.
2. If no folder is configured, report local-only.
3. If the folder is unavailable, report yellow and continue using local data.
4. If shared files exist, use their newest modification time as last backup.
5. Record shared write failures in process memory so reachable-folder write
   errors can be shown as red while the app is running.

## Testing

Unit-test local-only, available/synced, unavailable, and explicit write-error
states plus last-backup timestamp selection.
