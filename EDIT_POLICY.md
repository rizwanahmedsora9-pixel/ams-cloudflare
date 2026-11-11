# Editing & deleting — no mid-CRUD blockers

The rule the shop asked for: **editing a sale, a GRN, a payment or any
transaction must go through.** A save should only be refused when the data
would be wrong, not because of a date, a permission that nobody set, or a
dropdown left empty.

## What used to block, and what happens now

| Was | Now |
| --- | --- |
| `edit_entry`: "Permission Denied: Only Admins can edit back-dated records." — any staff member editing yesterday's dispatch was sent to the dashboard with no explanation. | Shared policy (`app/services/edit_policy.py`). Normal profiles pass at any date. |
| `delete_entry`: same admins-only block, redirect to `index`, so the operator never saw why. | Same policy; refusal (if any) explains itself and returns the operator to the page they came from. |
| GRN add/edit/cancel: **every** back-dated GRN edit refused for a restricted user, even one day old. | Restricted users may edit inside the licensed window; only older records are refused. |
| GRN edit: **every** item quantity/rate change, addition and removal blocked once any part of the lot had been sold ("locked lots"). | Saved. Lines are updated in place, so a lot keeps its identity for the sale that used it, and the sales that consumed it are **re-costed** to the corrected landed cost (`app/services/grn_edit.py`). |
| GRN edit: **every** delivered-cost change (freight, loading, a corrected supplier rate) refused once stock had been delivered ("frozen sale COGS"). | Saved, and the frozen COGS of the sales that used the lot follows the corrected cost — the two no longer disagree, so the edit no longer has to be refused. |
| A GRN expense that Accounts had already paid could not be touched at all. | Increasing it, renaming it or changing its cost treatment goes through. Only lowering it **below the amount already paid** (or paying a different recipient) is refused, with the paid figure in the message. |
| A GRN with no bill number crashed the GRN page and its edit page (HTTP 500): `url_for('view_bill', bill_no='')` cannot be built. | The row renders with a disabled view/print button instead; the edit page opens and saves normally. |
| Cash sale short of its total: "Cash Sale must be fully paid. Transaction not complete." — the whole entry was lost. | Saved, with the shortfall shown as unpaid and a message telling the operator to collect it from the ledger. |
| "Select a cash/bank account…" on sale add/edit, GRN edit, booking Paid Now, and receipt/refund save. | The account is auto-picked (only active one of the expected kind, else the stable lowest-id one) and the operator is told which account was used. Only fails when **no** account of that kind exists — that is a configuration problem, not data entry. |

## The one stop that remains

A user an admin deliberately flagged with **restrict back-dated edits** cannot
change data older than the licensed window:

| Setting | Default | Meaning |
| --- | --- | --- |
| `AMS_BACKDATE_DAYS` | `90` | How far back a restricted user may still edit. |
| `AMS_BACKDATE_LIMIT` | `1` | `0` removes the limit entirely — no date-based stop at all. |
| `AMS_AUTO_PICK_ACCOUNT` | `1` | `0` turns off payment-account auto-selection. |

Why keep it: a six-month-old dispatch has already been reconciled against a
locked cash day and reported to the owner. Rewriting it silently would make the
books disagree with the reports already issued. Administrators and root are
never restricted. Every other profile is unrestricted by default — the flag is
opt-in per user, so in normal use nobody meets this stop.

## Audit

Every allowed back-dated change made by a restricted user writes one audit row
(actor, record, reason if the form carried one). The reason field is **never
required** — flexibility should not turn a correction into paperwork. Deleting
a payment still snapshots client, amount, method, bill and date before the row
is removed (`app/services/void_rebuild.py`).

## Still blocked on purpose (data integrity, not obstruction)

These are refused because the save would otherwise create stock or money that
does not exist:

- Shrinking a GRN lot **below the quantity already sold** from it, removing a
  sold lot, or renaming a delivered line to another material. The message names
  the material, the quantity already sold and the way forward (enter that much
  or more, or reverse the sales first). Nothing is saved.
- Lowering a GRN expense **below what Accounts has already paid** on it, or
  paying a different recipient than the money already went to.
- Adding a *service* line to a GRN (services are billed, not received).
- Duplicate manual bill numbers across modules.
- Refunding more than the account holds.

Each of these is reported as a normal message, never a dead end.

## Tests

- `tests/test_edit_policy.py` — policy matrix, window configuration, account resolution.
- `tests/test_dispatch_edit_flexibility.py` — back-dated dispatch edit/delete through the real HTTP routes.
- `tests/test_grn_edit_flexibility.py` — GRN edits on a lot that has already been
  sold (quantity, rate, landed charge), the re-cost of the sales that consumed
  it, the refusals that remain, and the no-bill-number page that used to 500.
