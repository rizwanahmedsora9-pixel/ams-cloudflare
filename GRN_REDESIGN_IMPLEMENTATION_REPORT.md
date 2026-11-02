# AMS FBM — GRN / Purchase Cost / Payments / Accounts / Cash Flow Redesign
## PHASE 2 — IMPLEMENTATION REPORT

**Date:** 2026-11-02 · **Branch:** `arena/b00d6ff6-git-recovered`
**Approved design:** `GRN_LANDED_COST_PAYMENTS_PLAN.md` (Phase 1)
**Approval amendments (owner):** A1 / A2 at the top of that plan.

---

## 1. The two binding rules, as built

| Rule | Implementation |
|---|---|
| **A1 — GRN NEVER pays; pay only from Accounts** | `/grn` (add) and `/edit_grn/<id>` (edit) no longer contain or accept `paid_amount`, `payment_type`, `payment_account_id` or bank fields. They create **zero** `SupplierPayment`, **zero** `AccountTransaction` and **zero** `CashFlowEntry`. `GRN.paid_amount` stays 0 for all new documents. All money is posted from **Accounts → PAY EXISTING GRN** (`/accounts/grn_payments`) and from the "Make New Transaction" modal's new `grn_payment` target, which redirects to that one page. A charge's `Paid / Unpaid / Not Applicable` selector is **display-only** (`declared_status`); it never settles an obligation. Actual Paid / Remaining / status are derived only from Accounts payment rows. |
| **A2 — Supplier Ledger = material qty × rate, nothing else** | `financial_ledgers._supplier_rows`, `build_supplier_payable_overview`, `build_supplier_payable_summaries`, `ledgers._build_supplier_ledger_rows`, `supplier_ledger_shift._grn_total`, `/api/supplier_balance`, Accounts KPIs/dashboard/receipts and `tools/predator_truth_engine.py` all use `Σ(grn_item.qty × price_at_time)` as the **only** supplier credit. Freight, loading, unloading, transport, other charges, tax, discount and adjustment never enter it. Payments to transporters/labour/other recipients are excluded by `recipient_type` / `payment_kind`, even though `SupplierPayment.supplier_id` stays populated as a NOT NULL context FK. Charges cannot be assigned to the supplier at all. |

---

## 2. End-to-end behaviour (your example, verified by tests)

100 bags cement @ 1,500 = **150,000**; vehicle fare **5,000**; loading **1,000**; other **500**.

| Stage | Result |
|---|---|
| Save GRN, pay nobody | Supplier Ledger credit **150,000**; transporter payable 5,000; labour 1,000; other 500; `landed_cost_total` **156,500**; `GRNItem.landed_unit_cost` **1,565**; **0** cash rows; Cash Flow shows nothing. |
| Pay vehicle 5,000 (Cash) | 1 `AccountTransaction` of 5,000 out, attributed to *Rana Transport / GRN Payments*. Supplier payable **still 150,000**; transporter payable **0**; Supplier Ledger has **no** payment row. |
| Pay supplier 50,000, later 100,000 | Two separate dated cash-out rows; Supplier Ledger debits 150,000 → **0 payable**; payment history shows 2 vouchers. |
| Pay loading 1,000 | One more cash-out row; labour payable 0; other charge 500 still payable. |
| Totals | Cash Flow GRN outs = **156,000** across 4 rows of 1,000 / 5,000 / 50,000 / 100,000 — **never** a single 156,000/156,500 row at receipt. Total cash actually paid = 156,000; remaining = 500. Inventory (if unsold) valued at 100 × 1,565 = 156,500; COGS on sale uses 1,565, not 1,500. |

Payment status **never** changes the 1,565 rate. Paid and unpaid charges are both in the landed cost when they are material-related.

---

## 3. What was built

### 3.1 New / extended data structures (one new table only)

