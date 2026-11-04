# Full-app walkthrough report — `run-007-20261104T0636`

**Verdict: PASS.** The real application renders every documented page, carries
every documented form and form field, answers every link, agrees with itself on
all ten cross-page tie-outs, and completes all eight user workflows driven
through the actual HTML forms. **0 hard findings.**

This is the report that answers *"does it actually work in the app, or did you
only read the test files?"* — every line below came out of a live request against
the running application.

| | |
|---|---|
| Repository | `rizwanahmedsora9-pixel/git-recovered` |
| Branch / commit | `arena/9a9e9b43-git-recovered` @ `e8cdde0` + this audit's changes |
| Mechanism run | `1.all files/run-007-20261104T0636` — 82/86 pass, 4 known, 0 fail |
| Database | `run-007/cycle.db`, seeded from empty through 31 real HTTP form posts, then **copied** for the walk |
| Driven by | `1.all files/shared/app_walk.py` (new) — 14 s |
| Documentation compared against | `run-001/results/pages.md` (58 pages, 209 forms, 890 columns) and `full-app-work-test.md` |
| Evidence | `reports/evidence/app-walk.json`, `reports/evidence/app-walk.md` |

---

## 1. What was being asked, and what each layer can prove

The earlier report (`run-006-20261104T0609-full-app-audit.md`) did drive the real
app — it booted `create_app()`, posted forms and read rendered HTML — but its
*coverage* was the 86 figures the mechanism already knew about, plus the repo's
own 531 test files. The pages and forms the documentation describes had never
been walked as a set. That is what this report adds:

| Layer | What it drives | What it can prove | What it cannot |
|---|---|---|---|
| `pytest` (531) | Python functions and endpoints | units still behave | nothing about the running workflow |
| mechanism `checks.py` (86) | 31 form posts + rendered figures | the rupee totals are right | nothing outside those 31 flows |
| **`app_walk.py` — pages** | all 58 documented pages | the screens exist, with their forms, fields and columns | whether the numbers on them are right |
| **`app_walk.py` — routes** | all 243 sweepable GET routes | nothing 500s, nothing throws | whether a page is *useful* |
| **`app_walk.py` — links** | 214 hrefs found on those pages | navigation does not dead-end | whether the destination is meaningful |
| **`app_walk.py` — tie-outs** | 10 figures read on two pages each | the app agrees with itself | whether the shared value is correct |
| **`app_walk.py` — workflows** | 8 write flows through the real forms | a human can actually do these tasks | the accounting policy behind them |

That split is the honest answer to "test the full app": the walkthrough proves
the app *works*; only the figure checks can prove the numbers are *right*, and
there are still 8 open defects living in that half.

---

## 2. How the walk is driven

```
parse pages.md  ─► 58 pages, 209 forms, 773 named fields, 890 columns
        │
        ▼
boot(fresh=False) on a COPY of run-007/cycle.db  ─► real login (Admin)
        │
        ├─ 0. prerequisites: create a cash-flow party (see trap 3)
        ├─ 1. pages   : GET each page, strip <script>, collect real forms
        │              compare (method, action) -> field sets, columns, buttons
        ├─ 2. routes  : GET every read-only rule, decode bytes safely
        ├─ 3. links   : follow every href found (skipping /logout)
        ├─ 4. ties    : read 10 figures twice, on two different pages
        └─ 5. flows   : POST real forms; confirm on the LISTING page *and* in SQLite
```

Three details make the result trustworthy:

* **`<script>` is removed before forms are counted.** A form that exists only
  inside a JavaScript template is not a form a human can submit — that is
  precisely the confusion behind `KF-005`.
* **Prerequisites are created before asserting.** A page whose edit form lists
  rows cannot render that form when there are no rows; asserting first produces a
  false defect (traps 3 and 4 below).
* **A workflow only passes on three witnesses**: the flash message, the listing
  page, and the database row. One witness is a rumour, two is a coincidence.

---

## 3. Result at a glance

| Section | Result |
|---|---|
| Documented pages walked | **58 — 58 PASS · 0 PARTIAL · 0 FAIL** |
| Documented forms / found in markup | **209 / 209** (169 unique method+action pairs) |
| Documented form fields missing from the app | **0** of 773 |
| Documented column headers missing | **0** of 890 (after entity normalisation) |
| GET routes visited | 243 — 193 ok, 23 redirect, 21 expected 404, **0 bad** (8 destructive routes skipped) |
| Links followed | 214 — **0 dead** (2 skipped: `/logout`, an export link) |
| Page-vs-page tie-outs | **10 / 10** |
| Write workflows through real forms | **8 / 8** |
| Hard findings | **0** |

