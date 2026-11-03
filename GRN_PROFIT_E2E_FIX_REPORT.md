# GRN landed-cost profit: end-to-end verification and fixes

Date: 2026-11-03  
Branch: `arena/64d275bd-git-recovered`

## Owner rules verified

1. Supplier ledger contains **only material quantity × supplier rate**.
2. Vehicle rent, loading, unloading and other purchase costs are separate payables to their own recipients.
3. Costs marked **Include in material cost** are capitalised into the GRN lot’s landed rate.
4. COGS recognises the landed cost of the units actually delivered, paid or unpaid.
5. Costs marked **Separate expense** are recognised once at receipt, outside goods COGS.
6. Paying a supplier/transporter/labour payable settles cash and liability; it never creates a second expense.

## End-to-end scenario actually run

Fresh SQLite database, real HTTP routes, admin login, CSRF, supplier/client/material/account creation, GRN, charges, direct sale, Accounts payments, report HTML/PDF/Excel.

| Step | Result |
|---|---:|
| Receive 100 bags @ Rs. 1,500 | Supplier payable Rs. 150,000 |
| Vehicle rent | Rs. 5,000 payable to transporter |
| Loading | Rs. 1,000 payable to labour |
| Unloading | Rs. 500 payable to labour |
| Landed purchase cost | Rs. 156,500 |
| Landed rate | Rs. 1,565/bag |
| Cash/payment rows at receiving | 0 |
| Sell 40 bags @ Rs. 1,800 | Revenue Rs. 72,000 |
| COGS | 40 × 1,565 = Rs. 62,600 |
| Gross profit | Rs. 9,400 |
| Remaining stock | 60 bags, Rs. 93,900 |
| Pay all four obligations | Cash Rs. 156,500; profit/COGS unchanged |
| Sell remaining 60 bags | Total COGS Rs. 156,500; total profit Rs. 23,500; stock 0 |

Additional verified cases:

- Separate Rs. 700 GRN expense: goods COGS stays Rs. 62,600, gross profit Rs. 9,400, net profit Rs. 8,700.
- Two landed lots: 10 @ 1,050 then 30 @ 1,300; sell 40 @ 1,400 → COGS Rs. 49,500, profit Rs. 6,500. FIFO uses each lot’s own landed rate, not the latest average.
- Booking advance is not profit; booking delivery recognises the same landed COGS.
- NOT_APPLICABLE charge is excluded from inventory cost, expense and payable.
- Fractional landed allocation reconciles to the paisa.
- Separate GRN expense is included in supplier/GRN filters and its transaction-detail page opens.

## Problems found and fixed

### 1. Reporting did not explain COGS

The old report showed a combined cost figure and did not split supplier material from capitalised freight/handling. It also labelled the sum of profitable entries as “Total Profit”, which is not net profit.

Fixed:

- New **COGS — Cost of Goods Sold** bridge on the report page.
- Split: supplier material in goods sold + capitalised purchase costs in goods sold + explicitly disclosed other/unattributed material cost = goods COGS.
- Gross profit on goods shown separately from direct service costs, separate GRN expenses and net profit.
- Purchase/stock view now shows supplier value, capitalised charges and total landed value for receipts and remaining stock.
- Same bridge added to PDF and Excel (`COGS Bridge` sheet); transaction export includes supplier/landed/other COGS columns.
- Positive-entry and negative-entry totals renamed to **Profitable Entries Total** and **Loss-making Entries Total**; net result remains the authoritative profit/loss.
- GRN expense rows now carry supplier/GRN attribution and have a working detail model.

### 2. Cost edits after delivery could rewrite stock value but not frozen sale COGS

`edit_grn` blocked item-line changes on locked lots, but charge sync/recompute still ran. Increasing freight after a sale could revalue the remaining stock while the delivered sale stayed frozen at the old rate.

Fixed:

- Cost-affecting edits to a consumed/locked landed GRN are rejected before commit with a clear message.
- The guard covers direct-sale allocations and reconstructed booking/legacy dispatch consumption.
- Header-only edits and re-submitting the identical cost grid remain allowed.
- Regression test proves COGS, allocation rate and remaining stock stay unchanged after a rejected edit.

### 3. NOT_APPLICABLE charges were inconsistent

Breakdown/recompute/expense recognition now use one effective-amount helper: a NOT_APPLICABLE or void charge contributes zero to capitalisation, expense and obligations while retaining its stored amount for audit.

## Test evidence

Focused suites run with background reconciliation/scheduler disabled:

- `tests/test_grn_landed_profit_e2e.py`: **8 passed**
- `tests/test_grn_landed_cost_advanced.py`: **6 passed**
- `tests/test_profit_loss_control_center.py`, `test_profit_loss_fifo.py`, `test_fifo_grn_profit_realtime.py`: **21 passed**
- `tests/test_predator_regressions.py`, `test_grn_datetime_override.py`: **29 passed**
- `tests/test_ledgers_and_pdf_accuracy.py`, `test_full_cycle_smoke.py`: **22 passed**
- `tests/test_grn_landed_profit_e2e.py`, `test_grn_landed_cost_payments.py`, `test_grn_costs_tab.py`: **20 passed** in the combined run before the final NOT_APPLICABLE test correction; the corrected E2E file then passed **8/8**.
- `tests/test_profit_simple_summary.py` and `test_profit_loss_multi_grn_costing.py`: passed in the combined reporting run.
- Frontend DOM controller: **16/16 checks passed**.

## Accounting note

The system intentionally keeps **per-GRN FIFO landed rates**, not one global moving average across all purchases. This preserves historical sale cost when a newer, differently priced lot arrives. A sale spanning multiple lots recognises each lot’s own landed cost.

---

## Update: optional supplier billing checkbox for GRN costs

The owner then asked for a GRN checkbox instead of always keeping every cost out of the supplier ledger.

New GRN field: **Add these GRN costs to the supplier ledger** (`include_charges_in_supplier`).

- **Unchecked (default / existing GRNs):** Supplier Ledger and Accounts supplier payable = stock material value only. Vehicle/loading/unloading/other costs remain payable to their own recipients.
- **Checked:** Supplier Ledger and Accounts supplier payable = material + applicable GRN costs. Those costs are paid through the supplier obligation and do not create a second transporter/labour payable.
- **Inventory / COGS unchanged:** the checkbox is a billing choice only. INVENTORY charges still capitalise into the landed lot rate; EXPENSE charges still remain outside goods COGS.

Linked places updated to use the same rule: GRN wizard live totals, GRN edit, GRN Costs tab, GRN bill/PDF, Accounts → PAY EXISTING GRN, Outstanding Purchase Payables, supplier ledger, supplier payable overview, supplier ledger shift preview, and P&L report notes.

Verified end-to-end:

| Case | Supplier ledger | Other recipient payables | COGS on 40 bags |
|---|---:|---:|---:|
| Unchecked | Rs. 150,000 | Rs. 6,500 | Rs. 62,600 |
| Checked | Rs. 156,500 | Rs. 0 | Rs. 62,600 |

Regression evidence after the checkbox change:

- GRN E2E + landed payments + advanced landed + charge grid + costs tab: **40 passed**
- Ledgers/PDF accuracy + full cycle + profit summary + multi-GRN costing: **37 passed**
- Frontend GRN charge grid: **48/48 checks passed**
- Frontend profit report controller: **16/16 checks passed**
