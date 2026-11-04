# Full Application Work-Test

**Application:** AMS SYSTEM FOR EASE — cement / building-material ERP (Flask + SQLAlchemy + SQLite)
**Source of truth for this document:** the running application at `/home/user/git-recovered`, read page-by-page (routes, handlers, templates, services, rendered HTML), then exercised end-to-end on a throw-away database.
**Document version:** 1.0 — built on commit `2867c3e` (branch `arena/acd08172-git-recovered`).
**Purpose:** a self-contained, sequential acceptance suite. Give this file back with the words *"run these tests"* and every step below can be executed exactly as written, with the expected on-screen number, the expected database value, the expected PDF value and a pass/fail box.

**Verification status:** the following were **executed** against a scratch SQLite file, with the rendered HTML, the PDF text and the database rows read back and compared: masters (§1–§6), GRNs and landed cost (§7), booking (§8), all three sale types (§9–§10), delivery rent (§11), all four payment paths and the driver settlement (§12), cash flow entries / transfers / reconciliation (§13), material return (§14), pending bills and decision ledger (§15), every report in §16, all 18 downloads in §17, the audit pages (§18.2–§18.3), settings and the sidebar (§19.2), client categories (§19.6), notifications (§19.5) and the admin module list (§19.4).

The following are **documented from the rendered forms and handler code, not yet executed** — treat their expected columns as predictions and mark them `?` rather than `P` on a first run: the per-account count/shift-close/finalise flow (§18.1), user creation and the permission matrix (§19.3), the import/export round-trip (§20.1), legacy migration (§20.2) and the data lab (§20.3). Sections marked *known* in §22 are deviations that were observed and deliberately left unfixed.

---

## Contents

| § | Section | What it proves |
|---|---|---|
| 0 | How to run this document | environment, harness, naming conventions, canonical dataset |
| 1–6 | Masters | suppliers, categories, materials, service, client, delivery person, accounts |
| 7–11 | Stock & sales | GRN + landed cost, booking, cash sale, credit sale, booking delivery, delivery rent |
| 12 | Money | client receipts, GRN payment, supplier payment, accounts transactions, driver settlement |
| 13 | Cash flow | manual entries, transfers, physical reconciliation |
| 14–15 | Corrections | material returns, pending bills, decision ledger |
| 16–17 | Reports | P&L, financial details, stock, tracking, payables, ledgers, PDFs |
| 18–20 | Governance | daily reconciliation, audits, settings, users, import/export, legacy migration |
| 21 | Cross-checks | 20 tie-outs between independent pages |
| 22 | Defect register | every known deviation, with reproduction |
| 23 | Sign-off | pass/fail sheet + 15-minute smoke run |

## 0. How to run this document

### 0.1 Environment

| Item | Value |
|---|---|
| Repo root | `/home/user/git-recovered` |
| Python | 3.11 (`python3 -m venv .venv`) |
| Install | `.venv/bin/pip install -r requirements.txt` |
| Start (interactive) | `APP_DB_PATH=/tmp/ams_wt.db DB_HEALTH_SNAPSHOT_PATH=/tmp/health.json BACKUP_EMBEDDED_SCHEDULER=0 ALLOW_EMPTY_DB=1 .venv/bin/python main.py` |
| URL | `http://127.0.0.1:5000` (bind `0.0.0.0` when the app must be reachable from a preview host) |
| Database | one SQLite file; `instance/ahmed_cement_v44_fresh.db` by default, overridden by `APP_DB_PATH` |
| Migrations | `0001`–`0005` apply automatically on boot |
| Login | `Admin` / `Admin@fbm12345` (role `admin`, bypasses every permission gate) |
| Seeded rows | user `Admin`; client `OPEN KHATA` (`OPEN-KHATA`, category `Open Khata`); material category `General` |

> **Always run this suite on a throw-away database.** Set `APP_DB_PATH` to a path that does not exist yet so step 1 starts from a truly empty system. Never point it at a production file: the wipe in 0.3 and the cross-checks in step 19 are destructive.

### 0.2 Two ways to drive it

1. **Browser (what a human tester does).** Follow the tables; every field name in this document is the real HTML `name=` attribute, so the value column can be typed directly.
2. **Script (what a machine tester does).** `tests/conftest.py::make_csrf_client(app)` returns a Flask test client that carries the CSRF token automatically:

```python
import os, sys
os.environ['APP_DB_PATH'] = '/tmp/ams_wt.db'
os.environ['BACKUP_EMBEDDED_SCHEDULER'] = '0'
os.environ['ALLOW_EMPTY_DB'] = '1'
sys.path[:0] = ['.', 'tests']
from app import create_app
from tests.conftest import make_csrf_client
app = create_app(); app.config['TESTING'] = True
c = make_csrf_client(app)
c.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'})
```

Every `POST` in the suite is a plain form post. When a step says *"flash"* it means the Bootstrap alert rendered at the top of the destination page; the string must appear in the HTML body of the followed response.

### 0.3 Reset to zero (run once, before step 1)

| # | Action | Where | Expected |
|---|---|---|---|
| 0.3.1 | Stop the app, delete the DB file named by `APP_DB_PATH` (plus `-wal` / `-shm`), start again | shell | Boot log `DB loaded: … counts={'client_total': 1, …}` — only the seeded `OPEN KHATA` |
| 0.3.2 | Open `/settings` → **Granular Data Wipe** | `/settings` | Section lists every wipe target; `PROTECTED_TABLES` (users, settings, audit log, bill counter, migration history) are not offered |
| 0.3.3 | Tick everything, type the confirmation text, press **Confirm Wipe** | `POST /delete_selected_data` | Success flash; `/system_report` shows 0 sync issues, 0 stock discrepancies |
| 0.3.4 | `/void_audit` | `/void_audit` | `Total 0 · Deleted 0 · Suspended 0` |

If you are scripting, `tools/audit_full_cycle.py` exposes the same list as `FULL_WIPE_TARGETS` and the wipe assertion as `business_leftovers(app)`.

### 0.4 Conventions used by every check below

* **Money** is shown with 2 decimals on record pages (`8,500.00`) and 0 decimals on summary tiles (`Rs. 175,500`). The document prints the value; accept either separator style.
* **Manual bill numbers** are normalised on save: typing `CYC-GRN-1` stores and displays `MB NO.CYC-GRN-1`. Always assert the normalised form.
* **Auto bill numbers** come from a per-namespace counter that starts at **1000**:

| Namespace | Prefix | First value |
|---|---|---|
| GRN | `SB-GRN-` | `SB-GRN-1000` |
| Booking | `SB-BK-` | `SB-BK-1000` |
| Direct sale | `SB-SL-` | `SB-SL-1000` |
| Client payment | `SB-CP-` | `SB-CP-1000` |
| Supplier payment | `SB-SP-` | `SB-SP-1000` |
| GRN supplier payment | `SB-GP-` | `SB-GP-1000` |
| Material return | `SB-RTN-` | `SB-RTN-1000` |

* **Dates** — `date` inputs take `YYYY-MM-DD`; `datetime-local` inputs take `YYYY-MM-DDTHH:MM`. Posting a future date is rejected.
* **`date_posted` on GRN is a datetime**: passing `date=2026-10-02` + `time=09:00` stores `2026-10-02 09:00:00`.
* **Stock** is the `material.total` column, kept in step with IN/OUT entries; it is *not* recomputed from FIFO.
* **Idempotency** — endpoints that accept `idempotency_key` treat a repeat of the same payload as a replay (`info` flash, no new row) and a *different* payload under the same key as an error. Never invent a shared key for two different transactions.
* **Pass/fail** — every check is written as *observed → expected*. Record `P` or `F`; any `F` must carry the observed value in the notes column.

### 0.5 The canonical dataset (all expected numbers derive from this)

Everything in steps 1–12 creates exactly this state. Later sections quote these figures, so **do not change a value without changing the expected column below**.

| Object | Key figures |
|---|---|
| Suppliers | Ravi Cement Supplier (`SUP-0001`), Kohat Traders (`SUP-0002`) |
| Material categories | General (seeded), Cement, Sand & Gravel, Sheets & Covers |
| Materials | DG Cement `DG` Bag · Pioneer Cement `PIO` Bag · Chenab Sand `SAND` Cft · TRANSPARENT SHEET `SHT` Pcs |
| Services | CEMENT RENT `SRV-RENT` Trip |
| Client | Bilal Construction `CYC-CL-1`, category General, opening 0 |
| Delivery person | Akram Driver |
| Accounts | Main Cash (cash, opening **200,000**) · Meezan Bank (bank, opening **500,000**) |
| GRNs | 6 receipts, material value **418,500** (see §7) |
| Bookings | MB NO.CYC-BK-1 · 20 × 1,500 = **30,000**, paid **10,000**, pending **20,000** |
| Direct sales | CYC-CASH-1 8,500 (paid 8,500) · CYC-CR-1 16,500 (paid 5,000) · CYC-BD-1 30,000 (paid 0, booking fulfilment) |
| Payments | client receipts 8,000 + 3,000 · GRN payment 60,000 · supplier payment 20,000 · driver payments 1,000 |
| Closing accounts (after step 12) | Main Cash **170,500** · Meezan Bank **483,000** · company **653,500** |
| Deliveries | 3 trips, rent **1,400**, paid **1,000**, remaining **400** |

---

## 1. Step 1 — Create suppliers

**Page:** `/suppliers` — heading *Supplier Ledger*, subtitle *Suppliers*.
**Why first:** every GRN, purchase payable and supplier ledger hangs off this master.

### 1.1 Page inventory

| Element | Detail |
|---|---|
| Filters (`GET /suppliers`) | `q`, `status` ∈ {All statuses, Payable, Settled, Advance / prepaid, Inactive suppliers}, `balance_min`, `balance_max`, `sort` ∈ {Name (A–Z), Name (Z–A), Balance (high → low), Balance (low → high), Purchase (high → low), Purchase (low → high), Paid (high → low)} |
| KPI strip | Total Purchase (Goods received) · Total Paid (Payments recorded) · Outstanding Payable · Advance Balance (Prepaid to suppliers) |
| Table columns | Supplier Name · Supplier Code · Phone Number · Total Purchase · Total Paid · Outstanding Payable · Advance Balance · Payment Status · Actions |
| Row actions | **View Ledger** · **Edit Supplier** · **Suspend Supplier** · **Transfer Data** · **Shift Entire Ledger…** · **Permanently Delete & Wipe Entries** · **Reclaim shifted ledger** |
| Add form | `POST /add_supplier`, modal **Add New Supplier**, fields `_csrf_token, name, phone, address, opening_balance, opening_balance_date`; button **Save Supplier** |
| Helper text | *"Use + for payable due, - for advance/prepaid."* |

### 1.2 Steps

| # | Action | Field | Value |
|---|---|---|---|
| 1.2.1 | Open `/suppliers` | — | page renders, table empty except the OPEN KHATA client is *not* listed here (clients ≠ suppliers) |
| 1.2.2 | Press **Add Supplier** | — | modal opens |
| 1.2.3 | Fill | `name` | `Ravi Cement Supplier` |
| | | `phone` | `0300-1234567` |
| | | `address` | `Ravi Road, Lahore` |
| | | `opening_balance` | `0` |
| | | `opening_balance_date` | `2026-10-01` |
| 1.2.4 | Press **Save Supplier** | — | `POST /add_supplier`; flash **"Supplier Added"** |
| 1.2.5 | Repeat 1.2.2–1.2.4 | `name` | `Kohat Traders` |
| | | `phone` | `0301-7654321` |
| | | `address` | `Kohat Bazaar` |
| | | `opening_balance` | `0` |
| | | `opening_balance_date` | `2026-10-01` |

### 1.3 Expected results

| Check | Observed | Expected | P/F |
|---|---|---|---|
| 1.3.1 List shows 2 rows | | Ravi Cement Supplier, Kohat Traders | |
| 1.3.2 Supplier code is server-generated | | `SUP-0001`, `SUP-0002` (zero-padded, sequential) | |
| 1.3.3 KPI *Total Purchase* | | `0.00` before any GRN | |
| 1.3.4 KPI *Outstanding Payable* | | `0.00` | |
| 1.3.5 Payment status badge | | `Settled` (no balance yet) | |
| 1.3.6 DB — `supplier` table | | 2 rows: `('Ravi Cement Supplier','0300-1234567','Ravi Road, Lahore',0.0)`, `('Kohat Traders','0301-7654321','Kohat Bazaar',0.0)` | |
| 1.3.7 Duplicate guard | | adding `Ravi Cement Supplier` again flashes a duplicate/validation error and creates no third row | |
| 1.3.8 Negative opening | | `opening_balance = -5000` on a *new* supplier stores an advance: KPI *Advance Balance* becomes 5,000 and status `Advance / prepaid` (delete the test row afterwards) | |

> **Note for the runner:** test 1.3.8 is the only step in §1 that mutates beyond the canonical dataset — delete the extra supplier with **Permanently Delete & Wipe Entries** before continuing, and confirm the KPI returns to 0.

---

## 2. Step 2 — Add material categories

**Two different "category" concepts share this word.** Keep them apart:

* **Material category** — a stock grouping (`Cement`, `Sand & Gravel`). Managed on `/settings` → *Material Categories* and stored in `material_category`.
* **Client category** — a customer grouping (`General`, `Open Khata`). Managed on `/client-ledger/categories`.

This step touches material categories only.

### 2.1 Page inventory — `/settings` → Material Categories

| Element | Detail |
|---|---|
| Table columns | Name · Status · Actions |
| Add form | `POST /material_categories/add`, field `category_name`, button **Add** |
| Row actions | rename (`POST /material_categories/<id>/rename`, field `category_name`), **Disable/Enable** (`POST /material_categories/<id>/toggle`) |

### 2.2 Steps

| # | Action | Field | Value |
|---|---|---|---|
| 2.2.1 | `/settings` → scroll to **Material Categories** | seeding | `General` already present |
| 2.2.2 | `category_name` → **Add** | `category_name` | `Cement` |
| 2.2.3 | Repeat | `category_name` | `Sand & Gravel` |
| 2.2.4 | Repeat | `category_name` | `Sheets & Covers` |
| 2.2.5 | Rename `Sheets & Covers` → `Sheets & Coverings` → back | `category_name` | rename works, materials keep their `category_id` |
| 2.2.6 | Duplicate: add `cement` (lower case) | `category_name` | flash **"Category already exists"**, no new row |

### 2.3 Expected results

| Check | Observed | Expected | P/F |
|---|---|---|---|
| 2.3.1 Flash per add | | **"Category added"** | |
| 2.3.2 DB — `material_category` | | `1 General, 2 Cement, 3 Sand & Gravel, 4 Sheets & Covers` | |
| 2.3.3 Category appears in every material picker | | `/materials` filter, `/inventory/stock_summary` filter, `/grn` category filter | |
| 2.3.4 Disable `Cement` | | material rows keep the category name but the option disappears from *new-record* pickers; re-enable before step 3 | |
| 2.3.5 Category with materials cannot be deleted | | no delete control is offered (only rename/toggle) | |

---

## 3. Step 3 — Add material brands (materials) and the rent service

### 3.1 Page inventory — `/materials` (*Material Brands*)

| Element | Detail |
|---|---|
| Filters | category, unit, `q` |
| Table columns | Brand Name · Category · Unit · Code · Status · Actions |
| Add form | `POST /add_material`, fields `_csrf_token, material_name, category_id, material_unit, material_code`; buttons **Auto Code**, **Save Brand**, **Reset** |
| Impact dialogs | **Merge/Shift Material** (`source_material_id`, `target_material_id`) · **Fix Old Material Name in History** (`old_label`, `target_material_id`) · **Bulk Update Units** (`category_id`, `new_unit`) |
| Row actions | **Edit** (`POST /edit_material/<id>`: `material_name, category_id, material_unit, material_code`) · **Suspend/Activate** (`POST /delete_material/<id>` — soft, never deletes history) · **Activate All Suspended** |
| Helper text | *"Old receipts and bills store the material name as text…"* (the rename tool rewrites history by label) |

### 3.2 Page inventory — `/services` (*Services & Charges*)

| Element | Detail |
|---|---|
| Search | `q` |
| Table columns | Service Name · Code · Unit · Historical Records · Status · Actions |
| Add form | `POST /services/add`, fields `service_name, service_code, service_unit` (code optional — auto-generated), button **Add Service** |
| Row actions | **Edit** (`POST /services/edit/<id>`) · **Suspend** (`POST /services/toggle/<id>`) · **Delete** (`POST /services/delete/<id>`) |
| Migration block | **Convert rent materials into services** (`POST /services/migrate`, `confirm`) — moves rent-like *materials* and their history into services |
| Merge block | `POST /services/merge`, `source_service_id`, `target_service_id` |

> **Rule:** a material holds stock and is costed FIFO; a service never touches stock. Both can be sold on the same bill.

