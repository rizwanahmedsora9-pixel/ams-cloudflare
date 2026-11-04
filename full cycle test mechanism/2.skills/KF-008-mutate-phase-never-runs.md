# KF-008 — `seed.mutate()` is dead code: five write flows have never run

**Severity:** high — the suite advertises 31 write paths while exercising 26 of the
36 it defines, and one assertion (`W-06`) can never pass for a reason unrelated to
the defect it blames
**Status:** open (confirmed on `e8cdde0`, run `run-005-20261104T0538`)
**Found by:** `SKL-002` (verify a number three ways) applied to a *failing* known
check — W-06 blamed `KF-001`, but the SQL row it reads does not exist

---

## Symptom

Every run of the mechanism prints:

```
seed     : 31/31 steps ok
...
[KNOWN] W-06 reconciliation difference 17,000 | got None want 17000.0
```

and `counts.json` from that same run shows the phase-2 tables empty:

```json
"material_return": 0, "material_return_item": 0,
"cash_flow_difference_adjustment": 0,
"cash_flow_reconciliation_audit": 0,
"account_reconciliation": 0
```

`W-06` is attributed to `KF-001` (cash-flow scope), but `KF-001` is about a
*wrong number*; this is a *missing row*. Two different faults, one label.

## Reproduction

```bash
.venv/bin/python "full cycle test mechanism/1.all files/run-005-20261104T0538/scripts/probe_mutate_gap.py"
```

```
seed() calls mutate()?        False
phase-1 stages                31
phase-2 stages (unreachable)  5
   [ok ] material return
   [ok ] pending bill
   [ok ] reconciliation
   [ok ] idempotent replay rejected
   [ok ] toggle bill paid

rows created by phase 2       {"cash_flow_difference_adjustment": [0, 1],
                               "material_return": [0, 1], "entry": [9, 10],
                               "payment": [2, 3], "pending_bill": [3, 4], ...}
stock DG before/after         195.0 -> 197.0
P&L profit same?              False
```

## Root cause

`full cycle test mechanism/1.all files/shared/seed.py:250`

```python
def mutate(session, db, ctx: dict) -> dict:
    """Phase-2 write flows: corrections that change the canonical numbers."""

    ...

    ctx["db_counts"] = db.counts()
    return ctx
```

`grep -n "mutate(" seed.py` returns exactly one hit — the `def` itself. `seed()`
returns at line 249 and nothing ever calls `mutate()`, so:

| Phase-2 flow | Table(s) it should write | Runs today? |
|---|---|---|
| material return (2 bags) | `material_return`, `material_return_item` | no |
| manual pending bill (4,500) | `pending_bill` | no |
| reconciliation save (physical 175,500) | `cash_flow_difference_adjustment`, `cash_flow_reconciliation_audit` | no |
| idempotent replay rejected | none (asserts a flash) | no |
| `toggle_bill_paid` on/off | `entry`, `bill_counter` | no |

## The proof that names the cause

Posting the reconciliation form by hand against the *same* run database writes
the row in 1.8 s:

```
rows before: 0
flash: success: Reconciliation saved for 2026-10-31. Next day opening will be
       Rs. 175,500. Account balances were not changed.
rows after: 1  ->  {'amount': 17000.0, 'physical_cash_available': 175500.0,
                    'calculated_closing': 158500.0, 'difference': 17000.0}
```

So the endpoint works, the data model works, `tests/test_cash_flow_reconciliation_chain.py`
covers the same path — and the mechanism still never visits it. The missing
17,000 is a missing *call*, not a broken page.

## Impact

* `W-06` burns a `known=` slot forever and hides the fact that the mechanism has
  no reconciliation coverage; a regression in `save_reconciliation` would be
  invisible to the full-cycle run.
* Material returns, manual pending bills and the idempotency guard are unchecked
  by every full-cycle run, including the two high-severity defects already in the
  register (`KF-003` is a *missing pending bill* — exactly what the unexecuted
  `pending bill` flow would have probed).
* The headline "31/31 write paths ok" is 86% of the defined flows (31 of 36), not
  100%; the README's promise of "one command builds the whole business" is
  overstated by five flows.
* Turning it on is **not** free: phase 2 changes ≥ 4 canonical figures
  (`stock_dg` 195 → 197, `pending_bill` 3 → 4, `account_transaction` 9 → 10,
  `payment` 2 → 3, P&L profit), so `data.py:EXPECT` must be re-derived in the
  same commit or ~15 checks go red for the wrong reason.

## Fix

Two options, in order of preference.

**(a) Keep phase 1 canonical, assert phase 2 separately** — no `EXPECT` churn:

```python
# seed.run.py, after checks.run_all(...)
post = seed.mutate(session, db, ctx)          # phase 2, its own checks
checks.run_after_mutation(session, db, results)
```

with `run_after_mutation()` holding the five new assertions
(`material_return` row exists, `stock_dg` 197, pending bill 4,500 visible,
reconciliation difference 17,000, replay flash contains "already"). Report the
seed total as `36/36`, not `31/31`.

**(b) Fold phase 2 into the canonical dataset** — acceptable only if `data.py`
is re-derived at the same time:

```python
# data.py
"stock_dg": 197.0,              # 195 after sales, +2 returned
"client_net": 16_000.0,         # 20,500 - 4,500 manual pending bill
```

## Acceptance

| Check | Before | After |
|---|---|---|
| `M-01` phase-2 flows reachable from `seed.seed()` | `False` | `True` |
| `W-06` reconciliation difference | `None` | `17000.0` |
| `material_return` rows after a run | 0 | 1 |
| seed steps | 31/31 | 36/36 |

When `M-01` goes green, remove `known=D_MUTATE_GAP` from `M-01` and `W-06`;
`W-05` keeps `known=D_CASHFLOW_SCOPE`, because `KF-001` is a separate, real bug.

> **Rule:** a defect with no failing check is a rumour. `M-01` is that check, and
> it is deliberately static — it reads `inspect.getsource(seed.seed)`, so it
> cannot be satisfied by a stage list that merely *looks* right.