| Object | Change |
|---|---|
| **`grn_charge` (NEW)** | The only new table: `charge_type`, `label`, `amount` + `amount_minor` (authoritative paisa), `recipient_type`, `recipient_party_id`, `recipient_name`, `declared_status` (display only), `cost_treatment` (`INVENTORY` / `EXPENSE` / `NON_MATERIAL` / `UNTRACKED_LEGACY`), `allocation_basis`, `allocation_json`, `is_void`, `is_legacy_mirror`, `legacy_column`, audit columns. |
| `grn` | `costing_mode` (`LANDED`/`LEGACY`), supplier material / capitalised / landed / expense totals (+ `_minor`), allocation default, `revision`, audit fields, `is_cancelled` / `cancelled_at` / `cancelled_by` / `cancel_reason`, `charges` relationship. Legacy charge/tax/discount/payment columns kept as compatibility mirrors only. |
| `grn_item` | `base_rate_minor`, `allocated_charges_minor`, `line_landed_cost_minor`, `landed_unit_cost`, `landed_unit_cost_minor`, `allocation_basis`, cost-revision audit fields. `price_at_time` is never overwritten. |
| `supplier_payment` | `grn_id`, `grn_charge_id`, `recipient_type`, `recipient_party_id`, `recipient_name`, `payment_kind`, `cash_posted`, `reference`. Still the **one** payment table. |
| `cash_flow_party` | `party_role`, `is_payee_active`, `opening_balance(+_date)`, `created_by` — reused as the recipient master, no new party table. |
| `account_transaction` | `grn_id`, `party_type`, `party_id`, `party_name` for Cash Flow attribution. |
| `app/migrations/0003_grn_landed_cost_and_payments.sql` | Additive, idempotent, non-destructive. Creates `grn_charge` for the deploy runner, adds indexes, marks all existing GRNs `LEGACY`, backfills their supplier material totals and lot rates, backfills legacy charges as `UNTRACKED_LEGACY` unassigned obligations, classifies existing payments, and backfills `grn_id`/`cash_posted`/account-transaction attribution. No table rebuild; no historical money row rewritten. |

### 3.2 New services (logic, not duplicate systems)

* `app/services/grn_costing.py` — **single arithmetic authority**: `grn_breakdown()`, `recompute_landed_costs()`, `lot_cost_rate()`, `sync_charges_from_form()`, `mirror_legacy_charge_columns()`, `calculate_grn_total()` compatibility wrapper, `get_or_create_party()`.
  * Charges default to `INVENTORY` and are allocated to GRN lots in **exact paisa by line value** (`app/services/pricing.py::allocate_cents`); `QUANTITY` and `MANUAL` bases are supported. `EXPENSE` charges are never allocated. `Σ line landed costs = supplier material + capitalised charges`, always.
  * `Paid / Unpaid` never affects the rate; `NOT_APPLICABLE` removes a charge entirely.
* `app/services/grn_payments.py` — `save_grn_payment()`, `void_grn_payment()`, `restore_grn_payment()`, `grn_payment_obligations()`, `grn_payment_integrity()`. Validates obligation, remaining payable, method/account, balance, period lock, future date, idempotency and optimistic revision. One payment = one `SupplierPayment` + exactly one `AccountTransaction` (`GRN Payment`) + one `AccountingAuditLog`.
* `app/services/grn_cancel.py` — soft cancellation with quantity reversal, preserved payments/lots/charges, audit rows; refuses to cancel a GRN with locked (sold) lots or active Accounts payments.
* `app/services/accounting.py::_sync_linked_grn_payment_tx()` — convergence helper following the existing `_sync_linked_supplier_payment_tx` pattern (void-and-recreate, never duplicate).

### 3.3 GRN screens

* `templates/grn_wizard.html`: Step 1 payment/bank fields replaced with a "GRN never pays — pay from Accounts" notice; Expenses tab replaced with a **charge line grid** (type, label, amount, recipient type, recipient/person, declared status, cost treatment, allocation basis, add/remove); live totals strip (Supplier Material / Capitalised Charges / Total Actual Cost / Avg Actual Rate); records table gained Actual Cost, Cash Paid and Payment Status columns; expandable row gained a **Cost & Payments** panel with every obligation (original/paid/remaining/status), payment history and a "Pay this GRN" button. Tax/discount/adjustment are labelled memo-only.
* `/grn` and `/edit_grn/<id>` persist charge rows, recompute landed costs, preserve locked-lot rules, and refuse to change a charge that already has Accounts payments.
* `view_bill.html` and the printable GRN now show the full cost/obligation/payment breakdown.

### 3.4 Accounts & payments

* New page `/accounts/grn_payments` — select GRN → see all obligations with Original / Already Paid / Remaining / Status → select recipient → amount → Cash/Bank → account → date → reference → save. Full, partial and repeated payments supported; payment history with void/restore.
* New `pay_target='grn_payment'` in the existing "Make New Transaction" modal; it redirects to the same wizard (no second payment implementation).
* `/accounts/purchase_payables` — outstanding supplier + transporter/labour/other payables, plus an explicit "unassigned legacy charges" bucket.
* `/party_ledger/<id>` — transporter / labour / other recipient ledger reusing `financial_ledger.html` and the same read-only projection contract.
* `/api/grn_obligations/<grn_id>` — JSON obligations + payment history.
* Sidebar, permission map and bill namespace `GP` registered.

