# KF-002 — Receipts page reports "GRN Paid 0.00" despite real GRN payments

**Severity:** medium — a monitoring page that cannot be trusted
**Status:** open
**Found by:** page-by-page read of `pages.md`

---

## Symptom

`/accounts/receipts?from=2026-10-01&to=2026-10-31`

```
Sales Paid            Rs. 13,500.00
GRN Paid              Rs.     0.00      <-- 60,000 was actually paid
Total Cash Movement   Rs. 13,500.00
```

and the GRN block prints *"No GRN receipts in this range."* while
`supplier_payment` holds a 60,000 GRN payment against GRN 1.

## Root cause

`blueprints/accounts/payments.py::receipts()` selects GRNs with
`GRN.paid_amount > 0`, then sums `grn.paid_amount`.

But GRN payments are recorded in **`supplier_payment`** (with `grn_id` and
`payment_kind='GRN_MATERIAL'`), and `grn.paid_amount` is never updated:

```sql
select id, paid_amount from grn;
-- 1|0.0  2|0.0  3|0.0  4|0.0  5|0.0  6|0.0
```

So the filter excludes every GRN and the tile sums an always-zero column.

The same page's *Sales Paid* tile has the mirror problem: it sums
`direct_sale.paid_amount` (8,500 + 5,000 + 0 = 13,500) — the **advance taken at
sale time**, not the 34,500 of `Payment` receipts. So "Total Cash Movement" is
not a cash movement figure at all.

## Impact

* The page cannot be used to reconcile cash — it under-reports by 60,000.
* Two pages that both claim to show receipts disagree, with no explanation.

## Fix

```python
from app.services.grn_payments import grn_paid_total      # or an aggregate query

grns = (GRN.query
        .join(SupplierPayment, SupplierPayment.grn_id == GRN.id)
        .filter(GRN.is_void == False, SupplierPayment.is_void == False)
        .filter(SupplierPayment.date_posted.between(date_from, date_to_excl))
        .distinct().all())
grn_totals = {g.id: grn_breakdown(g)['landed_cost_total'] for g in grns}
grn_paid   = {g.id: paid_against_grn(g.id) for g in grns}
```

And relabel the tiles so they say what they mean:

| Current label | Reality | Better label |
|---|---|---|
| Sales Paid | advance collected on direct sales | *Sale Advances* |
| GRN Paid | (always 0) | *GRN Payments* |
| Total Cash Movement | neither | remove, or compute from `account_transaction` |

## Acceptance

| Check | Before | After |
|---|---|---|
| `Q-02` GRN Paid | 0.00 | 60,000.00 |
| GRN block | "No GRN receipts" | one row for `MB NO.CYC-GRN-1` |
| Total Cash Movement | 13,500 | matches `/cash_flow` received for the period (or the label is gone) |

Remove `known=D_RECEIPTS_MISMATCH` from `Q-02`.
