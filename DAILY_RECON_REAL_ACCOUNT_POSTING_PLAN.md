# Daily Reconciliation → Real Balances via Two Counter Accounts — Posting Plan (v2)

**Status:** **IMPLEMENTED 2026-11-07** (P0 + P1 + P1b + templates + tooling).
This document is kept as the design record; the shipped behaviour and its exact
semantics are summarised at the end (§16 “What shipped”).
**Date:** 2026-11-07 · **Branch:** `arena/4e939caf-git-recovered` · **Repo:** `rizwanahmedsora9-pixel/git-recovered`
**Supersedes:** v1 (one-sided `Reconciliation Loss/Excess` posting). Your two-account
strategy replaces it — it is stricter, because nothing is invented and the pair always
nets to zero.

---

## 1. Your rule, written as accounting

Two standing counter accounts, created once, invisible in every normal picker:

| Account | Holds | Normal balance |
|---|---|---|
| **Counter Less Account** (a.k.a. “Shortage / Cash-In-Transit”) | every rupee that was **counted less** than the app expected | positive (asset-like: money missing from the drawer) |
| **Counter Excess Account** (“Cash Over”) | every rupee that was **counted more** than the app expected | negative (liability-like: unknown extra cash) |

Every difference posts **one paired transfer** — two `AccountTransaction` rows that
always sum to zero:

```
LESS    (counted < expected):  FBM  ──100──▶  Counter Less Account
EXCESS  (counted > expected):  Counter Excess Account  ──100──▶  FBM
```

Your two examples, exactly:

```
FBM app 1,000 · counted 900 · difference −100   →  FBM  ──100──▶ Counter Less
    FBM.balance 1,000 → 900        Counter Less.balance 0 → +100
    App now equals the drawer. The 100 did not disappear — it is parked,
    visible, in one named account.

FBM app 900 · counted 1,000 · difference +100   →  Counter Excess ──100──▶ FBM
    FBM.balance 900 → 1,000        Counter Excess.balance 0 → −100
    The unknown surplus is credited to FBM so the app matches the cash box,
    and the counter account carries the −100 until you find where it came from.
```

Because both legs are real `AccountTransaction` rows, **Σ balances never changes** — you
only moved the unexplained part into a bucket that has a name, an owner and a history.
That is why this is better than v1: v1 was a one-sided entry whose other side existed only
as a P&L label; your version has a real second account you can look at on any screen.

---

## 2. The four screens this touches, and what each one shows

### 2.1 Daily board (`/daily_reconciliation`)

Unchanged entry flow: you type the physical count. Still **reporting-only until you
finalise the day** — that part of today's behaviour is correct and stays.

### 2.2 Lock (Finalize & Lock Day)

At lock, for each account that has a typed count and a non-zero difference, post the pair
with the day's date, then freeze the day. After the commit:

```
board opening next day  ==  Account.balance  ==  ledger_balance()  ==  counted
```

and the counter accounts show:

```
Counter Less Account      Rs. 100  (Dr)   ← 1 shortage on FBM, 2026-11-06
```

### 2.3 Differences report (`/daily_reconciliation/differences`)

Each row keeps the existing shape (day, account, expected, counted, difference%) and gains
the **transfer it created**:

| Day / account | Expected | Counted | Diff | Entry posted | Status |
|---|---|---|---|---|---|
| 2026-11-06 · FBM | 1,000 | 900 | −100 | `FBM → Counter Less · ATX-4412 / ATX-4413` | **OPEN** |
| 2026-11-05 · FBM | 5,000 | 5,050 | +50 | `Counter Excess → FBM · ATX-4390 / ATX-4391` | SETTLED by admin · 05-11 22:14 |

That is your “it shows that it sent to the counter less account” behaviour.

### 2.4 Solving a difference (your grey-out requirement)

There are exactly **two** ways a difference row can close, and they must not be mixed —
this is where such systems usually rot:

**Path A — the count was wrong** (corrected before the lock, or after unlocking the day)

Open the day on the board, fix the number, save. The existing `_sync_difference()`
(`app/services/cash_day_recon.py:551`) already marks the old row `settled` (count now
equals expected) or `superseded` (changed, still different) and stores
`closed_by / closed_at / closed_expected / closed_counted`. **Already implemented today.**

* If the day was **never locked**, nothing was posted — there is nothing to unwind, the
  row simply greys out.
