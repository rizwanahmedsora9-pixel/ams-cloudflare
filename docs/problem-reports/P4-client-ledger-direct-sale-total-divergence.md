# P4 — Client Ledger edit can desynchronize Direct Sale totals

**Status:** Guard added locally; not deployed.

The compact Client Ledger edit has no sale-line editor. When a sale has `DirectSaleItem` rows, it now rejects an amount change and directs the operator to the full Direct Sale editor, which rebuilds stock/accounting projections with the bill. Unchanged-total edits and sales without item rows retain the existing path. Route: POST `/edit_ledger_transaction/DirectSale/<id>`.

**Impact:** Prevents bill header totals diverging from line items, stock, and profit/report projections.

**Validation:** A regression test verifies that Client Ledger cannot change a DirectSale header while leaving item rows untouched. Focused suite: 31 passed. Full suite: 250 passed, 5 skipped. No schema/data changes.