21 of the 243 routes answer 404: every one is a placeholder id on a valid rule
(`/ledger/1`, `/cash_flow_differences/1`, `/legacy-migration/run/1` …), which is
the correct answer for a row that does not exist. The 23 redirects are login/
canonicalising redirects. The 8 skipped routes are `/logout` and the
wipe/drop/reset/backup family — sweeping those would destroy the evidence
mid-run (trap 1).

---

## 4. Page-by-page result — all 58 documented pages

Every row is a real `GET`; the verdict compares the page with the documentation:
status code, forms, per-form field sets, column headers, buttons, error markers.

| # | Page | Documented title | Verdict | Status | Forms doc/found |
|---|---|---|---|---|---|
| 1 | `/` | System Dashboard | PASS | 200 | 0/0 |
| 2 | `/inventory/stock_summary` | Stock Summary | PASS | 200 | 1/1 |
| 3 | `/inventory/daily_transactions` | Daily Breakdown | PASS | 200 | 1/1 |
| 4 | `/tracking` | History / Tracking | PASS | 200 | 1/1 |
| 5 | `/grn` | GRN (Receiving) - records tab | PASS | 200 | 15/15 |
| 6 | `/grn?tab=costs` | GRN - costs tab | PASS | 200 | 3/3 |
| 7 | `/bookings` | Bookings | PASS | 200 | 3/3 |
| 8 | `/direct_sales` | Sales (direct sales) | PASS | 200 | 5/5 |
| 9 | `/material_returns` | Material Return | PASS | 200 | 2/2 |
| 10 | `/pending_bills` | Pending Bills | PASS | 200 | 6/6 |
| 11 | `/delivery_rents` | Delivery Rent | PASS | 200 | 9/9 |
| 12 | `/payments` | Payments | PASS | 200 | 1/1 |
| 13 | `/accounts/` | Accounts dashboard | PASS | 200 | 1/1 |
| 14 | `/accounts/accounts` | Manage accounts | PASS | 200 | 5/5 |
| 15 | `/accounts/accounts/add` | Add account | PASS | 200 | 1/1 |
| 16 | `/accounts/categories` | Account groups | PASS | 200 | 11/11 |
| 17 | `/accounts/transfers` | Transfers | PASS | 200 | 1/1 |
| 18 | `/accounts/receipts` | Receipts | PASS | 200 | 1/1 |
| 19 | `/accounts/expenditures` | Expenditures | PASS | 200 | 1/1 |
| 20 | `/accounts/reconciliations` | Reconciliations | PASS | 200 | 1/1 |
| 21 | `/accounts/audit` | Account audit trail | PASS | 200 | 12/12 |
| 22 | `/accounts/purchase_payables` | Purchase payables | PASS | 200 | 0/0 |
| 23 | `/accounts/payments/clients` | Client payments | PASS | 200 | 4/4 |
| 24 | `/accounts/payments/suppliers` | Supplier payments | PASS | 200 | 4/4 |
| 25 | `/accounts/grn_payments` | Pay existing GRN | PASS | 200 | 1/1 |
| 26 | `/cash_flow` | Cash Flow | PASS | 200 | 13/13 |
| 27 | `/cash_flow_differences` | Cash Flow differences | PASS | 200 | 1/1 |
| 28 | `/daily_reconciliation` | Daily reconciliation | PASS | 200 | 7/7 |
| 29 | `/profit_reports` | Profit & Loss | PASS | 200 | 1/1 |
| 30 | `/financial_details` | Financial details | PASS | 200 | 1/1 |
| 31 | `/suppliers` | Suppliers | PASS | 200 | 10/10 |
| 32 | `/clients` | Clients | PASS | 200 | 5/5 |
| 33 | `/materials` | Material Brands | PASS | 200 | 13/13 |
| 34 | `/services` | Services & Charges | PASS | 200 | 7/7 |
| 35 | `/delivery_persons` | Delivery Persons | PASS | 200 | 3/3 |
| 36 | `/ledger` | Ledger (client list) | PASS | 200 | 0/0 |
| 37 | `/client-ledger/categories` | Client categories | PASS | 200 | 7/7 |
| 38 | `/decision_ledger` | Decision Ledger | PASS | 200 | 1/1 |
| 39 | `/current_payables` | Current Payables | PASS | 200 | 1/1 |
| 40 | `/notifications` | Notifications | PASS | 200 | 2/2 |
| 41 | `/notifications/upcoming` | Upcoming reminders | PASS | 200 | 0/0 |
| 42 | `/settings` | Settings | PASS | 200 | 18/18 |
| 43 | `/settings/activity` | Settings - Who did what | PASS | 200 | 1/1 |
| 44 | `/settings/sessions` | Settings - sessions | PASS | 200 | 0/0 |
| 45 | `/settings/sidebar` | Sidebar settings | PASS | 200 | 0/0 |
| 46 | `/import_export/` | Import / Export | PASS | 200 | 5/5 |
| 47 | `/legacy-migration/` | Legacy data migration | PASS | 200 | 1/1 |
| 48 | `/data_lab/` | Data Lab | PASS | 200 | 1/1 |
| 49 | `/admin/` | Admin dashboard | PASS | 200 | 0/0 |
| 50 | `/admin/modules` | Admin modules | PASS | 200 | 0/0 |
| 51 | `/system_report` | System report | PASS | 200 | 0/0 |
| 52 | `/void_audit` | Void audit | PASS | 200 | 1/1 |
| 53 | `/dashboard` | dashboard alias | PASS | 404 | 0/0 |
| 54 | `/dispatching` | Dispatching | PASS | 200 | 1/1 |
| 55 | `/receiving` | Receiving | PASS | 404 | 0/0 |
| 56 | `/supplier_ledger/1` | Supplier ledger | PASS | 200 | 10/10 |
| 57 | `/delivery_person_ledger/1` | Delivery person ledger | PASS | 200 | 9/9 |
| 58 | `/client_ledger/2` | Client ledger | PASS | 200 | 0/0 |