* If the day **was locked**, you unlock first (§6 event 2), which removes that lock’s pair
  and records who did it; the corrected count is then re-locked and a fresh pair is
  posted for whatever difference remains.

**Path B — the count was right, and you find out what happened to the money**
(the normal case, and the one your counter accounts exist for)

A locked day’s closing is a fact: the drawer really did hold 900. You do not un-post it.
You record the **explanation** as a real transaction on the differences page →
**“Resolve”**:

| Situation | Entry posted on resolve |
|---|---|
| shortage recovered by a cashier | `Counter Less Account → FBM`, amount 100 |
| shortage written off | `Counter Less Account → (expense)` — “Cash shortage written off”, P&L other loss |
| excess returned / corrected | `FBM → Counter Excess Account`, amount 100 |
| excess recognised as income | `(other income) → Counter Excess Account` |

The difference row is linked to that transaction and renders grey, exactly as you asked:

> **RESOLVED** · by *admin* · 07-11-2026 09:41:18
> by entry `Counter Less → FBM · ATX-4471` · *admin* · 07-11 09:41
> counter account now: **Rs. 0**

So the row tells you *who* solved it, *when*, and *which entry* did it — and the counter
account nets back to zero through a real explanation instead of a silent deletion. Path B
requires a reason and is admin-permission only.

---

## 3. Why a mirrored reversal, not a deletion

| Option | Result |
|---|---|
| Delete the original posting pair when the difference is solved | ❌ Ledger loses the fact that a shortage was ever posted; account balance history rewrites itself; the balance at the time of the lock can no longer be reproduced. |
| **Post the mirror pair (this plan)** | ✅ Ledger stays append-only and reproducible. Counter Less ends at 0, FBM ends at the correct counted figure, and the four rows tell the whole story. |
| Void (`is_void = 1`) | ❌ Rule 4 below — the boot purge deletes void rows with raw SQL without unwinding `Account.balance`. |

`void` is therefore never used here. Mirror-posting is the same discipline the app already
applies to client/supplier payments (`_sync_linked_receipt_tx` voids and recreates only
where it also re-applies the effect; here we avoid the void path entirely).

---

## 4. Why these two accounts cannot be abused or accidentally used

The app decides “is this a money account?” in exactly two places:

* `_cf_is_money_account()` — `app/services/cash_flow_svc.py:512` → `category in ('cash','bank')` **and** `is_active`
* `_cf_company_accounts()` — `app/services/cash_flow_svc.py:520` → same filter (this is what the board loops over)

…and every payment / GRN / driver / cash-flow picker repeats that filter
(`app/blueprints/accounts/grn_payments.py:41`, `app/blueprints/ledgers/delivery_person.py:50`,
`app/services/payments_crud.py:174`, `blueprints/accounts/transactions.py`).

So the two counter accounts are created with:

| Field | Value | Why |
|---|---|---|
| `category` | **`'recon'`** (not `cash`/`bank`) | excluded from the board, from cash-flow in/out totals, and from **every** payment picker by the existing filters — no code change in those 10+ places |
| `account_type` | `'recon_counter'` | hides them from `_company_accounts`-style lists that filter `account_type == 'company'` |
| `account_status` / `is_active` | `active` | they must keep accepting postings and stay visible in the Accounts list |
| `channel` | `ledger_only` | no cash/bank instrument attached |
| `class_category` / `class_subcategory` | `Equity / Own Funds` / `Reconciliation Clearing` (new subcategory in `blueprints/accounts/classification.py`) | they are a clearing bucket, not a wallet |
| `opening_balance` | `0` | never seeded |

They are still fully visible on **Accounts**, in each one’s **ledger**, on the dashboard
KPI list and on the differences report — deliberately, because the whole point is that the
shortage stops being invisible.

Their ids live in `Settings` (`recon_less_account_id`, `recon_excess_account_id`) and are
created once by a bootstrap helper (`ensure_recon_counter_accounts()`), so no name is
hardcoded in business logic. The Settings screen gets one line: “Difference counter
accounts — [Counter Less ▾] [Counter Excess ▾]”, so they can be renamed or swapped without
code.

---

## 5. Posting record — exact specification

Two `AccountTransaction` rows per difference, written in the **same transaction as the
lock**:

**Shortage** (`difference = counted − expected < 0`, i.e. 1,000 → 900)

