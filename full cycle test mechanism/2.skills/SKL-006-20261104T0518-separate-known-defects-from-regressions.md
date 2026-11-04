# SKL-006 — Separate known defects from regressions, or the suite goes red forever

**Confidence:** high — implemented as the `known=` flag in `checks.py`
**Reuse:** the moment a suite has more than one expected failure
**Cost:** one extra field per check

---

## The failure mode this prevents

A suite with three known-broken behaviours prints `3 FAILED` on every run. Within
a week nobody reads the output, the suite is moved to "manual", and it protects
nothing. The defects were never the problem — **undifferentiated output was.**

## The fix: three states, not two

```python
R.truth("Y-02", "missing pending bill for zero-amount delivery",
        "CYC-BD-1" in text, ..., known="KF-003")

R.truth("S-01", "DG stock", ...)          # no known= -> a failure is a regression
```

| State | Printed | Fails the build | Means |
|---|---|---|---|
| pass | `PASS` | no | working |
| known defect | `KNOWN` | **no** | broken, documented, tracked as `KF-NNN` |
| unexpected failure | `FAIL` | **yes** | a regression, or a new defect |

The run summary reports all three separately:

```
checks   : 85
passed   : 82  (96.47%)
known    : 3
failed   : 0
```

**`failed: 0` is the only green condition.** The known count is visible, never
suppressed, and it *cannot grow silently* — adding a `known=` is a deliberate
edit to `checks.py` that shows up in review.

## Why the check still asserts the broken behaviour

A known-defect check asserts *what currently happens*, and is written so it starts
failing the build the moment the defect is **fixed**:

```python
R.truth("F-03", "unknown type renders empty TOTAL 0 (known defect)",
        "TOTAL Rs. 0" in text, "TOTAL Rs. 0" in text, False, known="KF-004")
```

When someone implements a proper fallback, `"TOTAL Rs. 0"` disappears → the check
stops being `KNOWN`. The developer sees it, removes the `known=` flag, and the
check becomes a **regression guard against the defect coming back**.

That is the whole trick: known-defect checks are *inverted* tests that convert
themselves into normal tests on fix. Nothing has to be remembered.

## Pair every `known=` with a defect document

`checks.py` carries the ID; `2.skills/KF-NNN-*.md` carries the reproduction.

| ID | What |
|---|---|
| `KF-001` | cash-flow closing mixes cash-only opening with all-account movement |
| `KF-002` | receipts page reports GRN Paid 0 despite real GRN payments |
| `KF-003` | zero-amount booking delivery leaves no pending bill |
| `KF-004` | `/financial_details` prints TOTAL 0 for an unknown `type` |
| `KF-005` | `/cash_flow` ships JS for a form that is not in the markup |
| `KF-006` | `/system_report` stock KPI disagrees with its own body |
| `KF-007` | `markup_pct` computed, never rendered |

The check proves it still reproduces; the document proves *why* and *how to fix*.
Neither is useful alone.

## The discipline that keeps it honest

1. **Never add `known=` to a check that has not been seen failing for the stated
   reason.** Otherwise it becomes a place to hide real bugs.
2. **Never `known=` a whole feature.** One defect = one check.
3. **Re-run after every fix.** A `KNOWN` that has become `PASS` means the flag
   must be removed — leaving it is how a suite silently stops testing.
4. **Report the known count in every run.** Trend it. If it climbs, the team is
   accumulating debt faster than it is fixing.

The ledger records `known_ids` per run, so you can answer "which defects have
survived the last ten runs?" from `ledger.jsonl` alone.
