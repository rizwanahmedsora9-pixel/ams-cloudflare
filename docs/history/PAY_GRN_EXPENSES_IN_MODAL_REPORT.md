# Pay GRN expenses inside **Make New Transaction** — one box per expense

Owner request (2026-11-05), second iteration of the Pay GRN Expenses work.

> "when i selected grn expenses and those expenses were not added in supplier
> ledger means no check in grn making time it was supposed to show in account
> new transaction pay grn expenses … only that expenses only no stock qty price
> and no expenses that are with check box but all other which are not check box
> selected but see no place for them also no separate field against each expenses
> total vs paid"

## The problem

Choosing **Pay GRN Expenses** in the transaction modal only showed a note
("this opens Pay GRN Expenses, no money is posted here") and bounced the
operator to another screen. There was no place for the expenses that were **not**
ticked "Add to supplier ledger", and no per-expense **Total / Paid / To pay**
row anywhere in the modal.

## What the modal does now

`Pay Money → Pay Target → Pay GRN Expenses → Select GRN` renders the
**per-expense payment system inside the modal** (full width, `modal-xl`):

| Row | Meaning |
|---|---|
| Expense / recipient | `Vehicle Fare — Rana Transport`, `Loading — Mazdoor`, … with its recipient type and person |
| **Total** | the full amount the operator entered on the GRN |
| **Paid** | money already spent on *that* expense (recipient route + supplier route) |
| **To pay** | `Total − Paid`, from `app/services/grn_costing.py` |
| **Pay now (Rs.)** | its own money field + **Pay full** |

Rules the screen obeys:

* **Only the expenses the supplier ledger does not carry** (the rows with no
  tick on "Add to supplier ledger") get boxes.
* **No stock**: no quantity, no rate and no material amount anywhere in the
  panel. Material is `Σ qty × rate` and is paid through the supplier bill.
* **Ticked expenses are not offered again.** They are settled with the supplier
  bill, so the panel says how many there are and how much
  (`“2 more expenses (Rs. 8,000.00) are ticked "Add to supplier ledger" and
  settled with the supplier bill, not here”`) and links to
  **Open Pay GRN Expenses** for paying one of those to its recipient instead.
* **Every row proves `Total = Paid + To pay`**, so a partially paid expense
  (paid 200 of 500) reads `500.00 / 200.00 / 300.00` instead of hiding the
  money that already moved.

## Posting

The modal is now a real payment form in this mode:

* `POST /accounts/grn_expenses/pay` writes **one `GRN_CHARGE` voucher per filled
  box** (own cash-out row, own receipt number) through the same
  `save_grn_payment()` engine and the same guards as Pay GRN Expenses
  (balance, period, account, overpayment, permission).
* Empty boxes are ignored; an empty submit is refused with
  "Enter the amount next to at least one GRN expense you want to pay."
* An over-payment is blocked both in the browser and on the server
  ("… exceeds the remaining payable …").
* The GRN-expense fields are named `grn_expense_*` (`grn_expense_grn_id`,
  `grn_expense_account_id`, `grn_expense_method`, `grn_expense_reference`,
  `grn_expense_idempotency_key`) so the same `<form>` can never hand an
  ordinary transaction's amount or account to the expense posters.
* The form's `action` switches with the target: ordinary targets keep
  `accounts.add_transaction`, Pay GRN Expenses posts to the expense route.
* The supplier ledger stays untouched by an unticked expense, and the material
  payable never moves.

## Server side

* `app/services/grn_costing.py` — new `grn_expense_payment_rows(grn)`: the
  read-side projection behind the panel (`payment_rows` = unticked expenses with
  total / paid / remaining / status / recipient, `supplier_billed_rows` = the
  ticked ones, plus the supplier-ledger due and material remaining). Built from
  `grn_breakdown()`, so the modal can never invent its own payable.
* `GET /accounts/api/grn_expense_payments/<grn_id>` — JSON for the panel
  (payable rows, accounts to pay from, permission flag). Read-only.
* `POST /accounts/grn_expenses/pay` — the per-box posting described above.
  It refuses any key that is not an unticked expense of that GRN.
* `accounts.add_transaction` still refuses `pay_target=grn_payment`; it now
  redirects straight into the per-expense mode instead of a blank breakdown.

## Tests

* `tests/test_grn_expense_modal_payments.py` (9 tests) — the row projection
  (Total/Paid/To pay, no stock, no ticked rows), the API, the modal markup,
  one voucher per filled box, no supplier-ledger movement, refusal of a ticked
  expense, overpayment / empty / missing-account refusals, and the cash-out row
  plus party ledger.
* `tests/frontend/test_grn_expense_modal_dom.js` (26 checks) — panel visibility
  per target, route switching, rows built from server data only,
  Pay full per expense, totals, overpayment block, empty-submit refusal, ticked
  expenses never offered as boxes.
  Run: `node tests/frontend/test_grn_expense_modal_dom.js` (needs `npm i jsdom`).
* `tests/frontend/test_accounts_dashboard_grn_picker_dom.js` updated for the new
  submit label ("Pay GRN expenses" — the modal pays, it no longer just links).
* Existing GRN payment suites unchanged and green:
  `test_pay_grn_expense_mode.py` (10), `test_pay_grn_screen.py`,
  `test_grn_stock_expense_split_payments.py`, `test_grn_landed_profit_e2e.py`
  (38 together), plus `checking tool/checkallapp.py` at 216/216 (100%).