| Field | Row A (out of FBM) | Row B (into Counter Less) |
|---|---|---|
| `from_account_id` | FBM | `None` |
| `to_account_id` | `None` | Counter Less |
| `amount` / `amount_minor` | `100.00` / `10000` | same |
| `transaction_type` | `Reconciliation Loss` | `Reconciliation Loss` |
| `source_type` / `source_id` | `CashDayDifference` / `<difference id>` | same |
| `idempotency_key` | `daydiff:{pos_date}:{account_id}:out` | `…:in` |
| `date_posted` | lock instant (`datetime.combine(day, time.max)`) | same |
| `description` | `Counted less — sent to Counter Less Account (FBM)` | `Counted less — received from FBM` |
| `note` | `[RECON:DAY:<day>:<account_id>] expected=1000.00 counted=900.00 diff=-100.00 \| <reason>` | same |
| `reason` | the reason you typed | same |
| `created_by` | the user who locked | same |

**Excess** is the mirror: Row A `Counter Excess → None`, Row B `None → FBM`, type
`Reconciliation Excess`, keys `…:out` (out of the counter) / `…:in` (into FBM).

Rules:

1. Arithmetic in minor units only (`to_minor`/`from_minor`); `models/events.py` keeps
   `amount`/`amount_minor` in step.
2. **No typed count → no posting.** Accounts defaulted to expected at lock have a zero
   difference and post nothing. The system never manufactures money.
3. **Reason mandatory** for a non-zero difference at lock, or the lock is refused.
4. **Balances may go negative** on the counter accounts (that is the excess case) — the
   postings are written with `_apply_account_tx_effect()` directly, never through
   `validate_manual_cash_flow()` (`cash_flow_svc.py:1077` refuses an outflow larger than
   the balance). FBM itself is never allowed to go negative by this mechanism: the
   shortage leg is capped at `min(shortage, FBM.balance)`; if the counted figure exceeds
   what FBM holds, the difference is posted as a split with a warning, never a silent
   negative drawer.
5. **`_assert_period_open()`** (`payments_crud.py:154`) is checked for both accounts before
   writing: a day inside a finalised `AccountReconciliation` period cannot be locked —
   clear message instead of a silent post into a closed period.
6. Posted rows are **immutable**: `blueprints/accounts/transactions.py:123` already blocks
   edits for `source_type == 'AccountReconciliation'`; add `CashDayDifference`.

---

## 6. The five lifecycle events (each one atomic, each one audited)

| Event | Writes | Ledger effect |
|---|---|---|
| **1. Lock day** | for every counted account with `diff ≠ 0`: 2 rows + `CashDayDifference.posted_*` filled, `posted_status='posted'`; `CashDayLock.posted_total` | FBM ↔ counter pair posted |
| **2. Unlock day** | reverse-and-delete that lock’s postings, blank `posted_*`, `posted_status='pending'`; `accounting_audit` event `Unlock`; board opening falls back to ledger | pair removed (balance restored), audit retained |
| **3. Re-lock after a count change** | fresh pair for the new difference; new `idempotency_key` (day+account+sequence) so no duplicate | new pair posted |
| **4. Correct the count** (before the lock, or after an unlock) | `_sync_difference` → `settled`/`superseded`/`cleared` (exists today); the day’s pair is removed by the unlock in event 2 | counter returns to 0 |
| **5. Resolve a locked difference** (found out what happened to the money, §2.4 Path B) | linked explanation transaction, `CashDayDifference.posted_status='resolved'`, `reversed_*` = who/when/which entry | counter returns to 0 through a real entry, nothing deleted |

Deterministic `idempotency_key` + the partial unique index in §9 make a double-clicked
lock, a retried POST, or two admins racing the same day provably safe: the second attempt
finds the key and posts nothing.

**Unlock policy:** admin/root only once a posting exists (that is a real ledger event now),
with a mandatory reason, recorded in the audit trail.

---

## 7. Cash flow, P&L, reports — what each one now says

