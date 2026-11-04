# Full-app test report — `run-006-20261104T0609`

**Verdict: PASS WITH KNOWN DEFECTS** — 0 unexpected failures, 4 checks failing as
documented known defects, 8 open defects in the register, and 1 **new** mechanism
defect found by this audit (`KF-008`).

| | |
|---|---|
| Repository | `rizwanahmedsora9-pixel/git-recovered` |
| Branch / commit | `arena/9a9e9b43-git-recovered` @ `e8cdde0` (+ this audit's working-tree changes) |
| Mechanism run | `1.all files/run-006-20261104T0609` (14.0 s) |
| Baseline run | `1.all files/run-005-20261104T0538` (15.9 s, before the audit's changes) |
| Environment | Python 3.11.2, venv from `requirements.txt`, SQLite scratch DB, no WeasyPrint system libs (ReportLab fallback) |
| Executed | 4 layers: mechanism (86 assertions) · pytest suite (531 tests) · route census (566 rules) · URL-map crawl (257 routes) |
| Evidence | `reports/evidence/` — every figure below is reproducible from a file there |

---

## 1. Result at a glance

| Layer | Scope | Result | Time |
|---|---|---|---|
| **Full-cycle mechanism** (`shared/run.py`) | builds the business from an empty DB through 31 HTTP write paths, then asserts 86 figures | **82 pass · 4 known · 0 fail → 95.35 %** | 14 s |
| **Seed / write paths** | 31 of 36 defined flows (see `KF-008`) | **31 / 31 ok** | included |
| **Regression suite** (`pytest`) | the repository's own tests | **531 passed · 6 skipped · 0 failed** (11 subtests) | 26 m 23 s |
| **Route census** (`shared/route_census.py`) | 566 URL rules / 563 endpoints | **267 reached (47.17 %) · 299 never mentioned** | 4 s |
| **URL-map crawl** (`shared/urlmap_smoke.py`) | every GET route on a seeded DB | **257 crawled · 0 × 5xx · 117 ok · 76 redirect · 8 × 404 · 56 skipped** | 5 s |

Exit code of the mechanism is `0`: under the mechanism's own rule, a *known*
defect is reported but does not fail the build, and there were **no unexpected
failures**.

The headline did not move from 96.47 % to 95.35 % because something broke — it
moved because this audit **added a check** (`M-01`) that documents a real gap in
the mechanism itself. 82 of 86 is 82 of 85 plus one honest "we do not run this".

---

## 2. What "full app" meant here

The mechanism's 86 checks are deep but narrow: they assert exact rupee figures on
the pages that move money. They say nothing about the other 299 routes or about
flows the harness defines but never executes. So the audit stacked four layers,
each covering the previous layer's blind spot:

```
        correctness  ──────────────────────────────────────────────
        mechanism (86)    rupee-exact figures, 31 write paths, PDFs
             │
             ├── breadth 1 ─ static census: 566 rules vs the URLs the suites mention
             ├── breadth 2 ─ live crawl: GET every read-only route on a seeded DB
             └── harness    does the suite run every flow it defines?      ← KF-008

        regressions  ──────────────────────────────────────────────
        pytest (531 tests)  the repo's own suite, unchanged, as a backstop
```

Nothing was mocked. The app was booted with `create_app()` against a throw-away
SQLite file, driven through a CSRF-aware test client, and every write in the
canonical dataset went in through an **HTTP form post** — the same endpoints a
human clicks.

---

## 3. Mechanism results — 86 assertions

| Area | Checks | Pass | Known | Fail | Key figures verified |
|---|---|---|---|---|---|
| Page availability (`V-`) | 23 | 23 | 0 | 0 | all 23 top-level pages render (200, `/` may be 302) |
| Stock & inventory (`S-`) | 9 | 9 | 0 | 0 | DG 195 · Pioneer 60 · Sand 200 · Sheet 40 · received 530 · delivered 35 · net 495 |
| Clients (`C-`) | 5 | 5 | 0 | 0 | due 46,500 · paid 26,000 · net 20,500 |
| Suppliers (`P-`) | 5 | 5 | 0 | 0 | purchase 418,500 · outstanding 338,500 · Ravi 215,500 · Kohat 123,000 |
| Accounts (`A-`) | 7 | 7 | 0 | 0 | cash 175,500 · bank 483,000 · company 658,500 · 11 transactions |
| Delivery rent (`R-`) | 5 | 5 | 0 | 0 | earned 1,400 · paid 1,000 · remaining 400 |
| Profit & loss (`L-`) | 7 | 6 | 1 | 0 | sales 55,000 · COGS 43,400 · profit 11,600 · received 34,500 · margin 21.09 % |
| Financial details (`F-`) | 3 | 3 | 0 | 0 | cash 34,500 · credit 31,500 |
| Cash flow (`W-`) | 7 | 5 | 2 | 0 | opening 200,000 · received 39,500 · spent 81,000 · closing 158,500 |
| PDF documents (`D-`) | 5 | 5 | 0 | 0 | P&L / client ledger / supplier ledger / invoice / clearance — content asserted, not bytes |
| Receipts page (`Q-`) | 2 | 2 | 0 | 0 | page renders; the wrong "GRN Paid 0.00" is asserted as *known-broken* |
| System report (`Y-`) | 3 | 3 | 0 | 0 | page renders; two known disagreements asserted as known-broken |
| Dead links (`X-`) | 4 | 4 | 0 | 0 | `/dashboard`, `/journal`, `/call_center`, `/inventory/history` are 404 by design |
| Mechanism (`M-`) | 1 | 0 | 1 | 0 | **new** — phase-2 write flows are unreachable (`KF-008`) |
| **Total** | **86** | **82** | **4** | **0** | **95.35 %** |

Seed: all 31 write paths returned the flash a human would see — suppliers, 3
categories, 4 materials, service, client, driver, 2 accounts, 6 GRNs, booking, 3
sales, 2 client receipts, GRN payment, supplier payment, driver settlement,
cash-flow category and entry. 35 of 77 tables ended the run non-empty; the
per-table counts are in `evidence/cycle-counts.json` (e.g. `grn` 6, `direct_sale`
3, `payment` 2, `supplier_payment` 2, `delivery_rent` 3, `entry` 9,
`account_transaction` 11, `pending_bill` 3, `audit_log` 34).

### The four known failures (reported, not build-breaking)

| Check | Defect | Observed | Expected | Meaning |
|---|---|---|---|---|
| `L-07` | `KF-007` | `26.73` absent | present | `markup_pct` is computed on every P&L but rendered nowhere |
| `W-07` | `KF-005` | `id="cfRecordForm"` absent | present | `/cash_flow` ships JS for a form the markup never renders |
| `W-06` | `KF-008` *(was `KF-001`)* | `None` | `17000.0` | the reconciliation row is never written — `seed.mutate()` is dead code |
| `M-01` | `KF-008` | `phase-2 stages run: 0` | `5` | same root cause, asserted directly against the harness |

Five further checks **pass while describing broken behaviour** — that is the
mechanism's design: `W-05` (closing 158,500 instead of 175,500, `KF-001`), `Q-02`
("GRN Paid 0.00" despite a 60,000 payment, `KF-002`), `Y-02` (no pending bill for
the 30,000 zero-amount booking delivery, `KF-003`), `Y-03` (stock KPI 2 vs body
"none found", `KF-006`), `F-03` (`TOTAL Rs. 0` for an unknown `type`, `KF-004`).
Each flips to red the day the defect is fixed, which is how the register stays
alive.

---

## 4. Regression suite — 531 tests

```
531 passed, 6 skipped, 1 warning, 11 subtests passed in 1583.28s (0:26:23)
```

* Run unmodified (`pytest -q -rs`), same commit, same venv, twice — identical
  counts both times (1591 s, then 1583 s). Log: `evidence/pytest-full.log`.
* The 6 skips are **not** environment noise, they are one gate repeated:
  `tests/test_full_db_sidecar.py` needs a *"data-lab v4.4 template"* that is not
  in the repository, so six tests of the DB-sidecar/sync path cannot run here or
  in CI (see §7.5).
* One `SAWarning` worth a ticket of its own (see §7.4): `DELETE on grn_item
  expected to delete 1 row(s); 0 were matched` in
  `app/services/void_rebuild.py:768`, triggered by
  `tests/test_hard_delete_supplier.py`.
* Running both layers is deliberate: pytest proves *units and endpoints* still
  behave, the mechanism proves the *numbers a business would quote* are right.
  A defect can pass one and fail the other, and this audit produced exactly such
  a case (`KF-008`: endpoints fine, mechanism blind).

---

## 5. New findings from this audit

### 5.1 `KF-008` — `seed.mutate()` is dead code; 5 of 36 write flows never run (high)

`checks.py` W-06 asserted a reconciliation difference of 17,000 and had been
failing as "known `KF-001`" for every recorded run. The row it reads was simply
never created: `seed.py` defines `mutate()` (phase 2: material return, manual
pending bill, reconciliation save, idempotency replay, bill toggle) and **never
calls it** — `grep -n "mutate(" seed.py` returns the `def` and nothing else.

Probe (`1.all files/run-005-…/scripts/probe_mutate_gap.py`):

```
seed() calls mutate()?        False
phase-1 stages                31        ← what "31/31 ok" measures
phase-2 stages (unreachable)  5         ← never executed, by anyone
   [ok ] material return / pending bill / reconciliation /
   [ok ] idempotent replay rejected / toggle bill paid     ← they all work when run
stock DG before/after         195.0 -> 197.0               ← so they are not free
```

Consequences, all of them reportable:

1. the run's "31/31 write paths ok" is **31 of 36** defined flows (86 %);
2. `W-06` could never pass, and it blamed `KF-001` — a scope bug — for what is a
   missing call, so the register's attribution drifted;
3. reconciliation, material returns, manual pending bills and the idempotency
   guard have **no** full-cycle coverage at all, even though
   `KF-003` is literally a *missing pending bill* defect;
4. wiring it in is not a one-line fix: phase 2 changes ≥ 4 canonical figures
   (`stock_dg` 195 → 197, `pending_bill` 3 → 4, `payment` 2 → 3, P&L profit), so
   `data.py:EXPECT` must be re-derived in the same commit.

**Actions taken by this audit:** `KF-008` written with reproduction, root cause
and two fix options; `W-06` re-attributed to `KF-008`; new check `M-01` added
(static, `inspect.getsource(seed.seed)`) so the gap cannot silently return and
flips green by itself once the flow is wired. **Deliberately not done:** wiring
`mutate()` in, because that changes the canonical dataset and belongs to a
deliberate data decision, not to a test audit.

### 5.2 Breadth is 47 %, not 96 % (`SKL-008`)

The 95.35 % pass rate describes **assertions**, not the app. Census of the URL
map against every URL literal in the mechanism and the pytest suite:

| | |
|---|---|
| URL rules / endpoints | 566 / 563 |
| Reached by a URL literal | 267 (exact 165, f-string prefix 102) |
| Never mentioned by any suite | 299 |
| Static coverage | **47.17 %** |

Gaps by blueprint: `(app)` 127 · `misc` 28 · `accounts` 26 · `system` 22 ·
`import_export` 19 · `sales` 12 · `ledgers` 11 · `masters` 11 · `api` 10 ·
`reports` 9 · `auth` 7 · `legacy_migration` 6 · `data_lab` 4 · `admin` 3 ·
`ops` 3 · `inventory` 1. Full list: `evidence/route-coverage.md`.

This number is a **floor**, not a measurement of untested code: routes reached
via `url_for()` are invisible to a static census. It is still the honest way to
say "the suite names 267 of 566 routes", and it is now a metric that can be
watched run over run.

### 5.3 Every GET route still renders — 0 × 5xx

The crawl is the counterweight to §5.2: 257 read-only routes were visited on a
copy of the run's database, and **none returned 5xx or raised**. 117 rendered,
76 redirected (auth/permission or a canonicalising redirect), 8 returned 404 for
an id that genuinely does not exist, 56 were skipped by name
(`export|download|backup|sync|import|migrate|admin|wipe|reset|restore|repair|rebuild`).

The 8 × 404 are the same four rules twice (two endpoints per rule) and are all
correct behaviour for a placeholder id:

```
/cash_flow_differences/1          /delivery_rents/group/test
/legacy-migration/run/1           /legacy-migration/run/1/errors.xlsx
```

So: the routes nobody *asserts* on are not broken — they are unmeasured. That is
a weaker but genuinely different statement from "they work".

---

## 6. Defect register after this audit

| ID | Severity | Title | Status | Proven by |
|---|---|---|---|---|
| `KF-001` | high | Cash-flow closing mixes a cash-only opening with all-account movement | open — understates cash on hand by 17,000 | `W-05` |
| `KF-002` | medium | Receipts page reports "GRN Paid 0.00" despite real GRN payments | open | `Q-02` |
| `KF-003` | high | Booking delivery stored with amount 0.00 and no pending bill | open | `Y-02` |
| `KF-004` | low/high | `/financial_details` prints `TOTAL Rs. 0` for any unknown `type` | open | `F-03` |
| `KF-005` | medium | `/cash_flow` ships JS for a form missing from the markup | open — feature unreachable for a human | `W-07` |
| `KF-006` | low | `/system_report` stock KPI says 2 while its body says "none found" | open | `Y-03` |
| `KF-007` | low | `markup_pct` computed on every P&L but rendered nowhere | open (feature gap) | `L-07` |
| **`KF-008`** | **high** | **`seed.mutate()` is dead code: five write flows have never run** | **open — new this audit** | **`W-06`, `M-01`** |

No defect was fixed by this audit, and none was closed. Two were re-attributed
truthfully (`W-06`: `KF-001` → `KF-008`).

---

## 7. Observations that are not yet defects

**7.1 `KF-001` and `KF-003` interact on the same period.** The 17,000 cash-flow
difference is exactly `physical 175,500 − calculated 158,500`, and the
calculated figure is the all-account closing presented against a cash-only
opening. Until `KF-001` is fixed, any reconciliation saved through the UI will
report a "difference" that is not a shrinkage. Worth stating in the fix itself.

**7.2 WeasyPrint falls back silently.** The PDF checks pass (D-01…D-05, content
asserted) but the log opens with "WeasyPrint could not import some external
libraries", i.e. every PDF in this environment is rendered by the ReportLab
fallback. Good news for the fallback, bad news for PDF *layout* coverage: no run
in this environment has ever exercised the primary engine.

**7.3 The suite's 26-minute runtime is an adoption risk.** 531 tests at ~3 s each
means nobody runs it before pushing. The mechanism runs the business in 14 s; a
`--maxfail`/marker split (fast business layer vs slow report layer) would keep
the loop honest without requiring patience.

**7.4 One `SAWarening` to watch.** `DELETE on grn_item expected to delete 1
row(s); 0 were matched` (`app/services/void_rebuild.py:768`) during
`test_hard_delete_supplier_with_grn_and_payments`. Harmless today — the test
passes — but it is the signature of a rebuild path that thinks a row exists when
it does not, which is the class of bug `KF-003` belongs to.

**7.5 Six tests are permanently skipped — `data-lab v4.4 template not present`.**
Every skip in the suite is the same fixture in `tests/test_full_db_sidecar.py`
(lines 63–106), so the `full_db_sync` sidecar path is *entirely* unverified by
pytest in this checkout — and the full-cycle mechanism does not touch it either.
Combined with the 19 `import_export` route gaps (§5.2), the data-movement
surface is the least tested part of the app. Either ship the template as a test
fixture or delete the tests; a skip that is always skipped is a comment.

**7.6 56 "heavy" routes are never crawled.** Exports, backups, admin and
migration routes are excluded by name from the smoke crawl. Five of them are
covered by explicit PDF checks (`D-01…D-05`); the rest remain unmeasured, and
`import_export` (19 gaps) plus `legacy_migration` (6 gaps) are the largest
untouched families.

---

## 8. What this audit added to the mechanism

The mechanism's own rule: *a run that adds nothing is allowed, but it must say
so.* This run added:

| Artefact | What it is |
|---|---|
| `1.all files/run-006-20261104T0609/` | the run: `results.json`, `counts.json`, `report.md`, `cycle.db`, seed artefacts |
| `2.skills/KF-008-mutate-phase-never-runs.md` | new defect: reproduction, root cause, two fixes, acceptance |
| `2.skills/SKL-008-…-measure-breadth-not-just-correctness.md` | new skill: census + crawl + harness audit, with paste-ready code |
| `1.all files/shared/route_census.py` | reusable tool: URL map vs suite literals → gap list |
| `1.all files/shared/urlmap_smoke.py` | reusable tool: crawl every read-only route on a seeded DB copy |
| `checks.py` `M-01` + re-attribution of `W-06` | the new gap is asserted, not just described |
| `reports/` | this report, its evidence, and a template for the next one |
| `README.md` §Reports | the rule for how a report is written and what it may claim |

Checks went 85 → 86, pass rate 96.47 % → 95.35 %, known defects 3 → 4 — a
*descending* trend that is the correct direction of travel: the suite now admits
to one more thing it does not do.

---

## 9. Recommendations, in priority order

1. **Fix `KF-001` (cash-flow scope)** — it is the only known defect that makes a
   business number *wrong* rather than unreachable, and it contaminates every
   reconciliation a user saves. Fix: build the opening from the same scope as the
   movement (all accounts), or compute the closing per account and sum.
2. **Decide `KF-008` deliberately** — either wire phase 2 with a re-derived
   `data.py:EXPECT` (option a in the KF: keep phase 1 canonical, assert phase 2
   separately, no `EXPECT` churn), or delete `mutate()` and re-word the README's
   "31/31" claim. Leaving dead code that a report quotes as coverage is the worst
   of the three.
3. **Fix `KF-003`** — a 30,000 delivery that stores 0.00 and creates no
   receivable is the highest-consequence data bug in the register, and it is
   invisible to anyone reconciling totals.
4. **Restore the `#cfRecordForm` markup (`KF-005`)** — cheapest fix in the
   register; the backend is already correct.
5. **Close the top breadth gaps** rather than chasing the percentage: `accounts`
   (26), `system` (22), `import_export` (19) are the families that move money or
   delete data. One endpoint each per PR is enough to keep the number moving.
6. **Watch coverage as a metric** — commit `reports/evidence/route-coverage.json`
   each audit and diff `coverage_pct` between runs; that turns "did we test more?"
   into a number instead of a feeling.

---

## 10. Reproducing this report

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. the mechanism (14 s) — writes 1.all files/run-NNN-*/ and updates the ledger
.venv/bin/python "full cycle test mechanism/1.all files/shared/run.py" --label full-app-audit

# 2. the repo's own suite (26 m)
.venv/bin/python -m pytest -q -rs

# 3. breadth: census (4 s) and crawl (5 s)
.venv/bin/python "full cycle test mechanism/1.all files/shared/route_census.py" \
    --label run-006 --json "full cycle test mechanism/reports/evidence/route-coverage.json" \
    --md "full cycle test mechanism/reports/evidence/route-coverage.md"
.venv/bin/python "full cycle test mechanism/1.all files/shared/urlmap_smoke.py" \
    --db "full cycle test mechanism/1.all files/run-006-20261104T0609/cycle.db" \
    --label run-006 --json "full cycle test mechanism/reports/evidence/urlmap-smoke.json" \
    --md "full cycle test mechanism/reports/evidence/urlmap-smoke.md"

# 4. the new defect's probe
.venv/bin/python "full cycle test mechanism/1.all files/run-005-20261104T0538/scripts/probe_mutate_gap.py"
```

Exit code `0` from step 1 means no **unexpected** failure. To debug a failure
without re-seeding, boot the run's own database with `fresh=False` — never with
the default `fresh=True`, which deletes it.

---

## 11. Evidence index

| File | Contents |
|---|---|
| `evidence/cycle-results.json` | all 86 checks of `run-006`, machine-readable |
| `evidence/cycle-report.md` | the run's own auto-generated report |
| `evidence/cycle-counts.json` | row count for all 77 tables after the run |
| `evidence/route-coverage.md` / `.json` | 566 rules, 267 reached, 299 gaps (per blueprint) |
| `evidence/urlmap-smoke.md` / `.json` | 257 crawled routes with status and verdict |
| `evidence/pytest-full.log` | the 531-test suite, verbatim |
| `evidence/probe-mutate-gap.json` | phase-2 write flows and the figures they move |

---

## Appendix — every check in `run-006-20261104T0609`

| ID | Result | Check | Observed | Expected |
|---|---|---|---|---|
| `V-/` | PASS | GET / | `200` | `(200, 302)` |
| `V-/accounts/` | PASS | GET /accounts/ | `200` | `(200,)` |
| `V-/accounts/accounts` | PASS | GET /accounts/accounts | `200` | `(200,)` |
| `V-/accounts/payments/clients` | PASS | GET /accounts/payments/clients | `200` | `(200,)` |
| `V-/accounts/payments/suppliers` | PASS | GET /accounts/payments/suppliers | `200` | `(200,)` |
| `V-/accounts/grn_payments` | PASS | GET /accounts/grn_payments | `200` | `(200,)` |
| `V-/pending_bills` | PASS | GET /pending_bills | `200` | `(200,)` |
| `V-/decision_ledger` | PASS | GET /decision_ledger | `200` | `(200,)` |
| `V-/material_returns` | PASS | GET /material_returns | `200` | `(200,)` |
| `V-/grn` | PASS | GET /grn | `200` | `(200,)` |
| `V-/bookings` | PASS | GET /bookings | `200` | `(200,)` |
| `V-/direct_sales` | PASS | GET /direct_sales | `200` | `(200,)` |
| `V-/delivery_persons` | PASS | GET /delivery_persons | `200` | `(200,)` |
| `V-/materials` | PASS | GET /materials | `200` | `(200,)` |
| `V-/services` | PASS | GET /services | `200` | `(200,)` |
| `V-/client-ledger/categories` | PASS | GET /client-ledger/categories | `200` | `(200,)` |
| `V-/settings` | PASS | GET /settings | `200` | `(200,)` |
| `V-/admin/` | PASS | GET /admin/ | `200` | `(200,)` |
| `V-/void_audit` | PASS | GET /void_audit | `200` | `(200,)` |
| `V-/notifications` | PASS | GET /notifications | `200` | `(200,)` |
| `V-/import_export/` | PASS | GET /import_export/ | `200` | `(200,)` |
| `V-/legacy-migration/` | PASS | GET /legacy-migration/ | `200` | `(200,)` |
| `V-/system_report` | PASS | GET /system_report | `200` | `(200,)` |
| `S-01` | PASS | DG stock | `195.0` | `195.0` |
| `S-02` | PASS | Pioneer stock | `60.0` | `60.0` |
| `S-03` | PASS | Sand stock | `200.0` | `200.0` |
| `S-04` | PASS | Sheet stock (rent-word trap) | `40.0` | `40.0` |
| `S-05` | PASS | stock_summary renders | `200` | `200` |
| `S-06` | PASS | Total Received 530 | `see text` | `530.0` |
| `S-07` | PASS | Total Delivered 35 | `see text` | `35.0` |
| `S-08` | PASS | Net Movement 495 | `see text` | `495.0` |
| `S-09` | PASS | tracking TOTAL BAGS 495 | `see text` | `495.0` |
| `C-01` | PASS | clients page renders | `200` | `200` |
| `C-02` | PASS | Payable (This Page) 20,500 | `see text` | `20500.0` |
| `C-03` | PASS | ledger Total Due 46,500 | `see text` | `46500.0` |
| `C-04` | PASS | ledger Total Paid 26,000 | `see text` | `26000.0` |
| `C-05` | PASS | ledger Net Balance 20,500 | `see text` | `20500.0` |
| `P-01` | PASS | suppliers page renders | `200` | `200` |
| `P-02` | PASS | Total Purchase 418,500 | `see text` | `418500` |
| `P-03` | PASS | Outstanding 338,500 | `see text` | `338500.0` |
| `P-04` | PASS | Ravi payable 215,500 | `see text` | `215500.0` |
| `P-05` | PASS | payables Kohat 123,000 | `see text` | `123000` |
| `A-01` | PASS | Main Cash balance | `175500.0` | `175500.0` |
| `A-02` | PASS | Meezan Bank balance | `483000.0` | `483000.0` |
| `A-03` | PASS | company total | `658500.0` | `658500.0` |
| `A-04` | PASS | accounts dashboard renders | `200` | `200` |
| `A-05` | PASS | company KPI 658,500 | `see text` | `658500.0` |
| `A-06` | PASS | daily recon expected 658,500 | `see text` | `658500.0` |
| `A-07` | PASS | account transactions = 11 | `11` | `11` |
| `R-01` | PASS | rent page renders | `200` | `200` |
| `R-02` | PASS | rent earned 1,400 | `see text` | `1400.0` |
| `R-03` | PASS | rent paid 1,000 | `see text` | `1000.0` |
| `R-04` | PASS | rent remaining 400 | `see text` | `400.0` |
| `R-05` | PASS | driver ledger closing 400 | `see text` | `400.0` |
| `L-01` | PASS | P&L renders | `200` | `200` |
| `L-02` | PASS | Sales 55,000 | `see text` | `55000.0` |
| `L-03` | PASS | COGS 43,400 | `see text` | `43400.0` |
| `L-04` | PASS | Profit 11,600 | `see text` | `11600.0` |
| `L-05` | PASS | Money Received 34,500 | `see text` | `34500.0` |
| `L-06` | PASS | margin 21.09% | `True` | `True` |
| `L-07` | KNOWN | markup_pct is computed but never rendered (known gap) | `False` | `True` |
| `F-01` | PASS | cash detail TOTAL 34,500 | `see text` | `34500.0` |
| `F-02` | PASS | credit detail TOTAL 31,500 | `see text` | `31500.0` |
| `F-03` | PASS | unknown type renders empty TOTAL 0 (known defect) | `True` | `False` |
| `W-01` | PASS | cash flow renders | `200` | `200` |
| `W-02` | PASS | opening 200,000 | `see text` | `200000.0` |
| `W-03` | PASS | received 39,500 | `see text` | `39500.0` |
| `W-04` | PASS | spent 81,000 | `see text` | `81000.0` |
| `W-05` | PASS | closing 158,500 (cash-only opening vs all-account movement) | `see text` | `158500.0` |
| `W-06` | KNOWN | reconciliation difference 17,000 | `None` | `17000.0` |
| `W-07` | KNOWN | record-movement form present in markup | `False` | `True` |
| `D-01` | PASS | PDF /profit_reports/export/pdf (57040B) ok | `200 57040B ok` | `200 >1kB Profit & Loss ['55,000', '11,600']` |
| `D-02` | PASS | PDF /download_client_ledger/2 (46725B) ok | `200 46725B ok` | `200 >1kB Total Due ['46,500', '20,500']` |
| `D-03` | PASS | PDF /download_supplier_ledger/1 (5150B) ok | `200 5150B ok` | `200 >1kB SUPPLIER LEDGER ['215,500']` |
| `D-04` | PASS | PDF /download_invoice/SB-SL-1000 (44571B) ok | `200 44571B ok` | `200 >1kB INVOICE ['8,500']` |
| `D-05` | PASS | PDF /download_client_clearance/2 (46240B) ok | `200 46240B ok` | `200 >1kB Outstanding ['20,500']` |
| `Q-01` | PASS | receipts page renders | `200` | `200` |
| `Q-02` | PASS | GRN Paid is 0 despite a 60,000 GRN payment (known defect) | `see text` | `0.0` |
| `Y-01` | PASS | system report renders | `200` | `200` |
| `Y-02` | PASS | missing pending bill for zero-amount delivery (known defect) | `True` | `False` |
| `Y-03` | PASS | stock KPI/body disagree (known defect) | `see text` | `True` |
| `X-/dashboard` | PASS | /dashboard is 404 (documented dead link) | `404` | `404` |
| `X-/journal` | PASS | /journal is 404 (documented dead link) | `404` | `404` |
| `X-/call_center` | PASS | /call_center is 404 (documented dead link) | `404` | `404` |
| `X-/inventory/history` | PASS | /inventory/history is 404 (documented dead link) | `404` | `404` |
| `M-01` | KNOWN | phase-2 write flows reachable from seed.seed() | `phase-2 stages run: 0` | `5` |

Totals: **82 passed / 86 checks**, 4 known, 0 unexpected failure(s), pass rate **95.35 %**.
