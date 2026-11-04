# SKL-005 — Prove idempotency and reversibility, not just the happy path

**Confidence:** high — replay, void and restore all verified
**Reuse:** every money-writing endpoint
**Cost:** one extra POST per endpoint

---

## Why the happy path is not enough

A payment endpoint that saves correctly can still:

* create a **second payment** when the user double-clicks
* leave the **account balance** inflated when the payment is voided
* **lose** the reversal when a GRN is cancelled after a payment

Each of those is a money bug, and none of them shows up in a passing happy-path
check. Three cheap probes catch all three.

## Probe 1 — replay the same payload

```python
payload = {...payment..., "idempotency_key": "cyc-rcpt-1"}
r1 = session.post("/accounts/payments/clients/save", payload)
r2 = session.post("/accounts/payments/clients/save", payload)      # identical
assert db.scalar("select count(*) from payment") == expected       # NOT expected+1
assert "already" in session.flash_text(r2).lower()
```

Verified behaviour on this app:

| Endpoint | Replay result |
|---|---|
| client payment | one row; info flash *already processed; no duplicate was created* |
| direct sale | one sale; the second post is recognised by `idempotency_key` |
| driver settlement | *"This settlement was already recorded"*; keys suffixed `:0`, `:1`, `:2` per slice |

## Probe 2 — reuse the key with a *different* payload

This is the half that most implementations get wrong: the same key must not
silently accept new data.

```python
payload["amount"] = "9999"
r3 = session.post("/accounts/payments/clients/save", payload)
assert "different payment" in session.flash_text(r3).lower()
```

A key collision with changed content must be a **loud error**, because it means
the client is confused about which transaction it is submitting.

## Probe 3 — void, then restore, then check the balances

```python
before = balance("Meezan Bank")
session.post(f"/accounts/payments/clients/void/{pid}")
assert balance("Meezan Bank") == before - amount       # effect reversed
assert db.one("select is_void from payment where id=?", (pid,))["is_void"] == 1
session.post(f"/accounts/payments/clients/restore/{pid}")
assert balance("Meezan Bank") == before                # effect reapplied
```

**The assertion is on the balance, not on the flag.** A void that flips
`is_void` but forgets to un-post the account transaction is exactly the bug this
catches — and it is invisible if you only check the row.

## The matrix worth running on every money path

| Probe | Passes when | Catches |
|---|---|---|
| identical replay | row count unchanged, info flash | double-click / retry bugs |
| changed-payload replay | danger flash, no write | client confusion |
| void | flag **and** balance reversed | half-reversals |
| restore | flag **and** balance reapplied | one-way voids |
| void twice | second is a no-op or a clear message | double reversals |
| source void | linked rows (`supplier_payment` ↔ GRN) stay consistent | orphan payments |

## What "reversible" means for each entity type

| Entity | Reversal must restore |
|---|---|
| payment | account balance, client receivable |
| GRN | stock quantity **and** the FIFO lot's consumed/remaining |
| sale | stock, FIFO layer, delivery rent, pending bill row |
| material return | stock, client credit note, ledger balance |
| reconciliation | nothing — it is an *observation*, not a movement (verify this!) |

That last row matters: a physical-cash reconciliation must **never** change
`account.balance`. Assert it explicitly, because "the count fixed the balance"
is a tempting bug to introduce.

## The rule that generalises

> Every write needs three tests: **once** (happy path), **twice** (replay), and
> **undone** (void/restore with balance assertions).

A suite that only tests "once" measures whether the code runs, not whether the
money is right.