| Screen | Today | After |
|---|---|---|
| **Accounts list** | FBM only, wrong after a count | FBM correct + two counter balances visible |
| **Cash Flow report** | shows postings as generic “Accounts” rows, KPI “Total Spent” inflated | new `CF_SECTION_RECONCILIATION` label (“Reconciliation”), the **counter-account leg is hidden** (it is not a money account, so `collect_cash_flow_rows` already skips it — `cash_flow_svc.py:1353` filters on `category in ('cash','bank')`), and the FBM leg is shown in a separate “Reconciliation” block, **excluded from Total Received / Total Spent KPI sums** so a shortage does not read as spending. Running balance still includes it, so closing ties to FBM’s balance |
| **P&L** | `Reconciliation Loss/Excess` already classified as other loss/gain (`profit_loss.py:2118`) | unchanged — but now the amount is also real in a balance sheet account, so nothing is double counted when the GL lands |
| **Differences report** | status only | status + the transfer it created + who/when it was solved (§2.4) |
| **Daily board next day** | carried from the lock only | identical numbers, now matching the ledger |
| **Cash Flow “physical cash” form** (`CashFlowDifferenceAdjustment`) | its own carry chain — the same shortage would be carried twice | must defer when a day lock exists for that date: show “day locked on 2026-11-06 — the lock is authoritative” and disable the input |
| **Wipes** | `CashDayDifference` + shift-close tables missing from `DOMAIN_WIPE_REGISTRY` (`app/services/constants.py:108`) | registered; posting rows cleared by the existing `AccountTransaction` wipe, then `rebuild_account_balances_from_ledger()` (`app/services/wipe.py:146`) restores every balance from the ledger |

---

## 8. Two new guards (cheap, and they protect the equality)

1. **Backdating into a locked day.** Any new/edited movement dated inside a locked day of
   the same account must be refused — otherwise tomorrow’s backdated receipt silently
   re-opens what the lock closed. New `_assert_day_open(account_id, posted_at)` in
   `payments_crud.py`, called from manual transactions, cash-flow entries, transfers,
   payments, GRN payments, expenses. Same shape as the existing `_assert_period_open`.
2. **Counter-account immutability.** No manual transaction, transfer, payment or expense may
   target a `recon` category account from the UI; the only writer is the reconciliation
   service. Enforced in one place (the validator), tested.

---

## 9. Schema / migration (additive)

```sql
-- app/migrations/0006_daily_recon_counter_postings.sql
ALTER TABLE cash_day_difference ADD COLUMN posted_out_tx_id INTEGER;
ALTER TABLE cash_day_difference ADD COLUMN posted_in_tx_id  INTEGER;
ALTER TABLE cash_day_difference ADD COLUMN posted_status    VARCHAR(16) DEFAULT 'pending';  -- pending|posted|reversed
ALTER TABLE cash_day_difference ADD COLUMN posted_at        DATETIME;
ALTER TABLE cash_day_difference ADD COLUMN posted_by        VARCHAR(80);
ALTER TABLE cash_day_difference ADD COLUMN reversed_at      DATETIME;
ALTER TABLE cash_day_difference ADD COLUMN reversed_by      VARCHAR(80);
ALTER TABLE cash_day_difference ADD COLUMN reversal_out_tx_id INTEGER;
ALTER TABLE cash_day_difference ADD COLUMN reversal_in_tx_id  INTEGER;
ALTER TABLE cash_day_difference ADD COLUMN resolution_note  VARCHAR(500);
ALTER TABLE cash_day_difference ADD COLUMN resolution_kind  VARCHAR(24);  -- recovered|written_off|corrected|income
ALTER TABLE cash_day_lock       ADD COLUMN posted_total REAL DEFAULT 0;
ALTER TABLE settings ADD COLUMN recon_less_account_id   INTEGER;
ALTER TABLE settings ADD COLUMN recon_excess_account_id INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS uq_account_tx_idem_daydiff
  ON account_transaction (idempotency_key) WHERE idempotency_key LIKE 'daydiff:%';
```

Mirror columns go into `models/cash.py`; `_ensure_model_columns()`
(`app/services/schema.py:109`) picks them up on boot, and the numbered file is applied by
`app/services/auto_migrate.py`.

---

## 10. Code changes by file

