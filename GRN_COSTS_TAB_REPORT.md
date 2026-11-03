# GRN Costs tab + no paid option on a GRN

**Date:** 2026-11-03 · **Branch:** `arena/67e1b990-git-recovered`

Two owner requests from the last PR review:

1. **No paid option on a GRN.** Every paid control belongs to Accounts.
2. **A GRN Costs tab** that shows the other costs — vehicle fare, loading,
   unloading, other — next to the stock cost, filterable by cost kind,
   supplier and date range.

---

## 1. The paid option is gone from the GRN charge grid

* The per-charge **Payment Status** dropdown (`Unpaid / Paid (declaration only)
  / Not Applicable`) is removed from `templates/grn_wizard.html`, together with
  its column and the explanatory note about it.
* `static/grn_charges.js` no longer reads or validates the field:
  * the live capitalised preview counts `INVENTORY` charges only;
  * a new row still may not be saved costless — but there is no longer a
    "Not Applicable" checkbox that could bypass that check.
* `app/services/grn_costing.py::sync_charges_from_form` no longer invents a
  declaration. If a form posts no `charge_status[]` (the normal case now), a
  stored charge keeps its historical value and a new charge defaults to
  `UNPAID`; nothing about that value can change a cost, a payable or a balance.
* Dead payment-mode / bank-detail JavaScript in the wizard (it targeted
  `#paymentTypeSelect` and friends, which no longer exist on the page) was
  removed, and Step 1 is now "Select Supplier, Date & Time" — a GRN has no
  payment mode.
* Actual paid / remaining / status still come **only** from
  `Accounts -> PAY EXISTING GRN` (`app/services/grn_payments.py`). A GRN still
  creates no payment row, no cash row and no account transaction.

## 2. New **Costs** tab on the GRN screen

The records card now opens on a two-tab strip: **Records** (default, unchanged)
and **Costs**.

`Costs` lists every individual cost line of every GRN in scope:

| Column | Meaning |
|---|---|
| Date / GRN / Supplier | which document the cost belongs to |
| Cost kind | Stock material, Vehicle fare / transport, Loading, Unloading, Other |
| Detail | material name, or the charge label (e.g. "Rana Transport") |
| Recipient / person | the supplier for stock, the transporter / labourer / party for a charge |
| Qty / Rate | qty × rate for stock lines, blank for charges |
| Amount | the cost |
| Treatment | stock cost, in material cost, separate expense, not material cost |

Filters (all server-side, in the URL so a view can be bookmarked):

* **Cost kind** — `All costs | Stock / material | Vehicle fare / transport |
  Loading | Unloading | Other expenses` (`cost_kind`). Transportation is grouped
  under the vehicle kind, because it is a vehicle cost.
* **Supplier** — only suppliers that actually have GRNs (`cost_supplier`).
* **Date range** — `cost_start` / `cost_end` on the GRN posting date.

The KPI strip at the top always shows **every** kind (with its line count) plus
the total purchase cost, so narrowing the detail list never hides the whole
picture. The footer repeats the filtered total.

### Where the numbers come from

`app/services/grn_costs.py` is a pure read-side projection on top of
`grn_costing.grn_breakdown()` — the single cost authority — so:

* stock cost is exactly `Σ(qty × rate)` per line (owner rule A2);
* vehicle fare / transport, loading, unloading and other are separate lines
  with their own recipients, never folded into the supplier amount;
* cancelled / void GRNs are excluded, exactly like the records table;
* a charge added or edited in the wizard appears here immediately, because both
  screens read the same projection.

## 3. Tests

* `tests/test_grn_costs_tab.py` (new, 7 tests) — no paid control in the grid,
  GRN still creates no payment, every cost kind listed, kind / supplier / date
  filters, totals matching the filtered rows, and the projection's edge cases
  (unknown kind or date falls back instead of failing).
* `tests/frontend/test_grn_charges_dom.js` updated: the fixture row no longer
  has a paid field; it now asserts a charge row has **no** `charge_status[]`
  control and that only the amount moves the capitalised preview.
* `tests/test_grn_screen_layout.py`, `test_grn_datetime_and_sorting.py`,
  `test_grn_charge_grid_no_auto_rows.py`, `test_grn_landed_cost_*`,
  `test_grn_consumption_indicator.py`, `test_sidebar_navigation.py` all still
  pass.