### 3.3 Steps — materials

| # | `material_name` | `category_id` | `material_unit` | `material_code` | Expected flash |
|---|---|---|---|---|---|
| 3.3.1 | `DG Cement` | Cement | `Bag` | `DG` | **Brand Added** |
| 3.3.2 | `Pioneer Cement` | Cement | `Bag` | `PIO` | **Brand Added** |
| 3.3.3 | `Chenab Sand` | Sand & Gravel | `Cft` | `SAND` | **Brand Added** |
| 3.3.4 | `TRANSPARENT SHEET` | Sheets & Covers | `Pcs` | `SHT` | **Brand Added** |

`TRANSPARENT SHEET` is deliberate: it contains the letters **rent** without being a rent word. It must stay an ordinary stock material (before the 2024 fix, the substring rule hijacked such names into services and silently removed them from stock and FIFO costing).

### 3.4 Steps — service

| # | Field | Value |
|---|---|---|
| 3.4.1 | `service_name` | `CEMENT RENT` |
| 3.4.2 | `service_unit` | `Trip` |
| 3.4.3 | `service_code` | `SRV-RENT` |
| 3.4.4 | **Add Service** | flash **Service "CEMENT RENT" added.** |

### 3.5 Expected results

| Check | Observed | Expected | P/F |
|---|---|---|---|
| 3.5.1 DB — `material` | | 4 rows, `total = 0.0`, `is_active = 1`, id 1–4 in the order created | |
| 3.5.2 Category binding | | id1→Cement, id2→Cement, id3→Sand & Gravel, id4→Sheets & Covers | |
| 3.5.3 DB — `service` | | 1 row `('CEMENT RENT','SRV-RENT','Trip')` | |
| 3.5.4 `TRANSPARENT SHEET` is a material | | appears in `/inventory/stock_summary`, **not** in `/services` | |
| 3.5.5 `CEMENT RENT` is a service | | appears in `/services`, **not** in `/inventory/stock_summary` | |
| 3.5.6 Duplicate name/code | | adding `DG Cement` or code `DG` again is rejected with a collision message | |
| 3.5.7 Auto Code | | leaving `material_code` blank and pressing **Auto Code** fills a unique code from `/api/material_next_code?category_id=` | |
| 3.5.8 Suspend + Activate | | `POST /delete_material/3` sets `is_active = 0`; the row still shows in *All* filter with status **Suspended**; **Activate All Suspended** returns it | |

---

## 4. Step 4 — Create the client (and the client categories)

### 4.1 Page inventory — `/clients` (*Client Ledger*)

| Element | Detail |
|---|---|
| Filters | `category` (from `/client-ledger/categories`), `search` |
| KPI strip | Payable (This Page) *Clients owe you* · Advance (This Page) *You owe clients* · Billed *Total debit* · Received *Total credit* · Active Clients |
| Table columns | Client Name · Code · Pages · Opening · Billed · Received · Payable / Balance · Last Activity · Phone · Actions |
| Row actions | **Payable/Advance/Settled** badge, **Receivable** quick-link, edit modal, **Delete** (`POST /delete_client/<id>` — soft), **Reclaim** |
| Add form | `POST /add_client`, fields `name, category, code, page_entry, phone, location_url, address, opening_balance, opening_balance_date`; buttons **Auto** (code), **Add Page**, **Create Client**, **Reset** |
| Helper text | *"Use + for pending due, - for advance/credit."* |
| API used by the form | `GET /api/client_next_code` → `{"code": "…"}` |

### 4.2 Page inventory — `/client-ledger/categories`

| Element | Detail |
|---|---|
| Table columns | Category · Clients · Status · Created · Actions |
| Add form | `POST /client-ledger/categories/add`, field `name`, button **Add Category** |
| Row actions | **Rename** (`POST /client-ledger/categories/<id>/rename`, field `name`) · **Deactivate/Activate** (`…/toggle`) · **Delete** (`…/delete`) |

### 4.3 Steps

| # | Page | Field | Value |
|---|---|---|---|
| 4.3.1 | `/client-ledger/categories` | — | verify seeded `General` and `Open Khata` exist |
| 4.3.2 | same | `name` → **Add Category** | `Contractor` (optional extra; leave it active) |
| 4.3.3 | `/clients` → **+ New Client** | `name` | `Bilal Construction` |
| | | `code` | `CYC-CL-1` (or press **Auto**) |
| | | `category` | `General` |
| | | `phone` | `0321-1112223` |
| | | `address` | `Islamabad` |
| | | `location_url` | *(blank)* |
| | | `opening_balance` | `0` |
| | | `opening_balance_date` | `2026-10-01` |
| 4.3.4 | press **Create Client** | — | flash **"Client Registered"** |

### 4.4 Expected results

| Check | Observed | Expected | P/F |
|---|---|---|---|
| 4.4.1 DB — `client` | | 2 rows: `OPEN KHATA` (`OPEN-KHATA`, Open Khata, id 1) and `Bilal Construction` (`CYC-CL-1`, General, id 2) | |
| 4.4.2 OPEN KHATA is special | | cannot be deleted; it is the automatic counterparty for "Open Khata" sales | |
| 4.4.3 Code uniqueness | | `CYC-CL-1` again → collision error, no second row | |
| 4.4.4 Client appears in the picker of every sales page | | `/bookings`, `/direct_sales`, `/add_payment`, `/material_returns`, `/accounts/payments/clients` | |
| 4.4.5 Opening balance re-post | | `/ledger/2` → **Set Opening Balance** (`POST /client_opening_balance/2`, `opening_balance`, `opening_balance_date`) → flash **"Opening balance updated"**; ledger *Opening Balance* tile changes; set it back to `0` before step 5 | |
| 4.4.6 Category cannot be deleted while it has clients | | `POST /client-ledger/categories/<General>/delete` is refused (status shows *in use*) | |

---

## 5. Step 5 — Create the delivery person

### 5.1 Page inventory — `/delivery_persons`

| Element | Detail |
|---|---|
| Table columns | Name · Phone · Status · Actions |
| Add form | `POST /delivery_persons/add`, fields `name, phone`, button **Add Driver** |
| Row actions | **Ledger** (→ `/delivery_person_ledger/<id>`) · **Edit** (`POST /delivery_persons/edit/<id>`, `name`, `phone`) · **Deactivate** (`POST /delivery_persons/toggle/<id>`) |

### 5.2 Steps

| # | Field | Value |
|---|---|---|
| 5.2.1 | `name` | `Akram Driver` |
| 5.2.2 | `phone` | `0333-9998887` |
| 5.2.3 | **Add Driver** | flash **"Delivery person saved"** |

### 5.3 Expected results

| Check | Observed | Expected | P/F |
|---|---|---|---|
| 5.3.1 DB — `delivery_person` | | 1 row `('Akram Driver','0333-9998887',0.0,is_active=1)` | |
| 5.3.2 Ledger link | | `/delivery_person_ledger/1` shows *Opening balance Rs. 0.00*, *Total debit 0.00*, *Total credit 0.00*, *Closing balance 0.00* | |
| 5.3.3 Driver picker | | appears as `Akram Driver` in `/direct_sales` *Delivery Person* combobox and `/delivery_rents` filter | |
| 5.3.4 Deactivate/reactivate | | toggling hides the driver from new-sale pickers but keeps history; reactivate before step 9 | |

---

## 6. Step 6 — Create the company accounts (cash + bank)

**Page:** `/accounts/accounts/add` (*Create Account*), reached from `/accounts/` → **Add Account**.

### 6.1 Page inventory — the account form

The form is a **cascading three-level classification**, then a channel-specific block, then an opening-balance block.

| Block | Field | Notes |
|---|---|---|
| Identity | `name`, `note` | free text |
| Legacy group | `source_category` | `Clients`, `Company`, `External`, `Loan`, `Own Funds` — kept for old rows; new rows use the classification below |
| Classification | `class_category` → `class_subcategory` → `class_account_type` | server-validated from the registry (see table 6.2) |
| Channel | `channel` | derived from the account type: `cash`, `bank`, `digital_wallet`, `ledger_only`, `other` |
| Cash block | `cash_location`, `cash_responsible` | shown for cash channels |
| Bank block | `bank_name`, `account_holder_name`, `account_number`, `branch_code` | **required** for bank channels |
| Wallet block | `wallet_provider`, `wallet_number`, `wallet_holder` | required for digital wallets |
| Entity link | `linked_entity_type`, `linked_client_id`, `linked_supplier_id`, `linked_party_name` | required when the account type declares an entity (e.g. *Client Ledger*, *Supplier Ledger*) |
| Opening | `opening_amount`, `opening_position` ∈ {debit, credit}, `opening_effective_date` | debit = money in hand |
| Status | `account_status` ∈ {active, inactive, archived} | |
| Buttons | **Quick Add Group** (`POST /accounts/categories/add`: `name`, `note`), **Create Account**, **Save** (on edit) | |

### 6.2 Classification registry (the only valid Category → Subcategory → Type triples)

| Category | Subcategory | Account types (channel) |
|---|---|---|
| Assets | Cash | Main Cash, Petty Cash, Cash Drawer, Site Cash, Temporary Cash (cash) |
| Assets | Bank | Operating Bank, Collection Bank, Savings Bank, Settlement Bank (bank) |
| Assets | Digital Wallet | Mobile Wallet, Payment App (digital_wallet) |
| Assets | Client Receivables | Client Ledger, Client Advance Receivable (ledger_only, **client**) |
| Assets | Advances Given | Advance to Worker, Advance to Party, Staff Advance (ledger_only) |
| Assets | Other Assets | General Asset, Security Deposit Given (ledger_only) |
| Liabilities | Supplier Payables | Supplier Ledger, Supplier Outstanding (ledger_only, **supplier**) |
| Liabilities | Client Advances | Client Advance Received (ledger_only, client) |
| Liabilities | Loans Payable | Bank Loan, Personal Loan, Partner Loan, External Loan |
| Liabilities | Partner / External Payables | Partner Payable, External Payable |
| Liabilities | Expenses Payable | Expense Payable |
| Liabilities | Other Liabilities | General Liability |
| Equity / Own Funds | Owner Capital · Partner Capital · Owner Drawings / Withdrawals · Retained Funds · Other Equity | Owner Capital, Partner Capital, Owner Drawings, Retained Earnings, General Equity |
| Income | Sales Income · Service Income · Other Income | the single matching type each |
| Expenses | Operating Expenses · Delivery & Transport · Salaries & Labour · Rent & Utilities · Administrative Expenses · Other Expenses | the single matching type each |
| External / Clearing | Partner Clearing · Intercompany / Company Transfer · External Settlement · Suspense / Temporary Clearing | the single matching type each |

An invalid triple (e.g. *Expense + Bank*) cannot be saved; the server rejects it even if the client-side cascade is bypassed.

### 6.3 Steps

| # | Field | Account A | Account B |
|---|---|---|---|
| 6.3.1 | `name` | `Main Cash` | `Meezan Bank` |
| 6.3.2 | `class_category` | `Assets` | `Assets` |
| 6.3.3 | `class_subcategory` | `Cash` | `Bank` |
| 6.3.4 | `class_account_type` | `Main Cash` | `Operating Bank` |
| 6.3.5 | `account_status` | `active` | `active` |
| 6.3.6 | `opening_amount` | `200000` | `500000` |
| 6.3.7 | `opening_position` | `debit` | `debit` |
| 6.3.8 | `opening_effective_date` | `2026-10-01` | `2026-10-01` |
| 6.3.9 | `bank_name` / `account_holder_name` / `account_number` | — | `Meezan Bank` / `Ahmed Cement` / `0123456789` |
| 6.3.10 | Submit | **Create Account** → flash **"Account added successfully!"** | same |

### 6.4 Expected results

| Check | Observed | Expected | P/F |
|---|---|---|---|
| 6.4.1 DB — `account` | | id1 `Main Cash`, `category='cash'`, `channel='cash'`, `opening_balance=200000.0`, `balance=200000.0`, `opening_balance_minor=20000000` | |
| 6.4.2 DB — second row | | id2 `Meezan Bank`, `category='bank'`, `channel='bank'`, `opening_balance=500000.0`, `balance=500000.0` | |
| 6.4.3 `/accounts/` KPI *Total Cash Available* | | `Rs. 200000.00` | |
| 6.4.4 `/accounts/` KPI *Total Money Available in Company* | | `Rs. 700000.00` | |
| 6.4.5 `/accounts/accounts` table | | columns *Account · Group · Type · Channel · Balance · Status · Created · Actions*; both rows **Active**, channel badge **Cash** / **Bank** | |
| 6.4.6 Missing bank details | | creating a bank account without `bank_name` is rejected with a field error | |
| 6.4.7 Invalid combination | | posting `class_category=Expenses` + `class_subcategory=Bank` is rejected server-side | |
| 6.4.8 Edit form | | `/accounts/<id>/edit` exposes `desired_balance`, `adjustment_reason`, `adjustment_date`, `idempotency_key`, `current_balance_hidden` — a balance change is recorded as a reconciliation **adjustment**, not a silent overwrite | |
| 6.4.9 Account groups | | `/accounts/categories` lists groups with *ID · Category / Group Name · Note · Accounts Count · Status · Actions* | |
| 6.4.10 Duplicate account name | | adding `Main Cash` again is rejected | |

---

## 7. Step 7 — Receive GRNs covering (almost) all materials

**Page:** `/grn` — *GRN (Goods Receipt Note)*. Two tabs: **Records** (`/grn`) and **Costs** (`/grn?tab=costs`).

### 7.1 Page inventory — the GRN form

| Region | Fields |
|---|---|
| Header | `supplier`, `supplier_id` (combobox), `date`, `time`, `manual_bill_no`, **Use current time** |
| Items grid | `mat_name[]`, `qty[]`, `price[]` (rows added with **Add** / removed with **Reset**) |
| Charge grid | `charge_id[]`, `charge_type[]` ∈ {Vehicle Fare, Transportation, Loading, Unloading, Other Expenses}, `charge_label[]`, `charge_amount[]`, `charge_row_key[]`, `charge_include_in_supplier[]`, `charge_recipient_type[]` ∈ {Vehicle / Transporter, Loading / Labour, Other charge recipient}, `charge_recipient[]`, `charge_treatment[]` ∈ {Include in material cost, Separate expense, Not material cost}, `charge_basis[]` ∈ {By value, By quantity, Manual}; flags `charge_grid_present`, `charge_supplier_billing_present`; button **Add charge** |
| Cost allocation | `allocation_basis_default` ∈ {By line value (recommended), By quantity} |
| Memo fields | `adjustment_amount`, `discount`, `tax_percent`, `tax_amount`, `tax_type` ∈ {Asset, Expense, Purchase(Adv Tax)}, `supplier_invoice_no`, `bill_date`, `due_date` |
| Notes | `note`, `photo` |
| Buttons | **Next**, **Add**, **Reset**, **Add charge**, **Recalculate**, **Save GRN**, **Cancel** |
| Live totals | *Supplier Material* · *Supplier Ledger Bill* · *Capitalised Charges* · *Total Actual Cost* · *Avg Actual Rate / Unit* |

**"GRN never pays."** A GRN records stock and a payable; payment happens later in Accounts → *PAY EXISTING GRN* (step 12).

### 7.2 Page inventory — the records table

Columns: *GRN # · Date & Time · Supplier · Items · Total Qty · Discount · Actual Cost · Cash Paid · Payment Status · Actions*.
Row actions: **Consumption by lot** (expands to *In hand / Received / Consumed / Remaining*), **Shift GRN Supplier** (`POST /shift_grn_supplier/<id>`: `target_supplier_id`), **Cancel** (`POST /grn`: `action=delete, id`).
Filters: `start_date`, `end_date`, `search`; button **Filter**, **Recalculate**.

### 7.3 Page inventory — the costs tab

Filters `tab=costs`, `cost_kind` ∈ {All costs, Stock / material, Vehicle fare / transport, Loading, Unloading, Other expenses}, `cost_supplier`, `cost_start`, `cost_end`.
Columns: *Date · GRN · Supplier · Cost kind · Detail*; links to *In hand / Received / Consumed / Remaining*.

### 7.4 Steps — six receipts

Post body = `action=add, supplier=<name>, supplier_id=<id>, date, time, manual_bill_no, mat_name[]=…, qty[]=…, price[]=…, allocation_basis_default=VALUE`.