| File | Change |
|---|---|
| `app/services/recon_counter.py` *(new, ~250 lines)* | `ensure_recon_counter_accounts()` (creates/returns the pair from `Settings`), `post_difference_pair(diff_row, actor, reason)`, `reverse_difference_pair(diff_row, actor, reason)`, `resolve_difference(diff_row, kind, counterpart, actor, note)` (Path B), `posted_summary_for_day(day)`. Single writer of the two accounts. |
| `app/services/cash_day_recon.py` | `lock_day()` → after freezing positions, call `post_difference_pair()` for each row with `diff ≠ 0` (reason check + `_assert_period_open` first). `unlock_day()` → reverse-and-delete the day’s postings, audited. Board positions gain `posted_status`, `posted_out_tx_id` so the row can show “POSTED”. |
| `app/services/payments_crud.py` | `_assert_day_open(account_id, posted_at)`. |
| `app/services/cash_flow_svc.py` | `'cashdaydifference' → CF_SECTION_RECONCILIATION` in `_CF_SECTION_BY_SOURCE`; exclude that section from in/out KPI sums in `summarize_cash_flow_rows`; make `_automatic_cash_opening_balance()` defer to a day lock. |
| `blueprints/accounts/classification.py` | `Equity / Own Funds → Reconciliation Clearing` subcategory, and `legacy_account_type_for()` → `'recon_counter'`. |
| `app/blueprints/reports/cash.py` | Lock handler: pass the reason, flash the posted pair (“Locked. Rs. 100 shortage sent to Counter Less Account.”). Differences page: expose the new fields + a **Resolve** action (`POST /daily_reconciliation/differences/<id>/resolve`) with kind/counterpart/note, admin-permission gated. |
| `templates/_daily_recon_board.html` | Lock confirm text (“…the difference will be posted to the counter account”); reason box when a difference exists; locked rows show “POSTED → Counter Less”. |
| `templates/daily_reconciliation_differences.html` | “Entry posted” column, `POSTED / REVERSED` chips, grey-out already styled, solved-by/at line, deep links to `ATX-…`. |
| `blueprints/accounts/transactions.py` | Treat `source_type in ('AccountReconciliation', 'CashDayDifference')` as immutable. |
| `app/services/wipe.py`, `app/services/constants.py`, `app/blueprints/misc/_wipe_delete_selected_data.py` | register + clear `CashDayDifference`, `CashDayShiftClose*`; never delete the two counter accounts silently — they go with the account wipe and are re-created on demand. |
| `tools/consistency_report.py` | New check: for every account whose last day is locked, `ledger_balance() == locked counted`; and `Σ counter balances == Σ open differences`. |

---

## 11. Tests

1. `test_shortage_posts_fbm_to_less_counter` — FBM 1,000 / count 900 → FBM 900, Counter Less 100, exactly 2 rows, keys `daydiff:…:out|in`.
2. `test_excess_posts_excess_counter_to_fbm` — FBM 900 / count 1,000 → FBM 1,000, Counter Excess −100.
3. `test_pair_always_nets_to_zero` — Σ(all account balances) identical before/after lock (property test over random counts).
4. `test_lock_is_idempotent` — double POST → still 2 rows.
5. `test_solving_the_count_reverses_the_pair` — count corrected to expected → counter back to 0, difference `settled`, 4 rows total, `reversed_by/at` set.
6. `test_superseded_count_posts_new_pair_only_for_the_new_difference` — 1,000 → count 1,300 → 1,400: pairs reversed/re-posted, never duplicated.
7. `test_unlock_reverses_and_removes_postings` — balance restored, rows gone, audit event present.
8. `test_uncounted_account_posts_nothing`.
9. `test_lock_requires_reason_for_difference`.
10. `test_counter_accounts_absent_from_every_picker_and_board` — `_cf_company_accounts()`, GRN payment picker, driver payment picker, cash-flow picker, `/daily_reconciliation` HTML.
11. `test_counter_accounts_cannot_be_used_manually` — manual transaction / transfer / expense to them is refused.
12. `test_backdating_into_locked_day_is_refused`.
13. `test_counter_balances_track_open_differences` — `Σ counter == Σ open differences`
    after a mixed sequence of lock / unlock / resolve.
14. `test_resolve_shortage_recovered` — Path B: `Counter Less → FBM` posts, row goes
    grey with `resolution_kind='recovered'`, counter back to 0, who/when/entry stored.