### 3.5 Ledgers, cash flow, inventory, P&L

* **Supplier Ledger clean (A2)** in every projection, PDF/CSV export, KPI/dashboard/receipts, supplier-ledger shift preview and the independent truth engine. Shift now excludes non-supplier payments and GRN payee parties.
* **Cash Flow** derives from `AccountTransaction` as before; added `GRN Payment` source/section labels, recipient (`party_name`) and `grn_id` on each row. `GRN Payment` is explicitly excluded from P&L expenses and from the cash-based expenditures list. `cash_day_recon` and reconciliations pick it up automatically.
* **Inventory / FIFO / P&L**: `lot_cost_rate()` is now used by `sales_core.py` (`_cost_rate_for_material`, `_cost_rate_for_grn_item`, FIFO lots, sale posting), `profit_loss.py` (purchase rates, lot layers, allocation fallbacks, booking/delivery costing), and `grn_consumption.py` (received/consumed/remaining value). Each `GRNItem` keeps its own landed rate; frozen `GRNAllocation.cost_rate` and `DirectSaleItem.cost_rate_at_sale` are never rewritten.
* **No double counting**: `INVENTORY` charges never become expenses; `EXPENSE` charges are accrued once in P&L from `GRNCharge` rows (even unpaid), shown separately on the Expenditures page, and excluded from inventory valuation.
* **Outstanding payables / General Accounts**: account balances, reconciliations, integrity audit (`grn_payment_integrity`) and the new purchase-payables projection stay consistent.

### 3.6 Editing, cancellation, historical safety

* GRN delete is now a **soft cancel** (voids quantities via `Entry.is_void`, rebuilds `Material.total`, keeps GRN/lots/charges/payments and writes audit rows). Purging via `hard_delete_transaction('GRN')` or hard-deleting a supplier refuses when Accounts payments exist and cascades `grn_charge` rows.
* Wipe routines (`app/services/wipe.py`, `_wipe_delete_selected_data.py`) include `grn_charge` in child-before-parent order.
* Legacy GRNs stay `LEGACY`: their FIFO cost remains `price_at_time`, so historical P&L/COGS is unchanged. Their old charges are visible as unassigned party obligations, not supplier payables.
* Supplier ledger shift previews/report the exclusion of transporter payments and payee parties.

### 3.7 Import / export / truth engine / docs

* New `GRNCharges` Excel sheet in master export/import (`export_build.py`, `engine.py`, `sheets_master_supply.py`, `_common.py`). `full_db_sync` snapshots the raw SQLite DB, so `grn_charge` is included automatically.
* `tools/predator_truth_engine.py` supplier-payable truth updated to A2 and excludes charge payments by `recipient_type` / `payment_kind`.
* `README.md` and `app/migrations/README.md` document the new workflow and migration 0003.

---

## 4. Verification

**Full test suite: `474 passed, 6 skipped, 11 subtests passed` in 25m 22s** (`python -m pytest -q`).

New regression suites:

* `tests/test_grn_landed_cost_payments.py` (6 tests) — receiving never pays, exact 1,565 landed rate, clean supplier ledger, vehicle → supplier → loading payments, Cash Flow 4 separate rows, expense charges excluded from inventory, overpayment blocked, void/reverse, cancel preserves history, legacy backfill, modal redirect.
* `tests/test_grn_landed_cost_advanced.py` (6 tests) — multi-material value allocation (3,000 / 4,000 of a 7,000 charge; exact 357,000), FIFO keeps each GRN's own rate (1,550 then 1,600), one P&L expense row for an `EXPENSE` charge, charge edit blocked after payment, cancellation blocked with active payments, supplier shift does not move transporter payments.

Existing suites updated for the new contract (not weakened): `test_full_cycle_smoke.py` now posts the part payment from Accounts; `test_grn_edit_form_null_fields.py` no longer expects removed payment/bank inputs; `test_grn_screen_layout.py` expects the 3 new columns; `test_sidebar_navigation.py` includes "PAY EXISTING GRN".

All major pages were smoke-tested (HTTP 200): `/grn`, `/edit_grn/<id>`, `/accounts/grn_payments`, `/accounts/purchase_payables`, `/party_ledger/<id>`, `/view_bill/<bill>`, `/download_invoice/<bill>`, `/cash_flow`, `/accounts/`.

---

## 5. Conflicts handled