| # | `manual_bill_no` | `supplier` (id) | `date` | `mat_name[]` | `qty[]` | `price[]` | Line value |
|---|---|---|---|---|---|---|---|
| 7.4.1 | `CYC-GRN-1` | Ravi Cement Supplier (1) | `2026-10-02` | DG Cement | `100` | `1200` | **120,000** |
| 7.4.2 | `CYC-GRN-2` | Ravi Cement Supplier (1) | `2026-10-04` | DG Cement | `50` | `1350` | **67,500** |
| 7.4.3 | `CYC-GRN-3` | Kohat Traders (2) | `2026-10-06` | DG Cement | `80` | `1400` | **112,000** |
| 7.4.4 | `CYC-GRN-4` | Ravi Cement Supplier (1) | `2026-10-08` | Pioneer Cement | `60` | `1600` | **96,000** |
| 7.4.5 | `CYC-GRN-5` | Kohat Traders (2) | `2026-10-10` | Chenab Sand | `200` | `55` | **11,000** |
| 7.4.6 | `CYC-GRN-6` | Ravi Cement Supplier (1) | `2026-10-12` | TRANSPARENT SHEET | `40` | `300` | **12,000** |

All six post with `time=09:00`. Flash: **"GRN added successfully!"**.

### 7.5 Expected results

| # | Check | Expected | P/F |
|---|---|---|---|
| 7.5.1 | DB `grn` rows | 6 rows; `costing_mode='LANDED'`; `supplier_material_amount = landed_cost_total` for every row (no charges yet) | |
| 7.5.2 | GRN 1 totals | `supplier_material_amount=120000.0`, `landed_cost_total=120000.0` | |
| 7.5.3 | GRN 2 totals | `67500.0` / `67500.0` | |
| 7.5.4 | GRN 3 totals | `112000.0` / `112000.0` | |
| 7.5.5 | GRN 4 totals | `96000.0` / `96000.0` | |
| 7.5.6 | GRN 5 totals | `11000.0` / `11000.0` | |
| 7.5.7 | GRN 6 totals | `12000.0` / `12000.0` | |
| 7.5.8 | Sum of purchases | **418,500** | |
| 7.5.9 | DB `grn_item` | ids 1–6 with `qty`, `price_at_time`, `landed_unit_cost = price` (1,200 / 1,350 / 1,400 / 1,600 / 55 / 300) | |
| 7.5.10 | Auto bills | `SB-GRN-1000` … `SB-GRN-1005` in creation order | |
| 7.5.11 | Manual bills | stored/displayed as `MB NO.CYC-GRN-1` … `MB NO.CYC-GRN-6` | |
| 7.5.12 | DB `material.total` | DG **230**, Pioneer **60**, Chenab Sand **200**, TRANSPARENT SHEET **40** | |
| 7.5.13 | `/inventory/stock_summary` (range 01–31 Oct) | *Total Received* **530.00**, *Total Delivered* **0.00**, *Net Movement* **530.00** | |
| 7.5.14 | Stock-summary grid | DG Cement 230 / 0 / 230 · Pioneer 60 / 0 / 60 · Chenab Sand 200 / 0 / 200 · Sheet 40 / 0 / 40 | |
| 7.5.15 | `/suppliers` KPIs | Total Purchase **418,500.00**, Total Paid **0.00**, Outstanding **418,500.00** | |
| 7.5.16 | `/suppliers` rows | Ravi purchase 295,500 · Kohat purchase 123,000 | |
| 7.5.17 | GRN row status | **Unpaid** on all six | |
| 7.5.18 | Duplicate manual bill | repeating `CYC-GRN-1` is rejected (manual bill uniqueness) | |
| 7.5.19 | Future date | `date=2030-01-01` is rejected | |
| 7.5.20 | Unknown supplier | `supplier_id=999` is rejected (must select from the list) | |
| 7.5.21 | Zero/negative qty | `qty=0` or `-5` is rejected; no GRN row created | |
| 7.5.22 | Missing price | blank `price[]` is rejected | |

### 7.6 Charge coverage (optional but required by the "landed cost" feature)

Repeat one extra GRN to prove charges capitalise, then cancel it so the canonical totals above stay valid.

| # | Action | Value |
|---|---|---|
| 7.6.1 | Add GRN `CYC-GRN-X`, supplier Ravi, DG Cement, qty 10, price 1,200 | material 12,000 |
| 7.6.2 | Press **Add charge**; set `charge_type[]` = `TRANSPORT`, `charge_amount[]` = `2000`, `charge_recipient_type[]` = `TRANSPORTER`, `charge_recipient[]` = `Ravi Transport`, `charge_treatment[]` = `INVENTORY`, `charge_basis[]` = `VALUE`, `charge_grid_present=1` | |
| 7.6.3 | **Save GRN** → open the row's **Consumption by lot** | GRN shows *Supplier Material 12,000* · *Capitalised Charges 2,000* · *Total Actual Cost 14,000* · *Avg Actual Rate / Unit 1,400* |
| 7.6.4 | DB `grn_item.landed_unit_cost` | **1,400** (not 1,200) |
| 7.6.5 | `/grn?tab=costs`, `cost_kind=VEHICLE` | the 2,000 transport charge appears under *Vehicle fare / transport* | |
| 7.6.6 | `charge_treatment[]=EXPENSE` variant | the charge does **not** raise `landed_unit_cost`; it appears on the costs tab as a separate expense | |
| 7.6.7 | **Cancel** the test GRN | `POST /grn` `action=delete&id=<id>` → flash **"GRN cancelled; 1 lot(s) reversed, 0 payment record(s) preserved."**; `grn.is_void=1`, `is_cancelled=1`; stock returns to its previous value | |
| 7.6.8 | Re-check canonical totals | stock DG back to 230, purchases back to 418,500 | |

> **Runner warning:** the GRN page's own flash for the charge grid has been observed to say *"No charges on this GRN. The purchase cost is the supplier material only."* while the charge **was** persisted. Always assert on the DB (`grn_item.landed_unit_cost`) and the *Total Actual Cost* tile, never on that sentence.

---

## 8. Step 8 — Book material (booking)

**Page:** `/bookings` — *Bookings*.

### 8.1 Page inventory

| Region | Detail |
|---|---|
| Filters (`GET /bookings`) | `show` ∈ {active, voided, all} · `client` · `bill_no` · `date_from` · `date_to` · `per_page` ∈ {10, 20, 50}; buttons **Filter**, **Reset** |
| Table columns | Manual Bill · Auto Bill · Client · Material · Qty · Total Amount · Actually Paid · Notes · Actions |
| Add form (`POST /add_booking`) | `client_code` (combobox, name or code) · `material_id[]` · `service_id[]` · `material_name[]` · `qty[]` · `unit_rate[]` · `amount` · `paid_amount` · `payment_method` ∈ {Cash, Bank} · `payment_account_id` · `date` (datetime-local) · `discount` · `discount_reason` · `manual_bill_no` · `photo` · `photo_url` · `note`; buttons **+ Add More Items**, **Save Booking** |
| Row actions | **Delete** (`POST /delete_transaction/Booking/<id>` — soft void) · edit modal (`POST /edit_bill/Booking/<id>`) |
| Helper text | *Required when Paid Now is greater than 0* (on the receive account) |

### 8.2 Steps

| # | Field | Value |
|---|---|---|
| 8.2.1 | `client_code` | `CYC-CL-1` |
| 8.2.2 | item row 1: `material_name[]` | `DG Cement` |
| 8.2.3 | `qty[]` | `20` |
| 8.2.4 | `unit_rate[]` | `1500` |
| 8.2.5 | `amount` | `30000` (auto-computed, may be edited) |
| 8.2.6 | `paid_amount` | `10000` |
| 8.2.7 | `payment_method` | `Cash` |
| 8.2.8 | `payment_account_id` | `Main Cash` |
| 8.2.9 | `date` | `2026-10-13T09:00` |
| 8.2.10 | `discount` / `discount_reason` | `0` / *(blank)* |
| 8.2.11 | `manual_bill_no` | `CYC-BK-1` |
| 8.2.12 | `note` | `20 bags booked at 1500` |
| 8.2.13 | **Save Booking** | flash **Booking added successfully (Bill: MB NO.CYC-BK-1) — Pending amount: 20000.0** |

### 8.3 Expected results

| Check | Expected | P/F |
|---|---|---|
| 8.3.1 DB `booking` | 1 row: `client_name='Bilal Construction'`, `amount=30000.0`, `paid_amount=10000.0`, `discount=0.0`, `manual_bill_no='MB NO.CYC-BK-1'`, `auto_bill_no='SB-BK-1000'`, `receive_in_account_id=1` | |
| 8.3.2 DB `booking_item` | `('DG Cement', 20.0, 1500.0)` | |
| 8.3.3 Stock unchanged | DG still **230** — a booking reserves material, it does not move it | |
| 8.3.4 Cash account | `Main Cash.balance = 210,000.00` (200,000 + 10,000) | |
| 8.3.5 `account_transaction` row 1 | `to_account_id=1`, `amount=10000.0`, `transaction_type='Receipt'`, `source_type='Booking'`, `source_id=1`, description *Booking paid now from Bilal Construction (MB NO.CYC-BK-1)* | |
| 8.3.6 Booking list row | Manual `MB NO.CYC-BK-1` · Auto `SB-BK-1000` · Bilal Construction · DG Cement · 20.0 · 30000.00 · 10000.00 · *20 bags booked at 1500* | |
| 8.3.7 Bill view | `/view_bill_detail/Booking/1` → *Current Bill Total 30,000* · *Paid Amount 10,000* · **Bill Pending: 20,000** | |
| 8.3.8 Pending bill | `pending_bill` row `MB NO.CYC-BK-1` amount **9,000** (the not-yet-delivered 10,000 less the 20,000 still owed = line-level allocation; verify on `/pending_bills`) | |
| 8.3.9 Client ledger | `/ledger/2` *Total Due (Debit)* **30,000.00**, *Total Paid/Credit* **10,000.00**, *Net Balance* **20,000.00** | |
| 8.3.10 Booking with paid > total | rejected (*paid cannot exceed the booking value*) | |
| 8.3.11 Booking with no account but paid > 0 | rejected (*select the account that received the money*) | |
| 8.3.12 Unknown client | *Client "XYZ" not found. Please add client first.* | |
| 8.3.13 Zero rate | *Unit rate is required and must be greater than 0 for "DG Cement".* | |
| 8.3.14 Stock not checked at booking | booking 500 bags is accepted (reservation only); the shortage shows at delivery time | |

---

## 9. Step 9 — Cash sale (direct sale)

**Page:** `/direct_sales` — *Sales*.

### 9.1 Page inventory

| Region | Detail |
|---|---|
| Filters (`GET /direct_sales`) | `show` · `page` · `client` · `bill_no` · `bill_state` ∈ {All, Billed, Unbilled} · `category` ∈ {Booked Sale, Booked + Due, Due Sale, Open Khata, Cash Sale} · `material` · `per_page` ∈ {10, 20, 50, 100} |
| Tiles | **Billed Sales (Due / Booking)** — click to add · **Unbilled Sales (Cash)** — click to add |
| Table columns | Bill No. · System Ref · Status · Client · Date & Time · Material · Qty · Total Amount · Driver Rent · Notes · Actions |
| Sale form (`POST /add_direct_sale`) | `category` ∈ {Booking Delivery, Mixed Transaction, Credit Customer, Open Khata, Cash} · `client_code` · `client_name` · `manual_client_name` · `has_bill` · `create_invoice` · `track_as_cash` · `draft_id` · `idempotency_key` · `delivery_person_id[]` · `delivery_bags[]` · `delivery_rent_amount[]` · `sale_date` · `material_id[]` · `service_id[]` · `product_name[]` · `grn_item_id[]` · `alternate_material_id[]` · `alternate_material[]` · `qty[]` · `unit_rate[]` · `ignore_booking_item[]` · `delivery_rent` · `manual_bill_no` · `photo` · `photo_url` · `note` · `amount` · `discount` · `discount_reason` · `paid_amount` · `payment_method` ∈ {Cash, Bank Transfer, Check} · `payment_account_id` · `bank_name` · `account_name` · `account_no` · `allow_negative_stock` |
| On-screen live panels | **CLIENT BOOKING STATUS** (booked / delivered / remaining per material) · **RUNNING PENDING** (Total Due · Total Paid · Waive-Off (Loss) · Net Pending) · **RENT CHARGED TO CLIENT (TOTAL)** · **DELIVERY PERSON RENT (ACTUAL)** · **RENT DIFFERENCE (PROFIT/LOSS)** |
| Buttons | **+ Add More Items**, **+ Add Delivery Person**, **Save Sale**, **Hold** (draft), **Resume**, **Delete**, **Reset** |
| Row actions | **Delete** (`POST /delete_transaction/DirectSale/<id>`) · edit modal (`POST /edit_bill/DirectSale/<id>`) |
| APIs | `/api/client_booking_status/`, `/api/client_financial_summary/` |

**Category → behaviour**

| Category | Client needed | Stock effect | Financial effect |
|---|---|---|---|
| `Cash` | manual name only | OUT (FIFO) | fully paid; no receivable |
| `Credit Customer` | yes | OUT (FIFO) | `paid_amount` received now, remainder becomes receivable |
| `Booking Delivery` | yes | OUT (FIFO), consumes the booking pool | no new bill; revenue recognises against the booking |
| `Mixed Transaction` | yes | OUT (FIFO) | split between booking consumption and a new credit portion |
| `Open Khata` | manual name; auto-routed to `OPEN KHATA` | OUT (FIFO) | runs an open running balance |

### 9.2 Steps

| # | Field | Value |
|---|---|---|
| 9.2.1 | **New Direct Sale** → *Unbilled Sales (Cash)* | — |
| 9.2.2 | `category` | `Cash` |
| 9.2.3 | `manual_client_name` | `Walk-in Customer` |
| 9.2.4 | `has_bill` | `on` |
| 9.2.5 | `sale_date` | `2026-10-14` |
| 9.2.6 | `delivery_person_id[]` | `Akram Driver` |
| 9.2.7 | `delivery_bags[]` | `5` |
| 9.2.8 | `delivery_rent_amount[]` | `200` |
| 9.2.9 | item: `product_name[]` | `DG Cement` |
| 9.2.10 | `qty[]` | `5` |
| 9.2.11 | `unit_rate[]` | `1700` |
| 9.2.12 | `ignore_booking_item[]` | `1` (cash sale never consumes a booking) |
| 9.2.13 | `delivery_rent` | `200` |
| 9.2.14 | `manual_bill_no` | `CYC-CASH-1` |
| 9.2.15 | `amount` | `8500` |
| 9.2.16 | `discount` | `0` |
| 9.2.17 | `paid_amount` | `8500` |
| 9.2.18 | `payment_method` / `payment_account_id` | `Cash` / `Main Cash` |
| 9.2.19 | `idempotency_key` | `cyc-cash-1` |
| 9.2.20 | **Save Sale** | flash **"Direct sale added successfully"** |

### 9.3 Expected results

| Check | Expected | P/F |
|---|---|---|
| 9.3.1 DB `direct_sale` row 1 | `category='Cash'`, `client_name='Walk-in Customer'`, `client_code IS NULL`, `amount=8500.0`, `paid_amount=8500.0`, `manual_bill_no='MB NO.CYC-CASH-1'`, `auto_bill_no='SB-SL-1000'`, `driver_name='Akram Driver'`, `delivery_rent_cost=200.0` | |
| 9.3.2 DB `direct_sale_item` row 1 | `('DG Cement', 5.0, 1700.0, cost_rate_at_sale=1200.0)` | |
| 9.3.3 FIFO lot consumed | lot 1 (`SB-GRN-1000`, 1,200) drops 100 → 95 | |
| 9.3.4 Stock | DG 230 → **225** | |
| 9.3.5 Cash | `Main Cash` 210,000 → **218,500.00** | |
| 9.3.6 `account_transaction` row 2 | `to_account_id=1`, `8500.0`, `Receipt`, `source_type='DirectSale'`, `source_id=1` | |
| 9.3.7 `delivery_rent` row 1 | `('Akram Driver','MB NO.CYC-CASH-1',200.0)` | |
| 9.3.8 `entry` row (OUT) | `type='OUT'`, `material='DG Cement'`, `client='Walk-in Customer'`, `qty=5.0`, `bill_no='MB NO.CYC-CASH-1'`, `nimbus_no='Direct Sale'`, `client_category='Cash'`, `driver_name='Akram Driver'` | |
| 9.3.9 List row | `MB NO.CYC-CASH-1` · `SB-SL-1000` · **BILLED** · Walk-in Customer · 14 Oct 2026 · DG Cement · 5.0 · 8500.00 · 200.00 | |
| 9.3.10 Invoice | `/view_bill/SB-SL-1000`: DG Cement 5 × 1,700 = 8,500 · *Current Bill Total 8,500* · *Previous Balance 0* · *Paid 8,500* · *Outstanding 0* | |
| 9.3.11 Cash sale forced fully paid | posting `paid_amount` < `amount` on a `Cash` sale is normalised to fully paid (or rejected) — the sale must never leave a receivable | |
| 9.3.12 Negative stock guard | qty greater than stock without `allow_negative_stock` is rejected with a user-readable message (see 10.3.13 for the real case) | |
| 9.3.13 Duplicate submit | re-posting the identical body with `idempotency_key=cyc-cash-1` → info flash *already saved*, **no second sale** | |

