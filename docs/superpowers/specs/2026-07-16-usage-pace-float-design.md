# Cursor Usage Pace Float — Design

Date: 2026-07-16  
Base app: [jondereck/cursor-usage-float](https://github.com/jondereck/cursor-usage-float) (Python / Tk floater)

## Goal

Remind the user to stop when today’s **fair share** of remaining Cursor Pro allowance is used. Budgets **auto-adjust** from learned Mon–Sun burn weights (weekdays get more if that’s how you historically burn).

## Confirmed decisions

- Behavior: soft-stop on today’s fair allotment (not hard block)
- Surface: existing always-on-top compact float (pill + expanded)
- Plan: Cursor Pro
- Data: existing `GetCurrentPeriodUsage` API + **local daily burn history** for weekday weights / usedToday
- Pacing: `fairToday = remaining × (todayWeight / Σ weights of remaining days in cycle)`
- Soft-stop: OK &lt; 80%, WARN ≥ 80%, STOP ≥ 100% (“Tama na muna…”)

## Why local history (not usage-events API)

The floater already uses `api2.cursor.sh` `GetCurrentPeriodUsage` (percent + optional spend/limit + billing end). Learning weights from a local rolling log of daily burn avoids a second undocumented events endpoint while still adapting to weekday-heavy use.

## Architecture

```
cursor_auth → cursor_usage (PlanUsage)
                    ↓
            pace_history (day start + daily burns)
                    ↓
               pacing (weights, fairToday, OK/WARN/STOP)
                    ↓
                 main.py UI (pill + expanded pace row)
```

## Pacing rules

1. Derive `used` / `remaining` / `limit` from PlanUsage (prefer cents if present; else percent of 100).
2. Persist day-start `used` at local midnight; `usedToday = max(0, used - day_start)`.
3. When the calendar day rolls, record yesterday’s burn into a ~28 day log; learn Mon–Sun weights with a weekend floor.
4. `fairToday` from remaining and weights over remaining calendar days through `billingCycleEnd`.
5. Soft-stop vs `usedToday / fairToday`.

## Out of scope (v1)

- Hard-blocking Cursor
- Official usage API guarantee
- Per-hour models
- Replacing the Python floater with Electron
