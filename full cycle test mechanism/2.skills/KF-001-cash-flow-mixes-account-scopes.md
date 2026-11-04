# KF-001 — Cash-flow closing mixes a cash-only opening with all-account movement

**Severity:** high — the cash-flow report understates money on hand
**Status:** open (reproduces on `2867c3e`)
**Found by:** `SKL-002` (three-way number verification)

---

## Symptom

```
/cash_flow?from_date=2026-10-01&to_date=2026-10-31
    Opening Balance      Rs. 200,000
    Total Received       Rs.  39,500
    Total Spent          Rs.  81,000
    Closing Balance      Rs. 158,500      <-- wrong
```

Reality: Main Cash **175,500**, Meezan Bank **483,000**, company **658,500**.
The report is short by **17,000**.

## Reproduction

1. Seed the canonical dataset (`shared/run.py`).
2. Open `/cash_flow?from_date=2026-10-01&to_date=2026-10-31`.
3. Compare the closing tile with `/accounts/` → *Total Cash Available*.

```bash
.venv/bin/python "full cycle test mechanism/1.all files/shared/run.py" --label kf-001
grep -A2 "W-05" "1.all files"/run-*/report.md
```

## Root cause

Two different account sets are summed in the same formula.

`app/services/cash_flow_svc.py`:

```python
def _cash_accounts_opening_total(as_of_date=None):
    for acc in _cf_company_accounts(active_only=True):
        if (acc.category or '').lower() != 'cash':
            continue          # <-- bank accounts excluded from the opening
        total += float(from_minor(acc.opening_balance_minor))
```

but the movement query includes every company account:

```python
def _cash_flow_in_out_between(start_date, end_date):
    cash_bank_ids = [a.id for a in _cf_company_accounts(active_only=False)]
    # ^ cash AND bank
```

So the report computes `cash-only opening + all-account movement`.

## The proof that names the cause

The gap equals the bank's net movement exactly:

```
bank in  3,000
bank out 20,000
bank net     -17,000
158,500 + 17,000 = 175,500      <- the real Main Cash balance
```

A per-account view confirms it. `/cash_flow?account_id=2` (the bank) prints
*Opening Balance Rs. 200,000* — the **cash** opening — and closes at 183,000
while the account holds 483,000.

## Impact

* Any period with a bank transaction reports a wrong closing.
* Periods with **no** bank movement look correct, which is why this survived —
  the bug is invisible on a cash-only dataset.
* The reconciliation block compares a physical count against this wrong closing,
  producing a phantom 17,000 "excess".

## Fix (either direction works)

**A — widen the opening** (makes the report a *company* cash-flow statement):

```python
opening = sum(float(from_minor(a.opening_balance_minor) or 0)
              for a in _cf_company_accounts(active_only=True)
              if (a.opening_balance_date or date.min) <= as_of_date)
```

Canonical closing becomes 700,000 + 39,500 − 81,000 = **658,500**, matching
`/accounts/` *Total Money Available in Company*.

**B — narrow the movement** (makes the report a *cash-drawer* statement):

restrict `_cash_flow_in_out_between` to `category == 'cash'`. Closing becomes
200,000 + 36,500 − 61,000 = **175,500**, matching Main Cash.

Either is defensible; **A** matches the page's own subtitle
(*"Total Money Available in Company"*) and the reconciliation block, which
already expects the company total.

## Also fix

The per-account filter must drive the opening, not just the rows. With `A`, add
`and (account_filter is None or a.id == account_filter)`.

## Acceptance

| Check | Before | After |
|---|---|---|
| `W-05` closing for the canonical period | 158,500 | 658,500 |
| `W-06` reconciliation difference | 17,000 | 0 |
| `/cash_flow?account_id=2` opening | 200,000 | 500,000 |
| `/cash_flow` closing == `/accounts/` cash KPI | ✗ | ✓ |

Remove `known=D_CASHFLOW_SCOPE` from `W-05` and `W-06` in `checks.py`.