---

## 10. Step 10 — Credit sale, then booking delivery

### 10.1 Credit sale

| # | Field | Value |
|---|---|---|
| 10.1.1 | `category` | `Credit Customer` |
| 10.1.2 | `client_code` | `CYC-CL-1` |
| 10.1.3 | `sale_date` | `2026-10-15` |
| 10.1.4 | `delivery_person_id[]` / `delivery_bags[]` / `delivery_rent_amount[]` | `Akram Driver` / `10` / `400` |
| 10.1.5 | item | `DG Cement`, `qty[]=10`, `unit_rate[]=1650`, `ignore_booking_item[]=1` |
| 10.1.6 | `delivery_rent` | `400` |
| 10.1.7 | `manual_bill_no` | `CYC-CR-1` |
| 10.1.8 | `amount` / `paid_amount` | `16500` / `5000` |
| 10.1.9 | `payment_method` / `payment_account_id` | `Cash` / `Main Cash` |
| 10.1.10 | `idempotency_key` | `cyc-cr-1` |
| 10.1.11 | **Save Sale** | **"Direct sale added successfully"** |

### 10.2 Booking delivery

| # | Field | Value |
|---|---|---|
| 10.2.1 | `category` | `Booking Delivery` |
| 10.2.2 | `client_code` | `CYC-CL-1` |
| 10.2.3 | `sale_date` | `2026-10-16` |
| 10.2.4 | `delivery_person_id[]` / `delivery_bags[]` / `delivery_rent_amount[]` | `Akram Driver` / `20` / `800` |
| 10.2.5 | item | `DG Cement`, `qty[]=20`, `unit_rate[]=1500`, `ignore_booking_item[]=0` (consume the booking) |
| 10.2.6 | `delivery_rent` | `800` |
| 10.2.7 | `manual_bill_no` | `CYC-BD-1` |
| 10.2.8 | `amount` / `paid_amount` | `30000` / `0` |
| 10.2.9 | `idempotency_key` | `cyc-bd-1` |
| 10.2.10 | **Save Sale** | **"Direct sale added successfully"** |

### 10.3 Expected results

| Check | Expected | P/F |
|---|---|---|
| 10.3.1 `direct_sale` row 2 | `Credit Customer`, `Bilal Construction`, `CYC-CL-1`, `16500.0`, paid `5000.0`, `MB NO.CYC-CR-1`, `SB-SL-1001`, rent 400 | |
| 10.3.2 `direct_sale` row 3 | `Booking Delivery`, `Bilal Construction`, **`amount=0.0`**, paid `0.0`, `MB NO.CYC-BD-1`, `SB-SL-1002`, rent 800 | |
| 10.3.3 `direct_sale_item` row 2 | `('DG Cement', 10.0, 1650.0, cost_rate_at_sale=1200.0)` | |
| 10.3.4 `direct_sale_item` row 3 | `('DG Cement', 20.0, price_at_time=0.0, cost_rate_at_sale=NULL)` — the delivery carries no new price; revenue is taken from the booking line | |
| 10.3.5 Stock | DG 225 → 215 → **195** | |
| 10.3.6 FIFO layers used | 5 @1200 (cash) + 10 @1200 (credit) + 20 @1200 (delivery) = 35 bags off lot 1 → lot 1 remaining **65** | |
| 10.3.7 Cash | **223,500.00** (218,500 + 5,000) | |
| 10.3.8 `account_transaction` row 3 | `to_account_id=1`, `5000.0`, `Receipt`, `source_type='DirectSale'`, `source_id=2` | |
| 10.3.9 No cash row for the booking delivery | the 3rd sale adds **no** `account_transaction` (paid 0) | |
| 10.3.10 `delivery_rent` rows 2–3 | 400 and 800 against `MB NO.CYC-CR-1`, `MB NO.CYC-BD-1` | |
| 10.3.11 Entries | two more OUT rows, `qty` 10 and 20, `nimbus_no='Direct Sale'`, `client_category` `Credit Customer` / `Booking Delivery`, driver `Akram Driver` | |
| 10.3.12 Client ledger | `/ledger/2` *Total Due* **46,500.00** (30,000 + 16,500) · *Total Paid* **15,000.00** (10,000 + 5,000) · *Net* **31,500.00** — the "Previous Balance 20,000" on the credit-sale invoice is the booking's unpaid part | |
| 10.3.13 Over-sell guard | a 4th sale of 300 bags without `allow_negative_stock` is rejected (only 195 in stock); with `allow_negative_stock=1` it saves and `material.total` goes negative | |
| 10.3.14 Booking pool exhausted | a second `Booking Delivery` for 1 more bag is rejected: *Cannot dispatch 1.0 bags. Only 0.0 bags available from booking. (Booked: 20.0, Dispatched: 20.0)* | |
| 10.3.15 Open Khata path | `category=Open Khata` + `manual_client_name=Random Guy` saves against client `OPEN KHATA` and leaves a running balance | |

---

## 11. Step 11 — Deliveries and delivery rent

**Page:** `/delivery_rents` — *Delivery Person Rent*.

### 11.1 Page inventory

