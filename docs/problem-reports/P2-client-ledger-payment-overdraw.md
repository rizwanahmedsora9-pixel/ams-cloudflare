# P2 — Client Ledger payment edit can overdraw an account

**Status:** Fix implemented locally; automated test added. Runtime tests could not be run in this workspace because the previously used `/home/user/.venv` no longer exists and the system Python has no `pytest` installed. Not deployed.

## User-visible problem

Editing a receipt from Client Ledger can reduce the linked cash/bank balance by more than the account currently holds. The old route updates the payment and rebuilds its linked accounting entry without checking whether the debit caused by reducing the receipt is affordable.

**Affected page/route:** Client Ledger → Edit Payment; `POST /edit_ledger_transaction/Payment/<id>`.

**Potential report impact:** Cash/bank balances, ledgers, cash flow, daily reconciliation, and exports.

## Change

Before mutating the payment, the legacy route now calculates the reduction in minor currency units and compares it with the linked account's current balance. Since that balance already includes the original receipt, only the amount being removed is checked. If funds are insufficient, it shows an actionable error and redirects without changing the payment or account. Existing edits that do not reduce the receipt are unchanged.

## Files

- `app/blueprints/sales/_bills_edit_ledger_transaction.py` — add the pre-mutation balance guard.
- `tests/test_client_ledger_payment_edit_balance.py` — regression test for a 5,000 receipt edit when only 1,050 remains.
- `docs/problem-reports/P2-client-ledger-payment-overdraw.md` — this report.

## Validation

- `git diff --check` — passed.
- `python -m compileall` on the changed route and new test — passed.
- Focused regression suite — **31 passed**; full test suite — **250 passed, 5 skipped**.
- `git diff --check` and Python compile checks passed.

## Safety and limitations

No schema or existing data changes. Rejected edits do not alter the source payment or account balance. This guards reductions of a positive receipt against its linked account's current available balance; it does not replace broader payment-accounting or reconciliation checks. Not deployed. If rollback is needed, revert the route change and remove the regression test/report; no data rollback is needed.
