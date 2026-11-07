# AMS FBM — Complete GRN / Purchase Cost / Payments / Accounts / Cash Flow Redesign

## PHASE 1 — ANALYSIS AND IMPLEMENTATION PLAN ONLY

**Status:** Phase 1 plan **APPROVED 2026-11-02** with the two binding amendments below; **Phase 2 IMPLEMENTED 2026-11-02** (see `GRN_REDESIGN_IMPLEMENTATION_REPORT.md`).
**Phase 1 produced no application code changes** — only this document.
**Date:** 2026-11-02 · **Branch:** `arena/b00d6ff6-git-recovered` · **Repo:** `rizwanahmedsora9-pixel/git-recovered`
**Instruction honoured:** I inspected the existing application first and thought the accounting logic through before proposing any change. Implementation (Phase 2) will start **only after you approve this plan**.

---

## ✅ APPROVED AMENDMENTS (owner, 2026-11-02) — binding, supersede the text below

> **A1 — GRN NEVER pays.** A GRN records *only*: material received, purchase costs,
> charge details, and the resulting payment obligations. **No payment row, no
> settlement row, no cash/bank account, no `paid_amount`, no
> `AccountTransaction` and no "paid outside Accounts" document is ever created
> by a GRN (add or edit).** Every payment is made **only from Accounts → PAY
> EXISTING GRN**. A charge's `Paid / Unpaid / Not Applicable` selector is an
> **informational declaration only**; it never settles an obligation and never
> changes a balance. Actual Paid / Remaining / status are derived **exclusively**
> from payment rows posted in Accounts.
>
> **A2 — Supplier Ledger is EXACTLY material qty × purchase rate.** The supplier
> ledger credit for a GRN is `Σ(grn_item.qty × grn_item.price_at_time)` and
> **nothing else**: no vehicle fare, loading, unloading, transport, other
> charges, **no tax, no discount, no adjustment**. Supplier debits are only
> payments whose recipient is that supplier. A payment to a vehicle person,
> labourer or any other recipient must never appear in the supplier ledger.
> Charges **cannot** be assigned to the supplier as recipient; they always
> create their own party payable.
>
> Consequences, applied throughout Phase 2:
> * `supplier_material_amount = Σ(qty × price_at_time)` (gross, unrounded to paisa).
> * `landed_cost_total = supplier_material_amount + Σ(INVENTORY charges)`.
>   Legacy `tax_amount`, `discount`, `adjustment_amount` remain on the GRN
>   document as memo fields only — they are **not** posted to any party ledger
>   and **not** capitalised into inventory for `LANDED` GRNs.
> * D2, D3 and D5 in §16 are **resolved**: no inline/outside-accounts payment,
>   no supplier recipient for charges, no tax in supplier payable.
> * Remove `GRN_CHARGE_SETTLED_EXTERNAL` and any `SUPPLIER` value from
>   `grn_charge.recipient_type`; `initial_payment_status` is renamed
>   `declared_status` and is display-only.
> * The clean rule applies to **all** GRNs, including historical ones. It is a
>   read-side projection change only: no historical source row, payment, cash
>   row or frozen sale cost is rewritten. Legacy charges are backfilled into
>   `grn_charge` as their own party obligations, so total purchase payables stay
>   correct. This is disclosed in the implementation report.
>
> **A3 — "Pay supplier" and "pay GRN expenses" are two separate payables
> (owner, 2026-11-04).** A GRN has *one stock payable* (`Σ qty × rate`, paid to
> the supplier) and, separately, *the GRN expenses that were ticked "add to
> supplier ledger"*. Paying one must never settle the other, and each carries
> its own amount, paid figure and remaining balance. The GRN screen shows them
> as two boxes, each with its own **Pay full**. Expenses that were **not**
> ticked are never part of the supplier balance at all — they are payable to
> their own recipient (vehicle owner, labour team, other) from **PAY EXISTING
> GRN**. Implemented as `MATERIAL:<grn_id>` and `EXPENSES:<grn_id>` obligation
> keys in `app/services/grn_costing.py`, with `SupplierPayment.payment_kind`
> `GRN_MATERIAL` / `GRN_EXPENSES` (plus one `AccountTransaction` each), and the
> new **Accounts → PAY GRN (STOCK / EXPENSES)** screen at `/accounts/pay_grn`.
> The legacy lumped key `SUPPLIER:<grn_id>` still works: the amount is split
> stock-first, then supplier-billed expenses, posted as separate vouchers.

---

---

## 0. What I inspected

| Area | Files read (main ones) |
|---|---|
| GRN models | `models/stock.py` (`GRN`, `GRNItem`, `Entry`), `models/sales.py` (`GRNAllocation`, `DirectSaleItem`) |
| GRN routes / services | `app/blueprints/ops/grn.py`, `app/blueprints/misc/pending.py` (`edit_grn`, `export_grn`), `app/services/grn_svc.py` |
| Inventory / FIFO | `app/services/sales_core.py`, `app/services/grn_consumption.py`, `app/services/allocation_integrity.py` |
| Supplier ledger | `app/services/financial_ledgers.py`, `app/services/ledgers.py`, `app/blueprints/misc/suppliers.py`, `app/services/supplier_ledger_shift.py`, `app/services/supplier_ledger_pdf.py` |
| Accounts / payments | `blueprints/accounts/{payments,transactions,kpis,dashboard,helpers}.py`, `app/services/payments_crud.py`, `app/services/accounting.py`, `models/cash.py`, `models/parties.py` |
| Cash flow | `app/services/cash_flow_svc.py`, `app/blueprints/reports/cash.py`, `cash_flow_reconciliation_helpers.py`, `app/services/cash_day_recon.py` |
| Expenses / P&L | `app/services/profit_loss.py` (3007 lines), `app/services/profit_loss_breakdown.py`, `app/blueprints/reports/_profit_*.py` |
| Booking / delivery costing | `app/services/sales_core.py`, `app/blueprints/ops/_dispatch_*.py`, `app/services/billing.py` |
| Schema / migrations | `app/services/schema.py`, `app/services/auto_migrate.py`, `app/migrations/0001_*.sql`, `0002_*.sql`, `README.md` |
| Import / export / wipe | `blueprints/import_export/{sheets_master_supply,export_build,engine}.py`, `app/services/wipe.py`, `full_db_sync/engine.py` |
| Independent truth engine | `tools/predator_truth_engine.py` |
| Existing tests | `tests/test_grn_*.py`, `tests/test_supplier_ledger_*.py`, `tests/test_profit_loss_*.py`, `tests/test_predator_regressions.py`, `tests/test_fifo_grn_profit_realtime.py`, `tests/conftest.py` |
| Earlier design docs | `ACCOUNTING_MASTER_PLAN.md`, `AMS_COMPLETE_REBUILD_SPECIFICATION.md`, `FIXING_PLAN.md`, `MULTI_GRN_COSTING_FIX_REPORT.md`, `PROFIT_GRN_IMPLEMENTATION_REPORT.md`, `FIFO_LIVE_RECONCILIATION_REPORT.md`, `GRN_SUPPLIER_SHIFT_PLAN.md` |

---

# 1. Current system architecture and existing workflow

## 1.1 Stack and shape

* Flask + Flask‑SQLAlchemy on **SQLite**, single tenant DB (`app/__init__.py::create_app`), `db.create_all()` → `_ensure_model_columns()` → numbered SQL migrations (`app/services/auto_migrate.py`).
* Two blueprint trees: `app/blueprints/*` (registered explicitly in the factory) and `blueprints/*` (auto‑discovered by `utils/module_loader.py`). Split packages are stitched together by `utils/pkg_wire.py::wire_package`, so a new route file must be imported from the package `__init__.py`.
* Jinja templates in `templates/`, JS in `static/`. CSRF is enforced on **every** mutating request (`app/hooks.py::_protect_against_csrf`).
* Money is mostly `db.Float`; the newer accounting tables keep an authoritative integer minor‑unit mirror (`*_minor`) with `utils/money.py::{to_minor,from_minor,sync_money_fields}` and `app/services/pricing.py::allocate_cents` (largest‑remainder, exact paisa).
* There is **no double‑entry journal, no GL, no chart of accounts**. `AccountTransaction` is a *cash movement* between accounts; every financial report is a **read‑time projection** over source documents. `ACCOUNTING_MASTER_PLAN.md` proposes a full journal rebuild (§6, §22) but explicitly says it is **still a proposal, not built**. This plan deliberately does **not** adopt that rebuild: it extends the existing structures, as you requested.

## 1.2 Existing data model (relevant tables)

| Table | Key columns | Role today |
|---|---|---|
| `grn` | `supplier_id`, `supplier`, `manual_bill_no`, `auto_bill_no`, `loading_cost`, `freight_cost`, `other_expense`, `adjustment_amount`, `discount`, `tax_percent/amount/type`, **`paid_amount`**, `payment_type`, `payment_account_id`, `bank_name/account_name/account_no`, `date_posted`, `is_void`, `note` (`models/stock.py:33`) | One receipt header. Charges are **3 flat scalar columns** — no recipient, no per‑charge status, no per‑charge cost treatment. |
| `grn_item` | `grn_id`, `mat_name`, `qty`, **`price_at_time`**, `is_void`, `is_locked` (`models/stock.py:67`) | One FIFO lot. `price_at_time` is the **supplier rate only** and is the only cost rate used anywhere. |
| `entry` | `type IN/OUT`, `material`, `qty`, `auto_bill_no`, `date/time` | Quantity stock ledger; feeds `Material.total` and stock summary. |
| `grn_allocation` | `sale_id`, `sale_item_id`, `grn_item_id`, `qty`, **`cost_rate`**, `is_void` (`models/sales.py:276`) | Frozen FIFO consumption layer; `cost_rate` is copied from `grn_item.price_at_time` at sale posting. |
| `direct_sale_item` | `cost_rate_at_sale`, `grn_item_id`, `price_at_time`, `discount*` | Frozen cost on the sale line. |
| `supplier` | `opening_balance`, `opening_balance_date`, `transferred_to_id` | Supplier master. |
| `supplier_payment` | `supplier_id` **NOT NULL**, `amount`, `amount_minor`, `method`, `payment_type`, `source_type`, `source_id`, `date_posted`, `payment_account_id`, `is_void`, `idempotency_key(unique)`, `revision` (`models/parties.py:48`) | The **single** payment table for purchases. No GRN FK, no charge FK, no recipient dimension. |
| `account` | `balance`, `balance_minor`, `category cash/bank`, `linked_entity_type`, `linked_supplier_id`, `linked_party_name`, classification columns | Cash/bank/wallet record. |
| `account_transaction` | `from/to_account_id`, `amount`, `amount_minor`, `transaction_type`, `source_type`, `source_id`, `note`, `is_void`, `idempotency_key` (`models/cash.py:88`) | **The authoritative cash movement.** Cash Flow, account balances, reconciliations, daily board and expenditures all derive from it. |
| `cash_flow_entry` | `direction`, `amount`, `account_id`, `party_id`, `party_name`, `account_tx_id`, `source_type/id`, `is_void` | Manual cash‑flow rows only; system rows are *derived* from `AccountTransaction`. |
| `cash_flow_party` | `name`, `party_type`, `phone`, `is_active` (`models/cash.py:184`) | Existing reusable party master for non‑client/non‑supplier names. |
| `fbm_cash_drawer_entry` | `entry_type`, `amount`, `category`, `method` | Manual expense rows (P&L "Cash Drawer Expense"). |
| `account_reconciliation`, `cash_day_*`, `cash_flow_difference_adjustment` | — | Period locks / daily reconciliation. `_assert_period_open()` (`app/services/payments_crud.py:144`) blocks financial edits inside a finalised period. |