**58 of 58 pages pass** — 209 of 209 documented forms found, 0 missing form fields, 0 missing columns.

Two documentation artefacts, worth knowing when reading `pages.md`:

* the doc's *column* list includes shared chrome (`Table / setting`, `In`, `Upd`,
  `Skip`, `Fail`, `Note`) that is not a column of the data table;
* some doc "buttons" are actually description text glued to a button
  (`Financial Details Balances & totals`). The walk only compares short labels
  (≤ 40 chars) and normalises HTML entities, or it would report a dozen phantom
  failures.

---

## 5. The eight workflows, end to end

Each one is a real form POST built from the fields the page itself renders. The
"observed" column is read back from the database and the listing page.

| ID | Workflow | Result | Observed |
|---|---|---|---|
| W-01 | create supplier via /add_supplier -> row + listing | PASS | `db=True page=True` |
| W-02 | create brand via /add_material -> row + listing | PASS | `db=True page=True` |
| W-03 | material return 2 bags -> stock 195->197 and return listed | PASS | `stock 195.0->197.0 listed=True` |
| W-04 | manual pending bill 4,500 -> row + /pending_bills | PASS | `row=True listed=True` |
| W-05 | reconciliation 175,500 saved -> row(diff 17,000) + page | PASS | `row=True diff=17000.0 page=True` |
| W-06 | replaying a submitted sale is refused, no duplicate row | PASS | `flash='danger: This form token was already used for a different sale. Reload the page a' sales 3->3` |
| W-07 | toggle pending bill paid flips is_paid and back | PASS | `is_paid False -> True -> False` |
| W-08 | receipt 1,000 (+cash) then void (reversed, audited) | PASS | `cash 175500.0 -> 176500.0 -> 175500.0, listed=True, is_void=1` |

Two of these are worth reading twice:

* **W-06 — the same sale submitted twice.** The second POST carries the same
  `idempotency_key`, and the app answers `danger: This form token was already used
  for a different sale` while the sale count stays at 3. The guard works and the
  duplicate is refused *before* it becomes a second invoice.
* **W-08 — money in, then reversed.** A 1,000 receipt moves cash 175,500 →
  176,500, the payment appears on the payments page, and the void link restores
  cash to 175,500 with `is_void=1` plus an audit row. Creating is easy; the
  reversal is the part that usually breaks, and it does not.

W-03 … W-05 are also the three flows the mechanism *defines but never runs*
(`KF-008`). They work in the app; the mechanism simply never called them. That is
the difference between "untested" and "broken", and it is why `KF-008` is filed as
a harness defect rather than an app defect.

---

## 6. Ten tie-outs — one figure, two pages

| ID | Figure | Where it is read twice |
|---|---|---|
| T-01 | 658,500 company money | `/accounts/` KPI and `/daily_reconciliation` |
| T-02 | 495 bags of stock | `/inventory/stock_summary` Net Movement and `/tracking` TOTAL BAGS |
| T-03 | 20,500 client net | `/clients` Payable and `/ledger/2` Net Balance |
| T-04 | 400 driver rent due | `/delivery_rents` Remaining and `/delivery_person_ledger/1` |
| T-05 | 158,500 closing cash | `/cash_flow` closing vs its own opening + received − spent |
| T-06 | 34,500 money received | `/financial_details?type=cash` TOTAL and P&L Money Received |
| T-07 | 11,600 profit | P&L income − COGS vs Profit on the same page |
| T-08 | 338,500 supplier outstanding | `/suppliers` Total Purchase − Outstanding |
| T-09 | 215,500 / 123,000 payables | `/accounts/purchase_payables` vs `/suppliers` |
| T-10 | 8,500 invoice | `/download_invoice/SB-SL-1000` PDF, `/direct_sales` row, database |

