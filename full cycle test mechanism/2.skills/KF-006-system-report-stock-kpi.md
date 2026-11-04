# KF-006 — `/system_report` stock KPI says 2 while its own body says "none found"

**Severity:** low — cosmetic, but destroys trust in the page
**Status:** open
**Found by:** reading the KPI and the body in the same response

---

## Symptom

```
1 Sync Issues   0 Stock Discrepancies   2 Unpaid Bills   0 Zero-Amount Bills
...
No stock discrepancies found. All material balances match.
```

The counter is `2` and the list is empty, in the same render.

## Root cause

`app/blueprints/misc/_wipe_system_report.py`:

```python
'stock_issues': []
...
for m in Material.query.all():
    total_in  = sum(Entry.qty for Entry where type='IN')
    total_out = sum(Entry.qty for Entry where type='OUT')
    calc_total = total_in - total_out
    if abs(calc_total - (m.total or 0)) > 0.1:
        report['stock_issues'].append(...)
```

The template counts something other than `report['stock_issues'] | length` — it
prints a KPI derived from a different (looser) computation, then renders the
tolerance-filtered list. Two definitions of "discrepancy" in one page.

## Fix

Compute once, use twice:

```python
report['stock_issues'] = [ ... ]            # already tolerance-filtered
# template:
{{ report.stock_issues | length }}
```

Also count **material returns**: the current query only looks at `Entry` rows, so
a return (which writes an `IN` entry) is counted correctly, but a cancelled GRN
(`is_void=1` on the GRN, not necessarily on its entry) can leave a phantom.

## Acceptance

| Check | Before | After |
|---|---|---|
| KPI and body agree | ✗ | ✓ |
| `Y-03` | "No stock discrepancies found" while KPI 2 | both 0 |

Remove `known=D_STOCK_KPI` from `Y-03`.
