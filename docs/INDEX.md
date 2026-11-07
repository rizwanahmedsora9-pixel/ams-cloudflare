# Docs index

**Read this first, then `AGENTS.md`.** The root of the repo is now code + one
README. Everything written *about* the code lives here, in three folders.

| Folder | What belongs there | Read it when |
|---|---|---|
| [`specs/`](specs/) | The full functional contract of the app | You are rebuilding, or need exact business rules |
| [`plans/`](plans/) | Forward-looking design for modules not fully done | You are implementing something in that area |
| [`history/`](history/) | Session reports from dated work. **Never** a description of the current state | You need the "why" behind past commits |
| [`../README.md`](../README.md) | How to run, test, deploy | You are new or setting up |

---

## specs/ — the contract

| File | Size | What it is |
|---|---|---|
| [`specs/AMS_COMPLETE_REBUILD_SPECIFICATION.md`](specs/AMS_COMPLETE_REBUILD_SPECIFICATION.md) | ~3,300 lines | Reverse-engineered rebuild spec: data model, global rules, per-module workflows, URL map, data dictionary. **Dated 2026-10-31** — verify against code before trusting a detail. |

## plans/ — forward-looking design

| File | Topic | Status |
|---|---|---|
| [`plans/GRN_LANDED_COST_PAYMENTS_PLAN.md`](plans/GRN_LANDED_COST_PAYMENTS_PLAN.md) | GRN landed cost, multi-GRN costing, supplier payments | Largely implemented — verify in code |
| [`plans/DAILY_RECON_REAL_ACCOUNT_POSTING_PLAN.md`](plans/DAILY_RECON_REAL_ACCOUNT_POSTING_PLAN.md) | Daily reconciliation posting against real accounts | Implemented (`app/services/recon_counter.py`) |
| [`plans/ACCOUNTING_MASTER_PLAN.md`](plans/ACCOUNTING_MASTER_PLAN.md) | Chart of accounts / posting architecture | Partly implemented |
| [`plans/SERVICES_PLAN.md`](plans/SERVICES_PLAN.md) | Services vs materials, rent-name handling, invariants (§12, §15) | Implemented; `tests/test_services_master.py` locks it |
| [`plans/GRN_SUPPLIER_SHIFT_PLAN.md`](plans/GRN_SUPPLIER_SHIFT_PLAN.md) | Moving a whole supplier ledger | Implemented (see README) |
| [`plans/rent_solution.md`](plans/rent_solution.md) | Rental item revenue / delivery rent cost | Implemented |

## history/ — dated reports, not current truth

Twelve session reports from October–November 2026. They were accurate *when
written*. Several describe fixes that are now in code and covered by tests:

`AUDIT_REPORT.md`, `AUDIT_SEQUENCE_REPORT.md`, `FIXING_PLAN.md`,
`FIFO_LIVE_RECONCILIATION_REPORT.md`, `GRN_COSTS_TAB_REPORT.md`,
`GRN_PAYMENTS_AND_WIPE_E2E_REPORT.md`, `GRN_PROFIT_E2E_FIX_REPORT.md`,
`GRN_REDESIGN_IMPLEMENTATION_REPORT.md`, `MULTI_GRN_COSTING_FIX_REPORT.md`,
`PAY_GRN_EXPENSES_IN_MODAL_REPORT.md`, `PAY_GRN_EXPENSES_REPORT.md`,
`PROFIT_GRN_IMPLEMENTATION_REPORT.md`.

> **Do not treat any paragraph in `history/` as a bug report against today's
> tree.** If a defect still exists, reproduce it against the code and file a
> pytest, not a new markdown essay.

---

## Conventions that keep docs cheap

1. **One fact, one place.** Current behaviour goes in `README.md` or code
   docstrings. A new dated report goes in `history/` and is never edited later.
2. **No new root-level markdown.** Root holds `README.md` only.
3. **A plan that ships becomes history.** When the code lands, move the plan to
   `history/` in the same change.
4. **Prefer code over prose.** A docstring next to the rule beats a paragraph in
   a 3,000-line spec, because the compiler keeps it honest.
