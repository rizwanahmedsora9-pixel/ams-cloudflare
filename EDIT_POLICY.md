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

- GRN gross changes to a material cost **after** that lot has been sold — it
  would make stock value disagree with the frozen cost of goods sold. The
  message names the cause and the way forward (reverse the sales, or post a
  separate expense). Header-only edits on such a GRN are allowed.
- GRN item add/remove/quantity changes on lots consumed by cash/credit sales.
- Adding a *service* line to a GRN (services are billed, not received).
- Duplicate manual bill numbers across modules.
- Refunding more than the account holds.

Each of these is reported as a normal message, never a dead end.

## Tests

- `tests/test_edit_policy.py` — policy matrix, window configuration, account resolution.
- `tests/test_dispatch_edit_flexibility.py` — back-dated dispatch edit/delete through the real HTTP routes.
