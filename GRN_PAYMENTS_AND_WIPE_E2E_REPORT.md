# GRN payments (checkbox on / off) + Data Wipe — end-to-end test report

Date: 2026-11-05
Branch: `arena/e549934e-git-recovered` (from `main` @ `851493b`)
Scope: last four merged PRs — **#34** (pay GRN expenses inside Make New Transaction),
**#33** (per-expense payment system), **#32** (rename + real GRN dues),
**#31** (stock vs expenses as separate payables) — plus the reported
*"data wipe not working"*.

---

## 1. What was asked

1. Check the last PRs.
2. Test paying a GRN in **Accounts**, **with** and **without** the per-expense
   *"Add to supplier ledger"* checkbox — **pay supplier (stock)** and **pay
   expenses**, and show the output.
3. Check the **data wipe**, which is reported as not working.

## 2. New test suite

`tests/test_e2e_grn_checkbox_payments_and_wipe.py` — **11 tests**, all through the
real HTTP screens (login → GRN form → Accounts forms → Settings wipe), with the
production CSRF gate attached to every POST.

| # | Test | Proves |
|---|------|--------|
| 1 | `test_checkbox_only_moves_the_expense_between_two_payables` | The checkbox moves an expense between two payables and changes **nothing** else (landed cost, inventory value, per-bag rate, GRN total) |
| 2 | `test_pay_supplier_route_pays_stock_then_ticked_expenses` | Accounts → Pay Supplier pays stock, then the ticked expenses, each on its own voucher |
| 3 | `test_ticked_expense_paid_to_recipient_leaves_the_supplier_bill` | A ticked expense paid to its own recipient leaves the supplier bill by exactly that amount (never payable twice) |
| 4 | `test_unticked_grn_pays_supplier_stock_and_recipients_separately` | Unticked: supplier gets stock only, each recipient is paid one by one |
| 5 | `test_mixed_checkbox_splits_the_three_expenses` | Mixed GRN (one ticked, two not) + overpayment refused |
| 6 | `test_accounts_screens_report_the_same_payables` | Pay GRN / Pay GRN Expenses / Pay Supplier / ledger screens agree with the service numbers |
| 7 | `test_print_payment_matrix` | Prints the running figures (table below) |
| 8 | `test_wipe_check_all_without_hard_override_is_refused_and_changes_nothing` | The safe path: wipe refused, nothing deleted, message names the remedy |
| 9 | `test_wipe_check_all_with_hard_override_erases_every_module` | "Check All" + override + `DELETE ALL DATA` wipes everything, keeps users/settings |
| 10 | `test_wipe_single_module_keeps_the_rest` | GRN-only wipe deletes the GRN **and its payments**, reverses the cash, keeps accounts/suppliers |
| 11 | `test_wipe_cash_flow_categories_with_grn_recipients` | Party-master wipe no longer trips over GRN expense recipients |

Routes exercised: `POST /grn`, `POST /accounts/payments/suppliers/save`,
`POST /accounts/pay_grn/save`, `POST /accounts/grn_payments/save`,
`GET /accounts/`, `GET /accounts/pay_grn`, `GET /accounts/grn_payments`,
`GET /accounts/payments/suppliers`, `GET /supplier_ledger/<id>`,
`POST /data_wipe_preview`, `POST /delete_selected_data`, `GET /settings`.

---

## 3. Checkbox on / off — the numbers

Test GRN: **100 bags × Rs. 1,500 = 150,000 stock**, plus three expenses
(Vehicle fare 5,000 · Loading 1,000 · Tea shop 500).

| Checkbox | Supplier bill | Recipients owed | Landed cost | Per bag |
|---|---:|---:|---:|---:|
| **All ticked** | **156,500** | **0** | 156,000 | 1,560 |
| **All unticked** | **150,000** | **6,500** | 156,000 | 1,560 |
| Mixed (fare only) | 155,000 | 1,500 | 156,000 | 1,560 |

Inventory / COGS is identical in every case — the checkbox is a **billing choice
only**, exactly as designed in PR #31 / #22.

