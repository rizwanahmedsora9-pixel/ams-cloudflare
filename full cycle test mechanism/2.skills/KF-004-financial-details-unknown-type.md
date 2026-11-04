# KF-004 — `/financial_details` prints "TOTAL Rs. 0" for any unknown `type`

**Severity:** low (correctness of an error path), high (misleading)
**Status:** open
**Found by:** `SKL-002` — testing an **invalid** filter, not just valid ones

---

## Symptom

```
/financial_details?start_date=2026-10-01&end_date=2026-10-31&type=DirectSale
    No transactions found for the selected criteria.        TOTAL Rs. 0
```

There *are* direct sales in the period (8,500 + 16,500 + 30,000). Only `cash` and
`credit` are implemented:

```python
# app/blueprints/reports/_profit_financial_details.py
type_filter = request.args.get('type', 'cash')
...
if type_filter == 'cash':
    ...
elif type_filter == 'credit':
    ...
# no else: `transactions` stays []
```

The template then renders the empty state with `TOTAL Rs. 0`.

## Why it matters

An unknown filter value is indistinguishable from *"this period genuinely had no
activity"*. Anyone who bookmarked `?type=DirectSale` (a value the dashboard used
to use) reads "zero money moved" as a fact.

## Fix

```python
VALID_TYPES = ('cash', 'credit')
if type_filter not in VALID_TYPES:
    flash(f"Unknown report type '{type_filter}'. Showing cash received.", "warning")
    type_filter = 'cash'
```

or return HTTP 400 with the valid list. Either is fine; silently rendering zero
is not.

## Acceptance

| Check | Before | After |
|---|---|---|
| `F-03` `type=DirectSale` body | `TOTAL Rs. 0` | a warning + the cash report (34,500) |
| `?type=cash` | 34,500 | 34,500 (unchanged) |
| `?type=credit` | 31,500 | 31,500 (unchanged) |

Remove `known=D_FIN_DETAILS_TYPE` from `F-03`.