## 1.3 Existing GRN workflow

1. **Add** — `POST /grn` (`app/blueprints/ops/grn.py:26`):
   * supplier (auto‑created if unknown), manual/auto bill, date/time override via `parse_grn_datetime`.
   * item lines `mat_name[]`, `qty[]`, `price[]` → `GRNItem(qty, price_at_time)`; each line also writes an `Entry(type='IN')` and increments `Material.total`.
   * three flat charges `loading_cost`, `freight_cost`, `other_expense`, plus `adjustment_amount`, `discount`, `tax_amount`.
   * **`paid_amount` + `payment_type` + `payment_account_id`** are on the *same form* (Step 1 / Bill Details tab). If `paid_amount > 0` and method is Cash/Bank, a payment account is **mandatory** and must have sufficient balance.
   * `_sync_grn_auto_supplier_payment(new_grn)` (`app/services/grn_svc.py:136`) then creates **one** `SupplierPayment` to the GRN's supplier with marker `[AUTO_GRN_PAY:<grn.id>]`, and `_sync_supplier_payment_accounting()` (`app/services/accounting.py:545`) creates **one** `AccountTransaction` of type `Supplier Payment` with marker `[SRC:SupplierPayment:<id>]` — this is the *only* cash movement a GRN generates.
2. **Edit** — `POST /edit_grn/<id>` (`app/blueprints/misc/pending.py:184`): reverses `Material.total`, deletes+rebuilds all `GRNItem` and `Entry(IN)` rows (preserving item IDs for locked lots), rewrites header fields, and re‑runs `_sync_grn_auto_supplier_payment()`. If any lot is locked by a sale (`_grn_has_locked_lots`), only header‑only edits are allowed (`_grn_submitted_item_lines_unchanged`).
3. **Delete / cancel** — `POST /grn action=delete` → `hard_delete_transaction('GRN', id)` (`app/services/void_rebuild.py:651`): physically deletes GRN, its items, allocations, `Entry(IN)` rows **and the auto `SupplierPayment`**; blocked when lots are locked.
4. **View** — `/view_bill` and `/download_invoice` set `grn.amount = calculate_grn_total(grn) + grn.discount` (`app/blueprints/sales/_bills_view_bill.py:303`, `_bills_download_invoice.py:276`).

## 1.4 Purchase total and costing today

```python
# app/services/grn_svc.py:92
def calculate_grn_total(grn):
    item_total = sum(qty * price_at_time for active items)
    expenses   = loading_cost + freight_cost + other_expense
    return item_total + expenses + tax_amount - discount + adjustment_amount
```

That single number is used for **six different purposes**: GRN document total, supplier ledger credit, supplier payable overview, supplier‑ledger‑shift preview, Accounts "Receipts" GRN total, and printed bill amount.

**Inventory costing ignores those charges completely.** Every cost source reads `GRNItem.price_at_time` only:

* `app/services/sales_core.py:92 _cost_rate_for_material`, `:156 _cost_rate_for_grn_item`, `:215 _grn_fifo_lots_for_material`, `:405 _apply_grn_allocations_for_sale` (writes `GRNAllocation.cost_rate` / `DirectSaleItem.cost_rate_at_sale`).
* `app/services/profit_loss.py:451 purchase_rates`, `:785 lot rate`, `:755/:913/:1379 fallback rate` (FIFO replay, frozen allocations, delivery/booking costing, returns).
* `app/services/grn_consumption.py:217`, `:769`, `:843` (GRN consumption indicator, "remaining value" = qty × `price_at_time`).

`app/services/profit_loss.py:2845` **explicitly discloses** this: *"GRN loading, freight, tax and other landed‑cost fields are not allocated into the existing FIFO unit-cost records, so they are not silently expensed or added to COGS here."* FIFO itself is sound: each lot keeps its own rate, oldest first (`profit_loss.py:_Projection`, `FIFO_LIVE_RECONCILIATION_REPORT.md`), and a sale spanning two GRNs produces two cost layers.

## 1.5 Payables / ledgers today

* `app/services/financial_ledgers.py:1239 _supplier_rows()` builds the supplier ledger: **credit = `calculate_grn_total(grn)`** (i.e. includes freight/loading/other/tax − discount + adjustment), debit = every non‑void `SupplierPayment` for that supplier; legacy `grn.paid_amount` is added as a synthetic debit only when no auto payment row exists (`:1291`).
* `:1365 build_supplier_payable_overview` and `:1466 build_supplier_payable_summaries` repeat the same formula; `app/services/ledgers.py:616 _build_supplier_ledger_rows` is a **second** implementation used by PDF/legacy views; `app/services/supplier_ledger_shift.py:312 _grn_total` is a **third** copy.
* `/api/supplier_balance/<id>` (`app/blueprints/api.py:426`) and Accounts dashboard/KPIs (`blueprints/accounts/{helpers,dashboard,kpis}.py`) all consume those projections.
* `build_current_payables()` (`:1063`) is **client receivables**, not supplier payables — despite the name. There is currently **no** "outstanding purchase payables" report for transporters/other parties.

## 1.6 Accounts, expenses and cash flow today

* Cash Flow is a **derivation over `AccountTransaction`** (`app/services/cash_flow_svc.py:1341 collect_cash_flow_rows`): only rows whose `from/to_account_id` is a cash/bank account appear; `direction=out` when money leaves. A GRN with `paid_amount=0` produces **zero** cash‑flow rows — that part of your requirement is already satisfied.
* `section_label` / `CF_SOURCE_LABELS` / `_CF_SECTION_BY_SOURCE` (`:245–330`) attribute each row to the screen it came from; `grn` is a recognised section.
* `Account.balance_minor` is moved by `_apply_account_tx_effect` / `_reverse_account_tx_effect` (`app/services/accounting.py:120–160`); the `* _sync_linked_*_tx` helpers keep **exactly one** money‑out row per payment document (convergence on `[SRC:…]` markers). `financial_integrity_audit()` (`:1617`) flags duplicate `(source_type, source_id, transaction_type)` rows.
* `expenditures` (`blueprints/accounts/payments.py:283`) lists `FbmCashDrawerEntry(out)` plus `AccountTransaction` with type `Expense | Payment | Driver Payment`.
* P&L expenses come from `AccountTransaction` rows of type `Expense`/unlinked `Payment` and `FbmCashDrawerEntry` (`app/services/profit_loss.py:2091–2168`). So today an expense is recognised **only when money moves** — there is no accrued/unpaid purchase expense.
* "Make New Transaction" modal (`templates/accounts/dashboard.html:355`, `blueprints/accounts/transactions.py:180`) has `pay_target` = `company_transfer | supplier | driver | client_refund | loan | personal_expense | other_expense`. There is **no** "Pay existing GRN" option; `pay_target=supplier` calls `save_supplier_payment()` with no GRN linkage.
* `save_supplier_payment()` (`app/services/payments_crud.py:562`) validates supplier, account, balance, future date, period lock, idempotency and revision; `_supplier_payment_source()` (`:197`) treats `[AUTO_GRN_PAY:n]` payments as GRN‑owned and refuses to edit/delete them from Accounts.

## 1.7 Reports / exports / other consumers

`app/blueprints/misc/pending.py:598 export_grn` (Excel), `blueprints/accounts/payments.py:413 receipts`, `blueprints/accounts/kpis.py:51/273`, `blueprints/accounts/dashboard.py:24`, `templates/accounts/receipts.html`, `templates/grn_wizard.html` (JS `updateGrnTotal()` at `:1152` sums **only** item lines − discount), `templates/view_bill.html`, `tools/predator_truth_engine.py:100/823` (independent raw‑SQL GRN truth), `dummy_data/generate_dummy_data.py:436`, `blueprints/import_export/{sheets_master_supply,export_build,engine}.py`, `app/services/wipe.py:457`, `app/services/void_rebuild.py:651/690`, `app/services/supplier_ledger_shift.py`, `app/services/schema.py`, `app/services/constants.py` (permissions & bill namespaces), `app/services/sidebar_nav.py` (nav registry).

## 1.8 Your example traced through today's system

> 100 bags cement: supplier 150,000 · vehicle fare 5,000 · loading 1,000 · other 500 → landed 156,500, i.e. **1,565/bag**. Pay only the vehicle person (5,000).

| What happens today | Result |
|---|---|
| `GRNItem.price_at_time` | 1,500 → **inventory and P&L cost 1,500/bag**, COGS understated by 6,500 |
| Supplier ledger credit (`calculate_grn_total`) | **156,500** → supplier is shown as owed 156,500 although only 150,000 is his invoice |
| `GRN.paid_amount = 5,000` + Cash + account | creates one `SupplierPayment` **to the supplier** for 5,000 → supplier payable shown 151,500; vehicle payable **does not exist** |
| Cash Flow | one 5,000 out — correct amount, but described as a *supplier* payment |
| No transporter/loading ledger | the remaining 1,000 + 500 obligations are invisible |
| P&L | no freight/loading expense, no landed COGS → profit overstated by 6,500 |

This is the exact inconsistency you described, and it comes from **three** separate causes: (a) one flat total used for both payable and cost, (b) a single supplier‑only payment channel, (c) charges never reaching `GRNItem` cost.

---

# 2. Problems and accounting inconsistencies identified

