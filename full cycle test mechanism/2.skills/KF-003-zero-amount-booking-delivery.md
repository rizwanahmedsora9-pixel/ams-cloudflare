# KF-003 — A booking delivery is saved with amount 0.00 and leaves no pending bill

**Severity:** high — the sale document, the invoice and the receivable disagree
**Status:** open
**Found by:** `/system_report` sync issue, then traced to the sale row

---

## Symptom

`MB NO.CYC-BD-1` / `SB-SL-1002` — a 20-bag, 30,000 delivery fulfilling booking
`MB NO.CYC-BK-1` — is stored as:

```sql
select id, category, amount, paid_amount from direct_sale where id=3;
-- 3|Booking Delivery|0.0|0.0

select product_name, qty, price_at_time, cost_rate_at_sale
  from direct_sale_item where sale_id=3;
-- DG Cement|20.0|0.0|NULL
```

Yet it correctly consumes the booking (`booking_allocation` qty 20) and moves
20 bags out of stock.

Knock-on effects:

| Surface | Shows |
|---|---|
| `/view_bill/SB-SL-1002` | 0.00 |
| `/accounts/receipts` | a `0.00 / 0.00` row |
| `/system_report` | *Missing Pending Bill Entry #9 … (CYC-CL-1)* |
| P&L | **correct** 55,000 — revenue comes from the booking, not the sale |

## Root cause

The booking-delivery path stamps the sale from the POSTed `amount`/`unit_rate`,
but the dispatch form does not populate them for a fulfilment (there is no new
price — the price lives on `booking_item.price_at_time`). The pending-bill sync
then computes:

```python
pending_amount = max(0.0, sale.amount - discount - sale.paid_amount)
#                 max(0.0, 0 - 0 - 0) = 0   -> no PendingBill row created
```

while the OUT `Entry` row **was** created, so `/system_report` reports the
missing bill.

## Impact

* The invoice for a real 30,000 delivery says 0.00.
* The receivable is invisible on `/pending_bills`, though the client ledger is
  right because it reads the booking.
* Every run raises a false "sync issue", which trains people to ignore
  `/system_report`.

## Fix

On `category == 'Booking Delivery'`, derive the value from the allocation:

```python
consumed = sum(a.qty * item.price_at_time
               for a in allocations for item in booking_items
               if a.booking_item_id == item.id)
sale.amount = consumed
sale_item.price_at_time = item.price_at_time
sale_item.cost_rate_at_sale = fifo_rate
```

Then `pending_amount` becomes 30,000 − 0 = 30,000 for the bill sync. Because the
booking's own advance already covers part of it, the pending-bill writer must
subtract the booking's `paid_amount` — see `_rent_reconciliation_from_items()`
and `void_rebuild._sync_booking_pending_bill()` for where that lives.

## Acceptance

| Check | Before | After |
|---|---|---|
| `select amount from direct_sale where id=3` | 0.0 | 30000.0 |
| `/view_bill/SB-SL-1002` total | 0.00 | 30,000.00 |
| `/system_report` sync issues | 1 | 0 |
| `Y-02` | CYC-BD-1 present | CYC-BD-1 absent |
| P&L sales | 55,000 | 55,000 (unchanged — must not double count) |

**The last row is the real test.** Fixing the document must not add revenue.
Remove `known=D_ZERO_AMOUNT_BD` from `Y-02`.
