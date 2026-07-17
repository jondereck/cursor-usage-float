# Cursor Usage Pace Float — Design

Date: 2026-07-16  
Base app: [jondereck/cursor-usage-float](https://github.com/jondereck/cursor-usage-float) (Python / Tk floater)

## Goal

Remind the user to stop when today’s **equal share** of remaining Cursor Pro
allowance is used. Budgets automatically rebalance after each day so unused
allowance carries forward and over-use reduces the later daily allowance.

## Confirmed decisions

- Behavior: soft-stop on today’s fair allotment (not hard block)
- Surface: existing always-on-top compact float (pill + expanded)
- Plan: Cursor Pro
- Data: existing `GetCurrentPeriodUsage` API + a **local day-start baseline**
  for `usedToday`
- Pacing: `fairToday = (remaining + usedToday) / remaining calendar days`
- Soft-stop: OK &lt; 80%, WARN ≥ 80%, STOP ≥ 100% (“Tama na muna…”)

## Why a local baseline (not usage-events API)

The floater already uses `api2.cursor.sh` `GetCurrentPeriodUsage` (percent +
optional spend/limit + billing end). A local day-start baseline derives
`usedToday` without relying on a second undocumented events endpoint.

## Architecture

```
cursor_auth → cursor_usage (PlanUsage)
                    ↓
            pace_history (day start + daily burns)
                    ↓
               pacing (equal split, fairToday, OK/WARN/STOP)
                    ↓
                 main.py UI (pill + expanded pace row)
```

## Pacing rules

1. Derive `used` / `remaining` / `limit` from PlanUsage (prefer cents if present; else percent of 100).
2. Persist day-start `used` at local midnight; `usedToday = max(0, used - day_start)`.
3. When the calendar day rolls, set a new day-start baseline.
4. Reconstruct the start-of-day pool as `remaining + usedToday`, then divide it
   equally by the calendar days through `billingCycleEnd`. This keeps today's
   target stable while live remaining falls; unused or excess usage is
   redistributed when the next day starts.
5. Soft-stop vs `usedToday / fairToday`.

## Out of scope (v1)

- Hard-blocking Cursor
- Official usage API guarantee
- Per-hour models
- Replacing the Python floater with Electron