| Region | Detail |
|---|---|
| Filters | `date_from`, `date_to`, `driver`, `q`, `group_by` ∈ {By person, By day}, `sort` ∈ {Most due, Oldest unpaid, Highest rent, Most paid, Name}; button **FIND**/**Apply** |
| KPI strip | **Rent earned** · **Paid** · **Remaining** · **Delivery persons** |
| Group columns | Delivery Person · Rent · Paid · Remaining · Trips · Action |
| Trip columns | Date · Delivery Person · Bill · Client · Bags · Rent · Paid · Remaining · Action |
| Row actions | **Pay** (opens `rentEntryPayForm`) · **reverse** (`POST /delivery_rents/void/<id>`) · **View** (detail) |
| Pay forms | `POST /delivery_rents/pay/<allocation_id>` and `POST /delivery_rents/pay_driver/<person_id>`; fields `paid_amount, waive_off_amount, method` ∈ {Cash, Bank, Check, Online}, `payment_account_id`, `date`, `reference`, `note`, `idempotency_key`, `next`; button **Save Payment** |
| Account options | `[CASH] Main Cash (Rs. …)` / `[BANK] Meezan Bank (Rs. …)` — the label carries the live balance |

### 11.2 Expected results after step 10

| Check | Expected | P/F |
|---|---|---|
| 11.2.1 KPI *Rent earned* | **Rs. 1,400.00** (200 + 400 + 800) | |
| 11.2.2 KPI *Paid* | **Rs. 0.00** | |
| 11.2.3 KPI *Remaining* | **Rs. 1,400.00** | |
| 11.2.4 KPI *Delivery persons* | **1** | |
| 11.2.5 Group row | `Akram Driver` · 3 trips · *Rent* 1,400.00 · *Paid* 0.00 · *Remaining* 1,400.00 · badge **Due** | |
| 11.2.6 Trip rows | 14 Oct `MB NO.CYC-CASH-1` Walk-in Customer 5 bags 200.00 · 15 Oct `MB NO.CYC-CR-1` Bilal 10 bags 400.00 · 16 Oct `MB NO.CYC-BD-1` Bilal 20 bags 800.00 | |
| 11.2.7 `group_by=day` | same totals regrouped by date; the three days sum to 1,400 | |
| 11.2.8 `sort=due` / `oldest` | ordering changes only, totals unchanged | |
| 11.2.9 `/delivery_person_ledger/1` | *Opening balance Rs. 0.00* · *Total debit Rs. 1,400.00* · *Total credit Rs. 0.00* · *Closing balance Rs. 1,400.00 Payable* | |
| 11.2.10 No `account_transaction` yet | rent is a liability; nothing has left the bank | |

### 11.3 Step 12.5 (run later) — pay the driver

See §12.5; it is ordered with the other payments but checked here for the rent figures.

---

## 12. Step 12 — Pay and receive money

Four independent money paths. **Do them in this order** — later checks assume it.

### 12.1 Client receipt — `/accounts/payments/clients`

| Element | Detail |
|---|---|
| Filters | `show` ∈ {active, voided, all} · `from` · `to` · `party_id` · `account_id` · `method` ∈ {Cash, Bank, Check, Card, Online} · `payment_type` ∈ {Receipt / Payment Received, Refund Paid to Client, Waive-Off Only} · `per_page` · `q` |
| Table columns | Date · Client · Type · Account · Amount · Method · Bill # · Note · Actions |
| Form (`POST /accounts/payments/clients/save`) | `payment_id` · `revision` · `idempotency_key` · `show` · `client_code` · `client_name` · `payment_type` ∈ {Receipt, Refund, Waive-Off} · `amount` · `discount` · `discount_reason` · `method` · `payment_account_id` · `manual_bill_no` · `date` · `photo` · `photo_url` · `note`; buttons **New Payment**, **Save Payment** |
| Row actions | **View** (`/view_bill_detail/Payment/<id>`) · **Void** (`POST …/void/<id>`) · **Restore** (`POST …/restore/<id>`) — a voided row is hidden under *Active* |
| Legacy alias | `POST /add_payment` (used by `/payments`); same service, redirects to this page |

| # | Field | Receipt 1 | Receipt 2 |
|---|---|---|---|
| 12.1.1 | `client_code` | `CYC-CL-1` | `CYC-CL-1` |
| 12.1.2 | `payment_type` | `Receipt` | `Receipt` |
| 12.1.3 | `amount` | `8000` | `3000` |
| 12.1.4 | `discount` | `0` | `0` |
| 12.1.5 | `method` | `Cash` | `Bank Transfer` |
| 12.1.6 | `payment_account_id` | `Main Cash` | `Meezan Bank` |
| 12.1.7 | `date` | `2026-10-18` | `2026-10-19` |
| 12.1.8 | `manual_bill_no` | `CYC-RCPT-1` | `CYC-RCPT-2` |
| 12.1.9 | `note` | `part receipt against credit sale` | `bank receipt` |
| 12.1.10 | `idempotency_key` | `cyc-rcpt-1` | `cyc-rcpt-2` |
| 12.1.11 | Submit | flash **"Payment saved successfully."** | same |

| Check | Expected | P/F |
|---|---|---|
| 12.1.12 `payment` rows | `(Bilal Construction, 8000.0, Cash, Receipt, account 1, 'MB NO.CYC-RCPT-1', 'SB-CP-1000')` and `(…, 3000.0, Bank, Receipt, account 2, 'MB NO.CYC-RCPT-2', 'SB-CP-1001')` | |
| 12.1.13 Cash / Bank | Main Cash 223,500 + 8,000 = **231,500.00** · Meezan Bank 500,000 + 3,000 = **503,000.00** | |
| 12.1.14 Replay | identical resubmit of `cyc-rcpt-1` → info *already processed; no duplicate was created*; still 2 payment rows | |
| 12.1.15 Key reuse with a changed amount | → danger *This form token was already used for a different payment.* | |
| 12.1.16 Duplicate manual bill | `CYC-RCPT-1` on a new key → *Manual bill 'MB NO.CYC-RCPT-1' already exists in Payment #1.* | |
| 12.1.17 Refund path | `payment_type=Refund` larger than the account balance → *Insufficient balance in the selected account for this refund.* | |
| 12.1.18 Waive-off | `payment_type=Waive-Off` with `amount` + `discount` writes a `WaiveOff` row and reduces the receivable **without** touching any account | |
| 12.1.19 Void / restore | void → *Payment deleted. Balances reversed and recalculated.*, `is_void=1`, bank balance back to 503,000 − 3,000 = 500,000; restore → *Payment restored. Balances re-applied.*, `is_void=0`, balance 503,000 | |
| 12.1.20 `/payments` shows the same rows | Customer Payments table lists both, with **No Bill** badge where the auto bill is not displayed | |

### 12.2 GRN supplier payment — `/accounts/grn_payments` (*PAY EXISTING GRN*)

| Element | Detail |
|---|---|
| Filter | `grn_id` (dropdown `MB NO.… · supplier · date · cost … · due …`); button **Open GRN** |
| Obligation table columns | Recipient · Obligation · Original · Already Paid · Remaining · Status |
| Payment table columns | Date · Recipient · Amount · Method · Reference · Status |
| Form (`POST /accounts/grn_payments/save`) | `_csrf_token` · `grn_id` · `idempotency_key` · `obligation_key` (`SUPPLIER:<id>` or `CHARGE:<charge_id>`) · `amount` · `method` · `payment_account_id` · `date_posted` · `reference` · `note` · `allow_advance`; button **Save payment** |
| Row actions | **Void** (`POST /accounts/grn_payments/<id>/void`) · **Restore** (…/restore) |
| Guarantee | the remaining-balance guard refuses an over-payment unless `allow_advance` is set |

| # | Field | Value |
|---|---|---|
| 12.2.1 | `grn_id` | `1` (`MB NO.CYC-GRN-1`, cost 120,000, due 120,000) |
| 12.2.2 | `obligation_key` | `SUPPLIER:1` |
| 12.2.3 | `amount` | `60000` |
| 12.2.4 | `method` | `Cash` |
| 12.2.5 | `payment_account_id` | `Main Cash` |
| 12.2.6 | `date_posted` | `2026-10-20` |
| 12.2.7 | `reference` | `CYC-GRNPAY-1` |
| 12.2.8 | Submit | flash **"GRN payment of Rs. 60,000.00 recorded from Accounts."** |

| Check | Expected | P/F |
|---|---|---|
| 12.2.9 `supplier_payment` row 1 | `supplier_id=1`, `amount=60000.0`, `method='Cash'`, `payment_account_id=1`, `auto_bill_no='SB-GP-1000'`, `source_type='GRN_PAYMENT'`, `source_id=1`, `grn_id=1`, `recipient_type='SUPPLIER'`, `payment_kind='GRN_MATERIAL'`, `cash_posted=1`, `reference='CYC-GRNPAY-1'` | |
| 12.2.10 `account_transaction` | `from_account_id=1`, `60000.0`, `transaction_type='GRN Payment'`, `source_type='GRN_PAYMENT'`, `grn_id=1`, `party_type='SUPPLIER'`, `party_name='Ravi Cement Supplier'` | |
| 12.2.11 Main Cash | 231,500 − 60,000 → **171,500.00** at this point | |
| 12.2.12 GRN row | `MB NO.CYC-GRN-1` cost 120,000 · due **60,000** · status **Partially Paid** | |
| 12.2.13 Over-payment | a second 70,000 against the same obligation is refused (*remaining 60,000*); with `allow_advance=1` it posts and the remainder becomes an advance | |
| 12.2.14 `/suppliers` KPI | Total Paid **60,000.00**, Outstanding **358,500.00** (418,500 − 60,000) | |

### 12.3 Plain supplier payment — `/accounts/payments/suppliers` (alias `/add_supplier_payment`)

| Element | Detail |
|---|---|
| Filters | `show` · `from` · `to` · `party_id` · `account_id` · `method` · `per_page` · `q` |
| Table columns | Date · Supplier · Account · Amount · Method · Bill # · Note · Actions |
| Form (`POST /accounts/payments/suppliers/save`) | `payment_id` · `revision` · `idempotency_key` · `show` · `supplier_id` · `supplier_name` · `amount` · `method` · `payment_account_id` · `manual_bill_no` · `date` · `note` |
| Shift block | `supplierPaymentShiftForm`: `target_supplier_id`, `return_to` |
| Legacy | `POST /add_supplier_payment` (`return_to, supplier_id, date, amount, payment_account_id, method, bank_name, account_name, account_no, manual_bill_no, note`) |

| # | Field | Value |
|---|---|---|
| 12.3.1 | `supplier_id` | `1` (Ravi Cement Supplier) |
| 12.3.2 | `date` | `2026-10-21` |
| 12.3.3 | `amount` | `20000` |
| 12.3.4 | `payment_account_id` | `Meezan Bank` |
| 12.3.5 | `method` | `Bank Transfer` |
| 12.3.6 | `manual_bill_no` | `CYC-SUPPAY-1` |
| 12.3.7 | `note` | `part payment Ravi` |
| 12.3.8 | Submit | flash **"Supplier payment recorded."** |

| Check | Expected | P/F |
|---|---|---|
| 12.3.9 `supplier_payment` row 2 | `20000.0`, `method='Bank'` (normalised), `payment_account_id=2`, `manual_bill_no='MB NO.CYC-SUPPAY-1'`, `auto_bill_no='SB-SP-1000'`, `source_type IS NULL` | |
| 12.3.10 `account_transaction` | `from_account_id=2`, `20000.0`, `'Supplier Payment'`, `source_type='SupplierPayment'`, `source_id=2` | |
| 12.3.11 Meezan Bank | 503,000 − 20,000 → **483,000.00** | |
| 12.3.12 Supplier ledger | `/supplier_ledger/1`: *Total debit 80,000.00* · *Total credit 295,500.00* · *Closing 215,500.00 Payable* | |
| 12.3.13 `/suppliers` row | Ravi: purchase 295,500.00 · paid 80,000.00 · outstanding **215,500.00** · badge **Payable** | |
| 12.3.14 Over/under | negative amount rejected; amount above the payable allowed only as an advance (status becomes *Advance / prepaid*) | |
| 12.3.15 Shift entry | moving a payment to another supplier re-points the same `supplier_payment` row and re-checks both ledgers | |

### 12.4 Accounts dashboard *New Transaction* — `/accounts/`

| Element | Detail |
|---|---|
| Button | **New Transaction** → modal *Make New Transaction* (`POST /accounts/transactions/new`) |
| `tx_mode` | **Receive Money** (`receive`) or **Pay Money** (`pay`) |
| Common | `date_posted` (datetime-local) · `amount` · `method` ∈ {Cash, Bank Transfer, Check, Online} · `reference` · `note` · `idempotency_key` |
| Receive block | `receive_from_category` ∈ {Client Ledger, Clients, Company, External, Loan, Own Funds, Other Source} · `receive_account_id` · `client_input` (client combo) · `receive_from_account_id` (for Company transfers) · `receive_source_label` · `discount` |
| Pay block | `pay_from_account_id` · `pay_target` ∈ {`company_transfer` Company Account Transfer, `supplier` Supplier Payment, `grn_payment` PAY EXISTING GRN, `driver` Driver Service Payment, `client_refund` Client Refund, `loan` Loan Payment, `personal_expense` Personal Expense, `other_expense` Other Expense} · `grn_payment_grn_id` · `pay_to_account_id` · `supplier_id` · `supplier_input` · `target_label` · `client_id_refund` · `client_input_refund` · `delivery_person_id` · `driver_input` |
| Submit | **Submit Transaction** |

| # | Action | Fields | Expected |
|---|---|---|---|
| 12.4.1 | Receive from an outside party | `tx_mode=receive`, `receive_from_category=other_source`, `receive_source_label=Owner cash injection`, `amount=4000`, `receive_account_id=Main Cash`, date today | flash **"Receive transaction recorded successfully."**; cash +4,000; a `Receipt` row with `source_type IS NULL` |
| 12.4.2 | Pay a personal expense | `tx_mode=pay`, `pay_target=personal_expense`, `pay_from_account_id=Main Cash`, `target_label=Tea & misc`, `amount=1500` | flash **"Outgoing payment recorded successfully."**; cash −1,500; `transaction_type='Payment'` |
| 12.4.3 | Transfer between accounts | `pay_target=company_transfer`, `pay_from_account_id=Main Cash`, `pay_to_account_id=Meezan Bank`, `amount=10000` | one `Transfer` row: cash −10,000 → 165,500, bank +10,000 → 493,000; `/cash_flow` *Transfers* tile becomes **Rs. 10,000** while received/spent stay 39,500 / 81,000 |
| 12.4.4 | Linked rows are read-only | opening a `Payment`/`DirectSale`/`GRN`-sourced row | edit is refused with *This payment is controlled by … edit it from that source module* |
| 12.4.5 | Void | `POST /accounts/transactions/<id>/void` | row `is_void=1`; the linked source row is **not** silently changed — the void is recorded in the audit trail |

> **Ordering note:** §12.4 is optional for the canonical numbers in §0.5. If you run 12.4.1/12.4.2, subtract the net (2,500) from the cash figures quoted in §13–§17, or delete the two rows with **void** before continuing.

### 12.5 Driver settlement — `/delivery_person_ledger/1`

| Element | Detail |
|---|---|
| Header buttons | **Export / download** · **Delivery rents** · **Pay driver** · **Opening balance** · **Back** |
| Summary tiles | Opening balance Rs. 0.00 · Total debit Rs. 1,400.00 · Total credit Rs. 0.00 · Closing balance Rs. 1,400.00 **Payable** |
| Pay form (`POST /delivery_person_ledger/<id>/pay`) | `paid_amount` · `waive_off_amount` · `method` · `payment_account_id` · `date` · `reference` · `note` · `idempotency_key` |
| Edit form | `POST /delivery_person_payments/<id>/edit`: `amount_paid, waive_off_amount, method, payment_account_id, date, reference, note, expected_revision` |
| Row actions | **void** (`POST /delivery_person_payments/<id>/void`) · **restore** |

| # | Field | Value |
|---|---|---|
| 12.5.1 | `paid_amount` | `1000` |
| 12.5.2 | `waive_off_amount` | `0` |
| 12.5.3 | `method` | `Cash` |
| 12.5.4 | `payment_account_id` | `Main Cash` |
| 12.5.5 | `date` | `2026-10-22` |
| 12.5.6 | `reference` | `CYC-DRV-1` |
| 12.5.7 | `note` | `part driver settlement` |
| 12.5.8 | `idempotency_key` | `cyc-drv-1` |
| 12.5.9 | Submit | flash **"Driver payment recorded across 3 rent item(s). The cash/bank account and driver ledger were updated together."** |

| Check | Expected | P/F |
|---|---|---|
| 12.5.10 FIFO allocation | three `delivery_person_payment` rows: 200.00 (sale 1), 400.00 (sale 2), 400.00 (sale 3) — the 1,000 is spread oldest-first | |
| 12.5.11 Idempotency keys | `cyc-drv-1:0`, `cyc-drv-1:1`, `cyc-drv-1:2` | |
| 12.5.12 Account transactions | three `Driver Payment` rows of 200 / 400 / 400 from account 1, `source_type='DeliveryPersonPayment'` | |
| 12.5.13 Main Cash | 171,500 − 1,000 → **170,500.00** | |
| 12.5.14 `/delivery_rents` | *Paid* **Rs. 1,000.00**, *Remaining* **Rs. 400.00**; group badge stops being fully *Due* | |
| 12.5.15 Driver ledger | *Total credit Rs. 1,000.00* · *Closing balance Rs. 400.00 Payable* | |
| 12.5.16 Over-payment | paying 2,000 on a 1,400 debt is refused (or the extra needs a waive-off/advance) | |
| 12.5.17 Void one slice | voiding payment 1 puts 200 back on the rent item and refunds 200 to cash | |
| 12.5.18 Replay | identical resubmit with the same key → *"This settlement was already recorded; no duplicate was created."* | |

### 12.5b Why the driver payment is the last cash outflow

The 1,000 driver settlement is split across three `delivery_person_payment` rows (200 + 400 + 400) because the rent was accrued on three separate bills and each slice settles the oldest unpaid rent item first. The cash effect is a single 1,000 debit, spread as three `Driver Payment` account transactions. If a tester posts a *lump* 1,000 as one row with a custom `reference`, the allocation order still oldest-first and the row count still comes out as three.

### 12.6 Position after all payments

| Account | Opening | In | Out | Balance |
|---|---|---|---|---|
| Main Cash | 200,000 | 10,000 + 8,500 + 5,000 + 8,000 = **31,500** | 60,000 + 200 + 400 + 400 = **61,000** | **170,500.00** |
| Meezan Bank | 500,000 | **3,000** | **20,000** | **483,000.00** |
| **Company** | **700,000** | **34,500** | **81,000** | **653,500.00** |

| Check | Expected | P/F |
|---|---|---|
| 12.6.1 | `/accounts/` *Total Cash Available* = **Rs. 170,500.00** (200,000 + 31,500 − 61,000) | |
| 12.6.2 | `/accounts/` *Total Money Available in Company* = **Rs. 653,500.00** (170,500 + 483,000) | |
| 12.6.3 | `/accounts/` account row | Main Cash **170,500.00** — it becomes 175,500 only after §13 records the 5,000 owner investment | |
| 12.6.4 | Meezan Bank row | **483,000.00** | |
| 12.6.5 | `account_transaction` count | **10** rows: booking 10,000 · cash sale 8,500 · credit sale 5,000 · receipt 8,000 · receipt 3,000 · GRN payment 60,000 · supplier payment 20,000 · driver 200 / 400 / 400. The booking-delivery sale contributes **none** | |
| 12.6.6 | `/accounts/ledger/1` | every row of the cash ledger is present with a running balance ending at 170,500 | |
| 12.6.7 | No orphan cash | sum of `account.balance` = 653,500 = 700,000 + 34,500 − 81,000 | |

---

## 13. Step 13 — Cash flow: manual entry, transfer, reconciliation

**Page:** `/cash_flow` — tabs *Transactions* (`#tab-transactions`), *Reconcile* (`#tab-reconcile`), *Financial Details* (`#tab-financial-details`), *Categories* (`#tab-categories`), *Parties* (`#tab-parties`).

### 13.1 Page inventory

| Region | Detail |
|---|---|
| Filter form (`GET /cash_flow`, `#tab-transactions`) | `from_date` · `to_date` · `ft_preset` ∈ {Today, Yesterday, This Week, This Month, Last 30 Days, All} · `ft_direction` ∈ {All Directions, In (Received), Out (Spent), Transfer} · `ft_category` · `ft_account` · `ft_client` · `ft_supplier` · `ft_partner` · `ft_worker` · `ft_vehicle` · `ft_method` · `ft_q`; buttons **Apply Filters**, **Reset Filters**, and exports **CSV / PDF** |
| KPI tiles | *Opening Balance · Start of period* · *Total Received [IN]* · *Total Spent [OUT]* · *Closing Balance · Opening + received − spent* · *Transfers · Not income or expense* · *Physical Cash · Reconciled count* |
| Table columns | Date · Type · Account · Category · Subcategory · Party · Description · Notes · Reference · Received · Spent · Transfer · Actions |
| Entry write path | `POST /cash_flow` with `action=record_movement` (create) or `action=edit_entry` + `entry_id` (edit) |
| Entry fields | `direction` ∈ {in, out, transfer} · `amount` · `cash_account_id` · `to_account_id` (transfers) · `category_id` · `category_name` · `subcategory_id` · `subcategory_name` · `party_id` · `party_name` · `party_type` ∈ {client, supplier, worker, vehicle, partner, other} · `description` · `movement_note` · `reference` · `movement_date` · `idempotency_key` |
| Category form | `action=add_category`, `new_category_name`, `new_category_direction` ∈ {in, out, both}, `new_category_notes` |
| Sub-category form | `action=add_subcategory`, `new_subcategory_name`, `parent_category_id`, `new_subcategory_notes` |
| Party form | `action=add_party`, `new_party_name`, `new_party_type`, `new_party_phone`, `new_party_note` |
| Reconcile form (`#tab-reconcile`) | `action=save_reconciliation` · `adjustment_date` · `physical_cash_available` · `reconciliation_reason`; delete via `action=delete` |
| Edit/void/restore | `action=edit_entry` · `action=void_entry` + `void_reason` · `action=restore_entry` + `restore_reason` |

### 13.2 Steps — manual cash-flow entry

| # | Field | Value |
|---|---|---|
| 13.2.1 | open **Categories** tab → `new_category_name` | `Owner Investment` |
| 13.2.2 | `new_category_direction` | `in` |
| 13.2.3 | **Create Category** | flash **"Category saved."** |
| 13.2.4 | **Transactions** tab → **Record Movement** | form opens |
| 13.2.5 | `direction` | `in` |
| 13.2.6 | `amount` | `5000` |
| 13.2.7 | `cash_account_id` | `Main Cash` |
| 13.2.8 | `category_id` | `Owner Investment` |
| 13.2.9 | `description` | `Owner put cash in` |
| 13.2.10 | `movement_date` | `2026-10-23` |
| 13.2.11 | `reference` | `CYC-CF-IN` |
| 13.2.12 | `idempotency_key` | `cyc-cf-in` |
| 13.2.13 | **Post Received** (`action=record_movement`) | flash **"Cash flow transaction recorded and the account effect was applied."** |

### 13.3 Expected results — manual entry

| Check | Expected | P/F |
|---|---|---|
| 13.3.1 `cash_flow_category` row | `('Owner Investment', 'in')` | |
| 13.3.2 `cash_flow_entry` row | `direction='in'`, `amount=5000.0`, `account_id=1`, `category_id=1`, `description='Owner put cash in'`, `date_posted='2026-10-23 00:00:00'`, `source_type='MANUAL_CASH_FLOW'` | |
| 13.3.3 Cash affected | `Main Cash` 170,500 → **175,500.00** | |
| 13.3.4 `account_transaction` row 11 | `to_account_id=1`, `5000.0`, `transaction_type='Receipt'`, `source_type='CashFlowEntry'`, `source_id=1` | |
| 13.3.5 Cash-flow KPI *Total Received* | **Rs. 39,500** (34,500 + 5,000) | |
| 13.3.6 Cash-flow KPI *Closing Balance* | **Rs. 158,500** (200,000 + 39,500 − 81,000) — cash **only** | |
| 13.3.7 Row appears in the table | 23 Oct · Received · Main Cash · Owner Investment · — · — · *Owner put cash in* · `CYC-CF-IN` · received 5,000 | |
| 13.3.8 Idempotent resubmit | same `idempotency_key` → info *"This transaction was already recorded."*; cash stays 175,500 | |
| 13.3.9 Wrong-direction category | `direction=out` with the `in`-only category → danger flash, no entry | |
| 13.3.10 Amount ≤ 0 | rejected | |
| 13.3.11 Transfer needs two accounts | `direction=transfer` without `to_account_id` → rejected | |
| 13.3.12 Transfer must not double count | a 10,000 cash→bank transfer leaves *Total Received* and *Total Spent* unchanged and only moves the *Transfers* tile to **Rs. 10,000** | |
| 13.3.13 Edit | `action=edit_entry` changes amount 5,000 → 6,000, audit row written, account effect re-applied (cash ±1,000) | |
| 13.3.14 Void/restore | `action=void_entry` → row marked void, cash effect reversed; `action=restore_entry` → re-applied | |

### 13.4 Sub-categories, parties, accounts

| Check | Expected | P/F |
|---|---|---|
| 13.4.1 `action=add_subcategory` under *Owner Investment* | parent shown as *Owner Investment*, sub-category appears in the *Subcategory* column option list | |
| 13.4.2 `action=add_party` type `client` | party appears in the `ft_client` filter and the `party_name` autocomplete | |
| 13.4.3 Party type `supplier` / `worker` / `vehicle` / `partner` | each lands in its own filter dropdown | |
| 13.4.4 Deactivate a category | `POST /cash_flow/categories/<id>/toggle` (or the *Disable* button) — category disappears from new-entry pickers, old rows keep their label | |
| 13.4.5 Category with entries cannot be deleted | the delete control is refused and the entries stay | |

### 13.5 Reconciliation — `#tab-reconcile`

The block compares the **physical cash count** against the ledger closing for the period and stores the difference. It does **not** change any account balance.

| # | Field | Value |
|---|---|---|
| 13.5.1 | `adjustment_date` | `2026-10-31` |
| 13.5.2 | `physical_cash_available` | `175500` |
| 13.5.3 | `reconciliation_reason` | `month end physical count` |
| 13.5.4 | **Save Reconciliation** (`action=save_reconciliation`) | flash **"Reconciliation saved for 2026-10-31."** |

| Check | Expected | P/F |
|---|---|---|
| 13.5.5 `cash_flow_difference_adjustment` row | `adjustment_date='2026-10-31'`, `physical_cash_available=175500.0`, `calculated_closing=158500.0`, `difference=17000.0`, `reason='month end physical count'` | |
| 13.5.6 Difference sign | positive 17,000 = **excess** (physical count is *higher* than the calculated closing) | |
| 13.5.7 **The 17,000 gap is the scope bug, recorded as expected output** | `calculated_closing` = **158,500** but Main Cash really holds **175,500**. The opening (200,000) sums **cash-category accounts only**, while the receipts (39,500) and spends (81,000) sum **every company account including the bank**. The bank's net movement is 3,000 − 20,000 = **−17,000**, and that is exactly the gap: 158,500 + 17,000 = 175,500. See defect 22.7 — the report under-states closing by every bank movement in the period | |
| 13.5.7a | Proof by filter: `/cash_flow?account_id=1` → opening 200,000, closing 175,500 (correct for cash). `/cash_flow?account_id=2` → opening **still 200,000** (should be 500,000), closing **183,000** (should be 483,000). The opening never follows the selected account | |
| 13.5.7b | If the opening included the bank too, closing would be 700,000 + 39,500 − 81,000 = **658,500** — exactly `/accounts/` *Total Money Available in Company*. That is the number the reconciliation was designed to compare against | |
| 13.5.8 Audit trail | `cash_flow_reconciliation_audit` gets a `CREATE` row (`old_physical_cash=NULL`, `new_physical_cash=175500.0`) | |
| 13.5.9 Re-save | changing the count to 100,000 writes an `EDIT` row (`old=175500`, `new=100000`) and `difference=-58500.0` (shortage); `edit_count` increments | |
| 13.5.10 Delete | `action=delete` → flash **"Reconciliation removed for 2026-10-31. Audit trail retained."**; `physical_cash_available=NULL`, `difference=NULL`, `amount=0`, `note='Reconciliation removed; audit trail retained.'`; a `DELETE` audit row is written | |
| 13.5.11 Next-day opening | after a saved reconciliation the following day's cash flow opens at the counted figure (*"Next day opening will be Rs. …"*), which is how a physical count resets the chain | |
| 13.5.12 `/cash_flow_differences` | lists the row with *Date · Opening Balance · Cash In · Cash Out · Calculated Closing · Physical Cash · Difference · Reason · Created By · Edits · Last Updated · Actions*; `workflow_filter` switches between *New (Physical Cash)* and *Legacy (Difference)* | |

> **Known display defect (do not file twice):** on a filtered cash-flow view the header tiles and the reconciliation block can disagree, because the tiles honour the display filters (`ft_*`) while the reconciliation block deliberately ignores them. Compare reconciliation numbers only on an unfiltered `/cash_flow?from_date=…&to_date=…`.

---

## 14. Step 14 — Material return

**Page:** `/material_returns` — *Material Returns*.

### 14.1 Page inventory

| Region | Detail |
|---|---|
| Filters (`GET /material_returns`) | `client` · `bill_no` · `material` · `date_from` · `date_to` · `show` ∈ {All, Active, Deleted}; button **Go** |
| Table columns | Date · Bill · Client · Type · Items · Amount · Notes · Action |
| Form (`POST /add_material_return`) | `client_code` · `client` · `date` · `return_type` ∈ {normal, booked} · `material_id[]` · `material_name[]` · `qty[]` · `unit_rate[]` · `service_id[]` · `rent_rate[]` · `manual_bill_no` · `note`; button **Add Material Return** |
| Row actions | **Edit** (`POST /edit_material_return/<id>`) · **Delete** (`POST /delete_transaction/MaterialReturn/<id>` — soft void) |

**Return types**

* `normal` — stock comes **back** (IN entry), the client is credited, no booking is touched.
* `booked` — the return reverses part of a booking delivery; the booking pool is re-opened.

> **Important:** the correct endpoint is **`/add_material_return`**. A POST to `/material_return` (singular) returns **404** and saves nothing — do not use it.

### 14.2 Steps

| # | Field | Value |
|---|---|---|
| 14.2.1 | `client_code` | `CYC-CL-1` |
| 14.2.2 | `date` | `2026-10-26` |
| 14.2.3 | `return_type` | `normal` |
| 14.2.4 | `material_name[]` | `DG Cement` |
| 14.2.5 | `qty[]` | `2` |
| 14.2.6 | `unit_rate[]` | `1650` |
| 14.2.7 | `manual_bill_no` | `CYC-RTN-1` |
| 14.2.8 | `note` | `2 bags returned` |
| 14.2.9 | **Add Material Return** | flash **"Material return saved successfully."** |

### 14.3 Expected results

| Check | Expected | P/F |
|---|---|---|
| 14.3.1 `material_return` row | `client_name='Bilal Construction'`, `return_type='normal'`, `amount=3300.0`, `manual_bill_no='MB NO.CYC-RTN-1'`, `auto_bill_no='SB-RTN-1000'`, `date_posted='2026-10-26 00:00:00'`, `is_void=0` | |
| 14.3.2 `material_return_item` | `('DG Cement', 2.0, 1650.0)` | |
| 14.3.3 Stock | DG 195 → **197** | |
| 14.3.4 `entry` row | `type='IN'`, `qty=2.0`, `bill_no='MB NO.CYC-RTN-1'` — the *only* IN row that is not a GRN | |
| 14.3.5 Credit note | `payment` row id 3 of type `Return`/credit for 3,300 linked from `material_return.payment_id` | |
| 14.3.6 Client ledger | `/ledger/2` *Total Paid / Credit* 26,000 → **29,300** · *Net Balance* 20,500 → **17,200** | |
| 14.3.7 List row | 26 Oct · `MB NO.CYC-RTN-1` · Bilal Construction · **Normal** · DG Cement (2.00) · 3,300.00 · *2 bags returned* | |
| 14.3.8 `/inventory/stock_summary` | *Total Received* 530 + 2 = **532.00**, *Net Movement* **497.00** — a return counts as stock in | |
| 14.3.9 Return above sold qty | returning 500 bags is rejected (or flagged) rather than silently inflating stock | |
| 14.3.10 Booked return | `return_type=booked` on the booking-delivery bill re-opens the booking pool; a following `Booking Delivery` for the returned qty is then accepted again | |
| 14.3.11 Delete | soft void: `is_void=1`, stock back to 195, credit note reversed, ledger returns to 20,500, and the row shows only under `show=deleted` | |
| 14.3.12 Reversal is symmetric | after delete, `/system_report` shows the same stock as before the return (no drift) | |

---

## 15. Step 15 — Pending bills and the decision ledger

### 15.1 Page inventory — `/pending_bills`

| Region | Detail |
|---|---|
| Filters | `client` · `bill_no` · `bill_kind` ∈ {All (SB/MB), SB (Auto), MB (Manual)} · `bill_from` · `bill_to` · `category` ∈ {Booked Sale, Booked + Due, Due Sale, Open Khata, Cash Sale, Cash Paid (Open Khata)} · `show`; buttons **Search**, **Add Bill**, **Export** (Excel/CSV), **Import** |
| Table columns | Client Code · Bill Ref · Bill Name · Client Name · Reason · Notes · Amount · Status · Actions |
| Add form (`POST /add_pending_bill`) | `client_code` · `bill_no` · `is_manual` · `amount` · `reason` · `note` · `photo` · `photo_url`; button **Save** |
| Row actions | **Mark Paid** (`POST /toggle_bill_paid/<id>` — flips `is_paid`) · **Edit** · **Delete** (soft void) |
| Import | `POST /import_pending_bills` — row needs **BillNo AND (ClientCode OR ClientName)**; missing clients are auto-created |
| Export | `/export_pending_bills?format=excel` or `?format=csv` |

### 15.2 Steps

| # | Field | Value |
|---|---|---|
| 15.2.1 | **Add Bill** → `client_code` | `CYC-CL-1` |
| 15.2.2 | `bill_no` | `CYC-PB-1` |
| 15.2.3 | `amount` | `4500` |
| 15.2.4 | `reason` | `Manual charge: extra loading` |
| 15.2.5 | **Save** | flash **"Pending bill added."** |

### 15.3 Expected results

| Check | Expected | P/F |
|---|---|---|
| 15.3.1 `pending_bill` row 4 | `client_code='CYC-CL-1'`, `bill_no='MB NO.CYC-PB-1'`, `amount=4500.0`, `is_paid=0`, `is_manual=1` | |
| 15.3.2 List before step 15.2 | exactly 3 rows: `MB NO.CYC-CR-1` 11,500 **unpaid** · `MB NO.CYC-CASH-1` **0.00 Paid** · `MB NO.CYC-BK-1` 9,000 **unpaid** | |
| 15.3.3 **Booking pending is 9,000, not 20,000** | `/pending_bills` shows **Rs. 9,000.00** for `MB NO.CYC-BK-1` while the booking itself still owes 20,000. The pending-bill row is intentional and is *not* the booking's outstanding amount — it is the not-yet-delivered portion. When you later deliver the remaining booking, the row is recalculated. **Record the observed 9,000; do not "fix" it to 20,000.** | |
| 15.3.4 Cash sale row | `MB NO.CYC-CASH-1` amount **0.00** with status **Paid** (a fully paid cash sale leaves a paid, zero-value row) | |
| 15.3.5 Toggle paid | `POST /toggle_bill_paid/4` → `is_paid` flips 0 → 1 → 0; status text changes **Unpaid ⇄ Paid** | |
| 15.3.6 Export | `/export_pending_bills?format=excel` downloads an `.xlsx` (~5 KB); `format=csv` downloads text/csv | |
| 15.3.7 Import round-trip | export, re-import the same file → no duplicates (matched by bill no) | |
| 15.3.8 Manual bill normalisation | `CYC-PB-1` is stored as `MB NO.CYC-PB-1` | |
| 15.3.9 Duplicate bill refused | adding `CYC-PB-1` twice is rejected | |
| 15.3.10 Zero amount refused | `amount=0` is rejected on the manual path (only system rows may be zero) | |

### 15.4 Page inventory — `/decision_ledger`

| Element | Detail |
|---|---|
| Filter | `q` · `category` (auto-derived) · `per_page`; plus **Previous / Next** paging |
| Table | Booking / client rollup with *booked · delivered · remaining · total value* |
| Help text | *Booked: 30,000.00 · Delivered: 30,000.00 · Remaining: 0.00* |

| Check | Expected | P/F |
|---|---|---|
| 15.4.1 Booking 1 rollup | **Booked 30,000.00 · Delivered 30,000.00 · Remaining 0.00** — the 20-bag delivery closed the 20-bag booking | |
| 15.4.2 OPEN KHATA row | `OPEN KHATA` / `OPEN-KHATA` / *Open Khata* / 0 / **-** / *View* | |
| 15.4.3 Filters | `q` and `category` narrow the rows without changing the totals of the remaining rows | |
| 15.4.4 No page-level write form | the decision ledger is read-only; it renders no POST form | |

---

## 16. Step 16 — Reports: P&L, financial details, stock, tracking, payables

### 16.1 P&L — `/profit_reports`

**Filters:** `start_date` · `end_date` · `client` · `reference` · `rows` ∈ {25, 50, 100} · category multi-select (*Supplies*, *Sales*, *Delivery Revenue*, *Sale Returns*, *Booked Returns*, *Expenses*, *Other Income*, *Reconciliation*, *Discounts / Waives*, *Cost supplier*) · exports **PDF**, **Excel**.

| # | Action | Value |
|---|---|---|
| 16.1.1 | open with `start_date=2026-10-01&end_date=2026-10-31` | renders |

| Check | Expected (exact) | P/F |
|---|---|---|
| 16.1.2 | Sales (Money In) | **Rs. 55,000.00** (8,500 + 16,500 + 30,000; cash + credit + booked) | |
| 16.1.3 | COGS + Direct Service Cost | **Rs. 43,400.00** | |
| 16.1.4 | Supplier material cost in goods sold | **42,000.00** (= 18,000 actual + 24,000 estimated) | |
| 16.1.5 | Capitalised purchase costs in goods sold | **0.00** (no charges on the canonical GRNs) | |
| 16.1.6 | Delivery cost inside COGS | **1,400.00** | |
| 16.1.7 | Profit (Money Kept) | **Rs. 11,600.00** | |
| 16.1.8 | Net margin | **21.09 %** | |
| 16.1.9 | Markup | **26.73 %** | |
| 16.1.10 | Money Received (settlement only) | **Rs. 34,500.00** — never added to profit | |
| 16.1.11 | Recognized entries | **6** | |
| 16.1.12 | Profitable entries | *Total Rs. 13,000.00 · 3 profitable entries* | |
| 16.1.13 | Loss-making entries | *Total Rs. 1,400.00 · 3 loss entries* | |
| 16.1.14 | Inventory view | 495 qty · 376,500 value · 6 lots | |
| 16.1.15 | 42,000 = 18,000 + 24,000 | of which **actual** = 15 bags @1,200 (cash 5 + credit 10) = 18,000; **estimated** = 20 bags on the zero-priced booking delivery @1,200 fallback = 24,000. Both are inside the 42,000 line | |
| 16.1.16 | Profit arithmetic | 55,000 − 43,400 = **11,600**; 11,600 / 55,000 = **21.0909 %**; 11,600 / 43,400 = **26.7281 %** | |
| 16.1.17 | Every KPI is clickable | clicking *Money Received* opens `/financial_details?type=cash&start_date=…&end_date=…` and the TOTAL must equal 34,500 | |
| 16.1.18 | Empty period | a range with no activity shows 0.00 in every tile and does not crash | |
| 16.1.19 | Client filter | selecting `CYC-CL-1` drops *Sales* to **46,500** and *COGS* to **37,200** (the walk-in 8,500 / 6,000 falls out); profit becomes 9,300 | |

### 16.2 Financial details — `/financial_details`

**Filters:** `start_date` · `end_date` · `client` · `min_price` · `max_price` · `type`. Only **two** types exist:

| `type` | Title | Rows | TOTAL |
|---|---|---|---|
| `cash` (default) | *Cash Received Details* | 5 | **Rs. 34,500** |
| `credit` | *Due Amount Details* | 2 | **Rs. 31,500** |

| Check | Expected | P/F |
|---|---|---|
| 16.2.1 `type=cash` rows | 19 Oct Payment `MB NO.CYC-RCPT-2` 3,000 · 18 Oct Payment `MB NO.CYC-RCPT-1` 8,000 · 15 Oct Direct Sale `MB NO.CYC-CR-1` 5,000 · 14 Oct Direct Sale `MB NO.CYC-CASH-1` 8,500 · 13 Oct Booking Advance `MB NO.CYC-BK-1` 10,000 | |
| 16.2.2 `type=cash` TOTAL | **Rs. 34,500** | |
| 16.2.3 `type=credit` rows | 15 Oct Direct Sale Credit `MB NO.CYC-CR-1` **11,500** · 13 Oct Booking Credit `MB NO.CYC-BK-1` **20,000** | |
| 16.2.4 `type=credit` TOTAL | **Rs. 31,500** | |
| 16.2.5 Header line | *"Filtered: 5"* / *"Filtered: 2"* matches the row count | |
| 16.2.6 **`type=DirectSale` is not a valid filter** | posting it falls through to the empty branch and prints **`TOTAL Rs. 0`** with *"No transactions found for the selected criteria."* — only `cash` and `credit` are implemented. This is the source of the "TOTAL Rs. 0" report. Reach the page from the dashboard tiles, which always pass a valid type | |
| 16.2.7 `client=CYC-CL-1` | client **code** is resolved to a name server-side; rows filter to Bilal Construction only | |
| 16.2.8 `min_price`/`max_price` | bounds are inclusive; a min above every row gives the empty-state message, not an error | |

### 16.3 Stock summary — `/inventory/stock_summary`

| Check | Expected | P/F |
|---|---|---|
| 16.3.1 `date_from=2026-10-01&date_to=2026-10-31` | *Total Received* **530.00**, *Total Delivered* **35.00**, *Net Movement* **495.00** | |
| 16.3.2 Material-wise totals | DG **230 / 35.00 / 195.00** · Pioneer **60 / 0 / 60** · Chenab Sand **200 / 0 / 200** · TRANSPARENT SHEET **40 / 0 / 40** | |
| 16.3.3 Opening / In / Out / Closing / Physical Diff grid | DG 195 opening, +0 in, −0 out, 195 closing, `--` physical diff (no count recorded) | |
| 16.3.4 GRN receipts block | 6 rows, one per GRN, with bill + supplier + material + qty, all traceable | |
| 16.3.5 Day-wise totals | 2026-10-16 shows 0.00 received / 20.00 delivered etc.; the day list sums to 530 and 35 | |
| 16.3.6 Total qty tie | 530 − 35 = **495** = the P&L `inventory_view` qty | |

### 16.4 Tracking — `/tracking`

| Check | Expected | P/F |
|---|---|---|
| 16.4.1 `start_date`/`end_date` Oct | *TOTAL BAGS: **495*** · Chenab Sand 200 · DG Cement **195** · Pioneer 60 · TRANSPARENT SHEET 40 | |
| 16.4.2 Category chips | *Booking*, *Sales*, *General Walking-Customer*, *Misc* | |
| 16.4.3 Row columns | Date · Time · Type · Client · Code · Material · Qty · Bill · Driver | |
| 16.4.4 The 3 sales + 6 GRNs + 0 returns produce 9 movements; adding the §14 return adds a 10th (IN) row and moves the totals to 497 | | |

### 16.5 Purchase payables — `/accounts/purchase_payables`

| Check | Expected | P/F |
|---|---|---|
| 16.5.1 Rows | *Kohat Traders · Supplier · 123,000.00* · *Ravi Cement Supplier · Supplier · 215,500.00* | |
| 16.5.2 Columns | Supplier · Type · Balance · Actions (*Open ledger*) | |
| 16.5.3 Legacy charges column | **Rs. 0.00** (no legacy `supplier.charges` rows) | |
| 16.5.4 Sum | 123,000 + 215,500 = **338,500** = `/suppliers` *Outstanding Payable* | |
| 16.5.5 Explanation text | *"Supplier payables follow each GRN checkbox: material only, or material + GRN costs. Unchecked costs are payable to their own recipients."* | |
| 16.5.6 `/suppliers` KPI agreement | *Total Purchase 418,500.00 · Total Paid 80,000.00 · Outstanding 338,500.00* | |
| 16.5.7 Export | `/export_purchase_payables` → CSV (185 B on the canonical DB) | |

### 16.6 Supplier ledger — `/supplier_ledger/1`

| Check | Expected | P/F |
|---|---|---|
| 16.6.1 Header | supplier name, address, phone, period | |
| 16.6.2 Summary | *Balance brought forward Rs. 0.00 · Total bills (credit) Rs. 295,500.00 · Total payments (debit) Rs. 80,000.00 · Closing balance Rs. 215,500.00 **Payable*** | |
| 16.6.3 Row detail | 6 GRN credit rows + 2 payment debit rows, each with date, reference, particular, qty, rate, amount, debit/credit | |
| 16.6.4 Filters | *Transaction type* (All / Bills / Payments), date range, *Clear filters* | |
| 16.6.5 Downloads | **PDF** → `SL-1-<date>.pdf` (~5 KB, 1 page); **CSV** → 618 B. `scope=range&action=pdf` → 5,128 B. `format=` is ignored — PDF/CSV come from `action=` | |
| 16.6.6 295,500 tie | 120,000 + 67,500 + 96,000 + 12,000 = 295,500 (GRNs 1, 2, 4, 6 — all Ravi) | |
| 16.6.7 80,000 tie | 60,000 GRN payment + 20,000 plain payment | |

### 16.7 Client ledger — `/ledger/2` (*and* `/client_ledger/2`)

| Check | Expected | P/F |
|---|---|---|
| 16.7.1 Tiles | *Total Due (Debit)* **46,500.00** · *Total Paid / Credit* **26,000.00** · *Net Balance* **20,500.00 Client owes company** | |
| 16.7.2 Row count | booking 30,000 debit · credit sale 16,500 debit · advance 10,000 credit · receipts 8,000 + 3,000 credit · invoice-level paid 5,000 credit | |
| 16.7.3 Downloads | **PDF only** → 46,725 B, 2 pages, header *Total Due 46,500.00 / Total Paid 26,000.00 / Net Pending 20,500.00* | |
| 16.7.4 Client clearance | `/download_client_clearance/2` → 46,240 B; *Outstanding: Rs 20,500.00 (Please pay)*; unpaid rows `MB NO.CYC-CR-1` 11,500 · `MB NO.CYC-BK-1` 9,000 | |
| 16.7.5 Full history | `/download_full_client_history/2` → 54,915 B, 7 pages; *Total Bookings 30,000 · Total Direct Sales 16,500 · Total Paid 26,000 · Total Pending 20,500* | |
| 16.7.6 Read-only page | `/client_ledger/2` renders **no** write form — all edits go through the sale/payment pages | |

### 16.8 Delivery person ledger — `/delivery_person_ledger/1`

| Check | Expected | P/F |
|---|---|---|
| 16.8.1 Tiles | *Opening 0.00 · Total debit 1,400.00 · Total credit 1,000.00 · Closing **400.00 Payable*** | |
| 16.8.2 Rows | 3 rent debits (200/400/800) + 3 payment credits (200/400/400) | |
| 16.8.3 Download | `action=csv` → 716 B **CSV**; `action=pdf` also returns CSV (format switch not honoured on this ledger — known, matches supplier behaviour) | |
| 16.8.4 `/delivery_rents` agreement | Rent earned 1,400 · Paid 1,000 · Remaining **400** | |

---

## 17. Step 17 — Downloads and printed documents

Every link below was fetched and its bytes counted. A tester reproduces them by clicking the button named in the last column.

| # | Document | URL | Expected | Trigger |
|---|---|---|---|---|
| 17.1 | P&L PDF | `/profit_reports/export/pdf?start_date=2026-10-01&end_date=2026-10-31` | **57,042 B**, 6 pages, first line *Profit & Loss Control Center*, contains 55,000 / 11,600 / 1,400 | **PDF** button |
| 17.2 | P&L Excel | `/profit_reports/export/excel?…` | **21,888 B** `.xlsx` | **Excel** button |
| 17.3 | Client ledger PDF | `/download_client_ledger/2` | **46,725 B**, 2 pages, header *FAZAL BUILDING MATERIALS…*, *Total Due 46,500.00* | **PDF** on the client ledger |
| 17.4 | Client clearance | `/download_client_clearance/2` | **46,240 B**, *Outstanding: Rs 20,500.00 (Please pay)* | **Clearance** |
| 17.5 | Full client history | `/download_full_client_history/2` | **54,915 B**, 7 pages | **Full history** |
| 17.6 | Supplier ledger PDF | `/download_supplier_ledger/1?scope=full&action=pdf` | **5,148 B**, 1 page, *Closing balance 215,500.00* | **PDF** |
| 17.7 | Supplier ledger CSV | `…&action=csv` | **618 B** text/csv | **CSV** |
| 17.8 | Supplier ledger range PDF | `…?scope=range&action=pdf` | **5,128 B** | date range + **PDF** |
| 17.9 | Driver ledger | `/download_delivery_person_ledger/1?action=csv` | **716 B**; `action=pdf` also returns CSV | **CSV** |
| 17.10 | Invoice | `/download_invoice/SB-SL-1000` | **44,571 B**, 1 page; *Direct Sale (Cash) · MB: MB NO.CYC-CASH-1 · DG Cement 5 × 1,700 = 8,500 · Current Bill Total: 8,500* | **Invoice** on the sale |
| 17.11 | Cash flow PDF | `/cash_flow?from_date=2026-10-01&to_date=2026-10-31&export_pdf=1` | **50,511 B**, 4 pages; *Opening Balance: Rs. 200,000 · Total Received 39,500 · Total Spent 81,000 · Closing 158,500* | **PDF** |
| 17.12 | Cash flow CSV | `…&export_csv=1` | **2,474 B** | **CSV** |
| 17.13 | GRN export | `/export_grn` | **5,628 B** `.xlsx` | **Export** on `/grn` |
| 17.14 | Pending bills export | `/export_pending_bills?format=excel` | **5,210 B**; `format=csv` smaller | **Export** |
| 17.15 | Clients export | `/export_clients` | **5,129 B** | **Export** |
| 17.16 | Payables export | `/export_purchase_payables` | **185 B** CSV | **Export** |
| 17.17 | GRN consumption API | `/api/grn_consumption?grn_id=1` | **6,696 B** JSON with *in hand / received / consumed / remaining* per lot | *Consumption by lot* |
| 17.18 | Import template | `/import_export/template/pending_bills` | 200 with `.xlsx`; `/import_export/template/grn` → **400** (no template for GRN) | **Download template** |

**Rendering engine note.** WeasyPrint is not importable in this environment, so every PDF goes through `pdf_fallback._render_reportlab_pdf` at 14.8 × 21 cm with 1 cm margins. Byte counts above are from that path; a machine with WeasyPrint installed will produce different (usually larger) byte counts but identical *content*. Assert on the extracted text, not on the file size, when running on another machine.

**PDF content assertions that must hold on any engine**

| # | Assertion |
|---|---|
| 17.19 | The company name on client/supplier PDFs comes from `settings.company_name`; with no settings row it falls back to `FAZAL BUILDING MATERIALS` |
| 17.20 | Every money figure in a PDF carries a thousands separator and 2 decimals |
| 17.21 | No PDF contains the word `None` or `nan` |
| 17.22 | The P&L PDF carries a generated timestamp and the period label *2026-10-01 to 2026-10-31* |
| 17.23 | The invoice PDF lists the delivery person (`Akram Driver`) when one was assigned |
| 17.24 | A PDF requested for a non-existent id (e.g. `/download_client_ledger/999`) returns 404, not a stack trace |

---

## 18. Step 18 — Daily reconciliation, accounts audit, void audit

### 18.1 `/daily_reconciliation`

| Element | Detail |
|---|---|
| Account positions table | *Account · Opening · In · Out · Transfer In · Transfer Out · Expected Closing · Actual Counted · Difference · Action* |
| Header tiles | *Total Expected Ledger Balance* · *Total Actual Counted Balance* · *Net Difference* |
| Count form (`POST /daily_reconciliation`) | `account_id` · `counted` · `day` · `action` (count / shift_close / finalize) · `shift_name` · `shift_note` |
| Guarantee | a shift close captures every account's counted figure *at that moment*; finalising locks the day |

| Check | Expected | P/F |
|---|---|---|
| 18.1.1 Today's position | Main Cash opening **175,500** with 0 in/out → expected 175,500; Meezan Bank 483,000 | |
| 18.1.2 Header | *Total Expected Ledger Balance* **Rs. 658,500** *(All 2 company money accounts)* | |
| 18.1.3 Uncounted state | *Total Actual Counted Balance - · 0 of 2 accounts counted · Net Difference -* | |
| 18.1.4 Record a count | `account_id=1&counted=175500&day=<today>` → difference **0.00**, *1 of 2 accounts counted* | |
| 18.1.5 Mismatch | `counted=170000` → difference **−5,500** and the row is highlighted | |
| 18.1.6 Shift close | `action=shift_close&shift_name=Night` → *1 shift close checkpoint recorded*; the checkpoint keeps the counted values as of handover | |
| 18.1.7 Finalise | `action=finalize` → day locked; further counts for that day are refused with a clear message | |
| 18.1.8 No side effects | counting never changes `account.balance` — ledger vs count stay independent | |

### 18.2 `/accounts/audit` (transaction audit)

| Check | Expected | P/F |
|---|---|---|
| 18.2.1 Rows | all 11 `account_transaction` rows in date order with *type · account · amount · source · status · action* | |
| 18.2.2 Filters | `account_id` · `from`/`to` · `type` · `q` · `show_voided` | |
| 18.2.3 Void control | `POST /accounts/transactions/<id>/void` shows a confirm; the row is stamped `is_void=1` and struck through under *show_voided* | |
| 18.2.4 Void reverses the balance | voiding the 5,000 owner receipt takes Main Cash 175,500 → 170,500; restoring puts it back | |
| 18.2.5 Linked-source guard | voiding a `GRN Payment` row from here does **not** delete the `supplier_payment`; the two are reconciled by `source_type`/`source_id` and `/system_report` reports any mismatch | |

### 18.3 `/void_audit`

| Check | Expected | P/F |
|---|---|---|
| 18.3.1 Empty on a clean DB | *Total 0 · Deleted 0 · Suspended 0* and *"No records"* | |
| 18.3.2 After a soft delete | deleting a sale/GRN/payment adds a row with *Type · Title · Details · Status · Action*; `Section` filter switches Transactions/Directory | |
| 18.3.3 Restore | the action link restores the row and the audit entry flips status | |
| 18.3.4 Nothing is ever hard-deleted by the UI | the table only grows — `Total` counts deletions, not live rows | |

---

## 19. Step 19 — Directory, settings, users, permissions

### 19.1 `/clients` — client directory

| Check | Expected | P/F |
|---|---|---|
| 19.1.1 KPI strip | Payable *(This page)* **20,500.00** · Advance **0.00** · Billed **46,500.00** · Received **26,000.00** · Active Clients **2** | |
| 19.1.2 Row — Bilal Construction | Code `CYC-CL-1` · Opening 0.00 · Billed 46,500.00 · Received 26,000.00 · Payable **20,500.00** · badge **Payable** | |
| 19.1.3 Row — OPEN KHATA | code `OPEN-KHATA` · billed 0 · balance 0 · badge **Settled** | |
| 19.1.4 Category filter | `General` shows only Bilal; `Open Khata` shows only OPEN KHATA | |
| 19.1.5 Search | `CYC-CL-1` and `Bilal` both find the client | |
| 19.1.6 Opening balance edit | `/ledger/2` → **Set Opening Balance** → 1,500 with date → tiles shift by 1,500 and `/clients` Payable becomes 22,000; set back to 0 | |
| 19.1.7 Delete guard | a client with transactions cannot be hard-deleted — only soft-suspended | |

### 19.2 `/settings` — General

| Field | Value used in the test |
|---|---|
| `company_name` | `Ahmed Cement Co` |
| `company_address` | `Islamabad` |
| `company_phone` | `051-1234567` |
| `currency_symbol` | `Rs.` |
| `allow_negative_stock` | `1` (then back to `0`) |

| Check | Expected | P/F |
|---|---|---|
| 19.2.1 Save | `POST /update_settings` → flash **"Settings updated successfully!"**; `settings` row has `company_name='Ahmed Cement Co'` | |
| 19.2.2 Immediate propagation | every PDF requested after the save carries `Ahmed Cement Co` (no restart needed) | |
| 19.2.3 Negative-stock flag | with the flag on, the §10.3.13 over-sell is accepted and `material.total` goes negative; with it off the same post is refused | |
| 19.2.4 Material categories block | the 4 categories from §2 with *Name · Status · Action*; rename/toggle work here too | |
| 19.2.5 Sidebar settings | **Sidebar Settings** opens the drag-and-drop layout editor; the saved layout is what the next page load renders | |

### 19.3 Users and permissions — `/settings` → *Users*

| Element | Detail |
|---|---|
| Fields | `username` · `password` · `role` ∈ {admin, manager, sales, accounts, viewer} · per-module permission grid |
| Actions | **Add User** · **Edit** · **Reset Password** · **Delete** · **Change Password** (self) |

| Check | Expected | P/F |
|---|---|---|
| 19.3.1 Add `Cashier` role `accounts` | saved; appears in the user list | |
| 19.3.2 `Cashier` can open `/accounts/`, `/accounts/payments/clients`, `/cash_flow` | 200 | |
| 19.3.3 `Cashier` blocked from `/settings` and `/system_report` | redirected to `/` with *"Unauthorized"* danger flash | |
| 19.3.4 `viewer` role | every write POST is refused; no *Save* button is rendered | |
| 19.3.5 Self password change | `change_password` with the right current password succeeds; a wrong one is refused | |
| 19.3.6 Admin cannot delete itself | the last admin account is protected | |
| 19.3.7 Delete a non-admin user | removed; its audit rows keep the username string | |

### 19.4 Admin dashboard — `/admin/`

| Check | Expected | P/F |
|---|---|---|
| 19.4.1 Module count | **6 Loaded Modules** — `accounts`, `admin`, `data_lab`, `import_export`, `inventory`, `module_template` | |
| 19.4.2 Status | all six **Loaded**, *Online* system status | |
| 19.4.3 System info | server time (PKT), role `Admin` | |
| 19.4.4 Root `/` | the marketing/landing route is 404 — the real home is `/dashboard` | |

### 19.5 `/notifications` — reminder queue

| Check | Expected | P/F |
|---|---|---|
| 19.5.1 Tiles | *Total **2** · Pending **2** · Very High **1** · High **1** · Medium 0 · Low 0 · Active Reminders 0* | |
| 19.5.2 Queue table | *Client · Bill · Amount · Risk · Next Reminder · Last Response · Contacts · Action*; rows for `CYC-CR-1` (11,500) and `CYC-BK-1` (9,000) | |
| 19.5.3 Filters | `category` · `status` · `risk` · `q` | |
| 19.5.4 Set reminder | `POST /notifications/reminders` with `remind_at` (**not** `reminder_at`), format `YYYY-MM-DDTHH:MM`, plus `note` → row appears in *Upcoming Reminders* | |
| 19.5.5 Log contact | `POST /notifications/contacts` → new row in table **`follow_up_contact`** | |
| 19.5.6 Close reminder | the reminder leaves *Upcoming* and increments *Active Reminders* → 0 | |
| 19.5.7 Severity | `POST /set_severity` writes into `pending_bill.risk_override` (the column `severity` does not exist) | |
| 19.5.8 Risk counts follow severity | Very High/High/Medium/Low tiles recompute from the overrides | |

### 19.6 `/client-ledger/categories`

| Check | Expected | P/F |
|---|---|---|
| 19.6.1 Seeded rows | `General` (**default**) with 1 client · `Open Khata` with 1 client · both *Active* | |
| 19.6.2 Add `Contractor` | appears with 0 clients | |
| 19.6.3 Rename | the name changes on `/clients` filter too | |
| 19.6.4 Deactivate | the category disappears from the *new client* picker; existing clients keep it | |
| 19.6.5 Delete | refused while it holds clients | |

### 19.7 `/notifications/upcoming`

| Check | Expected | P/F |
|---|---|---|
| 19.7.1 Empty | *Due entries 0* and *"No upcoming reminders"* | |
| 19.7.2 With a reminder | the entry shows client, bill, amount, due time, note, and **Close** / **Reload** buttons | |

---

## 20. Step 20 — Import / export, legacy migration, data lab

### 20.1 `/import_export/`

| Element | Detail |
|---|---|
| Sections | `sections` = `literal_all`; `modules` = `accounts`, `bookings`, `cash_drawer`, `cash_flow`, `clients`, `delivery_persons`, `direct_sales`, `grn`, `material_returns`, `materials`, `notifications`, `payments`, `pending_bills`, `rentals`, `stock_movements`, `suppliers` |
| Mode | `mode` ∈ {merge, replace} |
| Buttons | **Export** (`POST /import_export/export`), **Import** (`POST /import_export/import`), **Full DB Export**, **Full DB Import** (`POST /import_export/full_db_import`, `file`, `confirm`) |
| Guarantee | *replace* wipes only the selected modules, inside a transaction |

| Check | Expected | P/F |
|---|---|---|
| 20.1.1 Export selected `clients` | `.xlsx` with a `clients` sheet, one row per client + header | |
| 20.1.2 **Merge** re-import | re-importing the same file does not duplicate rows (matched by code) | |
| 20.1.3 **Replace** re-import | the client table ends with exactly the file's rows; unrelated modules untouched | |
| 20.1.4 Full DB import | a full export re-imported into a fresh DB reproduces every count in `/system_report` | |
| 20.1.5 Wrong file type | uploading a `.pdf` for an `.xlsx` slot is rejected before any write | |
| 20.1.6 Partial module export | selecting `grn` alone exports GRNs **without** their items — re-import creates headers only (documented behaviour) | |

### 20.2 `/legacy-migration/`

| Element | Detail |
|---|---|
| Templates | `template_type` — 8 kinds covering suppliers, clients, materials, opening stock, GRNs, sales, payments, ledgers |
| Flow | download template → fill → upload → **preview** → **commit** |
| Guarantee | the preview counts every row as *insert / update / skip* before anything is written |

| Check | Expected | P/F |
|---|---|---|
| 20.2.1 Template download | each of the 8 templates downloads a non-empty `.xlsx` with headers | |
| 20.2.2 Preview | a 3-row file reports *3 to insert, 0 to update, 0 skipped* | |
| 20.2.3 Commit | rows appear in the target tables with `legacy` provenance | |
| 20.2.4 Re-run | running the same file twice does not duplicate (matched by code/bill) | |
| 20.2.5 Bad row | a row with a missing required column is *skipped* with a line number, never half-imported | |

### 20.3 `/data_lab`

| Check | Expected | P/F |
|---|---|---|
| 20.3.1 Renders | module loads, shows the query/inspection surface for the SQLite file | |
| 20.3.2 Read-only guard | destructive SQL (DROP/DELETE) is refused by the lab itself | |
| 20.3.3 Table list | lists every table in the DB, including `alembic_version` | |

---

## 21. Cross-checks — the numbers that must agree

Run these after the canonical dataset is complete (steps 1–13, with §14–§20 optional). Each line ties two independent pages together; a mismatch is a real defect.

| # | Tie | Value | P/F |
|---|---|---|---|
| 21.1 | `/accounts/` Main Cash balance == cash-flow closing on the cash account | 175,500 | |
| 21.2 | `/accounts/` company total == `/daily_reconciliation` expected | 658,500 | |
| 21.3 | `/suppliers` Outstanding == `/accounts/purchase_payables` sum | 338,500 | |
| 21.4 | `/suppliers` Total Purchase == Σ `grn.landed_cost_total` | 418,500 | |
| 21.5 | `/clients` Payable == `/ledger/2` net balance | 20,500 | |
| 21.6 | P&L *Money Received* == `/financial_details?type=cash` TOTAL | 34,500 | |
| 21.7 | `/financial_details?type=credit` TOTAL | **31,500** = credit sale unpaid 11,500 + booking unpaid-after-advance 20,000 | |
| 21.8 | Credit total vs client-ledger net | 31,500 − **20,500** = **11,000** = the 8,000 + 3,000 receipts taken *after* those bills. The credit report freezes each bill's unpaid amount at posting time and does not net later receipts; the ledger nets everything. Both are correct for their own question — record the 11,000 as an explained difference, not a defect | |
| 21.9 | `/delivery_rents` Remaining == driver ledger closing | 400 | |
| 21.10 | P&L Sales == Σ sale amounts (8,500 + 16,500 + 30,000) | 55,000 | |
| 21.11 | P&L COGS == Σ item qty × FIFO cost + delivery rent | 42,000 + 1,400 = 43,400 | |
| 21.12 | P&L Profit == Sales − COGS | 11,600 | |
| 21.13 | Stock total == 195 + 60 + 200 + 40 | 495 | |
| 21.14 | `/inventory/stock_summary` net == `/tracking` TOTAL BAGS | 495 | |
| 21.15 | Σ `account.balance` == opening 700,000 + in 34,500 − out 81,000 | 653,500 | |
| 21.16 | Cash-flow *Total Received* + *Total Spent* effect on cash | 175,500 − 200,000 = −24,500 = 36,500 − 61,000 | |
| 21.17 | Bank movement | 483,000 − 500,000 = −17,000 = 3,000 − 20,000 | |
| 21.18 | Every `account_transaction` with a `source_type`/`source_id` resolves to a live row | 10/10 resolve on the canonical DB (booking, 2 sales, 2 receipts, GRN payment, supplier payment, 3 driver payments) | |
| 21.19 | `/void_audit` total == number of voided rows | equal | |
| 21.20 | `/system_report` stock discrepancies | the KPI prints **2** while the body prints *"No stock discrepancies found."* — this is defect 22.4 row 2, not real drift. The real drift is **0** | |

---

## 22. Defect register (observed, reproducible)

These are the findings that came out of building this document. They are recorded here rather than fixed, so the runner knows what "expected" means for each.

### 22.1 Cash-flow record-movement form has no markup

`/cash_flow` renders the **JS that drives** `#cfRecordForm` / `#cfDirection` / `#cfAmount` / `#cfFormAction`, but **no element with those ids exists in the HTML** (verified: the strings appear only inside `<script>`). Consequences:

* There is no **Record Movement** button on the page for a human user.
* The documented `action=record_movement` POST still works when issued directly, and does everything correctly (entry + `account_transaction` + balance). Only the UI is missing.

Reproduce: `grep -c 'id="cfRecordForm"'` on the rendered page → **0**; `grep -c cfRecordForm` → **1** (inside the script block).

### 22.2 `/financial_details` shows `TOTAL Rs. 0` for an unknown `type`

The handler only implements `type == 'cash'` and `type == 'credit'`. Any other value (e.g. `type=DirectSale`, a value some bookmarks and the older dashboard used) falls through both branches, leaves `transactions` empty, and renders `TOTAL Rs. 0` with *"No transactions found for the selected criteria."* The two valid types are correct. Fix direction: treat an unknown type as `cash`, or return 400 with the valid list.

### 22.3 Receipts vs expenditures timing mismatch

`/accounts/receipts?from=2026-10-01&to=2026-10-31` → *Sales Paid 13,500 · GRN Paid 0.00 · Total Cash Movement 13,500* while `/accounts/expenditures?from=…` → *Total Spent 1,000, 3 entries*.

* **Sales Paid 13,500** is the sum of `direct_sale.paid_amount` (8,500 + 5,000 + 0) — it is **not** the 34,500 of `Payment` receipts, so the tile is "sale advances", not "cash received".
* **GRN Paid 0.00** despite a 60,000 GRN payment, because the page sums `grn.paid_amount`, which stays **0.0** — the GRN payment lives in `supplier_payment`, not on the GRN header.
* The two pages therefore never tie. Report both tiles as *markers*, and reconcile cash from `/cash_flow` instead.

### 22.4 `/system_report` — the three flagged rows on the canonical DB

| Row | Text | Root cause |
|---|---|---|
| 1 Sync Issue | *Missing Pending Bill Entry #9: Bill MB NO.CYC-BD-1 for Bilal Construction (CYC-CL-1) is missing from Pending Bills.* | The booking-delivery sale has `amount = 0.0`, so the pending-bill sync computes `pending = max(0, 0 − 0 − 0) = 0` and **creates no pending bill**, while the OUT entry still exists. Either the delivery should inherit the booking line's value, or the checker should exempt `Booking Delivery` rows |
| 2 Stock Discrepancies | *No stock discrepancies found. All material balances match.* (the count is nonetheless **2**) | The KPI counts `report.stock_issues` **before** the `>0.1` tolerance filter is applied to the display, so the number and the list disagree |
| 0 Unpaid / 0 Zero-Amount | — | correct |

The *Auto-Fix Issues* control posts to `/system_report` with `action=auto_fix`-style parameters and rebuilds the pending-bill rows; after it runs the sync issue clears but the underlying zero-amount delivery remains.

### 22.5 Zero-amount booking delivery (the anomaly behind 22.4)

`MB NO.CYC-BD-1` / `SB-SL-1002` is posted with `amount = 30,000` but stored as **0.0** with `paid_amount = 0.0`, one item at `price_at_time = 0.0` and `cost_rate_at_sale = NULL`, yet it correctly consumes the booking (`booking_allocation` qty 20) and moves 20 bags out of stock.

Effect on the reports:

* P&L still sees **55,000** revenue because revenue is recognised from the **booking**, not the sale — the delivery is the right *money* but the wrong *document*.
* The sale's own invoice (`/view_bill/SB-SL-1002`) prints **0.00**.
* `/accounts/receipts` lists a **0.00 / 0.00** row.
* `/system_report` raises the sync issue in 22.4.

Reproduce: `SELECT amount, paid_amount FROM direct_sale WHERE id=3` → `0.0, 0.0`; `SELECT price_at_time FROM direct_sale_item WHERE sale_id=3` → `0.0`.

Fix direction: on a `Booking Delivery`, stamp the sale `amount` from the consumed `booking_item.qty × price_at_time` (30,000 here) so the invoice, the receipts page and the pending-bill sync all agree, while keeping the P&L recognition on the booking.

### 22.6 Smaller observations

| # | Observation | Impact |
|---|---|---|
| 22.6.1 | `/material_return` (singular) → **404**; the working route is `/add_material_return` | documentation only |
| 22.6.2 | `format=` is ignored on ledger downloads; `action=pdf` / `action=csv` is the real switch (supplier and driver always return CSV even for `action=pdf`; the client ledger always returns PDF) | documentation only |
| 22.6.3 | Transfer form uses `from_account` / `to_account`; the cash-flow transfer uses `cash_account_id` / `to_account_id`; the accounts modal uses `pay_from_account_id` / `pay_to_account_id` — three names for the same pair | trap for API clients |
| 22.6.4 | Material return needs `return_type` = `normal` or `booked` (not the label "Normal Return") | trap |
| 22.6.5 | Reminder needs `remind_at`, not `reminder_at`; `YYYY-MM-DDTHH:MM` | trap |
| 22.6.6 | `404` (confirmed, do not retry): `/accounts/manage/accounts`, `/supplier_ledger` (no id), `/import_export/new`, `/tenants`, `/activity_log`, `/accounts/dashboard`, `/client_clearance/<id>`, `/party_ledger/<id>`, `/payment_receipt/<id>`, `/supplier_payment_receipt/<id>`, `/grn/<id>/print`, `/grn_bill/<id>`, `/accounts/transactions`, `/journal`, `/call_center`, `/inventory/history` | dead bookmarks |
| 22.6.7 | `/accounts` and `/financial_ledger/<id>` redirect (308 / 302) to `/accounts/` and `/ledger/<id>` | documentation only |
| 22.6.8 | `/accounts/receipts` GRN block prints *"No GRN receipts in this range"* whenever every `grn.paid_amount` is 0, even with 60,000 of real GRN payments | same root cause as 22.3 |
| 22.6.9 | The GRN charge-grid flash can say *"No charges on this GRN…"* while the charges **were** saved — assert on `landed_unit_cost` | misleading message |
| 22.6.10 | `charge_grid_present=1` alone does not persist charges; the full `charge_*[]` arrays are required | trap |
| 22.6.11 | `/financial_details` has no `type` dropdown on the page; only the dashboard tiles link into it | discoverability |
| 22.6.12 | The superadmin route `/admin/` reports **6** loaded modules; a module that fails to import is listed with status ≠ *Loaded* but the page still returns 200 | by design, but easy to miss |

### 22.7 Cash-flow report mixes two account scopes (opening vs movement)

**Defect, reproducible, highest-value finding in this run.**

| Fact | Value |
|---|---|
| `/cash_flow?from_date=2026-10-01&to_date=2026-10-31` — Opening | **200,000** (Main Cash opening only; the 500,000 Meezan Bank opening is excluded) |
| same — Total Received | **39,500** = cash 36,500 **+ bank 3,000** |
| same — Total Spent | **81,000** = cash 61,000 **+ bank 20,000** |
| same — Closing | **158,500** |
| Reality | Main Cash **175,500**, Meezan Bank **483,000**, company **658,500** |

The opening is computed by `app/services/cash_flow_svc.py::_cash_accounts_opening_total()`, which loops the company accounts and `continue`s on any account whose `category != 'cash'` — so it adds the 200,000 cash opening and skips the 500,000 bank opening. The movement figures come from `_cash_flow_in_out_between()`, which queries `_cf_company_accounts(active_only=False)` and therefore sums **every** company account, cash *and* bank.

The two halves of `opening + received − spent` are measured over different sets of accounts, so the closing can only be right when every bank movement in the period nets to zero:

* canonical dataset: bank net = 3,000 − 20,000 = **−17,000** → closing under-stated by exactly 17,000
* clean state (no bank movement): closing 175,500 ties to Main Cash and the bug is invisible

The same fault makes the per-account view wrong: `/cash_flow?account_id=2` still prints *Opening Balance Rs. 200,000* (the **cash** opening) even though the selected account is the bank, so its closing reads 183,000 while the account holds 483,000.

Minimal fix: make the opening scope follow the selected account (and, unfiltered, include every company account), i.e. either extend `_cash_accounts_opening_total()` to all `_cf_company_accounts()` or restrict the movement query to the same `category == 'cash'` set. Either change makes the canonical closing **658,500** and makes `?account_id=2` open at 500,000.

Reproduce in one query:

```sql
SELECT (SELECT SUM(opening_balance) FROM account WHERE category='cash')  AS opening_used,   -- 200000
       (SELECT SUM(amount) FROM account_transaction WHERE to_account_id IS NOT NULL AND is_void=0) AS `in_all`,  -- 39500
       (SELECT SUM(amount) FROM account_transaction WHERE from_account_id IS NOT NULL AND is_void=0) AS out_all; -- 81000
```

---

## 23. Sign-off sheet

| § | Area | Checks | Passed | Failed | Tester | Date |
|---|---|---|---|---|---|---|
| 1 | Suppliers | 8 | | | | |
| 2 | Material categories | 5 | | | | |
| 3 | Materials + service | 8 | | | | |
| 4 | Clients + categories | 6 | | | | |
| 5 | Delivery person | 4 | | | | |
| 6 | Company accounts | 10 | | | | |
| 7 | GRN + landed cost | 22 + 8 | | | | |
| 8 | Booking | 14 | | | | |
| 9 | Cash sale | 13 | | | | |
| 10 | Credit sale + booking delivery | 15 | | | | |
| 11 | Delivery rent | 10 | | | | |
| 12 | Payments (4 paths) | 7 + 6 + 7 + 5 + 9 | | | | |
| 13 | Cash flow + reconciliation | 14 + 8 + 12 | | | | |
| 14 | Material return | 12 | | | | |
| 15 | Pending bills + decision ledger | 10 + 4 | | | | |
| 16 | Reports | 19 + 8 + 6 + 4 + 7 + 7 + 4 | | | | |
| 17 | Downloads / PDFs | 18 + 6 | | | | |
| 18 | Daily recon + audits | 8 + 5 + 4 | | | | |
| 19 | Directory / settings / users | 7 + 5 + 7 + 4 + 8 + 5 + 2 | | | | |
| 20 | Import / export / migration | 6 + 5 + 3 | | | | |
| 21 | Cross-checks | 20 | | | | |
| 22 | Defect register | 6 + 12 | | | | |

**Verdict field.** A run passes when every line in §21 agrees and no check outside §22 fails. Anything in §22 is a *known* deviation: mark it `P (known)` rather than `F`.

### 23.1 Fast smoke run (15 minutes)

If the full suite is too long, run this subset — it touches every subsystem and every money path once:

`1.2 ×2 → 3.3.1 → 3.4 → 4.3 → 5.2 → 6.3 ×2 → 7.4.1 → 8.2 → 9.2 → 10.1 → 10.2 → 12.1 ×2 → 12.2 → 12.3 → 12.5 → 13.2 → 13.5 → 16.1 → 16.2 → 16.5 → 17.1 → 21.1…21.12`

Expected end state after the smoke run: Main Cash **175,500** · Meezan Bank **483,000** · company **658,500** · P&L profit **11,600** · client net **20,500** · supplier payable **338,500** · stock DG **195** · driver due **400**.

### 23.2 Machine-run harness notes

* `make_csrf_client(app)` handles the token; a raw client must send `_csrf_token` on every POST.
* Follow redirects (`follow_redirects=True`) on every write — most pages answer 302 and only the followed page carries the flash.
* Model-level seeds (inserting rows straight into SQLite) are allowed for *setup* but the numbers in §21 must be produced by HTTP posts, not by INSERTs, or the tie-outs prove nothing.
* Use a unique `idempotency_key` per intended transaction and reuse it deliberately when testing replays.
* Never run the wipe (§0.3) on a database you still need.

---

*End of document — 23 sections, 300+ individual checks.*
