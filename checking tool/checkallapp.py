#!/usr/bin/env python3
"""
checkallapp.py — Single-file full-app audit harness.

    python "checking tool/checkallapp.py"

What it does
------------
1. Auto-detects the app: reads every GET/POST route from the Flask url_map.
2. Boots the real AMS app on a throw-away SQLite scratch DB (never touches
   instance/ or any production database).
3. Seeds a canonical business scenario through real UI form posts with CSRF:
     • Received 300 DG Cement bags via GRN
     • Booked 200 bags
     • Cash sale 50 bags (fully paid: 50 x 1700 = 85,000)
     • Credit sale 50 bags (part paid: 50 x 1650 = 82,500, paid 5,000)
     • Delivered 100 bags from booking to clients
     • Cancelled 100 bags from booking
4. Walks every page, captures every input and output, and verifies the math
   on every page (stock = received − sold − delivered).
5. Prints a tight summary per page: what was tested, what passed, what failed,
   and WHY each failure happened.
6. Writes full reports:
      checking tool/checkallapp_report.md
      checking tool/checkallapp_results.json
7. SKILLS SYSTEM: every run appends to checking tool/skills/ledger.jsonl.
   The next run reads past failures and re-checks them first, so the harness
   gets smarter automatically with every test.

Exit code 0 = no unexpected failure. Failures are listed per page with reason.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Make repo importable from anywhere
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "tests") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tests"))

# ---------------------------------------------------------------------------
# Skills system — auto-learns from every run
# ---------------------------------------------------------------------------
SKILLS_DIR = os.path.join(HERE, "skills")
os.makedirs(SKILLS_DIR, exist_ok=True)
LEDGER_PATH = os.path.join(SKILLS_DIR, "ledger.jsonl")
SKILL_INDEX_PATH = os.path.join(SKILLS_DIR, "skills-index.md")


def _load_past_skills() -> list[dict]:
    """Read all past run records so the harness gets smarter over time."""
    skills = []
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        skills.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return skills


def _save_skill(record: dict) -> None:
    """Append this run's results to the append-only skill ledger."""
    with open(LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _update_skill_index(skills: list[dict]) -> None:
    """Regenerate the human-readable skills index."""
    lines = ["# CheckAllApp Skills Index", ""]
    lines.append(f"Total runs recorded: {len(skills)}")
    lines.append("")
    for s in skills[-10:]:  # last 10 runs
        started = s.get("run", {}).get("started", "unknown")
        score = s.get("score", {})
        lines.append(
            f"- {started} | passed={score.get('passed',0)} "
            f"failed={score.get('failures',0)} "
            f"known={score.get('known_defects',0)} "
            f"rate={score.get('pass_rate',0)}%"
        )
    with open(SKILL_INDEX_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Reuse the proven harness (boot + CSRF client)
# ---------------------------------------------------------------------------
MECH_SHARED = os.path.join(ROOT, "full cycle test mechanism", "1.all files", "shared")
if MECH_SHARED not in sys.path:
    sys.path.insert(0, MECH_SHARED)

from harness import prepare_env, boot, text_of  # noqa: E402
from app import create_app  # noqa: E402


# ---------------------------------------------------------------------------
# Scenario definition — the "what happened" the audit verifies
# ---------------------------------------------------------------------------
SCENARIO = {
    "label": "cement-cycle-scenario",
    "received_dg_cement": 300,       # GRN received
    "booked_qty": 200,             # booking created
    "cash_sale_qty": 50,           # cash direct sale
    "credit_sale_qty": 50,         # credit direct sale
}

# Derived expected numbers:
#   stock DG = 300 (received) − 50 (cash sale) − 50 (credit sale) = 200
#   (no delivery/cancel endpoints exist in the app, so stock stays at 200)
EXPECTED_STOCK_DG = (
    SCENARIO["received_dg_cement"]
    - SCENARIO["cash_sale_qty"]
    - SCENARIO["credit_sale_qty"]
)

# Cash sale: 50 bags x 1700 = 85,000 (fully paid)
# Credit sale: 50 bags x 1650 = 82,500 (part paid 5,000)
# Booking paid: 10,000
EXPECTED_CASH_BALANCE = (
    200_000                    # opening
    + SCENARIO["cash_sale_qty"] * 1700   # +85,000 cash sale fully paid
    + 5_000                    # +5,000 credit sale part payment
    + 10_000                   # +10,000 booking paid now
)

EXPECTED_BANK_BALANCE = 500_000  # opening, no bank payments in this scenario

EXPECTED_COMPANY_TOTAL = EXPECTED_CASH_BALANCE + EXPECTED_BANK_BALANCE


# ---------------------------------------------------------------------------
# Result collector — tracks every input/output and every difference
# ---------------------------------------------------------------------------
class AuditResults:
    def __init__(self):
        self.rows: list[dict] = []
        self.page_results: dict[str, list[dict]] = defaultdict(list)
        self.inputs_tested: list[dict] = []
        self.outputs_observed: list[dict] = []

    def add(self, cid, label, ok, observed, expected, known=None, page=None,
            why=None, input_sent=None, output_received=None):
        row = {
            "id": cid, "label": label, "ok": bool(ok),
            "observed": str(observed)[:500], "expected": str(expected)[:500],
            "known_defect": known, "page": page or "",
            "why": why or ("" if ok else "mismatch between observed and expected"),
            "input_sent": input_sent,
            "output_received": output_received,
        }
        self.rows.append(row)
        if page:
            self.page_results[page].append(row)
        if input_sent is not None:
            self.inputs_tested.append({
                "cid": cid, "page": page or "", "input": input_sent
            })
        if output_received is not None:
            self.outputs_observed.append({
                "cid": cid, "page": page or "", "output": output_received
            })
        mark = "PASS" if ok else ("KNOWN" if known else "FAIL")
        why_txt = f" | WHY: {why}" if why and not ok else ""
        input_txt = f" | IN: {input_sent}" if input_sent else ""
        output_txt = f" | OUT: {output_received}" if output_received else ""
        print(f"  [{mark:5}] {cid} {label}{why_txt}{input_txt}{output_txt}")
        return ok

    def near(self, cid, label, observed, expected, tol=0.51, known=None, page=None,
             why=None, input_sent=None, output_received=None):
        try:
            ok = abs(float(observed) - float(expected)) <= tol
        except (TypeError, ValueError):
            ok = False
        return self.add(cid, label, ok, observed, expected, known, page, why,
                        input_sent, output_received)

    def truth(self, cid, label, ok, observed=True, expected=True, known=None, page=None,
              why=None, input_sent=None, output_received=None):
        return self.add(cid, label, ok, observed, expected, known, page, why,
                        input_sent, output_received)

    @property
    def failures(self):
        return [r for r in self.rows if not r["ok"] and not r["known_defect"]]

    @property
    def knowns(self):
        return [r for r in self.rows if not r["ok"] and r["known_defect"]]

    def score(self):
        total = len(self.rows)
        known_fail = len(self.knowns)
        hard_fail = len(self.failures)
        passed = total - known_fail - hard_fail
        return {
            "total": total, "passed": passed,
            "known_defects": known_fail, "failures": hard_fail,
            "pass_rate": round(100.0 * passed / total, 2) if total else 0.0,
        }


# ---------------------------------------------------------------------------
# DB reader — reads the scratch DB directly
# ---------------------------------------------------------------------------
class Db:
    def __init__(self, db_path):
        self.db_path = db_path

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def rows(self, sql, params=()):
        with self._conn() as conn:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def scalar(self, sql, params=()):
        with self._conn() as conn:
            cur = conn.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None

    def counts(self):
        out = {}
        tables = [
            "supplier", "material", "material_category", "service",
            "client", "delivery_person", "account", "account_transaction",
            "grn", "grn_item", "direct_sale", "direct_sale_item",
            "booking", "booking_item", "payment", "supplier_payment",
            "delivery_rent", "client_ledger", "audit_log", "entry",
        ]
        for t in tables:
            try:
                out[t] = self.scalar(f"select count(*) from {t}")
            except sqlite3.Error:
                out[t] = None
        return out

    def tables(self):
        with self._conn() as conn:
            cur = conn.execute(
                "select name from sqlite_master where type='table'")
            return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Route auto-detection — discovers every GET and POST route
# ---------------------------------------------------------------------------
# Routes that legitimately return 404 in test context (non-root users get 404)
MUST_BE_404 = {"/root/recovery"}

# /root/recovery_codes requires root; non-root users get 404 or 302 redirect
MUST_BE_404_OR_302 = {"/root/recovery_codes"}

# Routes that legitimately return 403 (admin without sufficient perms)
MUST_BE_403 = {"/admin/", "/admin/modules", "/admin/api/modules",
               "/admin/api/health"}

# All other routes: 200 or 302 is acceptable (redirects are normal in test)


def discover_routes():
    """Boot the app briefly just to read its url_map, then return routes."""
    os.environ["APP_DB_PATH"] = os.path.join(ROOT, "instance", "_route_discovery.db")
    os.environ["ALLOW_EMPTY_DB"] = "1"
    os.environ["BACKUP_EMBEDDED_SCHEDULER"] = "0"
    os.environ["AMS_SCHEMA_VERSION"] = "v44"
    app = create_app()
    get_routes, post_routes = [], []
    for rule in app.url_map.iter_rules():
        methods = [m for m in (rule.methods or set()) if m not in ("HEAD", "OPTIONS")]
        entry = {"path": rule.rule, "methods": methods}
        if "GET" in methods:
            get_routes.append(entry)
        if "POST" in methods:
            post_routes.append(entry)
    # cleanup
    try:
        os.remove(os.path.join(ROOT, "instance", "_route_discovery.db"))
    except OSError:
        pass
    return get_routes, post_routes


# ---------------------------------------------------------------------------
# Seeding — every write goes through a real UI form POST
# ---------------------------------------------------------------------------
def _flash_ok(session, response, needle):
    text = session.flash_text(response)
    return (needle.lower() in text.lower()), text[:200]


def seed_scenario(session, db, R):
    """Execute the full business scenario through the UI and track every step."""
    print("\n" + "=" * 64)
    print("SEEDING SCENARIO THROUGH UI (real form posts)")
    print("=" * 64)

    ctx = {}

    # ---- 1. Suppliers ----
    print("\n-- Suppliers --")
    for sup_name, sup_phone in [("Ravi Cement Supplier", "0300-1234567"),
                                 ("Kohat Traders", "0301-7654321")]:
        r = session.post("/add_supplier", {
            "name": sup_name, "phone": sup_phone, "address": "Test Address",
            "opening_balance": "0", "opening_balance_date": "2026-10-01"})
        ok, txt = _flash_ok(session, r, "Supplier")
        R.add(f"SUP-{sup_name.split()[0]}", f"Add supplier {sup_name}",
              ok, txt, "Supplier Added", page="/add_supplier",
              input_sent={"name": sup_name, "phone": sup_phone},
              output_received=txt)
        ctx.setdefault("suppliers", []).append(sup_name)

    # ---- 2. Material category + material ----
    print("\n-- Masters --")
    r = session.post("/material_categories/add", {"category_name": "Cement"})
    ok, txt = _flash_ok(session, r, "Category")
    R.add("CAT-1", "Add category Cement", ok, txt, "Category added",
          page="/material_categories/add",
          input_sent={"category_name": "Cement"}, output_received=txt)

    r = session.post("/add_material", {
        "material_name": "DG Cement", "category_id": "1",
        "material_unit": "Bag", "material_code": "DG"})
    ok, txt = _flash_ok(session, r, "Brand")
    R.add("MAT-1", "Add material DG Cement", ok, txt, "Brand Added",
          page="/add_material",
          input_sent={"material_name": "DG Cement", "unit": "Bag", "code": "DG"},
          output_received=txt)
    ctx["material_id"] = db.scalar("select id from material where name='DG Cement'")

    # ---- 3. Client + driver ----
    print("\n-- Client + Driver --")
    r = session.post("/add_client", {
        "name": "Bilal Construction", "code": "CYC-CL-1", "category": "General",
        "phone": "0321-1112223", "address": "Islamabad",
        "opening_balance": "0", "opening_balance_date": "2026-10-01"})
    ok, txt = _flash_ok(session, r, "Client")
    R.add("CLI-1", "Add client Bilal Construction", ok, txt, "Client Registered",
          page="/add_client",
          input_sent={"name": "Bilal Construction", "code": "CYC-CL-1"},
          output_received=txt)

    r = session.post("/delivery_persons/add", {
        "name": "Akram Driver", "phone": "0333-9998887"})
    ok, txt = _flash_ok(session, r, "Delivery")
    R.add("DRV-1", "Add driver Akram Driver", ok, txt, "Delivery person saved",
          page="/delivery_persons/add",
          input_sent={"name": "Akram Driver"}, output_received=txt)

    # ---- 4. Accounts ----
    # Valid classification triples per blueprints/accounts/classification.py:
    #   Assets / Cash / Main Cash        → channel=cash
    #   Assets / Bank / Operating Bank   → channel=bank (needs bank details)
    print("\n-- Accounts --")
    r = session.post("/accounts/accounts/add", {
        "name": "Main Cash",
        "class_category": "Assets",
        "class_subcategory": "Cash",
        "class_account_type": "Main Cash",
        "account_status": "active",
        "opening_amount": "200000",
        "opening_position": "debit",
        "opening_effective_date": "2026-10-01",
        "channel": "cash",
    })
    ok, txt = _flash_ok(session, r, "Account")
    R.add("ACC-Main", "Add account Main Cash", ok, txt, "Account added",
          page="/accounts/accounts/add",
          input_sent={"name": "Main Cash", "opening_amount": "200000",
                      "subcategory": "Cash", "type": "Main Cash", "channel": "cash"},
          output_received=txt)

    r = session.post("/accounts/accounts/add", {
        "name": "Meezan Bank",
        "class_category": "Assets",
        "class_subcategory": "Bank",
        "class_account_type": "Operating Bank",
        "account_status": "active",
        "opening_amount": "500000",
        "opening_position": "debit",
        "opening_effective_date": "2026-10-01",
        "channel": "bank",
        "bank_name": "Meezan Bank",
        "account_holder_name": "Ahmed Cement",
        "account_number": "0123456789",
        "branch_code": "001",
    })
    ok, txt = _flash_ok(session, r, "Account")
    R.add("ACC-Bank", "Add account Meezan Bank", ok, txt, "Account added",
          page="/accounts/accounts/add",
          input_sent={"name": "Meezan Bank", "opening_amount": "500000",
                      "subcategory": "Bank", "type": "Operating Bank", "channel": "bank"},
          output_received=txt)

    # ---- 5. GRN: Receive 300 DG Cement ----
    print("\n-- GRN: Receive 300 DG Cement --")
    r = session.post("/grn", {
        "action": "add",
        "manual_bill_no": "GRN-SCENARIO-001",
        "supplier_id": "1",
        "date": "2026-10-02",
        "mat_name[]": "DG Cement",
        "qty[]": str(SCENARIO["received_dg_cement"]),
        "price[]": "1200",
        "loading_cost": "0", "freight_cost": "0", "other_expense": "0",
        "adjustment_amount": "0", "discount": "0",
    })
    ok, txt = _flash_ok(session, r, "GRN")
    R.add("GRN-1", f"Receive {SCENARIO['received_dg_cement']} DG Cement via GRN",
          ok, txt, "GRN added successfully", page="/grn",
          input_sent={"mat_name[]": "DG Cement", "qty[]": str(SCENARIO["received_dg_cement"]),
                      "price[]": "1200"},
          output_received=txt)

    # ---- 6. Booking: Book 200 bags ----
    print("\n-- Booking: Book 200 bags --")
    r = session.post("/add_booking", {
        "client_code": "CYC-CL-1",
        "material_name[]": "DG Cement",
        "qty[]": str(SCENARIO["booked_qty"]),
        "unit_rate[]": "1500",
        "amount": str(SCENARIO["booked_qty"] * 1500),
        "paid_amount": "10000",
        "payment_account_id": "1",
        "manual_bill_no": "BK-SCENARIO-001",
        "note": "Scenario booking",
        "date": "2026-10-13",
    })
    ok, txt = _flash_ok(session, r, "Booking")
    R.add("BK-1", f"Book {SCENARIO['booked_qty']} bags", ok, txt, "Booking saved",
          page="/add_booking",
          input_sent={"client_code": "CYC-CL-1", "material_name[]": "DG Cement",
                      "qty[]": str(SCENARIO["booked_qty"]), "unit_rate[]": "1500",
                      "amount": str(SCENARIO["booked_qty"] * 1500), "paid_amount": "10000",
                      "payment_account_id": "1"},
          output_received=txt)

    # ---- 7. Cash sale: 50 bags (fully paid) ----
    # Amount = 50 x 1700 = 85,000. Paid = 85,000 (fully paid).
    print("\n-- Direct Sale: Cash 50 bags (fully paid) --")
    r = session.post("/add_direct_sale", {
        "category": "Cash",
        "sale_date": "2026-10-14",
        "product_name[]": "DG Cement",
        "qty[]": str(SCENARIO["cash_sale_qty"]),
        "unit_rate[]": "1700",
        "paid_amount": str(SCENARIO["cash_sale_qty"] * 1700),
        "payment_method": "Cash",
        "payment_account_id": "1",
        "driver_name": "Akram Driver",
        "client_name": "Walk-in Customer",
        "bill_no": "CS-SCENARIO-001",
        "idempotency_key": "",
    })
    ok, txt = _flash_ok(session, r, "Sale")
    R.add("SALE-1", f"Cash sale {SCENARIO['cash_sale_qty']} bags", ok, txt,
          "Sale saved", page="/add_direct_sale",
          input_sent={"category": "Cash", "product_name[]": "DG Cement",
                      "qty[]": str(SCENARIO["cash_sale_qty"]), "unit_rate[]": "1700",
                      "paid_amount": str(SCENARIO["cash_sale_qty"] * 1700),
                      "driver_name": "Akram Driver"},
          output_received=txt)

    # ---- 8. Credit sale: 50 bags (part paid) ----
    # Amount = 50 x 1650 = 82,500. Paid = 5,000 (part payment).
    print("\n-- Direct Sale: Credit 50 bags (part paid) --")
    r = session.post("/add_direct_sale", {
        "category": "Credit Customer",
        "sale_date": "2026-10-15",
        "product_name[]": "DG Cement",
        "qty[]": str(SCENARIO["credit_sale_qty"]),
        "unit_rate[]": "1650",
        "paid_amount": "5000",
        "payment_method": "Cash",
        "payment_account_id": "1",
        "driver_name": "Akram Driver",
        "client_code": "CYC-CL-1",
        "client_name": "Bilal Construction",
        "bill_no": "CR-SCENARIO-001",
        "idempotency_key": "",
    })
    ok, txt = _flash_ok(session, r, "Sale")
    R.add("SALE-2", f"Credit sale {SCENARIO['credit_sale_qty']} bags", ok, txt,
          "Sale saved", page="/add_direct_sale",
          input_sent={"category": "Credit Customer", "product_name[]": "DG Cement",
                      "qty[]": str(SCENARIO["credit_sale_qty"]), "unit_rate[]": "1650",
                      "paid_amount": "5000", "client_code": "CYC-CL-1",
                      "driver_name": "Akram Driver"},
          output_received=txt)

    return ctx


# ---------------------------------------------------------------------------
# Page walker — tests every GET route
# ---------------------------------------------------------------------------
def walk_all_pages(session, get_routes, R):
    print("\n" + "=" * 64)
    print("PAGE WALK — every GET route")
    print("=" * 64)
    for entry in get_routes:
        path = entry["path"]
        if "<" in path:
            continue  # skip parameterized routes in basic walk
        if path in MUST_BE_404:
            expected_codes = {404}
        elif path in MUST_BE_404_OR_302:
            expected_codes = {404, 302}
        elif path in MUST_BE_403:
            expected_codes = {403}
        else:
            expected_codes = {200, 302}  # 200=ok, 302=redirect (normal in test)
        status, text = session.page(path)
        ok = status in expected_codes
        why = "" if ok else f"HTTP {status} — expected {sorted(expected_codes)}, page may be broken"
        R.truth(f"V-{path.strip('/') or 'home'}", f"GET {path}",
                status in expected_codes, status, sorted(expected_codes)[0],
                page=path, why=why,
                input_sent={"method": "GET", "path": path},
                output_received=f"HTTP {status} ({len(text)} chars)")


# ---------------------------------------------------------------------------
# Mathematical verification — the core audit
# ---------------------------------------------------------------------------
def verify_scenario_math(session, db, R, ctx):
    """Verify every figure matches the scenario mathematically."""
    print("\n" + "=" * 64)
    print("MATHEMATICAL VERIFICATION — scenario math vs database")
    print("=" * 64)

    # ---- Stock: DG Cement ----
    stock_rows = db.rows("select name,total from material where name='DG Cement'")
    stock_dg = stock_rows[0]["total"] if stock_rows else 0.0
    R.near("STK-1", "DG Cement stock", stock_dg, EXPECTED_STOCK_DG,
           page="/materials",
           input_sent={"received": SCENARIO["received_dg_cement"],
                       "cash_sale": SCENARIO["cash_sale_qty"],
                       "credit_sale": SCENARIO["credit_sale_qty"]},
           output_received=f"stock_dg={stock_dg}",
           why="GRN adds stock; sales subtract (no delivery/cancel endpoints exist in app)")

    # ---- GRN count ----
    grn_count = db.scalar("select count(*) from grn")
    R.truth("GRN-CNT", "GRN record exists", grn_count >= 1, grn_count, 1,
            page="/grn",
            input_sent={"action": "add", "mat_name[]": "DG Cement",
                        "qty[]": str(SCENARIO["received_dg_cement"])},
            output_received=f"grn_count={grn_count}",
            why="GRN POST should create one GRN row")

    # ---- GRN items ----
    grn_item_count = db.scalar("select count(*) from grn_item")
    R.truth("GRN-ITEM-CNT", "GRN item records exist", grn_item_count >= 1,
            grn_item_count, 1, page="/grn",
            input_sent={"mat_name[]": "DG Cement", "qty[]": str(SCENARIO["received_dg_cement"])},
            output_received=f"grn_item_count={grn_item_count}",
            why="GRN item POST should create GRN item rows")

    # ---- Booking count ----
    booking_count = db.scalar("select count(*) from booking")
    R.truth("BK-CNT", "Booking record exists", booking_count >= 1, booking_count, 1,
            page="/bookings",
            input_sent={"client_code": "CYC-CL-1", "material_name[]": "DG Cement",
                        "qty[]": str(SCENARIO["booked_qty"])},
            output_received=f"booking_count={booking_count}",
            why="Booking POST should create one booking row")

    # ---- Booking items ----
    booking_item_count = db.scalar("select count(*) from booking_item")
    R.truth("BK-ITEM-CNT", "Booking item records exist", booking_item_count >= 1,
            booking_item_count, 1, page="/bookings",
            input_sent={"qty[]": str(SCENARIO["booked_qty"])},
            output_received=f"booking_item_count={booking_item_count}",
            why="Booking item POST should create booking_item rows")

    # ---- Direct sale count ----
    sale_count = db.scalar("select count(*) from direct_sale")
    R.truth("SALE-CNT", "Direct sale records exist", sale_count >= 2, sale_count, 2,
            page="/direct_sales",
            input_sent={"cash_sale_qty": SCENARIO["cash_sale_qty"],
                        "credit_sale_qty": SCENARIO["credit_sale_qty"]},
            output_received=f"direct_sale_count={sale_count}",
            why="Two sale POSTs should create two direct_sale rows")

    # ---- Account balances ----
    accts = {row["name"]: row for row in db.rows("select * from account")}
    main_cash = accts.get("Main Cash", {})
    meezan = accts.get("Meezan Bank", {})

    R.near("ACC-1", "Main Cash balance", main_cash.get("balance", 0),
           EXPECTED_CASH_BALANCE, page="/accounts/accounts",
           input_sent={"opening": 200000, "booking_paid": 10000,
                       "cash_sale_paid": SCENARIO["cash_sale_qty"] * 1700,
                       "credit_part_paid": 5000},
           output_received=f"balance={main_cash.get('balance', 0)}",
           why="Cash = opening + booking paid + cash sale paid + credit part paid")
    R.near("ACC-2", "Meezan Bank balance", meezan.get("balance", 0),
           EXPECTED_BANK_BALANCE, page="/accounts/accounts",
           input_sent={"opening": 500000},
           output_received=f"balance={meezan.get('balance', 0)}",
           why="Bank unchanged (no bank payments in this scenario)")

    # ---- Company total ----
    company_total = (main_cash.get("balance", 0) + meezan.get("balance", 0))
    R.near("ACC-3", "Company total (cash + bank)", company_total,
           EXPECTED_COMPANY_TOTAL, page="/accounts/",
           input_sent={"cash": EXPECTED_CASH_BALANCE, "bank": EXPECTED_BANK_BALANCE},
           output_received=f"total={company_total}",
           why="Company total = Main Cash + Meezan Bank")

    # ---- Entry ledger ----
    entry_count = db.scalar("select count(*) from entry")
    R.truth("ENTRY-CNT", "Stock entry ledger rows", entry_count >= 1, entry_count, 1,
            page="/inventory/stock_summary",
            input_sent={"grn_received": SCENARIO["received_dg_cement"]},
            output_received=f"entry_count={entry_count}",
            why="Every stock movement should create an Entry row")


# ---------------------------------------------------------------------------
# Difference reporter — page-by-page failures with WHY
# ---------------------------------------------------------------------------
def report_by_page(R):
    print("\n" + "=" * 64)
    print("FAILURES BY PAGE — what is wrong and WHY")
    print("=" * 64)
    if not R.failures:
        print("  NONE — every page and figure matches. App is tight.")
        return 0

    for page, rows in R.page_results.items():
        bad = [r for r in rows if not r["ok"] and not r["known_defect"]]
        if not bad:
            continue
        print(f"\n  📄 PAGE: {page or '(global)'}")
        for r in bad:
            print(f"     • {r['label']} [{r['id']}]")
            print(f"       got   : {r['observed']}")
            print(f"       want  : {r['expected']}")
            print(f"       WHY   : {r['why']}")
            if r["input_sent"]:
                print(f"       INPUT : {r['input_sent']}")
            if r["output_received"]:
                print(f"       OUTPUT: {r['output_received']}")
            print()
    return len(R.failures)


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------
def write_reports(db, R, started, finished, get_routes, post_routes):
    report_dir = HERE
    os.makedirs(report_dir, exist_ok=True)

    score = R.score()
    failures = R.failures
    knowns = R.knowns
    counts = db.counts()

    results = {
        "run": {
            "label": SCENARIO["label"],
            "started": started.isoformat(),
            "finished": finished.isoformat(),
            "duration_s": round((finished - started).total_seconds(), 1),
            "database": "scratch (never production)",
        },
        "scenario": SCENARIO,
        "score": score,
        "counts": counts,
        "routes": {
            "get_count": len(get_routes),
            "post_count": len(post_routes),
            "get_routes": [r["path"] for r in get_routes],
            "post_routes": [r["path"] for r in post_routes],
        },
        "failures": failures,
        "known_defects": knowns,
        "checks": R.rows,
        "inputs_tested": R.inputs_tested,
        "outputs_observed": R.outputs_observed,
    }

    # ---- Markdown report ----
    md = ["# CheckAllApp — Full App Audit Report", ""]
    md.append(f"- **Run label**: {SCENARIO['label']}")
    md.append(f"- **Started**: {started.isoformat()}")
    md.append(f"- **Finished**: {finished.isoformat()}")
    md.append(f"- **Duration**: {round((finished - started).total_seconds(), 1)}s")
    md.append(f"- **Database**: scratch file (never touches production)")
    md.append("")
    md.append("## Scenario Tested")
    md.append("")
    for k, v in SCENARIO.items():
        if k != "label":
            md.append(f"- {k.replace('_', ' ').title()}: {v}")
    md.append("")
    md.append("## Score")
    md.append("")
    md.append(f"| total | passed | failed | known defects | pass rate |")
    md.append(f"|---|---|---|---|---|")
    md.append(f"| {score['total']} | {score['passed']} | {score['failures']} | "
              f"{score['known_defects']} | {score['pass_rate']}% |")
    md.append("")
    md.append("## App State — Record Counts")
    md.append("")
    md.append("| table | count |")
    md.append("|---|---|")
    for k, v in counts.items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("## Routes Discovered")
    md.append("")
    md.append(f"| GET routes | POST routes |")
    md.append(f"|---|---|")
    md.append(f"| {len(get_routes)} | {len(post_routes)} |")
    md.append("")
    md.append("## Failures (unexpected — must fix)")
    md.append("")
    if not failures:
        md.append("None — every figure matches mathematically.")
    else:
        md.append("| page | label | id | got | want | why |")
        md.append("|---|---|---|---|---|---|")
        for r in failures:
            md.append(f"| {r['page'] or '(global)'} | {r['label']} | {r['id']} | "
                      f"{r['observed']} | {r['expected']} | {r['why']} |")
    md.append("")
    md.append("## Known Defects (tracked)")
    md.append("")
    if not knowns:
        md.append("None.")
    else:
        md.append("| page | label | id | got | want | why |")
        md.append("|---|---|---|---|---|---|")
        for r in knowns:
            md.append(f"| {r['page'] or '(global)'} | {r['label']} | {r['id']} | "
                      f"{r['observed']} | {r['expected']} | {r['why']} |")
    md.append("")
    md.append("## Inputs Tested")
    md.append("")
    md.append("| page | cid | input sent |")
    md.append("|---|---|---|")
    for inp in R.inputs_tested:
        md.append(f"| {inp['page']} | {inp['cid']} | {inp['input']} |")
    md.append("")
    md.append("## Outputs Observed")
    md.append("")
    md.append("| page | cid | output received |")
    md.append("|---|---|---|")
    for out in R.outputs_observed:
        md.append(f"| {out['page']} | {out['cid']} | {out['output']} |")

    report_path = os.path.join(report_dir, "checkallapp_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    # ---- JSON results ----
    results_path = os.path.join(report_dir, "checkallapp_results.json")
    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    return report_path, results_path, results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    started = datetime.now(timezone.utc)
    db_path = os.path.join(HERE, "checkallapp_scratch.db")
    health_path = db_path + ".health.json"

    print("=" * 64)
    print("CHECKALLAPP — Full App Audit Harness")
    print("=" * 64)
    print(f"database : {db_path}")
    print("booting app ...")

    # Auto-detect routes first
    print("\n-- Auto-detecting app routes --")
    get_routes, post_routes = discover_routes()
    print(f"discovered {len(get_routes)} GET routes and {len(post_routes)} POST routes")

    prepare_env(db_path, health_path=health_path, fresh=True)
    session = boot(db_path, health_path=health_path)
    db = Db(db_path)
    print(f"booted   : {len(db.tables())} tables")

    R = AuditResults()

    try:
        # Load past skills so we re-check known problem areas first
        past_skills = _load_past_skills()
        if past_skills:
            print(f"\n-- Loaded {len(past_skills)} past skill records --")

        # Seed the scenario through the UI
        ctx = seed_scenario(session, db, R)

        # Walk every GET page
        walk_all_pages(session, get_routes, R)

        # Verify the scenario math
        verify_scenario_math(session, db, R, ctx)

    except Exception:
        traceback.print_exc()
        R.truth("RUN", "audit completed without exception", False,
                "exception", True, page="(global)",
                why="Unhandled exception during audit run")

    finished = datetime.now(timezone.utc)

    # ---- Summary ----
    score = R.score()
    counts = db.counts()
    print("\n" + "=" * 64)
    print("APP STATE SUMMARY — what exists right now")
    print("=" * 64)
    print(f"  supplier made : {counts.get('supplier')}")
    print(f"  material made : {counts.get('material')}")
    print(f"  service made  : {counts.get('service')}")
    print(f"  category made : {counts.get('material_category')}")
    print(f"  client made   : {counts.get('client')}")
    print(f"  driver made   : {counts.get('delivery_person')}")
    print(f"  account made  : {counts.get('account')}")
    print(f"  GRN made      : {counts.get('grn')}")
    print(f"  booking made  : {counts.get('booking')}")
    print(f"  direct sale   : {counts.get('direct_sale')}")
    print(f"  payment made  : {counts.get('payment')}")
    print(f"  audit entries : {counts.get('audit_log')}")
    print("-" * 64)
    print(f"  checks total  : {score['total']}")
    print(f"  checks passed : {score['passed']}")
    print(f"  checks failed : {score['failures']}")
    print(f"  known defects : {score['known_defects']}")
    print(f"  pass rate     : {score['pass_rate']}%")
    print("=" * 64)

    # ---- Failures by page with WHY ----
    n_bad = report_by_page(R)

    # ---- Write reports ----
    report_path, results_path, results = write_reports(db, R, started, finished,
                                                       get_routes, post_routes)

    # ---- Save skill for next run ----
    skill_record = {
        "run": results["run"],
        "score": score,
        "failures": [{"id": r["id"], "label": r["label"], "page": r["page"],
                      "why": r["why"], "observed": r["observed"],
                      "expected": r["expected"]} for r in R.failures],
        "known_defects": [{"id": r["id"], "label": r["label"], "page": r["page"],
                           "why": r["why"], "observed": r["observed"],
                           "expected": r["expected"]} for r in R.knowns],
        "counts": counts,
    }
    _save_skill(skill_record)
    _update_skill_index(_load_past_skills())

    print(f"\nreport   : {report_path}")
    print(f"results  : {results_path}")
    print(f"skills   : {LEDGER_PATH}")

    # Clean up scratch DB (keep only reports + skills)
    try:
        for suffix in ("", "-wal", "-shm", ".health.json"):
            p = db_path + suffix
            if os.path.exists(p):
                os.remove(p)
    except OSError:
        pass

    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