**10 / 10 pass.** Note what T-05 does *not* say: the cash-flow page is internally
consistent, yet 158,500 is still the wrong answer — `KF-001` compares a cash-only
opening against all-account movement. Internal consistency is not correctness;
that is exactly why the figure checks exist alongside this report.

---

## 7. What this report does and does not prove

**Proved, with a live request behind every claim:**

* every documented screen exists and renders its documented forms and columns;
* every documented field name still exists in the markup — no renamed input,
  no silently dropped select;
* navigation does not dead-end (214 links, 0 × 4xx);
* the app is self-consistent across ten independent readings;
* eight complete user tasks succeed, including a reversal and an idempotency
  refusal.

**Not proved — and still open:**

* the eight defects in the register (`KF-001` … `KF-008`) are *number* defects:
  the page renders, the figure is wrong. Four of them fail checks in the same
  mechanism run (82/86), which is how they stay visible;
* `/cash_flow` still has no way for a human to record a movement (`KF-005`): the
  markup has the script, not the form. The walkthrough cannot see this because
  `pages.md` documented the page *as it renders* — one reason a documentation-
  driven walk must always be paired with an intent-driven check;
* 299 of 566 routes are still never asserted (`SKL-008`), and 56 heavy
  export/backup/admin routes are skipped by policy;
* the `data-lab` sidecar path is skipped in pytest and untouched here.

---

## 8. Traps found while building the walk

| # | Trap | What happened | Fix in `app_walk.py` |
|---|---|---|---|
| 1 | Sweeping every GET route logs you out | `/logout` is a GET; after it, tie-outs read the login page and all ten "fail" | `NO_SWEEP` regex skips logout/login/wipe/reset/backup/sync, and the count is reported |
| 2 | Downloads decode as text | PDFs and XLSX exports raised `UnicodeDecodeError`, reported as 15 route failures | decode bytes with `errors="replace"`; only status and error markers matter |
| 3 | Forms that need rows | `/cash_flow` "missed" the party-edit form — the table had 0 parties | create one prerequisite row, then assert |
| 4 | HTML entities | `Date &amp; Time` reported eight real columns as missing | `html.unescape` on both the documentation and the page text |
| 5 | Re-running the tool on the same DB | a fixed idempotency key made the second receipt a duplicate | key derived from the database name |

Traps 2, 3 and 4 each produced *false defects* on the first run — the walk
reported 15 bad routes, 1 failed page and 1 failed workflow that were all the
tool's fault. They are listed here because the next person to write a walker will
hit exactly the same four.

---

## 9. Artefacts added by this run

| Artefact | What it is |
|---|---|
| `1.all files/shared/app_walk.py` | the walker: pages, routes, links, tie-outs, workflows |
| `1.all files/run-007-20261104T0636/` | the run: 86 checks, `cycle.db`, `results/app-walk.json`, `results/app-walk.md` |
| `reports/run-007-20261104T0636-real-app-walkthrough.md` | this report |
| `reports/evidence/app-walk.json` / `.md` | the full page matrix and every workflow |
| `2.skills/SKL-009-…-walk-the-real-app-page-by-page.md` | the technique, with the five traps |
| `reports/README.md` | index updated with both reports |

---

## 10. Reproducing it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. build a seeded database (real form posts, 14 s)
.venv/bin/python "full cycle test mechanism/1.all files/shared/run.py" --label real-app-walkthrough

# 2. walk the app against that database (14 s, works on a copy)
.venv/bin/python "full cycle test mechanism/1.all files/shared/app_walk.py" \
    --db "full cycle test mechanism/1.all files/run-007-20261104T0636/cycle.db" \
    --label run-007 \
    --json "full cycle test mechanism/reports/evidence/app-walk.json" \
    --md   "full cycle test mechanism/reports/evidence/app-walk.md"
```

Exit code `0` means no page, route, link, tie-out or workflow failed. To *see*
the same thing in a browser instead of the test client, start the app on the
scratch file and follow the same 58 pages:

```bash
APP_DB_PATH="$PWD/full cycle test mechanism/1.all files/run-007-20261104T0636/cycle.db" \
  .venv/bin/python main.py    # Admin / Admin@fbm12345
```