### Paying the fully ticked GRN from Accounts (cash account starts at 500,000)

| Step | Supplier billed | Stock due | Ticked due | Unticked due | Total due | Cash |
|---|---:|---:|---:|---:|---:|---:|
| After GRN (no payment) | 5,000 | 150,000 | 5,000 | 1,500 | **156,500** | 500,000 |
| Pay stock 150,000 (Pay Supplier) | 5,000 | 0 | 5,000 | 1,500 | 6,500 | 350,000 |
| Pay ticked fare 5,000 (Pay GRN) | 5,000 | 0 | 0 | 1,500 | 1,500 | 345,000 |
| Pay unticked 1,000 + 500 (one box each) | 5,000 | 0 | 0 | 0 | **0** | 343,500 |

Every voucher is its own row (`GRN_MATERIAL`, `GRN_EXPENSES`, one `GRN_CHARGE`
per recipient); nothing is posted twice and `financial_integrity_audit()` is `ok`.

Spot checks that passed:

* Pay supplier 50,000 → material remaining 100,000, supplier ledger **106,500**,
  cash **450,000**.
* Then pay the ticked expenses 6,500 → expenses remaining **0**, material
  remaining **100,000** (stock never touched), cash **443,500**.
* Then pay the rest of the stock → total remaining **0**, supplier ledger **0**,
  cash **343,500** (= 500,000 − 156,500).
* Unticked GRN: supplier bill **150,000** → pay 150,000 → supplier **0**;
  the three recipients are then paid 5,000 / 1,000 / 500 and all show **0**.
* Overpaying one expense (1,001 against an open 1,000) is **refused**; the
  payable stays 1,000.

---

## 4. Data wipe — two real bugs found and fixed

### 4.1 The reported failure: a GRN that has been paid can never be wiped

Reproduced by following the **exact** Settings flow — read every
`delete_targets` checkbox the page renders (33 of them), then post them the way
the browser does with *Enable hard cleanup* + `DELETE ALL DATA`:

```
flash: "Wipe failed: the operation could not be completed and no data was
        changed."                       ← nothing deleted, on every attempt
log  : sqlite3.IntegrityError: FOREIGN KEY constraint failed
       [SQL: DELETE FROM grn]
```

Cause: `supplier_payment.grn_id`, `supplier_payment.grn_charge_id` and
`account_transaction.grn_id` are foreign keys to `grn`, but the wipe deleted the
`grn` rows **before** the payment/ledger rows (and a GRN-only wipe never
touched them at all). Any yard that had paid even one GRN — i.e. the yard this
whole PR series is about — could not be wiped.

Fix (`app/blueprints/misc/_wipe_delete_selected_data.py`):
a new `_purge_grn_payment_ledger()` helper runs **before** the GRN rows are
removed. It:

1. finds every `SupplierPayment` linked to those GRNs (including per-expense
   `grn_charge_id` payments),
2. reverses each payment's one authoritative `AccountTransaction`
   (`_void_account_tx`) and deletes both, so the cash account never keeps money
   for a document that no longer exists,
3. detaches any other ledger row attributed to the GRN (cash movement kept,
   attribution dropped),
4. is used by **both** the full wipe and the GRN-only wipe.

### 4.2 Second bug found by sweeping all 33 checkboxes

Each Settings checkbox was run on its own against a yard containing a **paid
GRN** (payment + per-expense payment + recipient parties):

* **32 / 33** wiped cleanly.
* `cash_flow_categories` still failed: `grn_charge.recipient_party_id` and
  `supplier_payment.recipient_party_id` reference `cash_flow_party`, which the
  wipe deleted before unlinking them.

Fix: the category branch now nulls those two links first (documents and money
are kept, only the party-master link is dropped) → **33 / 33** wipe cleanly.

### 4.3 After the fix

