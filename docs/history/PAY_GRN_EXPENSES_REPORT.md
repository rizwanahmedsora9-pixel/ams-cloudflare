# Pay GRN Expenses — one payment system per kind of payable

Owner request (2026-11-05), implemented on **`/accounts/grn_payments`** (the
"Pay GRN Expenses" screen) and shared with the same-page split form.

## The problem reported

* On **Pay GRN Expenses** the single top "Payment amount" field sat above the
  obligation dropdown, so an operator paying a *vehicle loading / unloading*
  expense saw **one lump amount box** and, when the expense was ticked
  "Add to supplier ledger", the screen reported a **supplier-ledger-looking
  amount** for what is actually a transporter/labour expense.
* The per-expense system the owner asked for did not exist: each expense must be
  selected on its own and paid with **its own money field**, and while that
  section is open the **top single-payment field must disappear** (it is a
  different, unique payment system).
* Paying an expense must never invent a supplier amount, and the supplier ledger
  must stay exactly `stock + the expenses still ticked to the supplier`.

## What the screens do now

### Two payment modes (Pay GRN Expenses)

`2. Supplier bill` and `2. GRN expenses (one by one)` are separate renders of the
same page (`?mode=SUPPLIER|EXPENSES`):

| Supplier bill mode | GRN expenses mode |
|---|---|
| one amount field + supplier payable dropdown (stock, ticked expenses) | **no** supplier amount field at all; one money field per expense |
| list of supplier payables only | every vehicle fare / loading / unloading / other expense, each with `Amount`, `Paid`, `To pay`, `Status`, own "Pay full" |
| points at the expense system for the expenses | points back at the supplier bill for stock |

Opening an expense (`?charge_id=…`) starts directly in the expense system.

### One rupee, one place (costing authority)

`app/services/grn_costing.py` stays the single source of truth:

* `expense_route_allocation(grn)` — per expense: amount, paid to its own
  recipient, share settled through the supplier bill, and what is still open.
  Supplier expense vouchers are allocated to the ticked rows, oldest first.
* `charge_recipient_paid_minor()` / `charge_recipient_open_minor()` — payments
  already made to an expense's own recipient.
* `supplier_billed_charge_minor()` now returns only the ticked part **not yet
  paid to the recipient**, so:
  * `SUPPLIER` bill = stock + ticked-expenses-not-paid-through-recipient;
  * `EXPENSES` payable is capped at `original − paid`, so an amount the screen
    offered can never be rejected (and vice-versa);
  * paying the fare to the transporter removes exactly that money from the
    supplier payable. No double payment from either direction.
* `grn_breakdown()` lists **every** GRN expense as its own `CHARGE` obligation
  (ticked ones too, with `billed_to_supplier`, `recipient_paid`,
  `supplier_paid`). `counted_in_total_minor` keeps `total_remaining ==
  total_obligations` while a ticked expense is still carried by the supplier
  payable, so no figure is counted twice.
* `additional_remaining` is still "expenses outside the supplier ledger";
  `recipient_expenses_remaining` is every open expense (pay-box display).

### Saving

`POST /accounts/grn_payments/save` accepts either the classic supplier form or
`mode=EXPENSES` with parallel `expense_key[]` / `expense_amount[]` lists:
every filled box becomes its own `GRN_CHARGE` voucher (own cash-out row, own
receipt/voucher number), empty boxes are ignored, and the shared GRN payment
engine (`save_grn_payment`) still validates balance, period, account and
overpayment.

### Also updated

* `/accounts/pay_grn` (stock / expenses) shows the ticked expenses' own boxes
  too, labelled as "removes it from the supplier box above" — the same rule on
  the other screen, so both agree.
* Accounts dashboard picker: `GRN expenses still to pay (one by one)` (counts
  every open expense) and the supplier figure (stock + ticked, less anything
  already paid to the recipient).

## Tests

* `tests/test_pay_grn_expense_mode.py` (10 tests) — mode separation, per-expense
  vouchers, overpayment and empty-submit refusals, ticked-expense detachment
  from the supplier bill, no double payment in either direction, and the
  unchanged supplier numbers.
* `tests/frontend/test_grn_expense_payments_dom.js` — the browser contract for
  `static/grn_expense_payments.js` (Pay full per expense, totals, overpayment
  block, empty submit, permissions). Run: `node tests/frontend/test_grn_expense_payments_dom.js`
  (needs `npm i jsdom`).
* Adjusted expectations in `test_pay_grn_screen.py`,
  `test_grn_stock_expense_split_payments.py`, `test_grn_landed_profit_e2e.py`
  where the old "expenses are either supplier or recipient" assumption no longer
  holds.
* Full suite: **585 passed, 6 skipped** (0 failed). `checking tool/checkallapp.py`
  still 100% (216/216); `app/full_app_audit.py` still shows the same 8
  pre-existing seeding failures (unchanged by this work).
