# App walkthrough — run-007-20261104T0636

Drives the **real app** on a copy of a seeded database: every documented page, every documented form field, every GET route, every link, ten page-vs-page tie-outs, and seven write flows submitted through the actual HTML forms.

| Section | Result |
|---|---|
| Documented pages walked | 58 — **58 PASS · 0 PARTIAL · 0 FAIL** |
| Documented forms / found in markup | 209 / 209 |
| Forms missing from the markup | 0 |
| Field groups with missing fields | 0 |
| GET routes visited | 243 — 193 ok, 23 redirect, 21 404, **0 bad** (8 destructive routes skipped) |
| Links followed | 214 — **0 dead** |
| Page-vs-page tie-outs | **10/10** |
| Write workflows through real forms | **8/8** |

## Documented pages

| Page | Documented title | Verdict | Status | Forms doc/found | Missing forms | Missing fields |
|---|---|---|---|---|---|---|
| `/` | System Dashboard | PASS | 200 | 0/0 | 0 | 0 |
| `/inventory/stock_summary` | Stock Summary | PASS | 200 | 1/1 | 0 | 0 |
| `/inventory/daily_transactions` | Daily Breakdown | PASS | 200 | 1/1 | 0 | 0 |
| `/tracking` | History / Tracking | PASS | 200 | 1/1 | 0 | 0 |
| `/grn` | GRN (Receiving) - records tab | PASS | 200 | 15/15 | 0 | 0 |
| `/grn?tab=costs` | GRN - costs tab | PASS | 200 | 3/3 | 0 | 0 |
| `/bookings` | Bookings | PASS | 200 | 3/3 | 0 | 0 |
| `/direct_sales` | Sales (direct sales) | PASS | 200 | 5/5 | 0 | 0 |
| `/material_returns` | Material Return | PASS | 200 | 2/2 | 0 | 0 |
| `/pending_bills` | Pending Bills | PASS | 200 | 6/6 | 0 | 0 |
| `/delivery_rents` | Delivery Rent | PASS | 200 | 9/9 | 0 | 0 |
| `/payments` | Payments | PASS | 200 | 1/1 | 0 | 0 |
| `/accounts/` | Accounts dashboard | PASS | 200 | 1/1 | 0 | 0 |
| `/accounts/accounts` | Manage accounts | PASS | 200 | 5/5 | 0 | 0 |
| `/accounts/accounts/add` | Add account | PASS | 200 | 1/1 | 0 | 0 |
| `/accounts/categories` | Account groups | PASS | 200 | 11/11 | 0 | 0 |
| `/accounts/transfers` | Transfers | PASS | 200 | 1/1 | 0 | 0 |
| `/accounts/receipts` | Receipts | PASS | 200 | 1/1 | 0 | 0 |
| `/accounts/expenditures` | Expenditures | PASS | 200 | 1/1 | 0 | 0 |
| `/accounts/reconciliations` | Reconciliations | PASS | 200 | 1/1 | 0 | 0 |
| `/accounts/audit` | Account audit trail | PASS | 200 | 12/12 | 0 | 0 |
| `/accounts/purchase_payables` | Purchase payables | PASS | 200 | 0/0 | 0 | 0 |
| `/accounts/payments/clients` | Client payments | PASS | 200 | 4/4 | 0 | 0 |
| `/accounts/payments/suppliers` | Supplier payments | PASS | 200 | 4/4 | 0 | 0 |
| `/accounts/grn_payments` | Pay existing GRN | PASS | 200 | 1/1 | 0 | 0 |
| `/cash_flow` | Cash Flow | PASS | 200 | 13/13 | 0 | 0 |
| `/cash_flow_differences` | Cash Flow differences | PASS | 200 | 1/1 | 0 | 0 |
| `/daily_reconciliation` | Daily reconciliation | PASS | 200 | 7/7 | 0 | 0 |
| `/profit_reports` | Profit & Loss | PASS | 200 | 1/1 | 0 | 0 |
| `/financial_details` | Financial details | PASS | 200 | 1/1 | 0 | 0 |
| `/suppliers` | Suppliers | PASS | 200 | 10/10 | 0 | 0 |
| `/clients` | Clients | PASS | 200 | 5/5 | 0 | 0 |
| `/materials` | Material Brands | PASS | 200 | 13/13 | 0 | 0 |
| `/services` | Services & Charges | PASS | 200 | 7/7 | 0 | 0 |
| `/delivery_persons` | Delivery Persons | PASS | 200 | 3/3 | 0 | 0 |
| `/ledger` | Ledger (client list) | PASS | 200 | 0/0 | 0 | 0 |
| `/client-ledger/categories` | Client categories | PASS | 200 | 7/7 | 0 | 0 |
| `/decision_ledger` | Decision Ledger | PASS | 200 | 1/1 | 0 | 0 |
| `/current_payables` | Current Payables | PASS | 200 | 1/1 | 0 | 0 |
| `/notifications` | Notifications | PASS | 200 | 2/2 | 0 | 0 |
| `/notifications/upcoming` | Upcoming reminders | PASS | 200 | 0/0 | 0 | 0 |
| `/settings` | Settings | PASS | 200 | 18/18 | 0 | 0 |
| `/settings/activity` | Settings - Who did what | PASS | 200 | 1/1 | 0 | 0 |
| `/settings/sessions` | Settings - sessions | PASS | 200 | 0/0 | 0 | 0 |
| `/settings/sidebar` | Sidebar settings | PASS | 200 | 0/0 | 0 | 0 |
| `/import_export/` | Import / Export | PASS | 200 | 5/5 | 0 | 0 |
| `/legacy-migration/` | Legacy data migration | PASS | 200 | 1/1 | 0 | 0 |
| `/data_lab/` | Data Lab | PASS | 200 | 1/1 | 0 | 0 |
| `/admin/` | Admin dashboard | PASS | 200 | 0/0 | 0 | 0 |
| `/admin/modules` | Admin modules | PASS | 200 | 0/0 | 0 | 0 |
| `/system_report` | System report | PASS | 200 | 0/0 | 0 | 0 |
| `/void_audit` | Void audit | PASS | 200 | 1/1 | 0 | 0 |
| `/dashboard` | dashboard alias | PASS | 404 | 0/0 | 0 | 0 |
| `/dispatching` | Dispatching | PASS | 200 | 1/1 | 0 | 0 |
| `/receiving` | Receiving | PASS | 404 | 0/0 | 0 | 0 |
| `/supplier_ledger/1` | Supplier ledger | PASS | 200 | 10/10 | 0 | 0 |
| `/delivery_person_ledger/1` | Delivery person ledger | PASS | 200 | 9/9 | 0 | 0 |
| `/client_ledger/2` | Client ledger | PASS | 200 | 0/0 | 0 | 0 |