| Conflict | Resolution |
|---|---|
| `calculate_grn_total()` used as document total, supplier payable and cost | Split into `grn_breakdown()`; `calculate_grn_total()` is now a thin compatibility wrapper. All consumers updated. |
| `grn.paid_amount` auto-created a supplier `SupplierPayment` on every save/edit | Disabled for `LANDED` (and inside `_sync_grn_auto_supplier_payment`); kept only for pre-existing `LEGACY` edits. All legacy KPI fallbacks are gated on `costing_mode='LEGACY'`. |
| `SupplierPayment.supplier_id` NOT NULL (SQLite cannot relax it) | Kept as a context FK; `recipient_type` / `payment_kind` are the sole authority for ledger ownership. No destructive migration. |
| Frozen sale costs (`GRNAllocation.cost_rate`, `cost_rate_at_sale`) | Never rewritten; only new allocations and `LANDED` lots use the landed rate. |
| P&L expenses were cash-based | `EXPENSE` charges accrued once at receipt; `GRN Payment` transactions skipped in the expense scan. |
| Hard-delete GRN destroyed payment history | Soft cancel + purge guards + `grn_charge` cascade. |
| Supplier shift moved everything with `supplier_id` | Non-supplier payments and payee parties excluded from query, preview, shift and reclaim. |
| Two stock truths (`Entry`/`Material.total` vs GRN lots) | Redesign changes **value only**; quantity paths untouched. |
| `current_payables` is client receivables | Left alone; new `build_purchase_payables()` projection + dedicated page. |
| `ACCOUNTING_MASTER_PLAN.md` proposes a whole GL/journal rebuild | **Not adopted** — that remains a separate, unbuilt proposal; this work extends existing structures as requested. |

---

## 6. Known limitations / suggested follow-ups

1. **Historical reclassification tool (plan §12.3)**: legacy charges are backfilled as `UNTRACKED_LEGACY` unassigned obligations and are **not** capitalised into old inventory or recognised as expenses. An opt-in dry-run/apply tool to reclassify them (and to revalue only *remaining* unsold lot quantities) was intentionally not run, to avoid rewriting history without your explicit go-ahead.
2. **Cancellation with active payments**: currently blocked with a clear message. A guided refund / reallocate-as-advance workflow can be added next.
3. **MANUAL allocation basis** is supported in the service and validated server-side, but the wizard exposes only `VALUE` / `QUANTITY`; a per-line manual allocation editor can be added if you need it.
4. **Party opening balances / party PDF statement**: `CashFlowParty.opening_balance` exists and the party ledger reuses the shared template, but there is no opening-balance form or dedicated party PDF yet (HTML/print is available).
5. **`dummy_data/generate_dummy_data.py`** still seeds `LEGACY` GRNs with flat charge columns; those are migrated on boot. It can be updated to seed `LANDED` charge rows if demo data should exercise the new grid.
6. **Front-end DOM tests** (`tests/frontend/*.js`) are not run by pytest; the wizard markup changed, so re-run that JS suite in its own runner if it is part of your release gate.
7. `templates/accounts/receipts.html` still lists only GRNs with a legacy `paid_amount > 0`; new GRN payments appear in Cash Flow, GRN detail, payment history and KPIs derived from `SupplierPayment`. Extending that legacy "Receipts" page to list `GRN_PAYMENT` vouchers is a small cosmetic follow-up.

---

## 7. Manual verification recipe

1. Create a cash account with a balance, a supplier and a material.
2. **GRN** → select supplier, add 100 bags @ 1,500, add charge rows: Vehicle Fare 5,000 (Rana Transport), Loading 1,000 (Loading Team), Other 500 (Misc Party). Save. Note "Total Actual Cost 156,500 / Avg 1,565" and **Cash Paid 0.00**.
3. Open the Supplier Ledger → **150,000** payable only.
4. **Accounts → PAY EXISTING GRN** → select the GRN → pay the Vehicle charge 5,000 → verify supplier still 150,000 and Cash Flow has one 5,000 out attributed to Rana Transport.
5. Pay supplier 50,000, then 100,000 on a later voucher; pay loading 1,000. Verify payment history, remaining 500, and Cash Flow's four separate rows.
6. Sell/deliver some stock and open Profit Reports → COGS uses 1,565/bag (or the exact per-lot landed rate for multi-material GRNs), with no separate freight expense.
7. Try to change a paid charge on the GRN → refused with "already has payments"; try to cancel a GRN with payments → refused; void a payment → cash and balances reverse, history preserved.