| # | Problem | Evidence | Business effect |
|---|---|---|---|
| P1 | **Payment status is coupled to purchase cost.** `paid_amount` is a GRN header field and the only way to record money at receipt; `calculate_grn_total` is used as both payable and cost. | `models/stock.py:48–55`, `app/services/grn_svc.py:92` | You are forced to decide payment while receiving; unpaid charges are not valued into inventory. |
| P2 | **Landed charges never reach inventory / FIFO / P&L.** All cost lookups use `grn_item.price_at_time`; charges are header scalars. | `sales_core.py:92/156/215/405`, `profit_loss.py:451/785/1379`, `profit_loss.py:2845`, `grn_consumption.py:217/769` | True cost/bag is understated; profit overstated; GRN "remaining value" wrong. |
| P3 | **Supplier ledger is polluted.** It credits `item_total + freight + loading + other + tax − discount + adjustment`. | `financial_ledgers.py:1259/1406`, `ledgers.py:646`, `supplier_ledger_shift.py:313`, `tools/predator_truth_engine.py:100` | Supplier payable shows transporter/labour money; payment to vehicle person wrongly reduces supplier balance. **This is the "clean supplier ledger" issue you called out at the end of your request.** |
| P4 | **Only one payee exists.** `SupplierPayment.supplier_id` is NOT NULL; there is no transporter/labour/other party, no per‑charge linkage. | `models/parties.py:48`, `app/services/payments_crud.py:562` | Rs.5,000 paid to driver is booked against the supplier. |
| P5 | **No partial / multiple / dated payments against one GRN.** `grn.paid_amount` is one scalar; auto payment sync voids/recreates a single row on every edit. | `grn_svc.py:136–190`, `pending.py:240–380` | No payment history, no remaining‑per‑recipient balance. |
| P6 | **GRN delete is a hard delete** that also deletes the payment and its history. | `void_rebuild.py:651–680` | Violates "preserve historical payment records / never silently rewrite history". |
| P7 | **Cash‑flow attribution is wrong** for non‑supplier payments (row labelled `Supplier Payment`), and Accounts "Receipts"/KPIs mix `grn.paid_amount` fallbacks with `calculate_grn_total`. | `cash_flow_svc.py:300/384`, `accounts/payments.py:413–437`, `accounts/kpis.py:51/273`, `accounts/dashboard.py:24`, `accounts/helpers.py:10` | Cash amounts are right but the party/section is wrong; double‑count guards are marker‑based and fragile. |
| P8 | **No accrued expense concept.** Unpaid GRN charges are neither inventory nor expense; P&L only sees cash‑based `AccountTransaction` expenses. | `profit_loss.py:2091–2168`, `blueprints/accounts/payments.py:283` | Unrelated business expenses cannot be separated from landed cost; risk of double counting if both are posted. |
| P9 | **Four different GRN total formulas** (`grn_svc`, `financial_ledgers` ×2, `ledgers.py`, `supplier_ledger_shift.py`, `predator_truth_engine.py`) will diverge the moment one is fixed. | see §1.5/§1.7 | "One connected system" impossible. |
| P10 | **Legacy frozen costs are immutable by design** (`GRNAllocation.cost_rate`, `DirectSaleItem.cost_rate_at_sale`). Any naive revaluation would silently rewrite historical profit. | `sales_core.py:405–430`, `MULTI_GRN_COSTING_FIX_REPORT.md` | Needs an explicit policy, not an in‑place UPDATE. |
| P11 | **Two stock truths** (`Entry`/`Material.total` for quantity, GRN lots for cost) — `FIXING_PLAN.md` P0 already flags this. | `FIXING_PLAN.md:47`, `README.md:147` | A landed‑cost change must not disturb quantity stock. |
| P12 | **Charges have no allocation basis** for multi‑material GRNs; a flat `GRN.total/qty` would be meaningless across different units/materials. | `models/stock.py:33–80` | Need a defensible per‑line allocation. |
| P13 | **No "Outstanding Payables" report for purchase parties**; `current_payables` is client receivables. | `financial_ledgers.py:1063`, `_profit_unpaid_transactions_page.py` | Transporter/loading balances are invisible. |
| P14 | **Import/export/wipe/shift/truth engine are unaware of charges and GRN‑linked payments.** | `sheets_master_supply.py:5`, `export_build.py:180`, `wipe.py:457`, `supplier_ledger_shift.py`, `predator_truth_engine.py:823` | Migration and data‑safety gaps. |

---

# 3. Target accounting model (the rules everything else follows)

> These are **document‑level rules**, not a new GL/journal. The existing `AccountTransaction` remains the single cash truth and `GRNItem`/`GRNAllocation` remain the single FIFO truth.

**R0 — Payment never determines cost.** A GRN's landed cost is computed from *acquisition obligations* (supplier material + all material‑related charges), regardless of Paid/Unpaid status.

**R1 — One obligation per payee.**
* `SUPPLIER_MATERIAL` obligation = **Σ `qty × price_at_time` only (A2)** — no discount, tax, adjustment or charge → **supplier ledger only**.
* One obligation per additional charge (vehicle/transport, loading, unloading, other) → **that charge's recipient ledger only**. A charge can never have the supplier as recipient (A2).
* **HARD RULE (owner, A2):** the Supplier Ledger may contain **only** `Σ(qty × rate)` as credits and supplier‑recipient payments as debits. Freight, loading, unloading, other charges, tax, discount, adjustment and every non‑supplier payment are *never* in it. No exception.

**R2 — Cost treatment is explicit per charge.**
* `INVENTORY` (default for vehicle fare, loading, unloading, transport, material‑related "other"): capitalised into GRN lots → COGS when sold. **No** operating‑expense row now or at payment time.
* `EXPENSE` (unrelated business expense): recognised once as a dated operating expense in P&L; **excluded** from inventory valuation; payable still tracked to its recipient.
* `NOT_APPLICABLE` / `UNTRACKED_LEGACY`: amount 0 / no payable, no cost, no expense (used for historical safety).

**R3 — No cash movement without a payment document.** GRN save writes **zero** `AccountTransaction` rows. Every payment writes exactly **one** `AccountTransaction` (money out of a cash/bank account) → Cash Flow shows exactly that amount, once.

**R4 — One payment document, one cash row, one audit row.** Extend `SupplierPayment` (do not create a second payment table). Each payment targets exactly one obligation (`grn_id` + `recipient_type=SUPPLIER`, **or** `grn_id` + `grn_charge_id`). Marker `[SRC:GRN_PAYMENT:<payment.id>]` + unique `idempotency_key` prevent duplicates; the `_sync_linked_*` convergence pattern makes re‑saves idempotent.

**R5 — Derived balances, never stored duplicates.** `paid = Σ active payments for obligation`, `remaining = original − paid`, `status = Paid | Partially Paid | Unpaid`, `GRN total cash paid = Σ payments with cash_posted=True`. A `payment_status` entered on the GRN form is an **initial declaration**, reconciled with actual payment rows; it never overrides derived figures.

**R6 — FIFO per lot, landed.** Each `GRNItem` stores its own `landed_unit_cost`; old and new lots keep different rates; `GRNAllocation.cost_rate`/`DirectSaleItem.cost_rate_at_sale` remain frozen at posting time. Historical consumed costs are **never silently rewritten**.

**R7 — Single source of arithmetic.** `app/services/grn_costing.py::grn_breakdown(grn)` returns one immutable breakdown (`supplier_material`, `charges[]`, `capitalised_total`, `expense_total`, `landed_cost_total`, `per_line[]`, `paid_by_recipient`, `remaining_by_recipient`, `cash_paid_total`). Every screen, report, PDF, export, truth engine and test calls it. `calculate_grn_total()` becomes a thin compatibility wrapper.

### Equations

```
supplier_material_amount = Σ(qty_i × rate_i)                 # A2: gross material only, nothing else
capitalised_charges      = Σ charge.amount where cost_treatment = INVENTORY and status ≠ NOT_APPLICABLE
landed_cost_total        = supplier_material_amount + capitalised_charges
line_landed_cost_i       = qty_i × rate_i − discount_share_i + allocated_charge_share_i
landed_unit_cost_i       = line_landed_cost_i / qty_i
actual_avg_rate (GRN)    = landed_cost_total / Σqty      (only when all lines share a unit; otherwise show per-line rates)
expense_total            = Σ charge.amount where cost_treatment = EXPENSE
payable(recipient)       = obligation(recipient) − Σ payments(recipient)
cash_paid_total(GRN)     = Σ payments(GRN, cash_posted = True, is_void = False).amount
```

**Worked example (yours):** 100 bags × 1,500 = 150,000; fare 5,000 + loading 1,000 + other 500 = 6,500 → `landed_cost_total = 156,500`, `landed_unit_cost = 1,565/bag`. Supplier payable = 150,000; transporter payable = 5,000; loading payable = 1,000; other payable = 500. Pay fare 5,000 → Cash Flow −5,000, supplier payable still 150,000, loading still 1,000. Later pay supplier 50,000 → −50,000, supplier remaining 100,000. Later pay loading 1,000 → −1,000, loading 0. Total cash actually paid 56,000, **never** 156,000/156,500.

---

# 4. Proposed new GRN workflow (Phase 2)

## 4.1 Form (`templates/grn_wizard.html`, Step 3 "Expenses" tab)

Keep the existing Steps 1–2 and all existing fields. Replace the three flat charge inputs with a **charge line grid** (add/remove rows):

| Column | Input | Notes |
|---|---|---|
| Charge type | `VEHICLE_FARE`, `TRANSPORT`, `LOADING`, `UNLOADING`, `OTHER` | `OTHER` needs a free‑text label |
| Description / label | text | e.g. "Rana Transport" |
| Amount | number (paisa‑exact) | 0 → treated as Not Applicable |
| Recipient type | `Supplier`, `Transporter / Vehicle`, `Loading / Labour`, `Other` | defaults by charge type (fare→Transporter, loading/unloading→Labour) |
| Recipient / person | combobox into `CashFlowParty` (create‑new inline) | stored as `recipient_party_id` + denormalised `recipient_name` snapshot |
| Payment status | `Paid`, `Unpaid`, `Not Applicable` | initial declaration only (R5) |
| Cost treatment | `Include in material cost (default)`, `Separate expense`, `Not material cost` | R2 |
| Allocation basis | `By line value (default)`, `By quantity`, `Manual per line` | R12 / §9 |

**Remove the forced payment block from GRN entry**: `paid_amount`, `payment_type`, `payment_account_id`, bank fields become **hidden/legacy** on new GRNs and are no longer required. A new "Payments are recorded from Accounts → PAY EXISTING GRN" hint plus a link is shown. (Legacy GRNs being edited keep their existing fields so historical data stays valid.)

**Live totals strip** (JS `updateGrnTotal()` rewritten): Supplier Material Amount · Vehicle Fare · Loading · Unloading · Other · Total Actual Purchase Cost · Average Actual Cost per Unit (per line for multi‑material) · Total Purchase Payables · "Cash paid: Rs. 0.00 at receipt — pay from Accounts".

## 4.2 Server (`app/blueprints/ops/grn.py`, `app/blueprints/misc/pending.py`)

1. Validate + parse charges with `_parse_grn_money` (existing helper) → integer paisa via `to_minor`.
2. Create `GRN` (with `costing_mode='LANDED'`), `GRNItem` lines, `Entry(IN)` rows, `Material.total` — **unchanged quantity logic**.
3. Create one `GRNCharge` row per charge line. Mirror the amounts into the legacy `loading_cost`/`freight_cost`/`other_expense` columns **only as a deprecated compatibility cache** (`is_legacy_mirror=True` prevents double counting).
4. Call `grn_costing.recompute_landed_costs(grn)`: allocate capitalised charges to `GRNItem` lines (§9), write `landed_unit_cost_minor`, `lot_cost_minor`, `allocated_charges_minor`, `allocation_json`; write header totals.
5. `declared_status` is stored as display-only metadata. **No payment or settlement row of any kind is created (A1)** — zero `SupplierPayment`, zero `AccountTransaction`.
6. **Do not call `_sync_grn_auto_supplier_payment()`** for `costing_mode='LANDED'` GRNs (A1). No supplier payment, no cash movement, no supplier ledger debit arises from receiving.
7. Wrap in one `db.session` transaction; duplicate manual bill protection (`uq_grn_manual_bill_no`) and CSRF unchanged.