## Documented label vs what the screen says (informational)

These are documentation labels, not failures — the page renders.

| Page | Documented label |
|---|---|
| `/tracking` | History / Tracking |
| `/financial_details` | Financial details |
| `/ledger` | Ledger (client list) |
| `/settings/activity` | Settings - Who did what |
| `/settings/sessions` | Settings - sessions |
| `/void_audit` | Void audit |
| `/dashboard` | dashboard alias |
| `/dispatching` | Dispatching |
| `/receiving` | Receiving |

## Tie-outs (one figure, two pages)

| ID | Check | Result |
|---|---|---|
| T-01 | company money: /accounts KPI == /daily_reconciliation | PASS |
| T-02 | stock: /inventory/stock_summary Net == /tracking TOTAL BAGS | PASS |
| T-03 | client net: /clients Payable == /ledger/2 Net Balance | PASS |
| T-04 | rent due: /delivery_rents Remaining == /delivery_person_ledger/1 | PASS |
| T-05 | cash flow adds up: closing == opening + received - spent | PASS |
| T-06 | money received: /financial_details cash TOTAL == P&L Money Received | PASS |
| T-07 | P&L arithmetic: income - COGS == profit | PASS |
| T-08 | suppliers: Total Purchase - Total Paid == Outstanding | PASS |
| T-09 | payables page agrees with the suppliers page | PASS |
| T-10 | invoice PDF 8,500 == the SB-SL-1000 row on /direct_sales == DB | PASS |

## Write workflows driven through the real forms

| ID | Workflow | Result | Observed |
|---|---|---|---|
| W-01 | create supplier via /add_supplier -> row + listing | PASS | `db=True page=True` |
| W-02 | create brand via /add_material -> row + listing | PASS | `db=True page=True` |
| W-03 | material return 2 bags -> stock 195->197 and return listed | PASS | `stock 195.0->197.0 listed=True` |
| W-04 | manual pending bill 4,500 -> row + /pending_bills | PASS | `row=True listed=True` |
| W-05 | reconciliation 175,500 saved -> row(diff 17,000) + page | PASS | `row=True diff=17000.0 page=True` |
| W-06 | replaying a submitted sale is refused, no duplicate row | PASS | `flash='danger: This form token was already used for a different sale. Reload the page a' sales 3->3` |
| W-07 | toggle pending bill paid flips is_paid and back | PASS | `is_paid False -> True -> False` |
| W-08 | receipt 1,000 (+cash) then void (reversed, audited) | PASS | `cash 175500.0 -> 176500.0 -> 175500.0, listed=True, is_void=1` |
