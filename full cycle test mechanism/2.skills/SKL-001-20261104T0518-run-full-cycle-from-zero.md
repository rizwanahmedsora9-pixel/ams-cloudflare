# SKL-001 — Run the full acceptance cycle from zero in under a minute

**Confidence:** high (31/31 write paths reproduced, 82/85 checks green)
**Reuse:** every PR, every merge, every dependency bump
**Cost:** ~15 s wall clock, no network, no fixtures checked into git
**Prereqs:** `.venv` with `requirements.txt`; `pypdf` for PDF assertions

---

## What this skill replaces

Reading 14 code paths to convince yourself a change is safe. One command builds
the whole business from an empty database — two suppliers, four materials, six
GRNs, three sales, four payment paths, a driver settlement, a cash-flow entry,
a return, a reconciliation — then asserts 85 figures a human would check by hand.

## The command

```bash
.venv/bin/python "full cycle test mechanism/1.all files/shared/run.py" \
    --label pr-1234
```

Exit code `0` means no *unexpected* failure. Known defects (see the `KF-*`
documents) are reported but never fail the build.

Output lands in a new numbered directory:

```
1.all files/run-NNN-YYYYMMDDTHHMM/
    cycle.db          scratch database (the only DB touched)
    results.json      every check, machine-readable
    report.md         the human report
    counts.json       row counts per table
    artifacts/        seed context
```

## How the pieces fit

| File | Role | Change it when |
|---|---|---|
| `shared/harness.py` | boots the app, wraps the CSRF client, text/PDF/DB helpers | you need a new *kind* of observation |
| `shared/data.py` | every input value **and** every expected total | never hard-code a number elsewhere |
| `shared/seed.py` | writes the dataset through HTTP forms, in two phases | a new write path needs coverage |
| `shared/checks.py` | read-only assertions, returns pass/fail/known | you learn a new invariant |
| `2.skills/_tools/ledger.py` | numbering, run history, pass-rate trend | you want a new metric |

`data.py` is the single source of truth. `EXPECT["pl_profit"]` is computed once;
a dozen checks read it. Change a sale quantity and every dependent assertion
moves with it — that is why the suite does not rot.

## Why seeding goes through the UI

A row inserted with SQL proves the schema accepts it. A row created by POSTing
the real form proves the route, the CSRF guard, the validation, the side
effects, the flash message and the ledger hooks all work. The mechanism does the
second thing on purpose:

* every seed step asserts the **flash text** a human would see
* `seed.py` returns `31/31 steps ok`, which is itself a result — a broken write
  path shows up there before any number check fails

## Two-phase seeding

Phase 1 (`seed`) builds the canonical dataset. Phase 2 (`mutate`, called after
the read-only assertions) exercises corrections: the material return, the manual
pending bill, the physical reconciliation, and idempotency replays.

The split exists because a return legitimately changes stock 195 → 197.

## Re-running without re-seeding

Debugging a failed check by re-running the whole cycle wastes 15 s and hides the
state. Open the finished run's database instead:

```python
import harness
s = harness.boot(".../run-001-.../cycle.db", fresh=False)   # fresh=False is critical
status, text = s.page("/profit_reports?start_date=2026-10-01&end_date=2026-10-31")
```

`fresh=True` (the default) **deletes the file first**. Using the default on a
finished run destroys the evidence — this was learned the hard way.

## Adding a check

```python
def check_new_thing(session, db, R):
    status, text = session.page("/some/page?x=1")
    R.truth("N-01", "page renders", status == 200, status, 200)
    R.truth("N-02", "KPI reads 1,234",
            number_near(text, "Some Label", EXPECT["some_total"]),
            "see text", EXPECT["some_total"])
    R.near("N-03", "db agrees", db.scalar("select sum(x) from y"), EXPECT["some_total"])
```

Then call it from `run_all()`. Two rules:

1. **Prefer `R.near` over `R.truth` for money.** `number_near` accepts
   `8,500.00`, `8,500`, `8500.0` and `8500`, so a formatting change never
   red-lines the suite.
2. **Never assert on raw HTML.** Pull the text out with `session.page()`; markup
   churn is not a regression.

## Failure triage

| Symptom | Usually means |
|---|---|
| seed step fails | a form field was renamed — check the form, update `seed.py` |
| one number off by a round figure | `data.py` and the app disagree about a total, not a bug in the app |
| all money checks 0 | the run was pointed at a stale DB, or a filter date is wrong |
| PDF check fails but page passes | ReportLab fallback swallowed a number — see `SKL-004` |
| everything fails at boot | `APP_DB_PATH` not honoured, or `.venv` missing a package |