| Check | Result |
|---|---|
| Full wipe flash | `Data Wiped: Full Wipe (All Transactions, Accounts, Cash & Rentals)` |
| GRN / GRN items / charges / allocations / supplier payments | 0 |
| Suppliers, materials, clients, sales, invoices, bookings, returns, drivers, rentals | 0 |
| Accounts, transactions, cash-flow, reconciliation, cash drawer, daily locks | 0 |
| Users / roles / audit log / bill counter (reset to 1000) | survive |
| `financial_integrity_audit()` | `ok` |
| GRN screen / Accounts dashboard after the wipe | old GRN and supplier names gone |
| GRN-only wipe of a paid GRN | GRN gone, payment gone, cash restored 450,000 → **500,000** |

The blocked path (no hard-cleanup tick) still refuses the wipe, but the message
is now actionable instead of "use suspend/void workflows instead":

> Hard delete blocked for: clients, invoices, … **Nothing was deleted.** Tick
> "Enable hard cleanup for blocked datasets" and type DELETE ALL DATA to wipe
> them, or clear those boxes to wipe only the rest.

---

## 5. Third bug found while testing the ticked-expense route

Paying an **expense ticked to the supplier** directly to its recipient (a
supported path in PR #33) left the recipient's ledger showing an unexplained
**credit** — e.g. Rana Transport −5,000 after a 5,000 payment — because the
party ledger skipped every supplier-billed charge while still posting the
payment.

Fix (`app/services/financial_ledgers.py`): for a supplier-billed charge, the
party ledger now shows exactly the part settled through the recipient route
(from the single authority `expense_route_allocation`), so it reads
Charge 5,000 / Payment 5,000 / **Settled** instead of a phantom credit. The
supplier payable still drops by the same 5,000 — one rupee, one place.

---

## 6. Test runs

```bash
.venv/bin/python -m pytest -q tests/test_e2e_grn_checkbox_payments_and_wipe.py
# 11 passed

.venv/bin/python -m pytest -q -n 6 --dist loadfile      # full suite
# 594 passed, 6 skipped, 0 failed (new file run separately: 11 passed)

.venv/bin/python -m pytest -q -n 4 \
  tests/test_grn_per_expense_supplier_billing.py \
  tests/test_grn_stock_expense_split_payments.py tests/test_pay_grn_screen.py \
  tests/test_pay_grn_expense_mode.py tests/test_grn_expense_modal_payments.py \
  tests/test_grn_landed_cost_payments.py tests/test_wipe_granular.py \
  tests/test_daily_recon_wipe_and_account_reuse.py
# 68 passed

node tests/frontend/test_grn_expense_payments_dom.js   # all checks passed
node tests/frontend/test_pay_grn_dom.js                # 24 checks passed
node tests/frontend/test_grn_expense_modal_dom.js      # 26 checks passed
node tests/frontend/test_grn_charges_dom.js            # 58 passed, 0 failed
```

One-off sweep (not committed, 11 minutes): every one of the 33 Settings wipe
checkboxes on a yard with a paid GRN → **33/33 pass** after the fixes.

## 7. Files changed

| File | Change |
|---|---|
| `app/blueprints/misc/_wipe_delete_selected_data.py` | `_purge_grn_payment_ledger()` + used in full & GRN-only wipe; party-master unlink before deleting `cash_flow_party`; clearer blocked-wipe message |
| `app/services/financial_ledgers.py` | Party ledger shows the recipient-settled part of a supplier-billed GRN expense (no phantom credit) |
| `tests/test_e2e_grn_checkbox_payments_and_wipe.py` | New 11-test end-to-end suite (checkbox matrix + wipe) |

## 8. Notes / open items

* GRN expenses paid from the **Make New Transaction modal**
  (`POST /accounts/grn_expenses/pay`) are covered by the existing
  `tests/test_grn_expense_modal_payments.py` (9 tests) and
  `tests/frontend/test_grn_expense_modal_dom.js` (26 checks) — both pass; the
  new suite covers the three Accounts forms.
* A full wipe still requires the hard-cleanup tick and the stronger
  `DELETE ALL DATA` text by design; the *"Check All Datasets"* box alone does not
  delete anything (it never did).
* The visible "supplier billed" figure stays the gross billed amount after a
  recipient-route payment; the money actually owed is in *Ticked due* /
  *Total due*, which is what the screens total.
