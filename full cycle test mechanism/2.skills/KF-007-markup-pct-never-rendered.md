# KF-007 — `markup_pct` is computed on every P&L but rendered nowhere

**Severity:** low (feature gap)
**Status:** open
**Found by:** `SKL-004` — asserting a specific figure's presence in the PDF

---

## Symptom

`app/services/profit_loss.py:2528` computes:

```python
"margin_pct": (round(total_profit / recognized_revenue * 100.0, 2) ...),   # 21.09
"markup_pct": (round(total_profit / total_cogs          * 100.0, 2) ...),   # 26.73
```

`margin_pct` (21.09 %) appears on the page and in the PDF. `markup_pct` (26.73 %)
appears **nowhere**:

```bash
grep -rn "markup_pct" --include=*.html --include=*.py . | grep -v tests
# app/services/profit_loss.py:2528     <- the only hit
```

Two percentage concepts are conflated by users constantly (profit-on-sales vs
profit-on-cost), so a report that shows exactly one of them is ambiguous by
omission.

## Fix

Add it next to the margin in `templates/profit_reports.html` (and the PDF
template):

```html
<span class="text-white-50">Markup on cost</span>
<span class="fw-bold">{{ "%.2f"|format(summary.markup_pct) }}%</span>
```

Both numbers derive from the same `summary` dict, so there is no new query.

## Acceptance

| Check | Before | After |
|---|---|---|
| `L-07` "26.73" on `/profit_reports` | absent | present |
| P&L PDF contains 26.73 % | absent | present |
| margin 21.09 % still correct | ✓ | ✓ |

Remove `known=D_MARKUP_HIDDEN` from `L-07`.