## 4.3 GRN details / reports (requirement 9)

`templates/grn_wizard.html` records table gains columns: Supplier Material Amount · Additional Charges · Total Actual Cost · Avg Actual Rate · Paid (supplier) · Supplier Due · Charges Paid · Charges Due · Total Cash Paid · Status badge. The existing expandable "Consumption by lot" row gains a **"Cost & Payments" panel**: charge table (type, recipient, original, paid, remaining, status, treatment), per‑line landed unit cost, allocation basis, and a **payment history** list (date, recipient, amount, method, account, reference, void state) with a "Pay this GRN" button deep‑linking to `/accounts/grn_payments?grn_id=<id>&charge_id=<id>`.

`view_bill.html` / invoice PDF and `export_grn` Excel get the same breakdown from `grn_breakdown()` instead of `calculate_grn_total()`.

---

# 5. Proposed payment workflow (Phase 2)

## 5.1 Entry points (two, one service — no duplicate system)

1. **Accounts → "PAY EXISTING GRN / GRN PAYMENT"** — new page `/accounts/grn_payments` (GET/POST) with a full wizard; registered in `app/services/sidebar_nav.py` under Accounts and in `app/services/constants.py::ENDPOINT_PERMISSION_MAP` (`can_manage_payments`).
2. **"Make New Transaction" modal** — new `pay_target='grn_payment'` option in `templates/accounts/dashboard.html` + `blueprints/accounts/transactions.py:307`. Both call the **same** `app/services/grn_payments.py::save_grn_payment()`.

## 5.2 Wizard steps (exactly your list)

1. **Select GRN** — searchable (bill no / supplier / date); loads `grn_breakdown()` showing each obligation with **Original / Already Paid / Remaining**.
2. **Select payment recipient** — `Supplier (material only)` or one of the GRN charge recipients (`Vehicle / Transporter`, `Loading / Labour`, `Unloading`, `Other charge recipient`). Each option is a concrete obligation ID, so a vehicle payment can never touch the supplier balance.
3. **Display** original amount, already paid, remaining payable (derived, R5).
4. **Enter payment amount** — > 0, ≤ remaining by default (overpayment only with an explicit "record as advance" flag and audit note). Partial and repeated payments are natural: each save creates a new row.
5. **Cash / Bank** method.
6. **Payment date + reference** (date cannot be future; `resolve_posted_datetime`; `_assert_period_open` on the account).
7. **Pay From Account** — validated with `_validate_account_for_method`, `balance_minor` sufficiency, active status.
8. **Save** (idempotency key + CSRF).

## 5.3 What save writes (atomic)

| Row | Content |
|---|---|
| `SupplierPayment` (1) | `grn_id`, `grn_charge_id` (NULL for supplier material), `recipient_type`, `recipient_party_id`, `recipient_name`, `payment_kind='GRN_MATERIAL'|'GRN_CHARGE'`, `amount/amount_minor`, `method`, `payment_account_id`, `date_posted`, `manual_bill_no` (reference), `auto_bill_no` (new `GRN_PAYMENT` bill namespace), `source_type='GRN_PAYMENT'`, `source_id=grn.id`, `note` with `[SRC:GRN_PAYMENT:<id>]`, `cash_posted=True`, `idempotency_key`, `revision`, `created_by`. `supplier_id` remains populated as the **GRN's context supplier** (see D4). |
| `AccountTransaction` (1) | `from_account_id` = chosen cash/bank, `to_account_id=NULL`, `amount_minor`, `transaction_type='GRN Payment'`, `source_type='GRN_PAYMENT'`, `source_id=payment.id`, `grn_id`, `party_type`, `party_id`, `party_name`, `description` ("Vehicle fare payment — GRN <ref> — <recipient>"), `date_posted`. Balance moved through existing `_apply_account_tx_effect`. |
| `AccountingAuditLog` (1) + `audit_log()` | before/after snapshot, actor, reason. |

**Nothing** is written to `GRNItem`, `GRNAllocation`, `Material.total`, `Entry`, `CashFlowEntry`, `FbmCashDrawerEntry`, or any expense row. `GRN.paid_amount` stays 0 for new GRNs (it is a legacy field only).

## 5.4 Payment history, edit, void, restore

* `/accounts/grn_payments?grn_id=…` shows the full history; the GRN detail panel embeds it.
* Edit/void/restore go through the same service with `expected_revision`, `_assert_period_open`, and the `_sync_linked_*` convergence helper (void → `_reverse_account_tx_effect` + `is_void=True`; **never delete**). Derived balances update automatically. This reuses `delete_supplier_payment` / `restore_supplier_payment` semantics, but the new rows are GRN‑owned, so `_supplier_payment_source()` must recognise `GRN_PAYMENT` and route edit rights to the GRN payment page.
* **Duplicate prevention:** unique `idempotency_key`; partial unique index on `account_transaction(source_type='GRN_PAYMENT', source_id)`; `financial_integrity_audit()` extended with "each GRN payment has exactly one active money‑out row", "Σ payments per obligation ≤ original", "no orphan `grn_charge_id`".

---

# 6. Database changes and relationships

**Design principle honoured: extend existing structures; add only ONE new table.** No new journal, no new payment table, no new cash‑flow table, no new stock‑lot table, no new expense table, no new party master.

## 6.1 NEW table — `grn_charge` (the only new table; unavoidable)

Why necessary: 3 flat `grn` columns cannot hold per‑charge recipient, payment status, cost treatment, allocation basis, multiple "other" charges, or per‑charge paid/remaining. Without it you cannot have a transporter ledger or keep the supplier ledger clean.

```sql
CREATE TABLE IF NOT EXISTS grn_charge (
  id                    INTEGER PRIMARY KEY,
  grn_id                INTEGER NOT NULL REFERENCES grn(id),
  charge_type           VARCHAR(30) NOT NULL,     -- VEHICLE_FARE|TRANSPORT|LOADING|UNLOADING|OTHER
  label                 VARCHAR(160),
  amount                REAL DEFAULT 0,
  amount_minor          BIGINT NOT NULL DEFAULT 0, -- authoritative paisa
  recipient_type        VARCHAR(30) DEFAULT 'OTHER', -- TRANSPORTER|LABOUR|OTHER|UNSPECIFIED (never SUPPLIER: A2)
  recipient_party_id    INTEGER REFERENCES cash_flow_party(id),
  recipient_name        VARCHAR(160),             -- snapshot for history
  declared_status        VARCHAR(20) DEFAULT 'UNPAID', -- PAID|UNPAID|NOT_APPLICABLE (display only: A1)
  cost_treatment        VARCHAR(30) DEFAULT 'INVENTORY', -- INVENTORY|EXPENSE|NON_MATERIAL|UNTRACKED_LEGACY
  allocation_basis      VARCHAR(20) DEFAULT 'VALUE',    -- VALUE|QUANTITY|MANUAL
  allocation_json       TEXT,                     -- {grn_item_id: minor} for MANUAL / audit
  is_void               INTEGER DEFAULT 0,
  is_legacy_mirror      INTEGER DEFAULT 0,        -- backfilled from old scalar columns
  legacy_column         VARCHAR(40),              -- loading_cost|freight_cost|other_expense
  revision              INTEGER DEFAULT 1,
  created_by            VARCHAR(80), updated_by VARCHAR(80),
  created_at            DATETIME, updated_at DATETIME,
  note                  VARCHAR(500)
);
CREATE INDEX IF NOT EXISTS ix_grn_charge_grn        ON grn_charge(grn_id);
CREATE INDEX IF NOT EXISTS ix_grn_charge_party      ON grn_charge(recipient_party_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_grn_charge_legacy
  ON grn_charge(grn_id, legacy_column) WHERE legacy_column IS NOT NULL;
```

## 6.2 `grn` — additive nullable columns (auto‑added by `_ensure_model_columns()`)

`supplier_material_amount(+_minor)`, `capitalised_charge_total(_minor)`, `landed_cost_total(_minor)`, `expense_charge_total(_minor)`, `costing_mode` (`LEGACY|LANDED`), `allocation_basis_default`, `revision`, `created_by`, `updated_by`, `cancelled_at`, `cancelled_by`, `cancel_reason`, `is_cancelled`. `is_void` already exists. Legacy charge/tax/discount/adjustment/paid/payment columns **stay** for compatibility and imports; new code writes them only as mirrors.

## 6.3 `grn_item` — additive columns

`base_rate_minor`, `allocated_charges_minor`, `line_landed_cost_minor`, `landed_unit_cost` (float, 6 dp, for existing qty×rate maths), `landed_unit_cost_minor`, `allocation_basis`, `cost_revision` (int), `cost_revised_at`. `price_at_time` stays unchanged as the **supplier rate** (never overwritten). `is_locked`, `is_void` unchanged.

## 6.4 `supplier_payment` — additive columns (still the ONE payment table)

```text
grn_id                INTEGER  REFERENCES grn(id)
grn_charge_id         INTEGER  REFERENCES grn_charge(id)
recipient_type        VARCHAR(30)   -- SUPPLIER|TRANSPORTER|LABOUR|OTHER  (NULL/legacy => SUPPLIER)
recipient_party_id    INTEGER  REFERENCES cash_flow_party(id)
recipient_name        VARCHAR(160)
payment_kind          VARCHAR(30)   -- GRN_MATERIAL|GRN_CHARGE|GRN_CHARGE_SETTLED_EXTERNAL|STANDALONE|ADVANCE|LEGACY_GRN_AUTO
cash_posted           INTEGER DEFAULT 0/1  -- whether an AccountTransaction exists
reference             VARCHAR(80)
```

`supplier_id` is **NOT NULL in existing SQLite**; a plain `ALTER TABLE` cannot relax it and `auto_migrate.py` blocks `DROP TABLE`/rebuild DDL by default. Therefore non‑supplier GRN payments keep `supplier_id` = the GRN's supplier as a *context FK*, and **`recipient_type` is the sole authority for which ledger a payment belongs to** (D4). All projections must filter on `recipient_type`/`payment_kind`, never assume "every SupplierPayment is a supplier payment".

Indexes: `(grn_id)`, `(grn_charge_id)`, `(recipient_type)`, `(recipient_party_id)`, partial unique `(grn_id, grn_charge_id, idempotency_key)` where key present (existing `uq_supplier_payment_idempotency_key` already protects retries).

## 6.5 `cash_flow_party` — additive columns

`party_role` (`transporter|loading_labour|other|supplier_alias`), `is_payee_active`, `created_by`. Reused as the recipient master; no new party table. `Account.linked_party_name` stays for account classification.

## 6.6 `account_transaction` — additive columns

