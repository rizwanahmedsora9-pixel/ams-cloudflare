# SKL-002 — Verify a number three ways before you trust it

**Confidence:** high — this technique found every defect in the register
**Reuse:** any figure anyone quotes from this app
**Cost:** one extra query, one extra page load

---

## The rule

A total is only true if **the page**, **the database** and **the arithmetic**
agree. Any two can be wrong together; three cannot.

| Layer | What it proves | How |
|---|---|---|
| Arithmetic | the number is internally possible | compute it from `data.py` inputs |
| Database | the rows actually contain it | `db.scalar("select sum(...)")` |
| Page | the user can see it | `number_near(text, "Label", value)` |

## Worked example — the 17,000 cash-flow gap

The cash-flow page printed `Closing 158,500`. Three checks:

```
arithmetic : 200,000 + 39,500 - 81,000 = 158,500        ✓ the page is self-consistent
database   : account.balance Main Cash  = 175,500        ✗ disagrees by 17,000
page       : /accounts/ Total Cash     = 175,500        ✗ same disagreement
```

Two independent sources beating one page is the definition of a bug — and the
*exact* difference (17,000 = the bank's net movement 3,000 − 20,000) names the
cause without reading a line of code. That became `KF-001`.

If you only check arithmetic you conclude "158,500 is correct" and ship a
report that understates cash by every bank transaction in the period.

## Worked example — the pending bill that is 9,000, not 20,000

A booking owes 20,000. `/pending_bills` says 9,000.

```
arithmetic : booking 30,000 - paid 10,000 = 20,000 owed
database   : pending_bill.amount = 9,000, reason = "Booking: DG Cement"
page       : /view_bill_detail/Booking/1 -> Bill Pending 20,000   ✗ different number, same debt
```

Two pages disagree about the same obligation. Here the *explanation* is that the
pending-bill row tracks the undelivered portion while the bill view tracks the
unpaid portion — both defensible, but a user cannot tell them apart. Recorded as
"expected output, do not 'fix' to 20,000" with the reason, so a future run does
not chase it.

**Lesson:** before calling a mismatch a defect, look for a *third* page that
settles which of the two is authoritative. Sometimes the answer is "both, and
the labels are the defect."

## The three-way matrix to run on any new figure

|  | agrees | disagrees |
|---|---|---|
| arithmetic + db | page is the bug | page is right, the data is the bug |
| arithmetic + page | db is stale | db is right, the page's formula is the bug |
| db + page | arithmetic is wrong (a double count) | the whole feature is miscomputed |

## Practical shortcuts

* **Sum-by-source never ties:** group the same total by a second dimension. The
  17,000 gap was found by asking "what is the bank's net movement?" — a
  dimension the report never displayed.
* **A gap that equals a known quantity is the explanation.** 17,000 = bank net.
  495 = 530 − 35. 11,000 = 8,000 + 3,000 receipts. Always factor the difference
  before investigating.
* **Check the empty state separately.** `/financial_details?type=cash` was right
  while `type=DirectSale` printed `TOTAL Rs. 0` — a wrong-filter silent failure
  looks like a working empty state. Test a valid filter, an empty filter, and an
  **invalid** filter.
* **Assert the label, not just the number.** `20,500` appears on four pages with
  four different meanings (payable, net, outstanding, clearance).

## When to stop

Stop investigating when a gap is fully explained by a quantity the system
already knows about, and the explanation survives a *different* verification.
The 17,000 gap survived three: the account balance, the bank's own transactions,
and the filter that reproduces it per-account. That is enough to file a defect
with a fix, not just a symptom.