15. `test_resolve_shortage_written_off` — expense leg, P&L shows other loss, counter 0.
16. `test_resolve_requires_permission_and_reason` — non-admin refused; empty note refused.
17. `test_resolve_is_idempotent` — double-click posts one entry only.
18. `test_cash_flow_kpis_ignore_reconciliation_postings` but closing still ties.
15. **Change** `tests/test_daily_reconciliation_differences.py:26-61`: today it asserts *no*
    ledger row and balance unchanged **after a lock**. Split it: *saving a count* stays
    reporting-only (assertion kept), *locking* now posts (new expectations). Add a wipe
    test for `CashDayDifference`.
19. Full-cycle mechanism: `W-06` (“reconciliation difference 17,000”) is generated from
    the Cash Flow physical-count form; update `shared/data.py` + `shared/checks.py` in the
    same PR to read the day-lock pair.

---

## 12. Phased rollout

| Phase | Content | Acceptance | Size |
|---|---|---|---|
| **P0** | `ensure_recon_counter_accounts()` + Settings fields + `recon` category exclusion + immutability + `_assert_day_open` + wipe-registry gaps + tests 10–12 | Counters exist, are invisible everywhere, cannot be used manually; nothing posts yet | 1 day |
| **P1** | `post_difference_pair()` / `reverse_difference_pair()` + lock/unlock wiring + audit + idempotency + tests 1–9, 13 | Board next-day opening == Accounts balance; Σ balances unchanged; counter == Σ open differences | 1–1.5 days |
| **P1b** | `resolve_difference()` (Path B) + `/daily_reconciliation/differences/<id>/resolve` + tests 14–17 | A locked shortage can be recovered, written off, or corrected — each with who/when/entry, counter back to 0 | 1 day |
| **P2** | UI: POSTED / RESOLVED chips, “Entry posted”, reason box, grey-out with who/when, ledger deep links + test 18 | Manual walk-through: shortage → lock → resolve → excess → unlock → correct | 1 day |
| **P3** | Retire the double carry (Cash Flow physical count defers to a lock), consistency tool, docs (`AMS_COMPLETE_REBUILD_SPECIFICATION.md` “does not change account balances”), full-cycle expectations | `tools/consistency_report.py` green on the live DB; full-cycle has no new failures | ½ day |

**Historical locked days (P3.1):** they carried openings on the board but posted nothing.
Recommended: a one-off `tools/post_historical_differences.py --from YYYY-MM-DD --dry-run`
that prints every frozen `pos.difference`, its would-be pair and the effect on both
balances; run it once after a DB backup, then again without `--dry-run`. Rows are written
with `posted_status='posted'` and a `source='history'` marker so the report can distinguish
them from live postings.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| Double posting on lock → unlock → lock | deterministic keys + partial unique index; unlock removes its own rows |
| Void rows purged at boot without unwinding balances (`schema.py:936`) | never void these rows: reverse + delete inside one transaction, or mirror-post |
| FBM pushed negative by a huge shortage | shortage leg capped at `min(shortage, FBM.balance)` + explicit warning in the lock result |
| Someone pays a supplier out of a counter account | `recon` category is rejected by `_cf_is_money_account` and every picker; test 11 |
| Counter balances drift from posted differences | consistency check + test 13 (`Σ counter == Σ open differences`) |
| Two carry chains (lock vs physical-count form) | P3 precedence rule + test |
| Old locks look inconsistent | history tool with `--dry-run`, one run, with a backup |

---

## 14. Decisions I need before P1

1. **Naming/labels:** “Counter Less Account / Counter Excess Account”, or your wording
   (“Shortage Account / Excess Account”)? Only labels change, not the model.
2. **Reason:** mandatory whenever a lock posts a non-zero difference? *(recommend yes)*
3. **Unlock:** admin/root only once postings exist, with mandatory reason? *(recommend yes)*
4. **Cash-flow display:** hide reconciliation postings from Total Received/Spent but keep
   them in the running balance (recommended), or show them as their own “Reconciliation”
   block with their own tile?
5. **Historical locks:** post them via the `--dry-run` tool (recommended) or leave them
   board-only?
6. **Resolve targets (§2.4 Path B):** do you want all four explanations (recovered /
   written off / corrected / income), or only “recovered into FBM” and “written off”?

Answer these and I implement **P0 + P1 + P1b with the full test suite** in one PR.

---

## 15. Rollback

Additive and reversible: a `DAY_RECON_COUNTER_POSTING` flag (default on after P1) stops
new postings; existing pairs can be unwound with
`tools/consistency_report.py --reverse-daydiff --from <date>` (mirror-posts, never deletes);
`CashDayLock` / `CashDayAccountPosition` rows are untouched; dropping the two counter
accounts requires a zero balance, which the reversal guarantees.


