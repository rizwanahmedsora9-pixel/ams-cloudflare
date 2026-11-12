# P3 — Client Ledger edits bypass locked/reconciled periods

**Status:** Guard added locally; not deployed.

The Client Ledger payment edit route now checks the original account posting date against both finalized account reconciliation periods and locked daily-reconciliation days. If the date is changed, it also checks the requested date before mutating the payment. A locked period/day is rejected with the service's actionable unlock/open-period message. This applies to POST `/edit_ledger_transaction/Payment/<id>`.

**Impact:** Prevents closed-day/account totals from silently changing in cash/bank ledgers, cash flow, daily reconciliation, and exports.

**Files:** `app/blueprints/sales/_bills_edit_ledger_transaction.py`; regression coverage is intended to be supplemented by existing payment/reconciliation tests.

**Validation:** A regression test now verifies a payment dated on a locked day is left unchanged. Focused suite: 31 passed. Full suite: 250 passed, 5 skipped. No schema/data changes.