`grn_id`, `party_type`, `party_id`, `party_name`, plus new `transaction_type='GRN Payment'`. `source_type='GRN_PAYMENT'`, `source_id=payment.id`. No new table; Cash Flow, `cash_day_recon.py` (which reads **all** account transactions, `:227`) and reconciliations pick it up automatically.

## 6.7 Relationship diagram (proposed)

```
Supplier ──< GRN ──< GRNItem (FIFO lot, landed_unit_cost)
                │        └──< GRNAllocation ──< DirectSaleItem
                └──< GRNCharge ──> CashFlowParty (recipient)
                         │
GRN ──< SupplierPayment (grn_id, grn_charge_id, recipient_type)  ← ONE payment table
                │
                └──> AccountTransaction (1:1, type 'GRN Payment') ──> Account.balance_minor
                                                     │
                                                     └──> Cash Flow / Daily Recon / P&L cash rows
Supplier ──< SupplierPayment (recipient_type='SUPPLIER' / legacy NULL) ──> Supplier Ledger
```

## 6.8 Constraints / invariants to enforce in code + tests

* Exactly one active `AccountTransaction` per non‑void GRN payment; voided payments leave their row with `is_void=True`.
* `Σ payments(obligation) ≤ obligation.amount_minor` unless `payment_kind='ADVANCE'` with an audit reason.
* `landed_cost_total_minor = supplier_material_amount_minor + Σ INVENTORY charges`; `Σ line_landed_cost_minor = landed_cost_total_minor` (largest‑remainder guarantees exact paisa).
* No `AccountTransaction` exists for a GRN with no posted payments.
* Supplier ledger credit for a GRN = `supplier_material_amount` only (plus charges explicitly marked `recipient_type=SUPPLIER`).

---

# 7. Supplier and transporter / other‑party ledger changes

## 7.1 Supplier Ledger — clean rule

* `_supplier_rows()` (`financial_ledgers.py:1239`) credit changes from `calculate_grn_total(grn)` → **`grn_breakdown(grn).supplier_material_amount`**. Charges are never added. `item_lines` keep qty/rate/amount.
* Debits: `SupplierPayment` where `recipient_type='SUPPLIER'` (or legacy NULL) **and** `payment_kind` in (`STANDALONE`, `ADVANCE`, `GRN_MATERIAL`, `LEGACY_GRN_AUTO`). Explicitly **exclude** `GRN_CHARGE` payments to transporters/labour/other.
* Legacy `grn.paid_amount` fallback (`:1291`) stays only for `costing_mode='LEGACY'` GRNs without a linked payment, so old ledgers keep their historic numbers.
* Same rule applied to `build_supplier_payable_overview` (`:1365`), `build_supplier_payable_summaries` (`:1466`), `app/services/ledgers.py:646` (legacy/PDF implementation), `supplier_ledger_shift.py:312`, `/api/supplier_balance` (`app/blueprints/api.py:426`), Accounts dashboard/KPIs, `supplier_ledger_pdf.py`, `templates/supplier_ledger*.html`.
* Result for your example: Supplier Ledger = 150,000 credit, 0 debit after the fare payment → **150,000 payable**; fare/loading never appear there.

## 7.2 Transporter / labour / other‑party ledgers

* New **read‑only projection** `app/services/financial_ledgers.py::build_party_financial_ledger(party)` (mirrors `_supplier_rows`): credit = `GRNCharge` rows for that `recipient_party_id` (minus voided/cancelled), debit = `SupplierPayment` rows for that party, opening balance from a new nullable `cash_flow_party.opening_balance`, running balance `credit − debit`. No new table.
* New route `/party_ledger/<int:id>` reusing **`templates/financial_ledger.html`** with `entity_type='party'` (same template as supplier/client), plus PDF/CSV reuse of `supplier_ledger_pdf.py` parameterised.
* **Transporter Ledger** example: fare 5,000 credit − payment 5,000 debit = 0. **Loading Ledger**: 1,000 credit, 0 paid → 1,000 payable. **Other**: 500 payable.
* Supplier‑ledger shift (`app/services/supplier_ledger_shift.py`) must be changed so it moves **only** supplier obligations + supplier payments; `GRNCharge` rows with `recipient_type != SUPPLIER` and their payments **stay with their own parties**. The preview (`preview_supplier_ledger_shift`) must list "party obligations not moved" explicitly. `reclaim_supplier_ledger` must reverse exactly the same set.

## 7.3 Outstanding Payables / General Accounts

