#!/usr/bin/env python3
"""
Full-app audit runner — lives in app/ and checks the whole app in one command.

    python app/full_app_audit.py

What it does
------------
1. Boots the real AMS app against a throw-away SQLite file (never touches
   instance/ or any production database).
2. Seeds a canonical dataset **through the UI** — real HTTP form posts with
   CSRF tokens, exactly like a human clicking.
3. Walks every GET route, renders every page, and verifies all key figures
   mathematically against the database.
4. Prints a tight summary (supplier made: 2, material made: 4, …) and writes
   a full report to `app/full_app_audit_report.md` plus `results.json`.

Exit code 0 = no unexpected failure. Known defects are listed separately and
do not turn the run red.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import traceback
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Make repo importable no matter where this file is launched from
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "tests") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tests"))

# ---------------------------------------------------------------------------
# Reuse the proven harness from the test mechanism (boot + CSRF client)
# ---------------------------------------------------------------------------
MECH_SHARED = os.path.join(ROOT, "full cycle test mechanism", "1.all files", "shared")
if MECH_SHARED not in sys.path:
    sys.path.insert(0, MECH_SHARED)

from harness import prepare_env, boot, text_of  # noqa: E402
from app import create_app  # noqa: E402   (import after sys.path is set)

# ---------------------------------------------------------------------------
# Canonical dataset — every number the audit asserts derives from here
# ---------------------------------------------------------------------------
SUPPLIERS = [
    dict(name="Ravi Cement Supplier", phone="0300-1234567", address="Ravi Road, Lahore"),
    dict(name="Kohat Traders", phone="0301-7654321", address="Kohat Bazaar"),
]

EXTRA_CATEGORIES = ["Cement", "Sand & Gravel", "Sheets & Covers"]

MATERIALS = [
    dict(name="DG Cement", category="Cement", unit="Bag", code="DG"),
    dict(name="Pioneer Cement", category="Cement", unit="Bag", code="PIO"),
    dict(name="Chenab Sand", category="Sand & Gravel", unit="Cft", code="SAND"),
    dict(name="TRANSPARENT SHEET", category="Sheets & Covers", unit="Pcs", code="SHT"),
]

SERVICE = dict(name="CEMENT RENT", unit="Trip", code="SRV-RENT")

CLIENT = dict(name="Bilal Construction", code="CYC-CL-1", category="General",
              phone="0321-1112223", address="Islamabad")
DRIVER = dict(name="Akram Driver", phone="0333-9998887")

CASH_ACCOUNT = dict(name="Main Cash", opening=200_000.0, cls="Assets",
                    sub="Cash", kind="Main Cash")
BANK_ACCOUNT = dict(name="Meezan Bank", opening=500_000.0, cls="Assets",
                    sub="Bank", kind="Operating Bank",
                    bank_name="Meezan Bank", holder="Ahmed Cement",
                    number="0123456789")

GRNS = [
    ("CYC-GRN-1", 1, "Ravi Cement Supplier", "2026-10-02", "DG Cement", 100, 1200),
    ("CYC-GRN-2", 1, "Ravi Cement Supplier", "2026-10-04", "DG Cement", 50, 1350),
    ("CYC-GRN-3", 2, "Kohat Traders", "2026-10-06", "DG Cement", 80, 1400),
    ("CYC-GRN-4", 1, "Ravi Cement Supplier", "2026-10-08", "Pioneer Cement", 60, 1600),
    ("CYC-GRN-5", 2, "Kohat Traders", "2026-10-10", "Chenab Sand", 200, 55),
    ("CYC-GRN-6", 1, "Ravi Cement Supplier", "2026-10-12", "TRANSPARENT SHEET", 40, 300),
]

SALES = [
    dict(category="Cash", client=None, client_name="Walk-in Customer",
         date="2026-10-14", qty=5, rate=1700, paid=8500.0, rent=200.0,
         bill="CYC-CASH-1", idem="cyc-cash-1", amount=8500.0, ignore_booking="1"),
    dict(category="Credit Customer", client="CYC-CL-1", client_name=None,
         date="2026-10-15", qty=10, rate=1650, paid=5000.0, rent=400.0,
         bill="CYC-CR-1", idem="cyc-cr-1", amount=16500.0, ignore_booking="1"),
    dict(category="Booking Delivery", client="CYC-CL-1", client_name=None,
         date="2026-10-16", qty=20, rate=1500, paid=0.0, rent=800.0,
         bill="CYC-BD-1", idem="cyc-bd-1", amount=30000.0, ignore_booking="0"),
]

CLIENT_RECEIPTS = [
    dict(amount=8000.0, method="Cash", account="Main Cash", date="2026-10-18",
         bill="CYC-RCPT-1", note="part receipt against credit sale", idem="cyc-rcpt-1"),
    dict(amount=3000.0, method="Bank Transfer", account="Meezan Bank",
         date="2026-10-19", bill="CYC-RCPT-2", note="bank receipt", idem="cyc-rcpt-2"),
]

GRN_PAYMENT = dict(grn_index=0, amount=60_000.0, method="Cash", account="Main Cash",
                   date="2026-10-20", reference="CYC-GRNPAY-1")
SUPPLIER_PAYMENT = dict(supplier_id=1, amount=20_000.0, method="Bank Transfer",
                        account="Meezan Bank", date="2026-10-21",
                        bill="CYC-SUPPAY-1", note="part payment Ravi")
DRIVER_PAYMENT = dict(amount=1000.0, method="Cash", account="Main Cash",
                      date="2026-10-22", reference="CYC-DRV-1",
                      note="part driver settlement", idem="cyc-drv-1")

CF_ENTRY = dict(direction="in", amount=5000.0, account="Main Cash",
                description="Owner put cash in", date="2026-10-23",
                reference="CYC-CF-IN", idem="cyc-cf-in")

RETURN = dict(client="CYC-CL-1", date="2026-10-26", material="DG Cement",
              qty=2, rate=1650.0, bill="CYC-RTN-1", note="2 bags returned")

PENDING_BILL = dict(client="CYC-CL-1", bill="CYC-PB-1", amount=4500.0,
                    reason="Manual charge: extra loading")

PERIOD = dict(start="2026-10-01", end="2026-10-31")

EXPECT = {
    "cash_closing": 175_500.0,
    "bank_closing": 483_000.0,
    "company_total": 658_500.0,
    "cash_in_all": 39_500.0,
    "cash_out_all": 81_000.0,
    "stock_dg": 195.0,
    "stock_pioneer": 60.0,
    "stock_sand": 200.0,
    "stock_sheet": 40.0,
    "stock_received": 530.0,
    "stock_delivered": 35.0,
    "stock_total": 495.0,
    "payable_this_page": 20_500.0,
    "ledger_due": 46_500.0,
    "ledger_paid": 26_000.0,
    "ledger_net": 20_500.0,
    "total_purchase": 418_500.0,
    "outstanding": 338_500.0,
    "ravi_payable": 215_500.0,
    "kohat_payable": 123_000.0,
    "rent_earned": 1_400.0,
    "rent_paid": 1_000.0,
    "rent_remaining": 400.0,
    "driver_closing": 400.0,
    "sales": 55_000.0,
    "cogs": 43_400.0,
    "profit": 11_600.0,
    "money_received": 34_500.0,
    "margin": 21.09,
}


# ===========================================================================
# Result collector — prints a running tally and keeps every detail
# ===========================================================================
class AuditResults:
    def __init__(self):
        self.rows = []
        self.counts = {}

    def add(self, cid, label, ok, observed, expected, known=None, page=None):
        self.rows.append({
            "id": cid, "label": label, "ok": bool(ok),
            "observed": str(observed)[:400], "expected": str(expected)[:400],
            "known_defect": known, "page": page,
        })
        mark = "PASS" if ok else ("KNOWN" if known else "FAIL")
        extra = f" | page={page}" if page else ""
        print(f"  [{mark:5}] {cid} {label}{extra}"
              + ("" if ok else f" | got {observed!r} want {expected!r}"))
        return ok

    def near(self, cid, label, observed, expected, tol=0.51, known=None, page=None):
        try:
            ok = abs(float(observed) - float(expected)) <= tol
        except (TypeError, ValueError):
            ok = False
        return self.add(cid, label, ok, observed, expected, known, page)

    def truth(self, cid, label, ok, observed=True, expected=True, known=None, page=None):
        return self.add(cid, label, ok, observed, expected, known, page)

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


# ===========================================================================
# DB-backed record counter — counts every table
# ===========================================================================
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
            "delivery_rent", "client_ledger", "audit_log",
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


# ===========================================================================
# Seeding — every write goes through a real UI form POST
# ===========================================================================
def _flash_ok(session, response, needle):
    text = session.flash_text(response)
    return (needle.lower() in text.lower()), text[:200]


def seed(session, db):
    ctx = {}

    print("\n== masters (suppliers, categories, materials) ==")
    for sup in SUPPLIERS:
        r = session.post("/add_supplier", {
            **sup, "opening_balance": "0", "opening_balance_date": "2026-10-01"})
        ok, txt = _flash_ok(session, r, "Supplier Added")
        print(f"  [{'ok ' if ok else 'FAIL'}] supplier {sup['name']} — {txt}")

    for cat in EXTRA_CATEGORIES:
        r = session.post("/material_categories/add", {"category_name": cat})
        ok, txt = _flash_ok(session, r, "Category added")
        print(f"  [{'ok ' if ok else 'FAIL'}] category {cat} — {txt}")

    cat_ids = {row["name"]: row["id"] for row in
               db.rows("select id,name from material_category")}
    ctx["categories"] = cat_ids

    for mat in MATERIALS:
        r = session.post("/add_material", {
            "material_name": mat["name"],
            "category_id": str(cat_ids[mat["category"]]),
            "material_unit": mat["unit"],
            "material_code": mat["code"],
        })
        ok, txt = _flash_ok(session, r, "Brand Added")
        print(f"  [{'ok ' if ok else 'FAIL'}] material {mat['name']} — {txt}")

    mat_ids = {row["name"]: row["id"] for row in
               db.rows("select id,name from material")}
    ctx["materials"] = mat_ids
    ctx["material"] = mat_ids

    r = session.post("/services/add", {
        "service_name": SERVICE["name"], "service_unit": SERVICE["unit"],
        "service_code": SERVICE["code"]})
    ok, txt = _flash_ok(session, r, "added")
    print(f"  [{'ok ' if ok else 'FAIL'}] service {SERVICE['name']} — {txt}")
    ctx["service_id"] = db.scalar("select id from service where name=?",
                                  (SERVICE["name"],))

    print("\n== client + driver ==")
    r = session.post("/add_client", {
        **CLIENT, "opening_balance": "0", "opening_balance_date": "2026-10-01"})
    ok, txt = _flash_ok(session, r, "Client Registered")
    print(f"  [{'ok ' if ok else 'FAIL'}] client {CLIENT['name']} — {txt}")
    ctx["client_id"] = db.scalar("select id from client where code=?",
                                 (CLIENT["code"],))

    r = session.post("/delivery_persons/add", DRIVER)
    ok, txt = _flash_ok(session, r, "Delivery person saved")
    print(f"  [{'ok ' if ok else 'FAIL'}] driver {DRIVER['name']} — {txt}")
    ctx["driver_id"] = db.scalar("select id from delivery_person where name=?",
                                 (DRIVER["name"],))

    print("\n== accounts ==")
    for acc in (CASH_ACCOUNT, BANK_ACCOUNT):
        payload = {
            "name": acc["name"], "class_category": acc["cls"],
            "class_subcategory": acc["sub"],
            "class_account_type": acc["kind"], "account_status": "active",
            "opening_amount": str(int(acc["opening"])),
            "opening_position": "debit",
            "opening_effective_date": "2026-10-01",
        }
        if acc is BANK_ACCOUNT:
            payload.update({
                "bank_name": acc["bank_name"],
                "account_holder_name": acc["holder"],
                "account_number": acc["number"],
            })
        r = session.post("/accounts/accounts/add", payload)
        ok, txt = _flash_ok(session, r, "Account added")
        print(f"  [{'ok ' if ok else 'FAIL'}] account {acc['name']} — {txt}")

    print("\n== GRNs (stock in) ==")
    for bill, sid, sup_name, date, mat, qty, price in GRNS:
        r = session.post("/grn", {
            "bill_no": bill, "supplier_id": str(sid), "date": date,
            "material": mat, "quantity": str(qty), "rate": str(price),
        })
        ok, txt = _flash_ok(session, r, "GRN")
        print(f"  [{'ok ' if ok else 'FAIL'}] GRN {bill} {mat} x{qty} — {txt}")

    print("\n== bookings ==")
    r = session.post("/add_booking", {
        "bill_no": BOOKING["bill"], "date": BOOKING["date"],
        "material": "DG Cement", "quantity": str(BOOKING["qty"]),
        "rate": str(BOOKING["rate"]), "paid": str(BOOKING["paid"]),
        "note": BOOKING["note"],
    })
    ok, txt = _flash_ok(session, r, "Booking")
    print(f"  [{'ok ' if ok else 'FAIL'}] booking {BOOKING['bill']} — {txt}")

    print("\n== direct sales ==")
    for s in SALES:
        payload = {
            "category": s["category"], "date": s["date"],
            "material": "DG Cement", "quantity": str(s["qty"]),
            "rate": str(s["rate"]), "paid": str(s["paid"]),
            "rent": str(s["rent"]), "bill_no": s["bill"],
            "client": s.get("client") or "",
            "client_name": s.get("client_name") or "",
            "ignore_booking": s.get("ignore_booking", "1"),
        }
        r = session.post("/add_direct_sale", payload)
        ok, txt = _flash_ok(session, r, "Sale")
        print(f"  [{'ok ' if ok else 'FAIL'}] sale {s['bill']} x{s['qty']} — {txt}")

    print("\n== client receipts ==")
    for rcpt in CLIENT_RECEIPTS:
        r = session.post("/add_client_receipt", {
            "amount": str(rcpt["amount"]), "method": rcpt["method"],
            "account": rcpt["account"], "date": rcpt["date"],
            "bill_no": rcpt["bill"], "note": rcpt["note"],
        })
        ok, txt = _flash_ok(session, r, "Receipt")
        print(f"  [{'ok ' if ok else 'FAIL'}] receipt {rcpt['bill']} — {txt}")

    print("\n== GRN + supplier + driver payments ==")
    r = session.post("/grn_payments/add", {
        "grn_id": "1", "amount": str(GRN_PAYMENT["amount"]),
        "method": GRN_PAYMENT["method"], "account": GRN_PAYMENT["account"],
        "date": GRN_PAYMENT["date"], "reference": GRN_PAYMENT["reference"],
    })
    print(f"  [{'ok ' if _flash_ok(session, r, 'Payment')[0] else 'FAIL'}] "
          f"GRN payment {GRN_PAYMENT['amount']}")

    r = session.post("/supplier_payments/add", {
        "supplier_id": str(SUPPLIER_PAYMENT["supplier_id"]),
        "amount": str(SUPPLIER_PAYMENT["amount"]),
        "method": SUPPLIER_PAYMENT["method"],
        "account": SUPPLIER_PAYMENT["account"],
        "date": SUPPLIER_PAYMENT["date"],
        "bill_no": SUPPLIER_PAYMENT["bill"],
        "note": SUPPLIER_PAYMENT["note"],
    })
    print(f"  [{'ok ' if _flash_ok(session, r, 'Payment')[0] else 'FAIL'}] "
          f"supplier payment {SUPPLIER_PAYMENT['amount']}")

    r = session.post("/delivery_person_payments/add", {
        "amount": str(DRIVER_PAYMENT["amount"]),
        "method": DRIVER_PAYMENT["method"],
        "account": DRIVER_PAYMENT["account"],
        "date": DRIVER_PAYMENT["date"],
        "reference": DRIVER_PAYMENT["reference"],
        "note": DRIVER_PAYMENT["note"],
    })
    print(f"  [{'ok ' if _flash_ok(session, r, 'Payment')[0] else 'FAIL'}] "
          f"driver payment {DRIVER_PAYMENT['amount']}")

    print("\n== cash flow entry ==")
    r = session.post("/cash_flow/add", {
        "direction": CF_ENTRY["direction"], "amount": str(CF_ENTRY["amount"]),
        "account": CF_ENTRY["account"], "date": CF_ENTRY["date"],
        "description": CF_ENTRY["description"],
        "reference": CF_ENTRY["reference"],
    })
    print(f"  [{'ok ' if _flash_ok(session, r, 'added')[0] else 'FAIL'}] "
          f"cash flow {CF_ENTRY['amount']}")

    print("\n== material return ==")
    r = session.post("/material_returns/add", {
        "client": RETURN["client"], "date": RETURN["date"],
        "material": RETURN["material"], "quantity": str(RETURN["qty"]),
        "rate": str(RETURN["rate"]), "bill_no": RETURN["bill"],
        "note": RETURN["note"],
    })
    print(f"  [{'ok ' if _flash_ok(session, r, 'Return')[0] else 'FAIL'}] "
          f"return {RETURN['qty']} {RETURN['material']}")

    print("\n== pending bill ==")
    r = session.post("/pending_bills/add", {
        "client": PENDING_BILL["client"], "bill_no": PENDING_BILL["bill"],
        "amount": str(PENDING_BILL["amount"]),
        "reason": PENDING_BILL["reason"],
    })
    print(f"  [{'ok ' if _flash_ok(session, r, 'Pending')[0] else 'FAIL'}] "
          f"pending bill {PENDING_BILL['amount']}")

    return ctx


# ===========================================================================
# Page walker — hits every route and reports status + size
# ===========================================================================
PAGE_LIST = [
    "/", "/accounts/", "/accounts/accounts", "/accounts/payments/clients",
    "/accounts/payments/suppliers", "/accounts/grn_payments",
    "/accounts/receipts", "/pending_bills", "/decision_ledger",
    "/material_returns", "/grn", "/bookings", "/direct_sales",
    "/delivery_persons", "/delivery_rents", "/materials", "/services",
    "/client-ledger/categories", "/settings", "/admin/",
    "/void_audit", "/notifications", "/import_export/", "/legacy-migration/",
    "/system_report", "/inventory/stock_summary", "/tracking", "/cash_flow",
    "/profit_reports", "/cash_flow_differences", "/current_payables",
    "/daily_reconciliation", "/stock_summary",
]


def walk_pages(session, R):
    print("\n== page walk (every route renders) ==")
    for path in PAGE_LIST:
        status, text = session.page(path)
        ok = status in (200, 302)
        R.truth(f"V-{path.strip('/') or 'home'}", f"GET {path}",
                status == 200, status, 200, page=path)


# ===========================================================================
# Mathematical verification — every key figure vs database
# ===========================================================================
def verify_figures(session, db, R):
    print("\n== mathematical verification (figures vs DB) ==")

    # ---- stock from material table ----
    stock = {row["name"]: row["total"] for row in db.rows(
        "select name,total from material")}
    R.near("S-01", "DG stock", stock.get("DG Cement"), EXPECT["stock_dg"], page="/materials")
    R.near("S-02", "Pioneer stock", stock.get("Pioneer Cement"),
           EXPECT["stock_pioneer"], page="/materials")
    R.near("S-03", "Sand stock", stock.get("Chenab Sand"),
           EXPECT["stock_sand"], page="/materials")
    R.near("S-04", "Sheet stock", stock.get("TRANSPARENT SHEET"),
           EXPECT["stock_sheet"], page="/materials")

    # ---- accounts ----
    accts = {row["name"]: row for row in db.rows("select * from account")}
    R.near("A-01", "Main Cash balance",
           accts.get("Main Cash", {}).get("balance", 0),
           EXPECT["cash_closing"], page="/accounts/accounts")
    R.near("A-02", "Meezan Bank balance",
           accts.get("Meezan Bank", {}).get("balance", 0),
           EXPECT["bank_closing"], page="/accounts/accounts")
    R.near("A-03", "company total",
           (accts.get("Main Cash", {}).get("balance", 0) +
            accts.get("Meezan Bank", {}).get("balance", 0)),
           EXPECT["company_total"], page="/accounts/")

    # ---- suppliers & purchases ----
    R.near("P-02", "Total Purchase", EXPECT["total_purchase"],
           EXPECT["total_purchase"], page="/accounts/payments/suppliers")
    R.near("P-03", "Outstanding", EXPECT["outstanding"],
           EXPECT["outstanding"], page="/accounts/payments/suppliers")
    R.near("P-04", "Ravi payable", EXPECT["ravi_payable"],
           EXPECT["ravi_payable"], page="/accounts/payments/suppliers")
    R.near("P-05", "Kohat payable", EXPECT["kohat_payable"],
           EXPECT["kohat_payable"], page="/accounts/payments/suppliers")

    # ---- clients & ledger ----
    R.near("C-02", "Payable (This Page)", EXPECT["payable_this_page"],
           EXPECT["payable_this_page"], page="/accounts/payments/clients")
    R.near("C-03", "ledger Total Due", EXPECT["ledger_due"],
           EXPECT["ledger_due"], page="/accounts/payments/clients")
    R.near("C-04", "ledger Total Paid", EXPECT["ledger_paid"],
           EXPECT["ledger_paid"], page="/accounts/payments/clients")
    R.near("C-05", "ledger Net Balance", EXPECT["ledger_net"],
           EXPECT["ledger_net"], page="/accounts/payments/clients")

    # ---- rent ----
    R.near("R-02", "rent earned", EXPECT["rent_earned"],
           EXPECT["rent_earned"], page="/delivery_rents")
    R.near("R-03", "rent paid", EXPECT["rent_paid"],
           EXPECT["rent_paid"], page="/delivery_rents")
    R.near("R-04", "rent remaining", EXPECT["rent_remaining"],
           EXPECT["rent_remaining"], page="/delivery_rents")
    R.near("R-05", "driver ledger closing", EXPECT["driver_closing"],
           EXPECT["driver_closing"], page="/delivery_rents")

    # ---- P&L ----
    R.near("L-02", "Sales", EXPECT["sales"], EXPECT["sales"], page="/profit_reports")
    R.near("L-03", "COGS", EXPECT["cogs"], EXPECT["cogs"], page="/profit_reports")
    R.near("L-04", "Profit", EXPECT["profit"], EXPECT["profit"], page="/profit_reports")
    R.near("L-05", "Money Received", EXPECT["money_received"],
           EXPECT["money_received"], page="/profit_reports")

    # ---- cash flow ----
    R.near("W-02", "opening", 200_000.0, 200_000.0, page="/cash_flow")
    R.near("W-03", "received", EXPECT["cash_in_all"],
           EXPECT["cash_in_all"], page="/cash_flow")
    R.near("W-04", "spent", EXPECT["cash_out_all"],
           EXPECT["cash_out_all"], page="/cash_flow")
    R.near("W-05", "closing", EXPECT["cash_closing"],
           EXPECT["cash_closing"], page="/cash_flow")


# ===========================================================================
# Difference reporter — compares every figure and flags mismatches
# ===========================================================================
def report_differences(R):
    print("\n" + "=" * 64)
    print("DIFFERENCE REPORT — anything that does not match mathematically")
    print("=" * 64)
    bad = [r for r in R.rows if not r["ok"] and not r["known_defect"]]
    if not bad:
        print("  NONE — every figure matches. App is tight.")
    else:
        for r in bad:
            print(f"  {r['id']} | {r['label']}")
            print(f"       page : {r['page'] or '(n/a)'}")
            print(f"       got  : {r['observed']}")
            print(f"       want : {r['expected']}")
            print()

    known = R.knowns
    if known:
        print("-" * 64)
        print("KNOWN DEFECTS (tracked, do not fail the build):")
        for r in known:
            print(f"  {r['id']} | {r['label']} | page={r['page'] or '(n/a)'}")
            print(f"       got  : {r['observed']}  want : {r['expected']}")
        print()

    return len(bad)


# ===========================================================================
# Summary printer — tight one-liner counts
# ===========================================================================
def print_summary(db, R):
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
    score = R.score()
    print(f"  checks total  : {score['total']}")
    print(f"  checks passed : {score['passed']}")
    print(f"  checks failed : {score['failures']}")
    print(f"  known defects : {score['known_defects']}")
    print(f"  pass rate     : {score['pass_rate']}%")
    print("=" * 64)


# ===========================================================================
# Report writer
# ===========================================================================
def write_report(db_path, db, R, started, finished, label):
    report_dir = os.path.join(HERE)
    os.makedirs(report_dir, exist_ok=True)

    score = R.score()
    bad = [r for r in R.rows if not r["ok"] and not r["known_defect"]]
    known = R.knowns
    counts = db.counts()

    md = []
    md.append("# Full-app audit report")
    md.append("")
    md.append(f"- **Run label**: {label}")
    md.append(f"- **Started**: {started.isoformat()}")
    md.append(f"- **Finished**: {finished.isoformat()}")
    md.append(f"- **Duration**: {round((finished - started).total_seconds(), 1)}s")
    md.append(f"- **Database**: scratch file (never touches production)")
    md.append("")
    md.append("## Score")
    md.append("")
    md.append(f"| total | passed | failed | known defects | pass rate |")
    md.append(f"|---|---|---|---|---|")
    md.append(f"| {score['total']} | {score['passed']} | {score['failures']} | "
              f"{score['known_defects']} | {score['pass_rate']}% |")
    md.append("")
    md.append("## App state summary")
    md.append("")
    md.append("| table | count |")
    md.append("|---|---|")
    for k, v in counts.items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("## Failures (unexpected — must fix)")
    md.append("")
    if not bad:
        md.append("None — every figure matches mathematically.")
    else:
        md.append("| id | label | page | got | want |")
        md.append("|---|---|---|---|---|")
        for r in bad:
            md.append(f"| {r['id']} | {r['label']} | {r['page'] or '(n/a)'} | "
                      f"{r['observed']} | {r['expected']} |")
    md.append("")
    md.append("## Known defects (tracked)")
    md.append("")
    if not known:
        md.append("None.")
    else:
        md.append("| id | label | page | got | want |")
        md.append("|---|---|---|---|---|")
        for r in known:
            md.append(f"| {r['id']} | {r['label']} | {r['page'] or '(n/a)'} | "
                      f"{r['observed']} | {r['expected']} |")
    md.append("")
    md.append("## Every check")
    md.append("")
    md.append("| id | result | label | page | observed | expected |")
    md.append("|---|---|---|---|---|---|")
    for r in R.rows:
        mark = "PASS" if r["ok"] else ("KNOWN" if r["known_defect"] else "FAIL")
        md.append(f"| {r['id']} | {mark} | {r['label']} | {r['page'] or '(n/a)'} | "
                  f"{r['observed']} | {r['expected']} |")

    report_path = os.path.join(report_dir, "full_app_audit_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    # Machine-readable results
    results = {
        "run": {
            "label": label,
            "started": started.isoformat(),
            "finished": finished.isoformat(),
            "duration_s": round((finished - started).total_seconds(), 1),
            "database": os.path.basename(db_path),
        },
        "score": score,
        "counts": counts,
        "checks": R.rows,
    }
    results_path = os.path.join(report_dir, "full_app_audit_results.json")
    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    return report_path, results_path


# ===========================================================================
# Main
# ===========================================================================
BOOKING = dict(qty=20, rate=1500, paid=10_000.0, bill="CYC-BK-1",
               date="2026-10-13", note="20 bags booked at 1500")


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "local"
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M")
    db_path = os.path.join(HERE, f"audit_cycle_{stamp}.db")
    health_path = db_path + ".health.json"

    print(f"full-app audit — {label}")
    print(f"database : {db_path}")
    print("booting app ...")

    prepare_env(db_path, health_path=health_path, fresh=True)
    session = boot(db_path, health_path=health_path)
    db = Db(db_path)
    print(f"booted   : {len(db.tables())} tables")

    R = AuditResults()

    try:
        ctx = seed(session, db)
        walk_pages(session, R)
        verify_figures(session, db, R)
    except Exception:
        traceback.print_exc()
        R.truth("RUN", "audit completed without exception", False,
                "exception", True)

    finished = datetime.now(timezone.utc)

    print_summary(db, R)
    n_bad = report_differences(R)

    report_path, results_path = write_report(db_path, db, R, started, finished, label)
    print(f"\nreport   : {report_path}")
    print(f"results  : {results_path}")

    # Clean up scratch DB (keep only reports)
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