---

## 16. What shipped (2026-11-07)

| Piece | Where |
|---|---|
| Counter accounts (created on demand, ids in `Settings`) | `app/services/recon_counter.py::ensure_counter_accounts()` |
| Paired postings at lock / removal at unlock | `post_difference()`, `reverse_posting()`; called from `cash_day_recon.lock_day()` / `unlock_day()` |
| Resolve a posted difference with a real entry | `resolve_difference()` + `POST /daily_reconciliation/differences/<id>/resolve` |
| Board: difference panel, POSTED / resolved markers, reason box | `templates/_daily_recon_board.html`, `_dr_build_context()` |
| Report: counter tiles, “Counter account entry” column, Resolve form | `templates/daily_reconciliation_differences.html` |
| Auto-unpost when a superseded difference is closed | `cash_day_recon._sync_difference()` |
| Late-lock re-dating of already-locked later days | `recon_counter.refresh_forward_lock_openings()` |
| Backdating guard | `payments_crud._assert_day_open()` (wired beside every `_assert_period_open`) |
| Counter accounts hidden from every picker | `MONEY_CATEGORIES` / `is_recon_account()`; pickers in grn, pending, sales, transfers |
| Idempotency index | migration `0006` + `schema._ensure_daydiff_posting_index()` |
| Invariants + health check | `recon_counter.counter_invariants()`, `tools/consistency_report.py` |
| Historical postings | `tools/post_historical_differences.py --dry-run` |
| Wipe coverage | `DOMAIN_WIPE_REGISTRY`, `purge_daily_reconciliation_state()` (reverses each pair before deleting), `clear_account_reconciliation_state()` |
| Re-check of a finalised day re-posts a changed difference | `cash_day_recon.refresh_differences()` |

**Deliberate refinements to the plan above**

1. **The board never counts its own posting.** `in`/`out`/`transfer` exclude
   `source_type = CashDayDifference`; openings include them. Without this the next
   day reconciled against itself.
2. **Cash-flow KPI totals exclude reconciliation postings** (the running balance
   still includes them), so a shortage never looks like spending. They appear
   under their own “Reconciliation” section.
3. **The invariant is not “today’s balance equals the counted figure”** (a later
   recovery legitimately moves it on). It is: both legs exist, they are equal and
   net to zero, the counter is one leg, and the counters hold exactly the
   unresolved postings — `Σ counters = −Σ open posted differences`.
4. **An account with a finalised day is archived rather than hard-deleted**
   (its posting is a real ledger reference), and its history is preserved; a hard
   delete clears the difference rows and reverses the pair first.
5. **Unlock is open to whoever can lock** (`can_view_cash_flow`) because it now
   reverses a posting. Making it admin-only is a one-line change if you prefer
   (see §14.3); it is *not* admin-only today.
6. **A day's difference story does not shrink as rows are resolved.** The board's
   day panel and the report show every posting the day created (posted *and*
   resolved) and call out how many are still unexplained; only a reopened
   (reversed) posting leaves that set.
7. **Nothing is hard-coded to “FBM”.** The report renders
   `account → counter` from the row's own account name, so the same mechanism
   reads correctly for every account on the board.
8. **A shortage is never refused for lack of balance.** A count is a fact; when a
   day is finalised late, the money may already have moved on, so the posting is
   made anyway and the message says so. Refusing would leave the ledger claiming
   cash the drawer did not have.
9. **Re-checking is refused on a finalised day** (with a "unlock to correct"
   message). Re-deriving its differences from the ledger would recreate the very
   gap the posting explains — and after a resolve, post it a second time. A
   finalised day is corrected by unlocking it, which reverses the pair.
10. **A wipe reverses before it deletes.** The daily-reconciliation wipe (and the
    accounts domain wipe) removes each posted pair, so no shortage is stranded in
    a counter account after the board is cleared.

**Tests:** `tests/test_daily_reconciliation_differences.py` (28 tests, including
shortage/excess posting, net-zero, idempotency, unlock, resolve, invariant
lifecycle, backdating, picker exclusion, re-checking a finalised day (which must
never recreate or re-post a difference), and out-of-order locks that re-date and
re-post later finalised days).