* New `build_purchase_payables()` projection (supplier + all party payables, grouped by recipient) surfaced on the Accounts dashboard KPI and a new "Outstanding Purchase Payables" tab on `/unpaid_transactions` (which today is client receivables only — do **not** repurpose that page's numbers).
* General Accounts: `AccountTransaction` + `Account.balance_minor` + `AccountReconciliation` + `CashDayAccountPosition` all continue to work unchanged; only the transaction type/labels are new.
* Expense Accounts: `GRNCharge(cost_treatment='EXPENSE')` rows appear in `profit_loss` expense projection and in a new **"Accrued purchase expenses (unpaid)"** section of `blueprints/accounts/payments.py::expenditures`, kept separate from cash‑based expenditure totals so nothing is double counted.

---

# 8. Cash flow changes

**No new cash‑flow engine.** `collect_cash_flow_rows()` already shows only actual `AccountTransaction` money movement; that is exactly the behaviour you want and it must be preserved.

Changes required:

1. `app/services/cash_flow_svc.py`: add `SRC_GRN_PAYMENT = 'GRN_PAYMENT'`, label `'GRN Payment'`, `_CF_SECTION_BY_SOURCE['grn_payment'] = CF_SECTION_GRN_PAYMENTS` (new section label), `_CF_CREATOR_SOURCES` / `_CF_CREATOR_AUDIT_ENTITIES` entries so "created by" resolves. Populate `party_name`/`party_type` and `description` from the new `AccountTransaction` columns instead of leaving them blank. Add `grn_id`/recipient to the row dict + filter options in `filter_cash_flow_rows()` (`:1485`) and the Cash Flow template filters.
2. `templates/cash_flow.html`: optional GRN / recipient filter and section column (existing `section_label` mechanism).
3. `blueprints/accounts/kpis.py:51/273`, `blueprints/accounts/dashboard.py:24`, `blueprints/accounts/helpers.py:10`: **stop synthesising "GRN Purchase Payment" rows from `grn.paid_amount`** for `LANDED` GRNs; derive all GRN payment KPIs from `SupplierPayment`/`AccountTransaction` by `grn_id`. Keep the legacy fallback only for `costing_mode='LEGACY'` so old numbers don't vanish.
4. `blueprints/accounts/payments.py:413 receipts` and `templates/accounts/receipts.html`: replace `grn_totals` (full GRN total) with `grn_breakdown()` figures; the "GRN Paid" KPI must equal actual posted payments, not `paid_amount`.
5. **Never** create a `CashFlowEntry` or `AccountTransaction` at GRN save; never create one for `Paid outside Accounts` settlements (`cash_posted=False`).
6. Verify `app/services/cash_day_recon.py` (`:227`), `cash_flow_reconciliation_helpers.py`, `app/services/financial_ledgers.py::financial_integrity_audit` continue to balance — they read all account transactions, so they need only regression tests, not logic changes.

**Expected Cash Flow for your example:** 5,000 out (Vehicle, GRN #x) → 50,000 out (Supplier, later date) → 1,000 out (Loading, later date). Total 56,000. **No** 150,000/156,000/156,500 row at receipt.

---

# 9. Inventory costing changes

## 9.1 One new service module (no new table)

`app/services/grn_costing.py`:
* `grn_breakdown(grn)` — R7 single source (used by every consumer).
* `recompute_landed_costs(grn)` — allocate capitalised charges and write `GRNItem` cost columns + header totals.
* `lot_cost_rate(item)` — returns the landed rate (`landed_unit_cost` when `costing_mode='LANDED'`, else `price_at_time` for legacy), used by **all** cost lookups.
* `revalue_remaining_lots(grn, …)` — opt‑in, remaining‑qty‑only cost adjustment with `AccountingAuditLog` (§11/§12).

## 9.2 Allocation method for multiple materials in one GRN (your requirement 3)

* **Default: by line value** (weights = `qty × rate − discount_share`, in paisa). Justification: freight/loading usually correlate with value/bulk, and value‑weighting works when units differ (cement bags vs steel kg vs sand cft) where a plain `total/qty` would be nonsense.
* Split with **`app/services/pricing.py::allocate_cents(total_charge_minor, weights)`** — existing, exact, largest‑remainder, always sums to the charge to the paisa. Each charge is allocated independently; `GRNItem.allocated_charges_minor` accumulates its shares; `GRNCharge.allocation_json` stores the audit trail.
* Per‑charge override:
  * `QUANTITY` — weights = `qty` (allowed only when **all** GRN lines share one unit; otherwise validation error).
  * `MANUAL` — operator enters an amount per line; server validates the sum equals the charge exactly; store the mapping.
* `landed_unit_cost_i = (qty_i × rate_i − discount_share_i + allocated_charge_share_i) / qty_i`. Store `line_landed_cost_minor` (authoritative total), `landed_unit_cost_minor` (rounded paisa/unit) and a 6‑dp float `landed_unit_cost` for the existing `qty × rate` arithmetic. A reconciliation check uses the authoritative lot total with a 1‑paisa tolerance, so COGS never drifts.
* `EXPENSE` / `NON_MATERIAL` / `NOT_APPLICABLE` charges are **never allocated**.
* Recoverable purchase tax → **not** inventory (R2 / decision D5); non‑recoverable tax billed by the supplier stays in supplier payable and, if flagged, is capitalised via an INVENTORY charge.
* Purchase **discount** reduces both supplier payable and line cost (allocated with `allocate_cents` across lines), so `Σ line costs = supplier_material_amount`.

## 9.3 Every FIFO / cost consumer switches to `lot_cost_rate()`

`app/services/sales_core.py`: `_cost_rate_for_material` (`:92`), `_cost_rate_for_grn_item` (`:156`), `_grn_fifo_lots_for_material` (`:215–270`), `_apply_grn_allocations_for_sale` (`:405`) → `GRNAllocation.cost_rate` and `DirectSaleItem.cost_rate_at_sale` get the **landed** rate.
`app/services/profit_loss.py`: `purchase_rates` (`:451`), lot construction (`:785`), all `grn_item.price_at_time` fallbacks (`:755, 913, 1379`), estimated‑rate helper (`:720–765`).
`app/services/grn_consumption.py`: `_LotLedger._load_lots` (`:217`), `_ProjectionLedger` (`:769`), `available_fifo_lots` / `build_grn_consumption` (`:843`) — "received/consumed/remaining value" becomes landed value.
`app/services/allocation_integrity.py`, `app/services/void_rebuild.py`, `tools/predator_truth_engine.py` — checks compare against landed rate, not `price_at_time`.
`app/services/profit_loss.py:2845` disclosure note replaced with the new policy.

## 9.4 Preserve correct GRN batch costing

* Old lot @ its own old rate, new lot @ its own landed rate; a sale spanning both still creates two layers (`MULTI_GRN_COSTING_FIX_REPORT.md`, `FIFO_LIVE_RECONCILIATION_REPORT.md` behaviour **unchanged**). Never use only the latest GRN rate.
* `GRNItem.qty` / `Entry(IN)` / `Material.total` (quantity) are untouched — this redesign changes **value only**, avoiding the two‑stock‑truths problem (P11).
* `is_locked` rules stay: cost‑affecting edits on partially/fully consumed lots are blocked (§11).
* Double counting guard: INVENTORY charges produce **no** `AccountTransaction('Expense')` and **no** P&L expense row; EXPENSE charges produce **no** `allocated_charges_minor` and are excluded from COGS. A unit test asserts both directions.

---

# 10. Profit & Loss changes

1. **COGS** becomes landed automatically once all cost lookups use `lot_cost_rate()` (§9). Frozen `GRNAllocation.cost_rate` / `DirectSaleItem.cost_rate_at_sale` from historical sales are **left as posted** — no silent rewrite (R6). New sales pick up 1,565 instead of 1,500.
2. **Operating expenses**: `app/services/profit_loss.py` transaction collection (`:2091–2168`) gains a loop over `GRNCharge` rows with `cost_treatment='EXPENSE'`, emitting `entry_type='expense'`, `source_type='GRNCharge'`, `date=grn.date_posted`, `expense=amount`, with a de‑duplication rule: **skip** any `AccountTransaction` of type `'GRN Payment'` when scanning expenses (otherwise paying a charge would double count it). `GRN Payment` rows are payable settlements, not expenses.
3. `INVENTORY` charges are **never** emitted as expenses, and `EXPENSE` charges are **never** added to `landed_cost_total` — enforced in `grn_breakdown()` and asserted by tests.
4. `app/services/profit_loss_breakdown.py` needs no structural change (it buckets `row['expense']`), but `templates/partials/profit_loss_results.html` / `profit_reports.html` gain a "Landed purchase cost" line and the disclosure note (`:2845`, `:785` in breakdown) is updated.
5. `profit_loss.py:2617 build_current_payables` usage is client‑only; leave it. The new purchase‑payables projection is separate.
6. `app/services/profit_loss_exports.py` / `templates/profit_report_pdf.html` pick up the new fields through the shared row dict.
7. `tools/predator_truth_engine.py:100/823` — update the independent raw‑SQL GRN truth to `supplier_material_amount` for supplier payable and `landed_cost_total` for inventory, and add checks for charge payables and cash‑paid totals.

---

# 11. Editing, cancellation and historical records

## 11.1 GRN edit rules (extend `app/blueprints/misc/pending.py::edit_grn`)

| Change | Rule |
|---|---|
| Supplier / date / note / bill no / photo | Allowed (existing backdate policy `_enforce_grn_backdate_policy` unchanged). |
| Charge amount / recipient / treatment | Allowed **only if no posted payment targets that charge**. If payments exist → block with a readable message and offer "void those GRN payments first" (they remain in history). |
| Item qty / rate / add / remove | Existing `_grn_has_locked_lots` rule preserved: blocked once consumed by a sale (header‑only edit allowed). |
| Cost‑affecting change on a **partially consumed but unlocked** lot | Block in‑place rewrite; provide a separate **"Cost Adjustment"** action that (a) creates a new `AccountingAuditLog` with before/after, (b) revalues **only the remaining quantity** (`revalue_remaining_lots`), (c) leaves `GRNAllocation` / frozen sale costs untouched. No silent historical rewrite. |
| Recompute on save | `recompute_landed_costs()` re‑runs; mirrors legacy scalars; `_sync_grn_auto_supplier_payment()` runs **only** for `costing_mode='LEGACY'` GRNs. |

## 11.2 Cancellation (replace hard delete)

New `app/services/grn_cancel.py::cancel_grn(grn, reason, actor)`:

1. **Preconditions**: no consumed/locked lots (else require reversing those sales first — matches today's rule); list all linked payments and outstanding obligations in a preview.
2. Set `grn.is_void=True`, `is_cancelled=True`, `cancelled_at/by/reason`; void `GRNItem` rows and `GRNCharge` rows (keep rows, never delete).
3. Reverse quantity: mark `Entry(IN)` rows `is_void=True` and decrement `Material.total` (no physical delete).
4. **Preserve all `SupplierPayment` and `AccountTransaction` rows.** If cash was already paid, require an explicit decision: refund (new receipt transaction) or keep as an advance/credit against another GRN — never delete or rewrite the money row.
5. Post one `AccountingAuditLog` per affected object; P&L/ledger projections immediately stop counting voided lots/obligations while the preserved payments remain visible as advances.
6. `hard_delete_transaction('GRN')` in `app/services/void_rebuild.py:651` becomes an **admin purge only**: it must refuse to run when any linked payment exists, and must cascade to `grn_charge`. `hard_delete_supplier` (`:690`) gains the same guards. `app/services/wipe.py:457` and `app/blueprints/misc/_wipe_delete_selected_data.py` add `grn_charge` in child‑before‑parent order.

## 11.3 Payment edit / void

* Void reverses the `AccountTransaction` through `_reverse_account_tx_effect`, sets `is_void=True`, writes audit; derived balances recalculate. Rows are never physically deleted.
* `_assert_period_open()` and `expected_revision` optimistic locking apply exactly as in `payments_crud.py`.
* GRN‑owned payments are edited from the GRN payment page (extend `_supplier_payment_source()` to return `('GRN_PAYMENT', grn_id)` for the new `source_type`, so Accounts shows "edit from GRN Payments" instead of allowing a conflicting edit).

## 11.4 Supplier shift

`app/services/supplier_ledger_shift.py`: move only `supplier_material_amount` obligations + supplier‑recipient payments + `LEGACY` auto payments; transporter/labour/other `GRNCharge` rows and their payments **remain attached to their own parties**. Preview + reclaim must show the exclusion explicitly (decision D6).

---

# 12. Migration and historical data safety

## 12.1 Mechanism

* New numbered file **`app/migrations/0003_grn_landed_cost_and_payments.sql`** (0001/0002 already applied; do not edit them). `app/services/auto_migrate.py` applies it once on boot and records it in `migration_history`.
* New ORM columns are declared in the models and auto‑added by `app/services/schema.py::_ensure_model_columns()` **before** migrations run. All new columns are **nullable with defaults** — no table rebuild, no destructive DDL (which the runner blocks anyway).
* `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `INSERT … WHERE NOT EXISTS` — safe to retry.

## 12.2 Backfill policy (no silent rewrite)

| Data | Backfill |
|---|---|
| Existing `grn` | `costing_mode='LEGACY'`; `supplier_material_amount` = Σ `qty×rate − discount + tax ± adjustment` for **reporting only**; `landed_cost_total` = old `calculate_grn_total()`; **`price_at_time` unchanged**; `grn_item.landed_unit_cost = price_at_time`, `allocated_charges_minor=0`. Historical P&L COGS stays byte‑for‑byte identical. |
| Existing non‑zero `loading_cost` / `freight_cost` / `other_expense` | Create **one mirror `GRNCharge` each** with `is_legacy_mirror=True`, `legacy_column=…`, `cost_treatment='UNTRACKED_LEGACY'`, `recipient_type='UNSPECIFIED'`, `initial_payment_status='UNPAID'`. They are **excluded** from both inventory and expense, so no historical profit/payable changes without an explicit decision. `uq_grn_charge_legacy` prevents duplicates. |
| Existing `SupplierPayment` | `recipient_type='SUPPLIER'`; `payment_kind='LEGACY_GRN_AUTO'` where `[AUTO_GRN_PAY:n]` / `source_type='GRN'` marker exists, else `STANDALONE`; `grn_id` backfilled from the marker; `cash_posted` set from whether a matching `AccountTransaction` exists. |
| Existing `AccountTransaction` | `grn_id`/`party_*` backfilled where resolvable from the linked payment; otherwise NULL (legacy rows remain valid). |
| `cash_flow_party` | `party_role='other'`; no rows invented for old unnamed charges. |

## 12.3 Opt‑in reclassification tool (separate, after approval)

`tools/repair_controlled/reclassify_legacy_grn_charges.py` (dry‑run by default, `--apply` explicit):
* Preview per GRN: current supplier payable vs proposed supplier payable, new party payables, new landed unit cost, P&L delta.
* On `--apply`: post **visible adjustment rows** (never UPDATE history in place) — supplier ledger debit "Reclassified to transporter/other party" and party ledger credits; optionally revalue **only remaining (unsold) lot quantity** to the landed cost with `AccountingAuditLog` entries. Consumed cost layers stay frozen.
* This is the only way historical supplier ledgers become "clean"; your approval must say whether to run it (D7).

## 12.4 Backups / imports / exports

* Require a **full `.amsdb` snapshot** (`full_db_sync`, `README.md §Data`) before migration; verify on a copy using `tools/predator_truth_engine.py` plus the new invariant report.
* `full_db_sync/engine.py::list_user_tables` copies arbitrary tables → `grn_charge` is included automatically (verify in test).
* Excel import/export: add a `GRNCharges` sheet and extend `GRN` columns in `blueprints/import_export/sheets_master_supply.py::_process_grn`, `export_build.py:180`, `engine.py:723/865`; add payment recipient/GRN linkage columns to the SupplierPayments sheet. Old workbooks without these sheets import unchanged (all new columns nullable).
* `dummy_data/generate_dummy_data.py:436` — seed charges as `LANDED` rows so demo data exercises the new path.
* `LEGACY DATA/*.amsdb` snapshots are never modified.

---

# 13. Testing scenarios

Every scenario is an end‑to‑end pytest using `tests/conftest.py::client` (fresh SQLite + CSRF proxy), plus raw‑SQL invariant assertions.

| # | Scenario | Expected result |
|---|---|---|
| T1 | Your example: 100 bags @1,500 + fare 5,000 + loading 1,000 + other 500, **no payment** | `landed_cost_total=156,500`; `GRNItem.landed_unit_cost=1,565`; supplier payable 150,000; transporter 5,000; labour 1,000; other 500; **0 `AccountTransaction`**, **0 Cash Flow rows**, Supplier Ledger shows only 150,000. |
| T2 | Pay vehicle 5,000 cash from Account A | exactly 1 `AccountTransaction` out 5,000; A.balance_minor −5,000; Cash Flow one 5,000 out (recipient Transporter, GRN ref); supplier payable still **150,000**; transporter payable **0**; Supplier Ledger contains no payment row. |
| T3 | Later pay supplier 50,000 bank, then 100,000 on another date | supplier paid 150,000, remaining 0; Cash Flow two separate outs (50,000 + 100,000); payment history 2 rows with dates/references; no duplicate tx. |
| T4 | Pay loading 1,000 later | labour payable 0; supplier unaffected; total cash actually paid = 56,000; **no** 156,000/156,500 cash row anywhere. |
| T5 | Partial + multiple payments on one charge (2,000 then 1,500 then 1,500 of 5,000) | original 5,000 / paid 5,000 / remaining 0; status Paid; 3 cash rows; no negative balance. |
| T6 | Over‑payment attempt (6,000 on 5,000) | rejected with readable message unless `ADVANCE` flag; no rows written. |
| T7 | Multi‑material GRN (cement 100 bags @1,500 = 150,000; steel 10 ton @20,000 = 200,000; fare 7,000 by value) | allocation 3,000 / 4,000; landed unit costs 1,530 / 20,400; `Σ line_landed_cost = 357,000` exactly (paisa); per‑line rates shown, no single misleading average. |
| T8 | `QUANTITY` basis with mixed units | validation error; `MANUAL` basis with sum ≠ charge | validation error; `MANUAL` with exact sum | saved with `allocation_json` audit. |
| T9 | Charge marked `EXPENSE` | excluded from `landed_unit_cost`; one dated P&L expense row; **no** second expense when it is later paid; payable still tracked. Charge marked `INVENTORY` | no P&L expense row at receipt or payment; COGS includes it when sold. |
| T10 | Two GRNs of same material at 1,500 and 1,565; sale of 150 bags | COGS = 100×rate(lot1) + 50×rate(lot2); two `GRNAllocation` layers; **never** one "latest rate"; P&L profit differs accordingly. |
| T11 | Edit GRN charges after a payment exists | blocked with message; payment history intact; no orphan rows. |
| T12 | Edit GRN after lots are locked by a sale | item changes blocked (existing regression `test_predator_regressions.py:625`); header‑only edit allowed and does not change frozen cost. |
| T13 | Cancel an unpaid, unconsumed GRN | `is_void` set, `Entry(IN)` voided, `Material.total` restored, obligations voided, **zero** cash rows; ledger/payables drop to zero; audit rows present. |
| T14 | Cancel a GRN that already has payments | cancellation requires refund/advance decision; payment + `AccountTransaction` rows preserved and visible; no hard delete. |
| T15 | Cancel a partially delivered GRN | blocked (existing locked‑lot rule) with a clear message; nothing rewritten. |
| T16 | Void/restore a GRN payment | account balance reverses then re‑applies exactly; derived paid/remaining recalculates; `financial_integrity_audit()` returns ok. |
| T17 | Duplicate submit (same idempotency key / double click) | exactly one payment + one account transaction; balances unchanged on replay. |
| T18 | Legacy database (bundled `.amsdb`) boot + report | 0003 applies once; old supplier balances / COGS / P&L **unchanged**; mirror `GRNCharge` rows are `UNTRACKED_LEGACY`; truth engine agrees. |
| T19 | Opt‑in reclassification dry‑run vs apply | preview equals applied deltas; consumed sale costs unchanged; remaining lots revalued; audit rows present. |
| T20 | Supplier ledger shift with a transporter charge | only supplier material obligations/payments move; transporter charge + payment stay with the transporter; preview lists exclusions; reclaim reverses exactly. |
| T21 | Import/export round‑trip (`GRNCharges` sheet) and `.amsdb` snapshot | charges, recipients, payments, landed rates and linkages survive; no duplicates. |
| T22 | Regression | full existing suite: `tests/test_grn_*.py`, `test_supplier_ledger_*.py`, `test_profit_loss_*.py`, `test_fifo_*`, `test_predator_regressions.py`, `test_full_db_snapshot.py`, `test_cash_flow_*`, `test_ledgers_and_pdf_accuracy.py`. |

**Global invariant gate (run after every scenario):**
`Σ supplier payables + Σ party payables = Σ unpaid purchase obligations`; `Σ GRN cash paid = Σ 'GRN Payment' account transactions = Σ Cash Flow GRN outs`; `Σ open lot landed values = inventory asset value`; `landed_cost_total = supplier_material_amount + capitalised_charges`; no negative remaining balances; no duplicate `(source_type, source_id, transaction_type)` rows.

---

# 14. Exact files and modules that need modification

### 14.1 Models / schema / migrations

| File | Change |
|---|---|
| `models/stock.py` | New `GRNCharge` model (§6.1); additive columns on `GRN` (§6.2) and `GRNItem` (§6.3); relationships `grn.charges`, `grn.payments`, `grn_item.charge_allocations_json` accessor. |
| `models/parties.py` | Additive columns on `SupplierPayment` (§6.4) + relationships to `GRN`, `GRNCharge`, `CashFlowParty`. |
| `models/cash.py` | Additive columns on `CashFlowParty` (§6.5) and `AccountTransaction` (§6.6). |
| `models/__init__.py` | No change needed (star import already re‑exports new names from `stock.py`). |
| `app/services/schema.py` | `_ensure_model_columns()` covers new nullable columns; add `_ensure_grn_charge_indexes()` + `_ensure_supplier_payment_link_indexes()` (partial unique indexes), call from the boot sequence near `:1043`. |
| `app/migrations/0003_grn_landed_cost_and_payments.sql` | **New** — table, indexes, idempotent backfill (§12). |
| `app/migrations/README.md` | Document 0003. |

### 14.2 New services (logic, not duplicate systems)

| File | Purpose |
|---|---|
| `app/services/grn_costing.py` | **New** — `grn_breakdown`, `recompute_landed_costs`, `lot_cost_rate`, `allocate_charges`, `revalue_remaining_lots`. Single arithmetic authority. |
| `app/services/grn_payments.py` | **New** — `save_grn_payment`, `grn_payment_obligations`, `void/restore/edit` wrappers, `_sync_linked_grn_payment_tx`, invariant checks. |
| `app/services/grn_cancel.py` | **New** — soft cancellation with reversals (§11.2). |

### 14.3 GRN routes / UI

| File | Change |
|---|---|
| `app/blueprints/ops/grn.py` (`:26–367`) | Parse charge grid; create `GRNCharge`; call `recompute_landed_costs`; stop forcing payment; skip auto supplier payment for `LANDED`; pass `grn_breakdown` map to template. |
| `app/blueprints/misc/pending.py` (`edit_grn` `:184–560`, `export_grn` `:569–630`) | Charge edit rules, recompute, locked‑lot preservation, new export columns. |
| `app/services/grn_svc.py` (`:92`, `:109–190`) | `calculate_grn_total` → compatibility wrapper over `grn_breakdown`; keep `_sync_grn_auto_supplier_payment` **only** for `LEGACY` GRNs; expose `grn_bill_ref` helpers. |
| `templates/grn_wizard.html` (`:473–740`, `:830–1075`, JS `:1152–1170`, `:1551`) | Charge grid, remove forced payment block, live landed totals, records columns, "Cost & Payments" panel + payment history + Pay‑this‑GRN link. |
| `static/grn_consumption.js`, `static/ui.js` | Minor: landed rate display, expandable panel behaviour (reuse existing patterns). |
| `templates/view_bill.html`, `templates/payment_receipt.html`, `templates/supplier_payment_receipt.html` | GRN breakdown + charge/payment sections. |
| `app/blueprints/sales/_bills_view_bill.py:303`, `_bills_download_invoice.py:276` | Use `grn_breakdown()` instead of `calculate_grn_total()+discount`. |

### 14.4 Payments / Accounts

| File | Change |
|---|---|
| `blueprints/accounts/payments.py` | New `/accounts/grn_payments` page + POST save; `receipts()` (`:413`) and `expenditures()` (`:283`) updated. |
| `blueprints/accounts/transactions.py:307–460` | New `pay_target='grn_payment'` delegating to `save_grn_payment`. |
| `templates/accounts/dashboard.html` (`:355–520`, JS `:855/:1075`) | New pay target + GRN/charge/recipient pickers with original/paid/remaining display. |
| `templates/accounts/_supplier_payment_form.html`, `templates/accounts/supplier_payments.html` | Recipient/GRN columns, filters. |
| `templates/accounts/receipts.html`, `blueprints/accounts/kpis.py:51/273`, `blueprints/accounts/dashboard.py:24`, `blueprints/accounts/helpers.py:10` | Derive GRN payment KPIs from payment rows, keep legacy fallback. |
| `app/services/payments_crud.py:197/244/562/713/740` | `_supplier_payment_source`, snapshots, `save/delete/restore_supplier_payment` recognise `GRN_PAYMENT`; keep all existing validation. |
| `app/services/accounting.py:222/545` | New `_sync_linked_grn_payment_tx` (marker `[SRC:GRN_PAYMENT:id]`, type `GRN Payment`) following the existing convergence pattern; do **not** change supplier sync. |
| `app/services/constants.py` | `AUTO_BILL_NAMESPACES['GRN_PAYMENT']='GP'`; `ENDPOINT_PERMISSION_MAP` entries for new endpoints; `DOMAIN_WIPE_REGISTRY` if needed. |
| `app/services/sidebar_nav.py:255–280` | New `NavLink(key='grn_payments', …)` under Accounts. |
| `app/hooks.py` | No change (CSRF applies automatically); new forms must include `{{ csrf_token() }}`. |

### 14.5 Ledgers / reports

| File | Change |
|---|---|
| `app/services/financial_ledgers.py` (`:1239`, `:1365`, `:1466`, `:1617`) | Clean supplier credit/debit rules, `build_party_financial_ledger`, `build_purchase_payables`, extended integrity audit. |
| `app/services/ledgers.py:616–690` | Align legacy/PDF supplier ledger with the clean rule. |
| `app/blueprints/misc/suppliers.py` (`supplier_ledger`, downloads) | Pass breakdown; unchanged page structure. |
| `app/services/supplier_ledger_shift.py:295–340` + preview/reclaim | Exclude non‑supplier charges/payments from shifts. |
| `app/services/supplier_ledger_pdf.py` | Parameterise for party ledgers; GRN breakdown in statements. |
| `app/blueprints/api.py:426` | `api_supplier_balance` uses clean projection; new `/api/grn_payment_obligations/<grn_id>` for the wizard. |
| `app/services/api.py:450–476` | Re‑export new service functions (star‑import contract). |
| `app/blueprints/reports/_profit_unpaid_transactions_page.py` | Add "Outstanding Purchase Payables" tab (client page untouched). |
| `templates/financial_ledger.html`, `templates/supplier_ledger*.html`, `templates/unpaid_transactions.html`, `templates/accounts/kpi_*.html` | Party entity type, breakdown rows, new tab. |

### 14.6 Cash flow / expenses / P&L / costing

| File | Change |
|---|---|
| `app/services/cash_flow_svc.py:245–390, :1341–1473, :1485` | New source/transaction type, section label, party/description fields, filters. |
| `app/blueprints/reports/cash.py`, `templates/cash_flow.html` | Filter + display. |
| `app/services/cash_day_recon.py`, `cash_flow_reconciliation_helpers.py` | Regression only (no logic change expected). |
| `app/services/profit_loss.py:451/720–765/785/913/1379/2091–2168/2845` | Landed rates everywhere; EXPENSE charge rows; skip `GRN Payment` in expense scan; updated disclosure. |
| `app/services/profit_loss_breakdown.py`, `templates/partials/profit_loss_results.html`, `templates/profit_reports.html`, `app/services/profit_loss_exports.py` | Landed cost line, disclosure, exports. |
| `app/services/sales_core.py:92/156/215–270/405` | `lot_cost_rate()` at posting time. |
| `app/services/grn_consumption.py:217/769/843` | Landed valuation. |
| `app/services/allocation_integrity.py`, `app/services/void_rebuild.py:651/690`, `app/services/wipe.py:457`, `app/blueprints/misc/_wipe_delete_selected_data.py` | New table in checks/purge/wipe; cancellation guards. |

### 14.7 Import / export / tools / tests

| File | Change |
|---|---|
| `blueprints/import_export/sheets_master_supply.py`, `export_build.py`, `engine.py`, `_common.py` | `GRNCharges` sheet + new `GRN`/`SupplierPayments` columns. |
| `full_db_sync/engine.py` | Verify (no change expected — generic table copy), add a test. |
| `tools/predator_truth_engine.py:100/823` | New independent truth for supplier payable / landed cost / party payables / cash paid. |
| `dummy_data/generate_dummy_data.py:436–470` | Seed `LANDED` charges. |
| `tests/` | New `test_grn_landed_cost.py`, `test_grn_payments.py`, `test_grn_charge_ledgers.py`, `test_grn_cancel.py`, `test_grn_migration_backfill.py`, `test_grn_allocation.py`; update existing GRN/ledger/P&L expectations. |
| `README.md`, `ACCOUNTING_MASTER_PLAN.md` | Document the new rules and note that the journal rebuild (§6/§22) remains a separate, unbuilt proposal and is **not** part of this work. |

---

# 15. Conflicts with existing application logic (must be handled, not ignored)

| # | Conflict | Handling |
|---|---|---|
| C1 | `calculate_grn_total()` is simultaneously "document total", "supplier payable" and "purchase cost"; 6 consumers + raw‑SQL truth engine use it. | Split into `grn_breakdown()` with explicit fields; keep `calculate_grn_total()` as a wrapper for legacy callers only; update **all** consumers in one release so screens cannot disagree. |
| C2 | `GRN.paid_amount` + `_sync_grn_auto_supplier_payment()` is the only GRN cash channel and is auto‑synced on **every edit**. | Disabled for `LANDED`; retained for `LEGACY` edits so old rows keep working. All KPI/dashboard/receipts fallbacks updated. |
| C3 | `SupplierPayment.supplier_id` is NOT NULL and named "supplier"; SQLite `ALTER TABLE` cannot relax it and destructive migration DDL is blocked. | Keep it as a context FK; `recipient_type` is authoritative for ledger ownership; every projection filters explicitly (D4). No table rebuild. |
| C4 | `GRNAllocation.cost_rate` / `DirectSaleItem.cost_rate_at_sale` are frozen at posting; revaluing `GRNItem` would silently rewrite historical profit. | R6 + frozen costs preserved; only future allocations and (opt‑in) **remaining** lots change, with audit rows (D7). |
| C5 | P&L expenses are cash‑based (`AccountTransaction('Expense')` + drawer). A naive "post charge as expense" would double count when paid. | Accrue `EXPENSE` charges from `GRNCharge` rows; `GRN Payment` transactions are explicitly excluded from the expense scan; INVENTORY charges never become expenses. |
| C6 | `expenditures()` lists `Payment` transactions as expenses. | New `GRN Payment` type is **not** in that list (it is a payable settlement); accrued purchase expenses shown in a separate section. |
| C7 | Hard‑delete GRN deletes its payment; `hard_delete_supplier` and wipe routines cascade by explicit table lists. | Soft cancel + guards + register `grn_charge` in wipe/purge lists. |
| C8 | `supplier_ledger_shift` moves *everything* matching a supplier, including `CashFlowParty` rows. | Exclude non‑supplier charge obligations/payments; preview + reclaim updated. |
| C9 | Two stock truths (`Entry`/`Material.total` vs GRN lots). | Redesign changes **value only**; quantity paths untouched; new invariant test compares both. |
| C10 | `build_current_payables()` is client receivables despite its name. | Do not repurpose; add a separate purchase‑payables projection/tab. |
| C11 | `tools/predator_truth_engine.py`, Excel import/export, dummy data and `schema.py` encode the old formula. | All updated in the same release; migration marks old rows `LEGACY` so truth checks still pass. |
| C12 | Period locks (`_assert_period_open`) and backdated‑edit policy guard every financial mutation. | New GRN payment path calls the same guard; charge edits on closed periods are refused, not silently applied. |
| C13 | CSRF + permission map + blueprint wiring (`wire_package`) gate new endpoints. | New routes imported from package `__init__.py`, tokens in every form, permission entries added. |
| C14 | `ACCOUNTING_MASTER_PLAN.md` §9/§22 proposes `stock_lot`, `stock_movement`, `ap_document`, `ap_allocation`, a full GL journal. | **Not implemented here.** Those are a separate rebuild; adopting them now would create the duplicate systems you asked me to avoid. This plan extends `GRNItem`, `GRNCharge`, `SupplierPayment`, `AccountTransaction`, `CashFlowParty`. |

---

# 16. Decisions I need from you when approving (defaults proposed)

| ID | Decision | Recommended default |
|---|---|---|
| D1 | Cost allocation basis for multi‑material GRNs | **By line value** (exact paisa, `allocate_cents`); `QUANTITY` and `MANUAL` available per charge. |
| D2 | A charge marked **"Paid"** on the GRN form | **RESOLVED BY OWNER (A1):** display-only declaration; nothing is settled at GRN; all payments from Accounts only. |
| D3 | May a charge recipient ever be the **Supplier**? | **RESOLVED BY OWNER (A2): No.** Charges always create their own party payable; Supplier Ledger stays clean. |
| D4 | `SupplierPayment.supplier_id` NOT NULL constraint | Keep as **context FK** to the GRN's supplier; `recipient_type` decides ledger ownership. (Alternative: a one‑off table rebuild migration — higher risk, blocked by destructive‑DDL guard.) |
| D5 | Purchase tax / discount / adjustment | **RESOLVED BY OWNER (A2):** memo fields on the GRN only — never in the Supplier Ledger, never capitalised for `LANDED` GRNs. |
| D6 | Should legacy GRNs be reclassified automatically? | **No.** Migration is non‑destructive; a dry‑run/**opt‑in apply** tool reclassifies with visible adjustment rows. Tell me if you want it applied to all history during Phase 2. |
| D7 | Revalue **remaining** stock of old GRNs to their landed cost? | **Opt‑in**, only unsold quantity; consumed sale costs stay frozen. |
| D8 | Where should "PAY EXISTING GRN" live? | **Both**: dedicated Accounts page (`/accounts/grn_payments`) **and** a `pay_target` in the existing "Make New Transaction" modal — one shared service, no duplicate logic. |
| D9 | Separate expense charges | Include the `cost_treatment = Separate expense` flag (you explicitly asked for the "marked as separate expense" rule). Default = Include in material cost. |
| D10 | Overpayment on an obligation | Block by default; allow only with an explicit "Advance" flag + audit note. |

---

# 17. Phase 2 execution order (only after approval)

1. **Foundation** — models, migration 0003, `grn_costing.grn_breakdown`, compatibility wrapper, invariant unit tests, backup verification on a copy of the live DB.
2. **GRN entry** — charge grid, landed cost allocation, no forced payment, GRN details/payment panel, wizard JS, view/print/export.
3. **Payments** — `grn_payments` service, Accounts page + modal target, account transaction sync, idempotency, history/void/edit.
4. **Ledgers** — clean supplier rule everywhere, party ledgers, outstanding purchase payables, supplier‑shift fix.
5. **Cash flow / accounts / expenses** — source labels, KPI/receipt cleanup, accrued expense separation.
6. **Inventory / P&L** — switch all cost lookups to `lot_cost_rate`, EXPENSE charge rows, disclosure, FIFO regression suite.
7. **Edit / cancel / historical** — soft cancel, cost adjustment, purge/wipe guards, audit.
8. **Import/export/truth engine/docs** — sheets, predator truth, dummy data, README.
9. **Full test run** (`pytest`), live‑copy reconciliation report, implementation report with before/after numbers and the exact commands to reproduce.

---

# 18. Explicitly out of scope for this redesign

* The full double‑entry journal / chart of accounts / `stock_lot` / `ap_document` rebuild from `ACCOUNTING_MASTER_PLAN.md`.
* Client ledger, sales, bookings, dispatch, delivery rent, returns, waive‑offs, client reconciliation and payroll logic (unchanged, regression‑tested only).
* Changing `price_at_time`, historical `GRNAllocation.cost_rate`, or any past sale's frozen cost.
* Changing `Material.total` / `Entry` quantity semantics.
* Any destructive migration, any `DROP TABLE`, any in‑place rewrite of historical money rows.
* Auto‑applying the legacy reclassification (D6/D7) without your explicit go‑ahead.

---

## Appendix A — Accounting identity checks (to be enforced by tests and the truth engine)

```
For every active GRN:
  landed_cost_total            = supplier_material_amount + Σ(INVENTORY charges)
  Σ line_landed_cost_i         = landed_cost_total                      (exact paisa)
  Σ obligations                = supplier_material_amount + Σ(all charges)
  Σ payments(obligation)       ≤ obligation.amount                     (unless ADVANCE)
  remaining(obligation)        = obligation.amount − Σ active payments
  cash_paid_total              = Σ AccountTransaction(type='GRN Payment', is_void=0).amount
  Supplier Ledger credit       = Σ(qty × price_at_time)   # A2, nothing else
  Supplier Ledger debit        = Σ payments(recipient_type='SUPPLIER')
  Party Ledger credit/debit    = Σ charges/payments for that party
  P&L COGS from a lot          = consumed_qty × lot.landed_unit_cost
  P&L expense from GRN charges = Σ EXPENSE charges only (never INVENTORY charges)
  Cash Flow GRN outs           = cash_paid_total
```

## Appendix B — Your example, final state after the three payments

| Ledger / report | Value |
|---|---|
| GRN: Supplier Material Amount (= Supplier Ledger credit) | 150,000.00 |
| GRN: Vehicle Fare / Loading / Other | 5,000.00 / 1,000.00 / 500.00 |
| GRN: Total Actual Purchase Cost | 156,500.00 |
| GRN: Average Actual Cost / bag | 1,565.00 |
| Supplier Ledger (paid 50,000) | 150,000 credit − 50,000 debit = **100,000 payable** |
| Transporter Ledger | 5,000 − 5,000 = **0** |
| Loading / Labour Ledger | 1,000 − 1,000 = **0** |
| Other Party Ledger | 500 − 0 = **500 payable** |
| Cash Flow | −5,000 (fare), −50,000 (supplier), −1,000 (loading) = **−56,000** |
| Inventory (if unsold) | 100 bags × 1,565 = 156,500 asset value |
| P&L when all 100 bags sold | COGS 156,500 (not 150,000, no separate freight expense) |

---

**PHASE 1 PLAN — APPROVED with amendments A1 / A2. Phase 2 implemented 2026-11-02; full suite green (474 passed, 6 skipped).**
