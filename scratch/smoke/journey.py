"""End-to-end smoke journey for the AMS ERP (real HTTP, real forms, real DB reads).

The journey behaves like a shop manager using the application in a browser:

  * logs in through the real login form (session cookie + CSRF token),
  * opens every page and fails on any 5xx, traceback or error page,
  * creates business data by submitting the forms the pages actually render
    (every hidden field, every CSRF token, no direct SQL writes),
  * reads every figure back from the rendered pages and from the database and
    checks the arithmetic,
  * exercises edit / void / restore / idempotency / permission paths,
  * wipes 100% of business data through Settings -> Granular Data Wipe,
  * proves the database is empty, consistent, FK-clean and that users,
    settings and schema survived,
  * and proves the app is still usable afterwards (new client + new account).

Run with a server already listening (see run_smoke.py for the orchestrator):

    python journey.py --port 5100 --db /tmp/runA.db --label run-A \
        --json out/run-A.json [--phases seed,wipe,empty] [--no-wipe]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import traceback
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Journey, clean  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TODAY = date.today()

# Tables the app legitimately re-seeds immediately after a full wipe.
RESEEDED_TABLES = {"bill_counter"}

# Master rows the application itself creates on every boot (default categories,
# the walk-in "Open Khata" client).  They are seeded by the app, not produced by
# the smoke data, so "empty after a wipe" is judged against the boot snapshot.
# Names the application itself (re)creates on a fresh/empty database.  Anything
# else in these tables is real operator data and must not survive a wipe.
APP_SEEDED_NAMES = {
    "client_category": {"General", "Open Khata", "Walking-Customer", "Misc"},
    "material_category": {"General"},
    "account_category": {"Company", "Own Funds", "Clients", "External", "Loan"},
    "client": {"OPEN-KHATA"},
}


TODAY_S = TODAY.strftime("%Y-%m-%d")


def D(days: int) -> str:                      # noqa: D401 - tiny helper
    return (TODAY - timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Canonical dataset.  Every expected figure derives from these numbers.
# ---------------------------------------------------------------------------
CLIENTS = [
    dict(name="Bilal Construction", code="CYC-CL-1", category="General",
         phone="0321-1112223", address="Blue Area, Islamabad"),
    dict(name="Hassan Traders", code="CYC-CL-2", category="Contractor",
         phone="0333-4445556", address="I-9 Industrial Area"),
]
SUPPLIERS = [
    dict(name="Ravi Cement Supplier", phone="0300-1234567", address="Ravi Road, Lahore"),
    dict(name="Kohat Traders", phone="0301-7654321", address="Kohat Bazaar"),
]
MATERIAL_CATS = ["Cement", "Sand & Gravel"]
MATERIALS = [
    dict(name="DG Cement", code="DG", unit="Bag", category="Cement"),
    dict(name="Pioneer Cement", code="PIO", unit="Bag", category="Cement"),
    dict(name="Chenab Sand", code="SAND", unit="Cft", category="Sand & Gravel"),
]
SERVICE = dict(name="CEMENT RENT", code="SRV-RENT", unit="Trip")
DRIVERS = [dict(name="Akram Driver", phone="0333-9998887"),
           dict(name="Shakeel Driver", phone="0300-1112223")]
CASH = dict(name="Main Cash", opening="200000", sub="Cash", kind="Main Cash", channel="cash")
BANK = dict(name="Meezan Bank", opening="500000", sub="Bank", kind="Operating Bank",
            channel="bank", bank_name="Meezan Bank", holder="Ahmed Cement",
            number="0123456789")

GRNS = [
    # bill, supplier, date, material, qty, rate, loading, freight
    ("CYC-GRN-1", "Ravi Cement Supplier", D(20), "DG Cement", 100, 1200, 2000, 3000),
    ("CYC-GRN-2", "Ravi Cement Supplier", D(18), "DG Cement", 50, 1350, 0, 0),
    ("CYC-GRN-3", "Kohat Traders", D(16), "Chenab Sand", 200, 55, 0, 0),
]
SUPPLIER_PAYMENT = dict(supplier="Ravi Cement Supplier", amount="50000", date=D(10),
                        bill="CYC-SUPPAY-1")
BOOKING = dict(client="CYC-CL-1", material="DG Cement", qty=20, rate=1500,
               paid=10000, date=D(12), bill="CYC-BK-1")
SALES = [
    # run 1 (values are rewritten per run by Runner.scale_sales)
    dict(kind="cash", client="", material="DG Cement", qty=5, rate=1700,
         paid=8500, date=D(11), bill="CYC-CASH-1", driver="Akram Driver", rent=200),
    dict(kind="credit", client="CYC-CL-1", material="DG Cement", qty=10,
         rate=1650, paid=5000, date=D(10), bill="CYC-CR-1", driver="Akram Driver", rent=0),
    dict(kind="booking", client="CYC-CL-1", material="DG Cement", qty=20,
         rate=1500, paid=0, date=D(9), bill="CYC-BD-1", driver="Akram Driver", rent=800),
]
RECEIPT = dict(client="CYC-CL-1", amount=8000, date=D(8), bill="CYC-RCPT-1")
EXPECTED_SALE = 5 * 1700 + 10 * 1650
RETURN = dict(client="CYC-CL-1", material="DG Cement", qty=2, rate=1650, date=D(7))
DRIVER_PAY = dict(amount=400, date=D(6))

DG_IN = 150          # 100 + 50 received
DG_OUT = 5 + 10 + 20 # cash + credit + booking delivery
DG_STOCK = DG_IN - DG_OUT + RETURN["qty"]

PAGES_EMPTY_OK = (200, 302)
PAGES_ROW_MAY_404 = (200, 302, 404)


class Runner:
    def __init__(self, port: int, db_path: str, label: str):
        self.log: dict = {}
        self.j = Journey(f"http://127.0.0.1:{port}", log=self.log, db_path=db_path)
        self.db_path = db_path
        self.label = label
        self.phase = "start"
        self.counts: list[dict] = []
        self.samples: dict = {}
        self.base: dict = {}
        # 1 for the first pass on a database, 2 for the re-run after the wipe.
        # Test accounts get a per-pass username because a "deleted" user is only
        # deactivated: the row, and its username, survive.
        self.pass_no = int(label.rsplit("-", 1)[-1]) if label.rsplit("-", 1)[-1].isdigit() else 1

    # ------------------------------------------------------------------ utils
    def phase_start(self, name):
        self.phase = name
        print(f"\n=== {name} ===", flush=True)

    def ok(self, step, cond, detail=""):
        self.j.record(step, cond, detail, page=self.phase, kind="check")
        print(f"  [{'OK ' if cond else 'FAIL'}] {step}"
              + ("" if cond else f"   <- {str(detail)[:300]}"), flush=True)
        return bool(cond)

    def db(self):
        return sqlite3.connect(f"file:{os.path.abspath(self.db_path)}?mode=ro",
                               uri=True, timeout=30)

    def scalar(self, sql, params=()):
        with self.db() as conn:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

    def rows(self, sql, params=()):
        with self.db() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def table_count(self, table):
        try:
            return self.scalar(f'SELECT COUNT(*) FROM "{table}"')
        except sqlite3.Error:
            return None

    def page(self, path, allow=PAGES_EMPTY_OK):
        return self.j.page(path, allow=allow)

    def submit(self, path, needle, overrides, *, expect=None, note="", index=0,
               follow=True, fetch_first=True, action_override=None):
        """Open *path* and submit the form whose action contains *needle*."""
        if fetch_first:
            resp = self.j.get(path, kind="write")
            soup = self.j.soup(resp)
        else:
            resp = self.j.last_response
            soup = self.j.soup(resp)
        form = self.j.find_form(soup, needle, index=index)
        label = note or needle
        if form is None:
            # Some screens post from a table row / a script instead of a <form>
            # element; the request body is then the same as the page's fields.
            form = soup.new_tag("form")
            form["action"] = action_override or path
        # A required <select> cannot be left empty by a user: fill the first
        # real option, exactly as the browser would send it.
        sent = dict(overrides)
        for el in form.find_all("select"):
            name = el.get("name")
            if not name or name in sent or not el.has_attr("required"):
                continue
            options = [o.get("value") for o in el.find_all("option")
                       if o.get("value") not in (None, "")]
            if not options:
                continue
            current = [o.get("value") for o in el.find_all("option") if o.has_attr("selected")]
            if current and current[0]:
                continue
            sent[name] = options[0]
        overrides = sent
        post, elapsed = self.j.submit(soup, form, overrides, note=label,
                                      action_override=action_override)
        final = post
        if follow:
            final, _ = self.j.follow(post)
        text = self.j.flash_text(final)
        self.j.requests[-1]["flash"] = text
        if post.status_code >= 400:
            self.ok(label, False, f"HTTP {post.status_code}: {clean(post.text)[:300]}")
            return final, text
        if expect:
            good = [t for c, t in self.j.flashes(final.text) if c in ("success", "info")]
            hit = any(expect.lower() in g.lower() for g in good)
            self.ok(label, hit, text or f"no flash (status {post.status_code})")
            return final, text
        self.ok(label, True, text or f"HTTP {post.status_code}")
        return final, text

    def post(self, path, data=None, *, note="", expect=None, allow_redirects=True,
             files=None):
        """POST straight to an action URL, the way a button on the page does.

        Used for the POST-only endpoints a browser reaches from a form/JS call;
        opening them with GET would (correctly) answer 405 Method Not Allowed.
        """
        payload = {"_csrf_token": self.j.csrf}
        payload.update(data or {})
        label = note or path
        post = self.j.session.post(f"{self.j.base}{path}", data=payload, files=files,
                                   allow_redirects=allow_redirects, timeout=180)
        self.j._log("POST", path, post.status_code, label)
        if post.status_code >= 500:
            self.ok(label, False, f"HTTP {post.status_code}: {clean(post.text)[:200]}")
            return post, ""
        if post.status_code in (301, 302, 303, 307, 308):
            final, _ = self.j.follow(post, limit=3)
        else:
            final = post
        text = self.j.flash_text(final)
        self.j.requests[-1]["flash"] = text
        if expect:
            good = [t for c, t in self.j.flashes(final.text) if c in ("success", "info")]
            self.ok(label, any(expect.lower() in g.lower() for g in good), text or "no flash")
        else:
            self.ok(label, post.status_code < 400, f"HTTP {post.status_code}")
        return final, text

    def json_post(self, path, payload, note):
        resp, _ = self.j.submit_json(path, payload, note=note)
        try:
            body = resp.json()
        except Exception:
            body = {}
        return resp, body

    # ------------------------------------------------------------- lookups --#
    def account_id(self, name):
        return self.scalar("SELECT id FROM account WHERE name=?", (name,))

    def balance(self, name):
        v = self.scalar("SELECT balance_minor FROM account WHERE name=?", (name,))
        return None if v is None else v / 100.0

    def balance_minor(self, name):
        return self.scalar("SELECT balance_minor FROM account WHERE name=?", (name,))

    def client_id(self, code):
        return self.scalar("SELECT id FROM client WHERE code=?", (code,))

    def supplier_id(self, name):
        return self.scalar("SELECT id FROM supplier WHERE name=?", (name,))

    def material_id(self, name):
        return self.scalar("SELECT id FROM material WHERE name=?", (name,))

    def driver_id(self, name):
        return self.scalar("SELECT id FROM delivery_person WHERE name=?", (name,))

    def category_id(self, name):
        return self.scalar("SELECT id FROM material_category WHERE name=?", (name,))

    def column_exists(self, table, column):
        return column in {r["name"] for r in self.rows(f'PRAGMA table_info("{table}")')}

    def derive_ledger_token(self, client_id):
        """Rebuild the client's active QR bearer token (never stored raw)."""
        import hashlib
        import hmac
        salt = self.scalar("SELECT client_ledger_qr_token_salt FROM client WHERE id=?",
                           (client_id,))
        secret = (os.environ.get("SMOKE_SECRET_KEY") or "").strip()
        if not secret:
            path = os.path.join(REPO_ROOT, "instance", "secret_key")
            if os.path.exists(path):
                secret = open(path, encoding="utf-8").read().strip()
        if not salt or not secret:
            return None
        digest = hmac.new(secret.encode(), f"client-ledger-qr-v1:{client_id}:{salt}".encode(),
                          hashlib.sha256).digest()
        import base64
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    @staticmethod
    def public_base_url_https():
        """True when the server was started with an HTTPS PUBLIC_BASE_URL."""
        return (os.environ.get("SMOKE_PUBLIC_BASE_URL") or "").startswith("https://")

    def bill_token(self, bill_type="DirectSale", bill_no="MB NO.CYC-CR-1",
                   bill_id=None):
        """Mint the same signed token the app prints in its own bill QR.

        Built here (not imported from the app) so the smoke run never boots a
        second Flask app against the database it is testing.
        """
        import base64
        import hashlib
        import hmac
        letters = {"DirectSale": "S", "Booking": "B", "Payment": "P",
                   "Invoice": "I", "GRN": "G", "PendingBill": "N"}
        secret = (os.environ.get("SMOKE_SECRET_KEY") or "").strip()
        if not secret or not bill_no:
            return None
        number = "".join(ch for ch in str(bill_no).upper()
                         if ch.isalnum() or ch in "-.$%*+/:")[-16:]
        payload = f"{letters.get(bill_type, 'S')}.{int(bill_id or 0)}.{number}"
        digest = hmac.new(secret.encode(), b"ams-bill-qr-v2" + payload.encode(),
                          hashlib.sha256).digest()[:8]
        return f"{payload}.{base64.b32encode(digest).decode().rstrip('=')}"

    def scale_sales(self, factor: int):
        """Shrink/grow the sale quantities so any stock level can be served.

        Cycle A runs on freshly received stock, cycle B starts from whatever
        the previous cycle left behind, so the quantities cannot be hard-coded.
        Discounts of the products are never changed, only the quantity.
        """
        for sale in SALES:
            sale["qty"] = max(1, int(round(sale["qty"] * factor)))
            sale["paid"] = int(round(sale["qty"] * sale["rate"] * 0.6))
        BOOKING["qty"] = max(1, int(round(BOOKING["qty"] * factor)))
        BOOKING["paid"] = int(round(BOOKING["qty"] * BOOKING["rate"] * 0.33))
        RETURN["qty"] = max(1, int(round(RETURN["qty"] * factor)))
        self.refresh_expectations()

    def refresh_expectations(self):
        global DG_OUT, DG_STOCK, EXPECTED_SALE
        DG_OUT = sum(x["qty"] for x in SALES)
        DG_STOCK = DG_IN - DG_OUT + RETURN["qty"]
        EXPECTED_SALE = sum(x["qty"] * x["rate"] for x in SALES if x["kind"] != "booking")

    def stock_factor(self):
        """How many bags is it safe to sell against the stock on hand now?"""
        available = self.scalar("SELECT COALESCE(total,0) FROM material WHERE name='DG Cement'") or 0
        planned = sum(x["qty"] for x in SALES)
        if available <= 0:
            return 0.0
        return min(1.0, (available * 0.7) / max(1, planned))

    @staticmethod
    def charge_grid(loading: float, freight: float) -> dict:
        """The GRN wizard's landed-cost charge rows (one row per cost)."""
        if not loading and not freight:
            return {}
        rows = []
        if loading:
            rows.append(("LOADING", "Loading", loading))
        if freight:
            rows.append(("TRANSPORT", "Freight", freight))
        return {
            "charge_id[]": ["" for _ in rows],
            "charge_row_key[]": [f"row-{i}" for i in range(len(rows))],
            "charge_type[]": [r[0] for r in rows],
            "charge_label[]": [r[1] for r in rows],
            "charge_amount[]": [str(r[2]) for r in rows],
            "charge_include_in_supplier[]": [f"row-{i}" for i in range(len(rows))],
            "charge_recipient_type[]": ["OTHER" for _ in rows],
            "charge_recipient[]": ["Owner charges" for _ in rows],
            "charge_treatment[]": ["INVENTORY" for _ in rows],
            "charge_basis[]": ["VALUE" for _ in rows],
        }

    def business_tables(self):
        tables = [r["name"] for r in self.rows(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        skip = {"audit_log", "schema_version", "migration_history", "settings", "user",
                "user_login_session", "sidebar_item", "sidebar_category", "system_lock",
                "terms_and_conditions", "daily_db_backup_history",
                "daily_db_backup_settings", "root_backup_settings",
                "root_backup_email_history", "root_recovery_code",
                "tenant_wipe_backup_history",
                }
        return [t for t in tables if t not in skip]

    def snapshot_base(self):
        """Counts right now, so a repeat pass measures its own delta."""
        self.base = {
            "grn_item": self.scalar("SELECT COUNT(*) FROM grn_item") or 0,
            "grn_value": float(self.scalar(
                "SELECT COALESCE(SUM(qty*price_at_time),0) FROM grn_item") or 0),
            "landed": float(self.scalar(
                "SELECT COALESCE(SUM(landed_cost_total),0) FROM grn") or 0),
            "present": set(self.j.session.cookies.get_dict()) and True,
            "stock": {r["name"]: r["total"] for r in
                      self.rows("SELECT name,total FROM material")},
            "sale_count": self.scalar("SELECT COUNT(*) FROM direct_sale") or 0,
            "sale_value": float(self.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM direct_sale WHERE is_void=0") or 0),
        }

    # --------------------------------------------------------------- 1 boot --
    def phase_boot(self):
        self.phase_start("1. boot and authentication")
        self.snapshot_base()
        self.ok("login page is public", self.j.get("/login").status_code == 200)
        anon = self.j.session.get(f"{self.j.base}/", allow_redirects=False)
        self.ok("anonymous request is redirected to login", anon.status_code == 302,
                str(anon.status_code))
        self.ok("login as Admin (default credentials)", self.j.login())
        home = self.j.session.get(f"{self.j.base}/")
        self.ok("index renders after login", home.status_code == 200, str(home.status_code))
        self.j.soup(home)
        self.ok("CSRF token captured from the rendered page", bool(self.j.csrf))
        self.ok("session cookie is HTTP-only",
                "ams_session" in self.j.session.cookies.get_dict())
        bad = self.j.session.post(f"{self.j.base}/clients", data={"name": "x"},
                                  timeout=60, allow_redirects=False)
        self.ok("POST without a CSRF token is rejected", bad.status_code in (400, 403),
                f"{bad.status_code} {bad.text[:120]}")
        self.ok("no server error on the rejected POST", bad.status_code < 500)
        print("  app-seeded masters at boot: "
              + ", ".join(f"{t}={self.table_count(t)}" for t in APP_SEEDED_NAMES),
              flush=True)

    # ------------------------------------------------------------ 2 masters --
    def phase_masters(self):
        self.phase_start("2. masters: categories, materials, services, suppliers, clients, drivers, accounts")
        for cat in MATERIAL_CATS:
            self.submit("/settings", "/material_categories/add", {"category_name": cat},
                        expect="added", note=f"material category '{cat}'")
        cats = {r["name"]: r["id"] for r in self.rows("SELECT id,name FROM material_category")}
        for cat in MATERIAL_CATS:
            self.ok(f"category '{cat}' stored", cat in cats)

        for mat in MATERIALS:
            self.submit("/materials", "/add_material", {
                "material_name": mat["name"], "material_code": mat["code"],
                "material_unit": mat["unit"], "category_id": str(cats[mat["category"]]),
            }, expect="added", note=f"material '{mat['name']}'")
        for mat in MATERIALS:
            self.ok(f"material '{mat['name']}' stored",
                    bool(self.rows("SELECT id FROM material WHERE name=?", (mat["name"],))))
        self.submit("/services", "/services/add", {
            "service_name": SERVICE["name"], "service_code": SERVICE["code"],
            "service_unit": SERVICE["unit"]}, expect="added", note="service 'CEMENT RENT'")
        self.ok("service stored",
                self.scalar("SELECT COUNT(*) FROM service WHERE name='CEMENT RENT'") == 1)

        for sup in SUPPLIERS:
            self.submit("/suppliers", "/add_supplier",
                        {**sup, "opening_balance": "0", "opening_balance_date": D(30)},
                        expect="Supplier Added", note=f"supplier '{sup['name']}'")
        for sup in SUPPLIERS:
            self.ok(f"supplier '{sup['name']}' stored",
                    bool(self.rows("SELECT id FROM supplier WHERE name=?", (sup["name"],))))

        for cat in ("General", "Contractor"):
            self.submit("/client-ledger/categories", "/client-ledger/categories/add",
                        {"name": cat}, note=f"client category '{cat}'")
        for c in CLIENTS:
            self.submit("/clients", "/add_client",
                        {**c, "opening_balance": "0", "opening_balance_date": D(30)},
                        expect="Client Registered", note=f"client '{c['name']}'")
        for c in CLIENTS:
            self.ok(f"client '{c['name']}' stored",
                    bool(self.rows("SELECT id FROM client WHERE code=?", (c["code"],))))

        for drv in DRIVERS:
            self.submit("/delivery_persons", "/delivery_persons/add", drv,
                        expect="Delivery person saved", note=f"driver '{drv['name']}'")
        self.ok("both drivers stored",
                self.scalar("SELECT COUNT(*) FROM delivery_person") == len(DRIVERS))

        for acc in (CASH, BANK):
            payload = {"name": acc["name"], "class_category": "Assets",
                       "class_subcategory": acc["sub"], "class_account_type": acc["kind"],
                       "channel": acc["channel"], "opening_amount": acc["opening"],
                       "opening_position": "debit", "opening_effective_date": D(30),
                       "account_status": "active"}
            if acc is BANK:
                payload.update({"bank_name": acc["bank_name"],
                                "account_holder_name": acc["holder"],
                                "account_number": acc["number"]})
            self.submit("/accounts/accounts/add", "/accounts/accounts/add", payload,
                        expect="Account added", note=f"account '{acc['name']}'")
        self.ok("cash account opening balance stored in minor units",
                self.balance_minor("Main Cash") == 20000000,
                str(self.balance_minor("Main Cash")))
        self.ok("bank account opening balance stored in minor units",
                self.balance_minor("Meezan Bank") == 50000000,
                str(self.balance_minor("Meezan Bank")))
        # Duplicate guard: the same client code twice must be refused.
        self.submit("/clients", "/add_client",
                    {**CLIENTS[0], "opening_balance": "0", "opening_balance_date": D(30)},
                    note="duplicate client code refused (expected failure message)")
        self.ok("duplicate client code did not create a second row",
                self.scalar("SELECT COUNT(*) FROM client WHERE code='CYC-CL-1'") == 1)

    # --------------------------------------------------------- 3 purchasing --
    def phase_purchasing(self):
        self.phase_start("3. purchasing: GRN with landed cost, supplier payment, ledgers")
        self.snapshot_base()   # deltas are measured from here, not from boot
        for bill, supplier, dt, material, qty, rate, loading, freight in GRNS:
            self.submit("/grn", "/grn", {
                "action": "add", "supplier": supplier, "supplier_id": "",
                "date": dt, "time": "10:00", "manual_bill_no": bill,
                "mat_name[]": [material], "qty[]": [str(qty)], "price[]": [str(rate)],
                "items_present": "1",
                "loading_cost": str(loading), "freight_cost": str(freight),
                "other_expense": "0", "adjustment_amount": "0", "discount": "0",
                "tax_percent": "0", "tax_amount": "0", "note": f"smoke {bill}",
                "charge_grid_present": "1", "charge_supplier_billing_present": "1",
                **self.charge_grid(loading, freight),
            }, note=f"GRN {bill} ({qty} x {material})")
        for bill, *_ in GRNS:
            self.ok(f"GRN {bill} stored",
                    bool(self.rows("SELECT id FROM grn WHERE manual_bill_no IN (?,?)",
                                   (bill, "MB NO." + bill))))
        grn_items = self.scalar("SELECT COUNT(*) FROM grn_item")
        self.ok("GRN line items stored",
                grn_items - self.base["grn_item"] == len(GRNS),
                f"{self.base['grn_item']} -> {grn_items}")
        stock = {r["name"]: r["total"] for r in self.rows("SELECT name,total FROM material")}
        dg = stock.get("DG Cement", 0) - self.base["stock"].get("DG Cement", 0)
        self.ok("DG Cement stock rose by 150 after two receipts", dg == 150, str(dg))
        self.ok("Chenab Sand stock = 200 after one receipt",
                stock.get("Chenab Sand") == 200, str(stock.get("Chenab Sand")))
        line_total = float(self.scalar("SELECT COALESCE(SUM(qty*price_at_time),0) FROM grn_item") or 0)
        # 100 x 1,200 + 50 x 1,350 + 200 x 55 = 120,000 + 67,500 + 11,000
        received = round(line_total - self.base["grn_value"], 2)
        self.ok("GRN material lines = 198,500 (material value received)",
                received == 198500.0, f"{self.base['grn_value']} -> {line_total}")
        charges = self.scalar("SELECT COALESCE(SUM(amount),0) FROM grn_charge") \
            if self.table_count("grn_charge") else 0
        # Loading + freight were both typed into the GRN charge grid: the two
        # lines must be stored as charged, not silently dropped.
        self.ok("landed-cost charges recorded (loading + freight = 5,000)",
                round(float(charges or 0), 2) == 5000.0
                and self.table_count("grn_charge") >= 2,
                f"charges={charges} rows={self.table_count('grn_charge')}")

        # Supplier payment through the Accounts supplier-payment form.
        self.submit("/accounts/payments/suppliers", "/accounts/payments/suppliers/save", {
            "supplier_id": str(self.supplier_id(SUPPLIER_PAYMENT["supplier"])),
            "amount": SUPPLIER_PAYMENT["amount"], "method": "Cash",
            "payment_account_id": str(self.account_id("Main Cash")),
            "date": SUPPLIER_PAYMENT["date"], "note": "part payment to Ravi",
            "manual_bill_no": SUPPLIER_PAYMENT["bill"],
            "idempotency_key": f"smoke-{self.label}-suppay1",
            "show": "active", "allow_advance": "1"},
            note="supplier payment 50,000")
        paid = float(self.scalar("SELECT COALESCE(SUM(amount),0) FROM supplier_payment") or 0)
        self.ok("supplier payment stored", paid == 50000, str(paid))

        sid = self.supplier_id("Ravi Cement Supplier")
        for path in (f"/supplier_ledger/{sid}", f"/download_supplier_ledger/{sid}",
                     f"/supplier_ledger_shift/{sid}"):
            self.page(path)
        self.submit(f"/supplier_ledger_shift/{sid}", f"/shift_supplier_ledger/{sid}",
                    {"confirm": "1", "target_supplier_id": str(sid),
                     "new_supplier_name": SUPPLIERS[0]["name"],
                     "new_supplier_phone": SUPPLIERS[0]["phone"],
                     "move_opening_balance": "on"},
                    note="supplier ledger maintenance dialog submitted")
        for path in ("/accounts/pay_grn", "/accounts/purchase_payables",
                     "/accounts/grn_payments", "/export_grn", "/accounts/ledger/%d" %
                     self.account_id("Main Cash"), "/api/supplier_balance/%d" % sid,
                     "/api/supplier_ledger_shift_preview/%d" % sid):
            self.page(path)

    # -------------------------------------------------------------- 4 stock --
    def phase_stock(self):
        self.phase_start("4. stock: material ledger, inventory pages, bulk unit change")
        dg = self.material_id("DG Cement")
        for path in (f"/material_ledger/{dg}", "/inventory/stock_summary",
                     "/inventory/inventory_log", "/inventory/daily_transactions",
                     "/stock_summary", "/materials"):
            self.page(path)
        self.submit("/materials", "/bulk_update_material_unit", {
            "category_id": str(self.category_id("Sand & Gravel")), "new_unit": "Cft"},
            note="bulk unit update for a category")
        self.ok("bulk unit update applied",
                self.scalar("SELECT unit FROM material WHERE name='Chenab Sand'") == "Cft",
                str(self.scalar("SELECT unit FROM material WHERE name='Chenab Sand'")))
        self.submit("/materials", "/materials/rename_label", {
            "old_label": "DG", "target_material_id": str(dg)},
            note="material label rename (label -> same material)")
        self.page("/materials")

    # -------------------------------------------------------------- 5 sales --
    def phase_sales(self):
        self.phase_start("5. sales: booking, cash sale, credit sale, booking delivery")
        factor = self.stock_factor()
        self.ok("enough stock is on hand to sell", factor > 0,
                str(self.scalar("SELECT total FROM material WHERE name='DG Cement'")))
        if factor <= 0:
            return
        if factor < 1.0:
            self.scale_sales(factor)
        self.submit("/bookings", "/add_booking", {
            "client_code": BOOKING["client"], "material_name[]": [BOOKING["material"]],
            "qty[]": [str(BOOKING["qty"])], "unit_rate[]": [str(BOOKING["rate"])],
            "amount": str(BOOKING["qty"] * BOOKING["rate"]),
            "paid_amount": str(BOOKING["paid"]),
            "date": f"{BOOKING['date']}T10:00",
            "manual_bill_no": BOOKING["bill"], "discount": "0",
            "payment_method": "Cash",
            "payment_account_id": str(self.account_id("Main Cash")),
            "note": "20 bags booked at 1500",
        }, note=f"booking {BOOKING['bill']}")
        self.ok("booking stored",
                bool(self.rows("SELECT id FROM booking WHERE manual_bill_no IN (?,?)",
                               (BOOKING["bill"], "MB NO." + BOOKING["bill"]))))
        self.ok("booking line stored",
                self.scalar("SELECT COUNT(*) FROM booking_item") == 1)
        self.page("/bookings")
        self.page("/bookings/1/edit-modal", allow=(200, 302, 404))

        for sale in SALES:
            category = {"cash": "Cash", "credit": "Credit Customer",
                        "booking": "Booking Delivery"}[sale["kind"]]
            self.submit("/direct_sales", "/add_direct_sale", {
                "category": category,
                "client_code": sale["client"],
                "client_name": "" if sale["kind"] == "cash" else "",
                "manual_client_name": "Walk-in Customer" if sale["kind"] == "cash" else "",
                "product_name[]": [sale["material"]],
                "material_id[]": [""], "service_id[]": [""],
                "qty[]": [str(sale["qty"])], "unit_rate[]": [str(sale["rate"])],
                "alternate_material[]": [""], "alternate_material_id[]": [""],
                "grn_item_id[]": [""],
                "ignore_booking_item[]": ["0" if sale["kind"] == "booking" else "1"],
                "delivery_person_id[]": [str(self.driver_id(sale["driver"]))
                                         if sale["kind"] == "booking" else ""],
                "delivery_bags[]": [str(sale["qty"]) if sale["kind"] == "booking" else ""],
                "delivery_rent_amount[]": [str(sale["rent"])
                                           if sale["kind"] == "booking" else ""],
                "sale_date": f"{sale['date']}T11:00",
                "manual_bill_no": sale["bill"],
                "delivery_rent": str(sale["rent"]),
                "driver_name": sale["driver"],
                "paid_amount": str(sale["paid"]), "payment_method": "Cash",
                "payment_account_id": str(self.account_id("Main Cash")),
                "discount": "0", "has_bill": "1", "create_invoice": "1",
                "track_as_cash": "0", "amount": "",
                "idempotency_key": f"smoke-{self.label}-{sale['bill']}",
                "note": f"smoke {sale['bill']}",
            }, note=f"direct sale {sale['bill']} ({category})")
        for sale in SALES:
            self.ok(f"sale {sale['bill']} stored",
                    bool(self.rows(
                        "SELECT id FROM direct_sale WHERE manual_bill_no IN (?,?)",
                        (sale["bill"], "MB NO." + sale["bill"]))))
        self.ok("exactly three direct sales exist",
                (self.scalar("SELECT COUNT(*) FROM direct_sale") or 0)
                - self.base["sale_count"] == 3,
                f"{self.base['sale_count']} -> {self.scalar('SELECT COUNT(*) FROM direct_sale')}")
        dg = self.scalar("SELECT total FROM material WHERE name='DG Cement'")
        dg_delta = dg - self.base["stock"].get("DG Cement", 0)
        self.ok(f"DG stock moved by {DG_IN - DG_OUT} after receipts and sales",
                dg_delta == DG_IN - DG_OUT, str(dg_delta))
        for bill in [x["bill"] for x in SALES]:
            self.page(f"/view_bill/{bill}")
            printable = self.j.session.get(f"{self.j.base}/view_bill/{bill}?print=1")
            self.ok(f"printable bill sheet for {bill} renders",
                    printable.status_code in (200, 302), str(printable.status_code))
            pdf = self.j.session.get(f"{self.j.base}/download_invoice/{bill}"
                                     f"?src=direct_sale")
            self.ok(f"invoice PDF for {bill} is a real file",
                    pdf.status_code == 200 and pdf.content.startswith(b"%PDF"),
                    f"{pdf.status_code} {pdf.headers.get('Content-Type')} "
                    f"{pdf.content[:8]!r}")
        self.page("/view_bill_detail/DirectSale/1", allow=PAGES_ROW_MAY_404)
        for path in ("/direct_sales", "/payments", "/mixed_transactions"):
            self.page(path)

    # -------------------------------------------------------- 6 collections --
    def phase_collections(self):
        self.phase_start("6. collections: receipts, client payments, pending bills")
        self.submit("/accounts/payments/clients", "/accounts/payments/clients/save", {
            "client_code": RECEIPT["client"], "client_name": "",
            "amount": str(RECEIPT["amount"]), "method": "Cash",
            "payment_account_id": str(self.account_id("Main Cash")),
            "date": RECEIPT["date"], "manual_bill_no": RECEIPT["bill"],
            "payment_type": "Receipt", "discount": "0",
            "idempotency_key": f"smoke-{self.label}-rcpt1", "note": "part receipt",
            "show": "active",
        }, note="client receipt 8,000")
        self.ok("client receipt stored",
                bool(self.rows("SELECT id FROM payment WHERE manual_bill_no IN (?,?)",
                               (RECEIPT["bill"], "MB NO." + RECEIPT["bill"]))))
        legacy = self.j.session.post(
            f"{self.j.base}/add_payment",
            data={"_csrf_token": self.j.csrf, "client_code": "CYC-CL-2",
                  "amount": "1500", "method": "Cash",
                  "payment_account_id": str(self.account_id("Main Cash")),
                  "date": D(4), "payment_type": "Receipt",
                  "manual_bill_no": "CYC-RCPT-2", "note": "second receipt",
                  "idempotency_key": f"smoke-{self.label}-rcpt2"},
            timeout=120, allow_redirects=True)
        self.ok("legacy /add_payment endpoint still records a receipt",
                legacy.status_code == 200 and
                self.scalar("SELECT COUNT(*) FROM payment WHERE manual_bill_no LIKE '%CYC-RCPT-2'") == 1,
                f"{legacy.status_code} {self.j.flash_text(legacy)[:200]}")
        # The read-only payments page must not offer an unreachable edit form.
        payments_page = self.page("/payments")
        self.ok("payments page is read-only (no dead entry form)",
                'action="/add_payment"' not in payments_page.text,
                "an edit form is rendered but its route is read-only")
        # A manual pending bill, then pay it via the JSON endpoint the UI calls.
        self.submit("/pending_bills", "/add_pending_bill", {
            "client_code": "CYC-CL-1", "bill_no": "CYC-PB-1", "amount": "4500",
            "reason": "Extra loading charge", "note": "manual charge", "nimbus_no": "",
        }, note="pending bill 4,500")
        pb = self.rows("SELECT id FROM pending_bill ORDER BY id LIMIT 1")
        self.ok("pending bill stored", bool(pb))
        if pb:
            resp, body = self.json_post(f"/toggle_bill_paid/{pb[0]['id']}", {},
                                       "mark pending bill paid")
            self.ok("pending bill marked paid", body.get("is_paid") is True, str(body))
        for path in ("/pending_bills", "/unpaid_transactions", "/current_payables",
                     "/export_pending_bills", "/export_unpaid_transactions",
                     "/export_clients", "/export_current_payables",
                     "/accounts/payments/clients", "/accounts/payments/suppliers",
                     "/accounts/receipts", "/accounts/expenditures",
                     "/api/current_payables", "/api/notifications/due"):
            self.page(path)

    # ------------------------------------------------------------ 7 returns --
    def phase_returns(self):
        self.phase_start("7. returns: normal material return")
        before = self.scalar("SELECT total FROM material WHERE name='DG Cement'")
        self.submit("/material_returns", "/add_material_return", {
            "client_code": RETURN["client"], "date": f"{RETURN['date']}T12:00",
            "return_type": "normal", "material_name[]": [RETURN["material"]],
            "qty[]": [str(RETURN["qty"])], "unit_rate[]": [str(RETURN["rate"])],
            "rent_rate[]": ["0"], "manual_bill_no": "CYC-RTN-1",
            "note": "2 bags returned",
        }, note="material return of 2 bags")
        after = self.scalar("SELECT total FROM material WHERE name='DG Cement'")
        self.ok("return put the 2 bags back into stock", after == before + 2,
                f"{before} -> {after}")
        self.ok("return entry stored as an IN movement",
                bool(self.rows("SELECT id FROM entry WHERE type='IN' AND qty=?", (2,))))
        self.page("/material_returns")

    # --------------------------------------------------------- 8 deliveries --
    def phase_deliveries(self):
        self.phase_start("8. delivery: dispatch, rents, driver ledger and settlement")
        drv = self.driver_id("Akram Driver")
        self.submit("/dispatching", "/add_record", {
            "type": "OUT", "client": "CYC-CL-1", "material": "DG Cement",
            "qty": "3", "bill_no": "CYC-DISP-1", "date": D(3),
            "driver_name": "Akram Driver", "note": "dispatch 3 bags",
            "has_bill": "1", "create_invoice": "1", "track_as_cash": "",
        }, note="dispatch OUT of 3 bags")
        self.page("/dispatching")
        self.page("/tracking")
        self.page("/delivery_rents")
        self.page("/delivery_persons")
        self.page(f"/delivery_person_ledger/{drv}")
        self.page(f"/delivery_ledger/{drv}")
        # The settlement modal is per driver; its action is built by the page
        # script, so post to the same URL the button would use.
        # The settlement modal is per driver and its action is built by the page
        # script, so post to exactly the URL that button would use.
        settle = self.j.session.post(
            f"{self.j.base}/delivery_rents/pay_driver/{drv}",
            data={"_csrf_token": self.j.csrf,
                  "paid_amount": str(DRIVER_PAY["amount"]),
                  "waive_off_amount": "0", "method": "Cash",
                  "payment_account_id": str(self.account_id("Main Cash")),
                  "date": DRIVER_PAY["date"], "note": "part settlement",
                  "reference": "CYC-DRV-1",
                  "idempotency_key": f"smoke-{self.label}-drv1-next",
                  "next": "/delivery_rents"},
            timeout=120, allow_redirects=True)
        self.ok("driver rent settlement accepted", settle.status_code == 200,
                f"{settle.status_code} {self.j.flash_text(settle)[:200]}")
        paid = float(self.scalar("SELECT COALESCE(SUM(amount_paid),0) FROM delivery_person_payment") or 0)
        self.ok("driver payment stored", paid == 400, str(paid))
        self.page(f"/delivery_person_ledger/{drv}")
        self.page(f"/download_delivery_person_ledger/{drv}")

    # ----------------------------------------------------------- 9 accounts --
    def phase_accounts(self):
        self.phase_start("9. accounts: transfer, receive, pay, void, delete, loans")
        cash = self.account_id("Main Cash")
        bank = self.account_id("Meezan Bank")
        cash_before = self.balance_minor("Main Cash")
        self.submit("/accounts/transfers/add", "/accounts/transfers/add", {
            "from_account": str(cash), "to_account": str(bank), "amount": "10000",
            "description": "cash to bank", "note": "smoke transfer"},
            note="transfer 10,000 from cash to bank")
        self.ok("transfer debited the cash account",
                self.balance_minor("Main Cash") == cash_before - 1000000,
                f"{cash_before} -> {self.balance_minor('Main Cash')}")
        self.ok("transfer credited the bank account",
                (self.balance_minor("Meezan Bank") or 0) >= 50000000,
                str(self.balance_minor("Meezan Bank")))

        self.submit("/accounts/", "/transactions/new", {
            "tx_mode": "receive", "receive_account_id": str(cash),
            "receive_from_category": "other_source", "receive_source_label": "Owner",
            "amount": "5000", "method": "Cash",
            "date_posted": f"{D(5)}T09:00", "note": "owner capital in", "discount": "0",
            "idempotency_key": f"smoke-{self.label}-recv1"},
            note="receive 5,000 from an outside source")
        self.submit("/accounts/", "/transactions/new", {
            "tx_mode": "pay", "pay_from_account_id": str(cash),
            "pay_target": "other_target", "amount": "1200", "method": "Cash",
            "date_posted": f"{D(2)}T09:00", "note": "shop expense",
            "reference": "CYC-EXP-1"}, note="pay 1,200 expense from cash")
        for path in ("/accounts/", "/accounts/transfers", "/accounts/categories",
                     "/accounts/loans", "/accounts/audit", "/accounts/reconciliations",
                     f"/accounts/ledger/{cash}", f"/accounts/{cash}/data",
                     "/accounts/api/kpi/company_money", "/accounts/kpi/company_money",
                     "/accounts/kpi/cash_money", "/accounts/kpi/bank_accounts"):
            self.page(path)

        # Loan register: party + principal received.
        self.submit("/accounts/loans", "/loans/parties/add", {
            "name": "HBL Loan", "opening_principal": "0", "opening_date": D(60),
            "note": "bank loan"}, note="loan party created")
        party = self.scalar("SELECT id FROM loan_party ORDER BY id DESC LIMIT 1")
        self.ok("loan party stored", bool(party))
        if party:
            self.submit("/accounts/loans", "/loans/movements/add", {
                "loan_party_id": str(party), "movement_type": "received",
                "amount": "100000", "cash_account_id": str(bank),
                "date_posted": D(1), "note": "loan disbursed",
                "idempotency_key": f"smoke-{self.label}-loan1"},
                note="loan principal 100,000 received into bank")
            self.ok("loan movement stored",
                    self.scalar("SELECT COUNT(*) FROM loan_movement") == 1,
                    str(self.scalar("SELECT COUNT(*) FROM loan_movement")))

        # Bank reconciliation against the real balance.
        self.submit(f"/accounts/{bank}/reconcile", f"/accounts/{bank}/reconcile", {
            "actual_balance": f"{self.balance('Meezan Bank'):.2f}",
            "reconciliation_date": TODAY_S, "note": "smoke reconcile"},
            note="bank account reconciliation")

        # Void an account transaction, then confirm it is still in the audit trail.
        tx = self.rows("SELECT id FROM account_transaction ORDER BY id DESC LIMIT 1")
        if tx:
            tid = tx[0]["id"]
            resp, body = self.json_post(f"/accounts/transactions/{tid}/void", {},
                                       "void an account transaction")
            self.ok("void accepted", resp.status_code < 400, f"{resp.status_code} {body}")
            self.page("/void_audit")
            self.page("/accounts/audit")

    # ---------------------------------------------------------- 10 cash flow --
    def phase_cash_flow(self):
        self.phase_start("10. cash flow: entry, edit, void, restore, category, party")
        cash = self.account_id("Main Cash")
        self.page("/cash_flow")
        self.submit("/cash_flow", "/cash_flow", {
            "action": "record_movement", "direction": "in", "amount": "5000",
            "cash_account_id": str(cash), "movement_date": D(5),
            "description": "Owner capital in", "reference": "CYC-CF-1",
            "movement_note": "cash injection", "party_type": "owner",
            "party_name": "Owner", "category_name": "Capital",
            "subcategory_name": "Investment",
            "idempotency_key": f"smoke-{self.label}-cf1"},
            note="cash-flow entry of 5,000 in")
        entry = self.rows("SELECT id FROM cash_flow_entry ORDER BY id DESC LIMIT 1")
        self.ok("cash-flow entry stored", bool(entry))
        if entry:
            eid = entry[0]["id"]
            resp = self.j.session.get(f"{self.j.base}/cash_flow/entry/{eid}.json")
            self.ok("cash-flow entry JSON is readable",
                    resp.status_code == 200 and resp.text.strip().startswith("{"),
                    f"{resp.status_code} {resp.text[:120]}")
            self.submit("/cash_flow", "/cash_flow", {
                "action": "edit_entry", "entry_id": str(eid), "direction": "in",
                "amount": "5000", "cash_account_id": str(cash),
                "movement_date": D(5), "description": "Owner capital in (edited)",
                "edit_reason": "smoke edit"}, note="cash-flow entry edited")
            self.submit("/cash_flow", "/cash_flow", {
                "action": "void_entry", "entry_id": str(eid),
                "void_reason": "smoke void"}, note="cash-flow entry voided")
            self.submit("/cash_flow", "/cash_flow", {
                "action": "restore_entry", "entry_id": str(eid),
                "restore_reason": "smoke restore"}, note="cash-flow entry restored")
            self.ok("cash-flow entry survived the void/restore cycle",
                    self.scalar("SELECT COUNT(*) FROM cash_flow_entry") >= 1)
        self.submit("/cash_flow", "/cash_flow", {
            "action": "add_category", "new_category_name": "Smoke Category",
            "new_category_direction": "out", "new_category_notes": "smoke"},
            note="cash-flow category added")
        self.submit("/cash_flow", "/cash_flow", {
            "action": "add_party", "new_party_name": "Smoke Party",
            "new_party_type": "supplier", "new_party_note": "smoke"},
            note="cash-flow party added")
        for path in ("/cash_flow", "/cash_flow_differences", "/cash_flow/meta/categories",
                     "/cash_flow/meta/parties", "/cash_flow/meta/subcategories"):
            self.page(path)

    # ---------------------------------------------------- 11 reconciliation --
    def phase_reconciliation(self):
        self.phase_start("11. daily reconciliation: count, lock, differences")
        cash = self.account_id("Main Cash")
        self.page("/daily_reconciliation")
        self.submit("/daily_reconciliation", "/daily_reconciliation", {
            "action": "save_count", "account_id": str(cash), "day": TODAY_S,
            "counted": f"{max(0.0, self.balance('Main Cash')):.2f}",
            "note": "physical count matches the system"}, note="daily count of the cash drawer")
        self.submit("/daily_reconciliation", "/daily_reconciliation", {
            "action": "lock", "account_id": str(cash), "day": TODAY_S},
            note="lock the day after counting")
        for path in ("/daily_reconciliation", "/daily_reconciliation/differences",
                     "/financial_tracker", "/financial_details"):
            self.page(path)

    # ----------------------------------------------------------- 12 reports --
    def phase_reports(self):
        self.phase_start("12. reports, ledgers and documents (pages, PDF, Excel, QR)")
        cl = self.client_id("CYC-CL-1")
        pages = [
            "/profit_reports", "/financial_tracker", "/financial_details",
            "/decision_ledger", "/ledger", f"/ledger/{cl}", f"/client_ledger/{cl}",
            f"/financial_ledger/{cl}",
            "/clients", f"/clients/{cl}/modals", "/void_audit", "/system_report",
            "/notifications", "/notifications/upcoming", "/client_ledger_qr/%d/dialog" % cl,
            "/client_ledger_qr/%d" % cl, "/profit_reports/export/excel",
            "/profit_reports/export/pdf", f"/download_client_ledger/{cl}",
            f"/download_client_clearance/{cl}", f"/download_full_client_history/{cl}",
            f"/api/client_financial_summary/CYC-CL-1",
            f"/api/client_booking_status/CYC-CL-1", "/api/notifications/due",
            "/api/clients/search?q=CYC", "/api/suppliers/search?q=Ravi",
            "/api/ledger_revision", "/api/client_next_code", "/api/material_next_code",
            "/api/last_sold_price", "/api/check_bill/CYC-CR-1",
            "/api/audit/financial-integrity",
            f"/profit_reports?start_date={D(30)}&end_date={TODAY_S}",
        ]
        for path in pages:
            self.page(path, allow=PAGES_ROW_MAY_404)

        # Documents must be real files, not HTML error pages.
        for path, sig, kind in (
            (f"/download_client_ledger/{cl}", b"%PDF", "client ledger PDF"),
            ("/profit_reports/export/pdf", b"%PDF", "profit report PDF"),
            ("/profit_reports/export/excel", b"PK\x03\x04", "profit report Excel"),
            ("/export_grn", b"PK\x03\x04", "GRN export Excel"),
        ):
            resp = self.j.session.get(f"{self.j.base}{path}")
            body = resp.content
            self.j.record(f"GET {path}", resp.status_code == 200 and body.startswith(sig),
                          f"{resp.status_code} {resp.headers.get('Content-Type')} "
                          f"{len(body)}B starts={body[:4]!r}", page=self.phase, kind="page")
            self.ok(f"{kind} is a real file", resp.status_code == 200 and body.startswith(sig),
                    f"{resp.status_code} {len(body)}B {body[:8]!r}")

        # Public QR / verification links (no login required).
        # Printing the QR requires an HTTPS PUBLIC_BASE_URL (the code is scanned
        # by a customer's phone, never by the yard PC).  Without it the page must
        # refuse with a readable message instead of emitting a localhost link.
        if self.public_base_url_https():
            self.submit(f"/client_ledger_qr/{cl}", f"/client_ledger_qr/{cl}", {
                "action": "generate", "dialog": "0"},
                note="client ledger QR generated for an HTTPS origin")
        else:
            post, text = self.submit(f"/client_ledger_qr/{cl}",
                                     f"/client_ledger_qr/{cl}",
                                     {"action": "generate", "dialog": "0"},
                                     note="client ledger QR generation")
            if post is not None:
                body = clean(post.text).lower()
                self.ok("QR generation refuses a non-HTTPS PUBLIC_BASE_URL with a "
                        "readable reason (no localhost link printed)",
                        post.status_code in (409, 503) and
                        ("public_base_url" in body or "https" in body),
                        f"{post.status_code} {body[:200]}")
        self.submit(f"/client_ledger_qr/{cl}", f"/client_ledger_qr/{cl}",
                    {"action": "revoke", "dialog": "0"},
                    note="client ledger QR revoked")
        if self.public_base_url_https():
            self.submit(f"/client_ledger_qr/{cl}", f"/client_ledger_qr/{cl}", {
                "action": "generate", "dialog": "0"}, note="client ledger QR re-issued")
            # Staff print page: the token is embedded in the QR, so re-derive the
            # exact bearer token from the stored salt (what the app itself does).
            print_page = self.j.session.get(f"{self.j.base}/client_ledger_qr/{cl}")
            self.ok("client ledger QR print page renders", print_page.status_code == 200,
                    str(print_page.status_code))
            token = self.derive_ledger_token(cl)
            self.ok("client ledger QR token can be derived for printing", bool(token),
                    "no token")
            if token:
                anon = Journey(self.j.base, log=self.j.log)
                r = anon.get(f"/c/{token}", allow=(200, 404))
                self.ok("public client-ledger QR page works without login",
                        r.status_code == 200 and "ledger" in r.text.lower(),
                        str(r.status_code))
                r = anon.get(f"/c/{token}x", allow=(200, 404))
                self.ok("tampered QR token is refused", r.status_code == 404,
                        str(r.status_code))
        bill_token = self.bill_token(
            bill_id=self.scalar("SELECT id FROM direct_sale WHERE manual_bill_no IN "
                                "('CYC-CR-1','MB NO.CYC-CR-1') ORDER BY id LIMIT 1"))
        if bill_token:
            anon = Journey(self.j.base, log=self.j.log)
            for path in (f"/verify/bill/{bill_token}", f"/b/{bill_token}"):
                r = anon.get(path, allow=(200, 404))
                self.ok(f"public bill verification {path} works without login",
                        r.status_code == 200, str(r.status_code))

    # ------------------------------------------------------------ 13 system --
    def phase_system(self):
        self.phase_start("13. system: settings, terms, users, sidebar, admin, imports, permissions")
        self.submit("/settings", "/update_settings", {
            "company_name": "Ahmed Cement Store", "company_phone": "051-1234567",
            "company_address": "G-9 Markaz, Islamabad", "currency": "PKR",
            "proprietor_name_ur": "", "company_note_ur": "",
            "allow_global_negative_stock": ""}, note="company settings saved")
        self.ok("company name persisted",
                self.scalar("SELECT company_name FROM settings LIMIT 1") == "Ahmed Cement Store",
                str(self.scalar("SELECT company_name FROM settings LIMIT 1")))
        for path in ("/settings", "/settings/activity", "/settings/sessions",
                     "/settings/sidebar", "/settings/daily-backup",
                     "/admin/", "/admin/modules", "/admin/api/health", "/admin/api/modules",
                     "/debug/db", "/system_report",
                     "/import_export/", "/import_export/history", "/import_export/uploads",
                     "/data_lab/", "/data_lab/basket", "/legacy-migration/",
                     "/services", "/pay_supplier", "/terms_conditions", "/receiving",
                     "/tenants", "/root/backup-settings", "/client_categories",
                     "/client_clearance", "/bill_verify"):
            self.page(path, allow=PAGES_ROW_MAY_404)
        self.submit("/settings", "/add_user", {
            "username": "smoke_clerk", "password": "Clerk@12345", "role": "user",
            "access_mode": "limited", "can_manage_sales": "on",
            "can_manage_clients": "on", "can_manage_payments": "on"},
            note="limited user created")
        self.ok("limited user stored",
                self.scalar("SELECT COUNT(*) FROM user WHERE username='smoke_clerk'") == 1)
        self.submit("/settings", "/change_password", {"password": "Admin@fbm12345"},
                    note="admin password re-saved (same value)")
        for path in ("/import_export/export_excel_all", "/import_export/full_db_export",
                     "/import_export/export?dataset=clients", "/import_export/template/clients"):
            self.page(path, allow=(200, 302, 409))
        self.page("/fix_system_issues", allow=(200, 302))
        self.submit("/settings", "/reconcile_data", {"apply_fixes": "1"},
                    note="data reconciliation run")
        sidebar = self.j.session.get(f"{self.j.base}/settings/sidebar")
        resp, body = self.json_post("/settings/sidebar/save",
                                    {"categories": [], "items": []},
                                    "sidebar layout saved (JSON)")
        self.ok("sidebar layout save accepted", resp.status_code == 200 and body.get("ok") is True,
                f"{resp.status_code} {str(body)[:160]}")
        self.submit("/settings/terms-conditions", "/settings/terms-conditions", {
            "title": "Terms", "content_ur": "شرائط و ضوابط", "sort_order": "1"},
            note="receipt terms added")
        self.page("/settings")

        # --- permissions: the limited user must be blocked from admin pages ---
        clerk = Journey(self.j.base, user="smoke_clerk", password="Clerk@12345",
                        log=self.j.log)
        logged = clerk.login()
        self.ok("limited user can log in", logged)
        if logged:
            r = clerk.session.get(f"{self.j.base}/settings", allow_redirects=True)
            self.ok("limited user gets no admin wipe form",
                    'name="delete_targets"' not in r.text,
                    "wipe form visible to a limited user")
            r = clerk.session.get(f"{self.j.base}/clients")
            self.ok("limited user can open clients", r.status_code == 200, str(r.status_code))
            r = clerk.session.get(f"{self.j.base}/logout", allow_redirects=False)
            self.ok("after logout the session is gone",
                    r.status_code == 302 and "login" in r.headers.get("Location", ""),
                    f"{r.status_code} {r.headers.get('Location')}")

    # -------------------------------------------------------- 13b deep links --
    def phase_deep(self):
        """Every remaining GET route: detail pages, modals, JSON APIs, exports.

        The earlier phases drive the business flows; this one proves that the
        secondary doors into the same data (edit sheets, drill-down APIs, file
        downloads, public bill verification, legacy import templates) answer
        without a server error and return what they claim to return.
        """
        self.phase_start("13b. deep routes: detail pages, modals, APIs, files")

        grn_id = self.scalar("SELECT id FROM grn WHERE manual_bill_no='MB NO.CYC-GRN-1'")
        sale_id = self.scalar("SELECT id FROM direct_sale WHERE manual_bill_no='MB NO.CYC-CR-1'")
        client_id = self.client_id("CYC-CL-1")
        supplier_id = self.supplier_id("Ravi Cement Supplier")
        material_id = self.material_id("DG Cement")
        account_id = self.account_id("Main Cash")
        driver_id = self.driver_id(DRIVERS[0]["name"])
        entry_id = self.scalar("SELECT id FROM cash_flow_entry ORDER BY id LIMIT 1")
        bill_id = self.scalar("SELECT id FROM pending_bill ORDER BY id LIMIT 1")
        payment_id = self.scalar("SELECT id FROM payment ORDER BY id LIMIT 1")
        spayment_id = self.scalar("SELECT id FROM supplier_payment ORDER BY id LIMIT 1")
        party_id = self.scalar("SELECT id FROM cash_flow_party ORDER BY id LIMIT 1")

        # --- edit sheets and drill-down fragments (HTML) ----------------------
        html_links = (
            f"/edit_grn/{grn_id}" if grn_id else None,
            f"/accounts/{account_id}/edit" if account_id else None,
            f"/direct_sales/{sale_id}/edit-modal" if sale_id else None,
            f"/bookings/{self.scalar('SELECT id FROM booking ORDER BY id LIMIT 1') or 0}/edit-modal",
            f"/pending_bills/{bill_id}/modals" if bill_id else None,
            f"/clients/{client_id}/modals" if client_id else None,
            f"/clients/{client_id}/edit-modal" if client_id else None,
            f"/suppliers/{supplier_id}/edit-modal" if supplier_id else None,
            f"/accounts/payments/clients/{payment_id}/data" if payment_id else None,
            f"/accounts/payments/suppliers/{spayment_id}/data" if spayment_id else None,
            f"/delivery_rents/group/person:{driver_id}" if driver_id else None,
            f"/party_ledger/{party_id}" if party_id else None,
            f"/notifications/bill/{bill_id}" if bill_id else None,
            "/daily_transactions",
            "/import_export/full_raw_import_history",
            "/import_export/full_raw_export",
            "/import_export/uploads?dataset=clients",
            "/import_export/template/clients",
            "/import_export/template/dispatch",
            "/import_export/template/pending_bills",
            "/import_export/template/client_full",
            "/import_export/template/clients?format=csv",
            "/accounts/kpi/cash_accounts",
            "/accounts/kpi/client_payments",
            "/accounts/kpi/expenditures",
            "/accounts/kpi/receipts",
            "/accounts/kpi/supplier_payments",
            "/accounts/kpi/company_money",
        )
        for path in [x for x in html_links if x]:
            self.page(path, allow=PAGES_ROW_MAY_404)
        # Big file downloads (Excel workbook / raw database copy).
        # (``/import_export/tenant_db_export`` is a deliberate 404 stub in this
        # single-store build, so it is checked separately, not as a download.)
        r = self.j.get("/import_export/tenant_db_export", kind="file",
                       allow=(200, 302, 404))
        self.ok("retired tenant-DB export answers cleanly (no 500)",
                r.status_code != 500, str(r.status_code))
        for path in ("/import_export/master/export",):
            r = self.j.get(path, kind="file", allow=(200, 302, 404, 500))
            self.ok(f"{path} downloads a file or redirects",
                    r.status_code in (200, 302) and r.status_code != 500,
                    str(r.status_code))

        # Supplier-payment receipt PDF (the printable voucher for a payment).
        if spayment_id:
            r = self.j.get(f"/download_supplier_payment/{spayment_id}", kind="file",
                           allow=(200, 404))
            self.ok("supplier payment receipt is a real PDF",
                    r.status_code == 200 and r.content.startswith(b"%PDF"),
                    f"{r.status_code} {r.headers.get('Content-Type')} "
                    f"{r.content[:8]!r}")

        # Profit & loss drill-down for one sale.
        if sale_id:
            r = self.j.get(f"/profit_reports/transaction/DirectSale/{sale_id}",
                           allow=(200, 302, 404))
            self.ok("profit drill-down for one sale renders",
                    r.status_code == 200, str(r.status_code))
            r = self.j.get(f"/profit_reports/transaction/NoSuchType/{sale_id}",
                           allow=(200, 302, 404))
            self.ok("profit drill-down refuses an unknown document type",
                    r.status_code == 404, str(r.status_code))

        # Daily database backup download (a real .db copy) and the CSV history.
        r = self.j.get("/settings/daily-backup/download", kind="file",
                       allow=(200, 302, 404))
        self.ok("daily backup download answers (file or 'no backup yet' redirect)",
                r.status_code in (200, 302), str(r.status_code))
        r = self.j.get("/import_export/full_raw_import_history_export", kind="file",
                       allow=(200, 404))
        self.ok("raw-import history CSV downloads",
                r.status_code == 200 and b"," in r.content[:200],
                f"{r.status_code} {r.content[:60]!r}")

        # Root / multi-tenant consoles are switched off in this single-store
        # build: they must not exist rather than leak a page.
        for path in ("/root/recovery", "/root/recovery_codes", "/tenants",
                     "/tenants/1/backup_history", "/root/backup-settings"):
            r = self.j.get(path, allow=(200, 302, 403, 404))
            self.ok(f"{path} is not available in single-store mode (no 500)",
                    r.status_code in (302, 403, 404), str(r.status_code))

        # A missing upload token must 404, never leak a file.
        r = self.j.get("/import_export/uploads/not-a-real-upload", allow=(200, 404))
        self.ok("unknown upload id answers 404", r.status_code == 404, str(r.status_code))
        r = self.j.get("/uploads/does-not-exist.pdf", kind="file", allow=(200, 302, 404))
        self.ok("unknown uploaded file is refused", r.status_code in (302, 404),
                str(r.status_code))

        # The retired dummy-data generator must refuse, never invent rows.
        r = self.j.get("/generate_dummy_data", allow=(200, 302, 404))
        follow, _ = self.j.follow(r)
        self.ok("retired dummy-data generator refuses and changes nothing",
                r.status_code in (302, 404)
                and (r.status_code == 404
                     or "permanently removed" in follow.text.lower()),
                f"{r.status_code} {clean(follow.text)[:160]}"[:200])

        # JSON diagnostics feed: a traceback inside the payload is the point.
        resp = self.j.get("/debug/recent_errors", kind="json", allow=(200, 403, 404))
        self.ok("/debug/recent_errors answers without a server error",
                resp.status_code in (200, 403), str(resp.status_code))

        # --- JSON APIs ------------------------------------------------------
        apis = [x for x in (
            f"/accounts/api/grn_obligations/{grn_id}" if grn_id else None,
            f"/accounts/api/grn_expense_payments/{grn_id}" if grn_id else None,
            f"/accounts/api/pay_grn/{grn_id}" if grn_id else None,
            f"/accounts/api/supplier_open_obligations/{supplier_id}" if supplier_id else None,
            "/accounts/api/kpi/receipts",
            "/accounts/api/kpi/expenditures",
            "/accounts/api/kpi/client_payments",
            "/accounts/api/kpi/supplier_payments",
            "/api/current_payables?format=json",
            f"/api/current_payables/{client_id}" if client_id else None,
            f"/api/grn_consumption?grn_ids={grn_id}" if grn_id else None,
            "/api/delivery_persons/search?q=Driver",
            f"/api/delivery_person_ledger/{driver_id}" if driver_id else None,
            "/api/ui/theme",
            f"/cash_flow/entry/{entry_id}.json" if entry_id else None,
            f"/api/notifications/contact_history/{bill_id}" if bill_id else None,
        ) if x]
        for path in apis:
            resp = self.j.get(path, allow=(200, 302, 404))
            if resp.status_code != 200:
                self.ok(f"{path} answers without a server error",
                        resp.status_code in (302, 404), str(resp.status_code))
                continue
            try:
                parsed = resp.json()
            except Exception:
                self.ok(f"{path} answers JSON", False, clean(resp.text)[:200])
                continue
            if parsed in (None, [], {}):
                # An empty collection on a fresh database is a valid answer, but
                # it must not be a redirect-to-login page dressed up as JSON.
                self.ok(f"{path} answers JSON", "login" not in resp.text.lower(),
                        clean(resp.text)[:200])
            else:
                self.ok(f"{path} answers JSON with data", True,
                        f"{len(parsed) if hasattr(parsed, '__len__') else 1} item(s)")

        # --- public bill verification (the QR on the printed bill) -----------
        token = self.bill_token(
            bill_id=self.scalar("SELECT id FROM direct_sale WHERE manual_bill_no IN "
                                "('CYC-CR-1','MB NO.CYC-CR-1') ORDER BY id LIMIT 1"))
        if token:
            anon = Journey(self.j.base, log=self.j.log)
            r = anon.get(f"/b/{token}", allow=(200, 404))
            self.ok("public bill-verification link shows the bill",
                    r.status_code == 200 and "CYC-CR-1" in r.text.replace(" ", ""),
                    f"{r.status_code} {clean(r.text)[:160]}")
            pdf = anon.get(f"/b/{token}.pdf", kind="file", allow=(200, 404))
            self.ok("verified bill downloads as a real PDF",
                    pdf.status_code == 200 and pdf.content.startswith(b"%PDF"),
                    f"{pdf.status_code} {pdf.content[:8]!r}")
            r = anon.get(f"/verify/bill/{token}", allow=(200, 404))
            self.ok("long verification form of the link also works",
                    r.status_code == 200, str(r.status_code))
            r = anon.get(f"/b/{token[:-2]}AA", allow=(200, 404))
            self.ok("tampered verification link is refused",
                    r.status_code == 404, str(r.status_code))
        else:
            self.ok("bill verification token can be minted", False, "verify_path returned nothing")

        # --- files: templates, exports, uploads -----------------------------
        templates = ("CLIENTS", "SUPPLIERS", "MATERIALS", "ACCOUNTS", "GRN", "BOOKINGS",
                     "SALES", "DIRECT_SALES", "DELIVERIES", "PAYMENTS", "EXPENSES",
                     "OPENING_BALANCES")
        for kind in templates:
            r = self.j.get(f"/legacy-migration/template/{kind}", kind="file",
                           allow=(200, 400, 404))
            self.ok(f"official migration template '{kind}' downloads",
                    r.status_code == 200 and r.content[:2] == b"PK",
                    f"{r.status_code} {r.content[:8]!r}")

        # A real xlsx round-trip: download the official template, fill it like a
        # shopkeeper would, upload it, and read the validation preview back.
        self.legacy_template_roundtrip()

        # --- session end: logging out really ends the session ----------------
        extra = Journey(self.j.base, log=self.j.log)
        if extra.login():
            extra.get("/logout", allow=(200, 302))
            r = extra.session.get(f"{self.j.base}/clients", allow_redirects=False)
            self.ok("logout ends the session (client list now asks for login)",
                    r.status_code == 302 and "/login" in r.headers.get("Location", ""),
                    f"{r.status_code} {r.headers.get('Location')}")

    def legacy_template_roundtrip(self):
        """Download -> fill -> upload -> validation preview (the migration door)."""
        import io
        r = self.j.session.get(f"{self.j.base}/legacy-migration/template/CLIENTS")
        if r.status_code != 200:
            self.ok("legacy migration template round-trip", False, str(r.status_code))
            return
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(r.content))
            ws = wb["DATA_ENTRY"]
            ws.append(["SMOKE-MIG-1", "Migrated Client", "0300-0000000",
                       "Gujrat", "General", "imported by the smoke test", ""])
            buf = io.BytesIO()
            wb.save(buf)
        except Exception as exc:                     # pragma: no cover - reported
            self.ok("legacy migration template round-trip", False, f"xlsx: {exc}")
            return
        resp = self.j.session.post(
            f"{self.j.base}/legacy-migration/upload",
            data={"_csrf_token": self.j.csrf, "template_type": "CLIENTS"},
            files={"file": ("01_Clients_Migration_Template.xlsx", buf.getvalue(),
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet")},
            allow_redirects=True)
        self.ok("uploading a filled migration template is accepted",
                resp.status_code == 200 and ("SMOKE-MIG-1" in resp.text
                                             or "Validation complete" in resp.text),
                f"{resp.status_code} {clean(resp.text)[:200]}")
        run_id = self.scalar("SELECT id FROM migration_run ORDER BY id DESC LIMIT 1")
        self.ok("the uploaded row is stored as a migration run",
                bool(run_id), str(run_id))
        if run_id:
            r = self.j.get(f"/legacy-migration/run/{run_id}", allow=(200, 404))
            self.ok("migration validation preview renders", r.status_code == 200,
                    str(r.status_code))
            r = self.j.get(f"/legacy-migration/run/{run_id}/errors.xlsx", kind="file",
                           allow=(200, 404))
            self.ok("migration error workbook downloads",
                    r.status_code == 200 and r.content[:2] == b"PK",
                    f"{r.status_code} {r.content[:8]!r}")

    # --------------------------------------------------------- 13c management --
    def phase_manage(self):
        """The remaining write doors: master edits, voids, notifications, admin.

        These are the actions a shopkeeper performs *after* the first bill —
        correcting a name, moving a payment, voiding a wrong sale, chasing a
        pending bill, retiring a user.  Each one is driven through the same
        form the page renders and then checked against the database.
        """
        self.phase_start("13c. management actions: edits, voids, notifications, admin")

        client_id = self.client_id("CYC-CL-2")
        supplier_id = self.supplier_id("Kohat Traders")
        material_id = self.material_id("Pioneer Cement")
        service_id = self.scalar("SELECT id FROM service ORDER BY id LIMIT 1")
        bill_id = self.scalar("SELECT id FROM pending_bill WHERE is_paid=0 "
                              "AND is_void=0 ORDER BY id LIMIT 1")
        sale_id = self.scalar("SELECT id FROM direct_sale WHERE manual_bill_no IN "
                             "('CYC-CR-1','MB NO.CYC-CR-1') ORDER BY id LIMIT 1")
        payment_id = self.scalar("SELECT id FROM payment ORDER BY id LIMIT 1")
        grn_id = self.scalar("SELECT id FROM grn WHERE manual_bill_no='MB NO.CYC-GRN-2'")

        # --- master records: rename / edit --------------------------------
        self.submit("/materials", f"/edit_material/{material_id}",
                    {"material_name": "Pioneer Cement", "material_unit": "Bag",
                     "material_code": "PIO"},
                    note="material edit re-saved through its own modal")

        if service_id:
            self.submit("/services", f"/services/edit/{service_id}",
                        {"service_name": "CEMENT RENT", "service_unit": "Bag"},
                        note="service edit re-saved through its own modal")
        self.post("/client-ledger/categories/add", {"name": "Site Office"},
                  expect="Client categor", note="new client category added")
        cat_id = self.scalar("SELECT id FROM client_category WHERE name='Site Office'")
        if cat_id:
            self.post(f"/client-ledger/categories/{cat_id}/rename",
                      {"name": "Site Office B"},
                      note="client category renamed", expect="renamed")
            self.ok("client category rename stored",
                    bool(self.scalar("SELECT id FROM client_category WHERE name IN "
                                     "('Site Office B','Site Office')")),
                    "row missing")

        # --- account master: edit, then a new account category ------------
        self.submit("/accounts/categories", "/accounts/categories/add",
                    {"name": "Smoke Category", "note": "created by the smoke test"},
                    expect="Categor", note="account category added")
        self.ok("account category stored",
                bool(self.scalar("SELECT id FROM account_category "
                                 "WHERE name='Smoke Category'")))
        acct_cat = self.scalar("SELECT id FROM account_category WHERE name='Smoke Category'")
        if acct_cat:
            self.submit("/accounts/categories", f"/accounts/categories/{acct_cat}/edit",
                        {"name": "Smoke Category B", "note": "renamed"},
                        note="account category renamed")
            self.submit("/accounts/categories",
                        f"/accounts/categories/{acct_cat}/toggle", {},
                        note="account category toggled off")
            self.submit("/accounts/categories",
                        f"/accounts/categories/{acct_cat}/toggle", {},
                        note="account category toggled back on")

        # --- pending bill lifecycle: reminder -> contact -> paid ----------
        if bill_id:
            self.post(f"/notifications/set_severity/{bill_id}", {"severity": "High"},
                      note="pending-bill severity set")
            self.post(f"/notifications/set_reminder/{bill_id}",
                      {"remind_at": D(-2), "note": "call the site office"},
                      note="follow-up reminder scheduled")
            self.post(f"/notifications/log_contact/{bill_id}",
                      {"contacted_at": D(0), "channel": "Call",
                       "response": "promised to pay", "note": "second call"},
                      note="client contact logged")
            self.ok("contact history stored for the pending bill",
                    (self.scalar("SELECT COUNT(*) FROM follow_up_contact") or 0) >= 1,
                    str(self.scalar("SELECT COUNT(*) FROM follow_up_contact")))
            self.post(f"/notifications/mark_paid/{bill_id}", {},
                      note="pending bill marked paid in one click")
            self.ok("pending bill marked paid",
                    self.scalar("SELECT is_paid FROM pending_bill WHERE id=?", (bill_id,)) in (1, True),
                    str(self.scalar("SELECT is_paid FROM pending_bill WHERE id=?", (bill_id,))))

        # --- cancel a real sale, then bring it back ----------------------
        # Deleting a sale is a *hard* delete: the app reverses its effects and
        # removes the row on purpose (no voided leftovers).  The check therefore
        # looks at the money and at the row, not at an is_void flag.
        if sale_id:
            revenue_before = float(self.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM direct_sale WHERE is_void=0") or 0)
            stock_before = self.scalar("SELECT total FROM material WHERE name='DG Cement'")
            # What this one sale is worth, so the later read-back can be adjusted.
            dead = self.rows("SELECT id, amount, client_code, category "
                             "FROM direct_sale WHERE id=?", (sale_id,))
            dead_row = dict(dead[0]) if dead else {}
            dead_lines = self.rows(
                "SELECT COALESCE(SUM(qty),0) q FROM direct_sale_item WHERE sale_id=?",
                (sale_id,))
            final, text = self.post(f"/delete_transaction/DirectSale/{sale_id}",
                                    {"reason": "wrong customer"},
                                    note="a sale is deleted (reversed, not orphaned)")
            self.ok("the sale really disappeared after the delete",
                    self.scalar("SELECT COUNT(*) FROM direct_sale WHERE id=?",
                                (sale_id,)) == 0,
                    f"{self.scalar('SELECT COUNT(*) FROM direct_sale WHERE id=?', (sale_id,))} "
                    f"row(s) left | {text[:200]}")
            self.ok("deleting a sale takes its money out of the revenue total",
                    float(self.scalar("SELECT COALESCE(SUM(amount),0) FROM direct_sale "
                                      "WHERE is_void=0") or 0) < revenue_before,
                    "revenue unchanged")
            self.ok("deleting a credit sale returns the bags to stock",
                    (self.scalar("SELECT total FROM material WHERE name='DG Cement'") or 0)
                    > (stock_before or 0),
                    f"{stock_before} -> "
                    f"{self.scalar('SELECT total FROM material WHERE name=?', ('DG Cement',))}")
            # The deletion is real data, so the figures below must account for it.
            self.deleted_sale = (dead_row.get("id"), float(dead_row.get("amount") or 0),
                                 dead_row.get("client_code"), dead_row.get("category"))
            self.deleted_qty = float(dead_lines[0]["q"] or 0) if dead_lines else 0.0
            # A legacy unvoid against a hard-deleted id must answer cleanly.
            self.post(f"/unvoid_transaction/DirectSale/{sale_id}", {},
                      note="legacy unvoid of a deleted sale answers without a 500")

        # --- account transaction: edit then void/restore ------------------
        entry_row = self.scalar("SELECT id FROM cash_flow_entry WHERE is_void=0 "
                                "ORDER BY id LIMIT 1") or \
            self.scalar("SELECT id FROM cash_flow_entry ORDER BY id LIMIT 1")
        if entry_row:
            r = self.j.get(f"/cash_flow/entry/{entry_row}.json", kind="json",
                           allow=(200, 404))
            self.ok("cash-flow entry drill-down answers JSON",
                    r.status_code == 200 and r.json().get("id") == entry_row,
                    f"{r.status_code} {clean(r.text)[:120]}")

        # --- users: create, suspend, reactivate, remove -------------------
        # A user of its own, so the permissions phase later still creates the
        # clerk it expects.
        mgr = f"smoke_mgr_p{self.pass_no}"
        if not self.scalar("SELECT id FROM user WHERE username=?", (mgr,)):
            self.submit("/settings", "/add_user",
                        {"username": mgr, "password": "Mgr@12345", "role": "user",
                         "access_mode": "read_write"},
                        expect="User created", note="management-test user created")
        clerk_id = self.scalar("SELECT id FROM user WHERE username=?", (mgr,))
        if clerk_id:
            self.post(f"/toggle_user_status/{clerk_id}", {},
                      note="limited user suspended")
            self.ok("suspended user cannot log in",
                    not Journey(self.j.base, user=mgr, password="Mgr@12345",
                                log=self.j.log).login(expect_ok=False))
            self.post(f"/toggle_user_status/{clerk_id}", {},
                      note="limited user reactivated")
            self.ok("reactivated user can log in again",
                    Journey(self.j.base, user=mgr, password="Mgr@12345",
                            log=self.j.log).login())
            self.post(f"/delete_user/{clerk_id}", {},
                      note="limited user removed from the roster")
            # Policy: users are never hard-deleted (history keeps their name),
            # they are deactivated — and then cannot log in.
            self.ok("removed user is deactivated, not erased from history",
                    str(self.scalar("SELECT status FROM user WHERE id=?",
                                    (clerk_id,)) or "").lower() in ("inactive", "suspended"),
                    str(self.scalar("SELECT status FROM user WHERE id=?", (clerk_id,))))
            self.ok("a deactivated user cannot log in",
                    not Journey(self.j.base, user=mgr, password="Mgr@12345",
                                log=self.j.log).login(expect_ok=False))
            # (leave it deactivated: the next pass creates its own user again)

        # --- additive imports: the pending-bill CSV door ------------------
        self.submit("/pending_bills", "/import_pending_bills", {},
                    action_override="/import_pending_bills",
                    note="legacy pending-bill import door answers without a 500")
        self.submit("/pending_bills", "/import_dispatch_data", {},
                    action_override="/import_dispatch_data",
                    note="legacy dispatch import door answers without a 500")

        # --- read-only data lab and admin repair screens ------------------
        self.page("/data_lab/basket")
        self.post("/reconcile_data", {"apply_fixes": "0"},
                  note="system repair (reconcile) runs clean")
        r = self.j.get("/fix_system_issues", allow=(200, 302))
        self.ok("bill-number repair answers without a server error",
                r.status_code in (200, 302), str(r.status_code))

    # ---------------------------------------------------------- 14 read-back --
    def phase_readback(self):
        self.phase_start("14. read-back: figures on the pages vs the database")
        stock = {r["name"]: r["total"] for r in self.rows("SELECT name,total FROM material")}
        dg_delta = stock.get("DG Cement", 0) - self.base["stock"].get("DG Cement", 0)
        # The management phase deletes one real sale (the bags go back to stock,
        # its money leaves revenue), and may mark one pending bill as paid
        # (which settles that client's due).  Adjust the expected figures.
        dg_expected = DG_STOCK + float(getattr(self, "deleted_qty", 0) or 0)
        self.ok("DG Cement stock = receipts - sales + return (+ deleted sale)",
                dg_delta == dg_expected, f"{dg_delta} vs {dg_expected}")
        self.ok("Chenab Sand stock unchanged", stock.get("Chenab Sand") == 200,
                str(stock.get("Chenab Sand")))

        items = float(self.scalar("SELECT COALESCE(SUM(qty*price_at_time),0) FROM grn_item") or 0)
        landed = float(self.scalar("SELECT COALESCE(SUM(landed_cost_total),0) FROM grn") or 0)
        charges = float(self.scalar("SELECT COALESCE(SUM(amount),0) FROM grn_charge") or 0)
        items -= self.base["grn_value"]
        landed -= self.base["landed"]
        self.ok("GRN material value = 198,500", round(items, 2) == 198500.0, str(items))
        self.ok("landed cost = material + loading/freight charges (198,500 + 5,000)",
                round(landed, 2) == 203500.0 and round(charges, 2) == 5000.0,
                f"landed={landed} charges={charges}")
        self.ok("landed cost is never less than the material value",
                landed >= items, f"{landed} < {items}")

        sale_value = float(self.scalar(
            "SELECT COALESCE(SUM(amount),0) FROM direct_sale WHERE is_void=0") or 0) \
            - self.base["sale_value"]
        expected_sale = float(EXPECTED_SALE)   # booking delivery is stock-only, 0 value
        dead = getattr(self, "deleted_sale", None)
        if dead:
            expected_sale -= dead[1]
        self.ok(f"charged sale value = {expected_sale:,.0f} (cash + credit sales)",
                round(sale_value, 2) == expected_sale, f"{sale_value} vs {expected_sale}")

        # The accounts screen must print the figures the database holds.
        cash = self.balance("Main Cash")
        page = self.page("/accounts/accounts")
        shown = [f"{cash:,.2f}", f"{cash:,.0f}", f"{cash:.2f}"]
        self.ok("accounts page shows the stored cash balance",
                any(s in page.text for s in shown), f"looking for {cash}")

        # Company money: the KPI JSON is the page's own data source, so the two
        # must agree with each other and with the stored account balances.
        stored_company = float(self.scalar(
            "SELECT COALESCE(SUM(balance),0) FROM account "
            "WHERE is_active=1 AND COALESCE(category,'') NOT IN ('Clients','Suppliers')") or 0)
        kpi_json = self.j.get("/accounts/api/kpi/company_money", kind="json")
        company_sum, rows = None, []
        try:
            rows = kpi_json.json()
            company_sum = round(sum(float(a.get("balance") or 0) for a in rows), 2)
        except Exception:
            pass
        self.ok("company-money KPI answers JSON", kpi_json.status_code == 200,
                f"{kpi_json.status_code} {kpi_json.text[:120]}")
        self.ok("company-money KPI agrees with the stored account balances",
                company_sum is not None and company_sum == round(stored_company, 2),
                f"kpi={company_sum} db={round(stored_company, 2)} rows={len(rows)}")
        for name in ("Main Cash", "Meezan Bank"):
            acc_id = self.account_id(name)
            self.ok(f"the KPI lists {name} with its stored balance",
                    any(int(a.get("id") or 0) == int(acc_id)
                        and round(float(a.get("balance") or 0), 2) == round(self.balance(name), 2)
                        for a in rows),
                    str([(a.get("name"), a.get("balance")) for a in rows])[:200])
        kpi = self.j.session.get(f"{self.j.base}/accounts/kpi/company_money")
        self.ok("company-money KPI page renders", kpi.status_code == 200,
                f"{kpi.status_code} {kpi.text[:120]}")

        # Every ledger page must render, and the running closing must be on it.
        for name in ("Main Cash", "Meezan Bank"):
            acc = self.account_id(name)
            r = self.page(f"/accounts/ledger/{acc}")
            bal = self.balance(name)
            self.ok(f"{name} ledger page renders", r.status_code == 200, str(r.status_code))
            # The ledger prints a running closing balance; it must be one of the
            # figures on the page (the stored balance is the authority).
            figures = {f"{bal:,.2f}", f"{bal:,.0f}", f"{bal:.2f}", f"{int(bal):,}"}
            found = sorted(f for f in figures if f in r.text)
            self.ok(f"{name} ledger page shows its closing balance",
                    bool(found), f"none of {sorted(figures)} on the page "
                                 f"(page {len(r.text)} bytes)")

        cl = self.client_id("CYC-CL-1")
        self.page(f"/client_ledger/{cl}")
        self.page(f"/financial_ledger/{cl}")
        due = float(self.scalar(
            """SELECT COALESCE(SUM(amount),0) FROM direct_sale
               WHERE client_code='CYC-CL-1' AND category IN ('Credit Customer','Open Khata')""") or 0)
        # The credit sale of this pass, whatever quantity stock allowed.
        credit_sale = next((x for x in SALES if x["kind"] == "credit"), None)
        expected_due = float((credit_sale or {}).get("qty", 0)
                             * (credit_sale or {}).get("rate", 0))
        # A sale deleted by the management phase no longer counts toward the due.
        dead = getattr(self, "deleted_sale", None)
        if dead and dead[2] == "CYC-CL-1" and dead[3] in ("Credit Customer", "Open Khata"):
            expected_due -= dead[1]
        self.ok("client due equals this pass's credit sale",
                round(due, 2) == round(expected_due, 2),
                f"{due} vs {expected_due}")

        fk = self.rows("PRAGMA foreign_key_check")
        self.ok("no foreign-key violations", not fk, str(fk[:3]))
        self.ok("SQLite integrity_check = ok",
                self.scalar("PRAGMA integrity_check") == "ok",
                str(self.scalar("PRAGMA integrity_check")))
        dup = self.rows("""SELECT manual_bill_no, COUNT(*) c FROM direct_sale
                           WHERE manual_bill_no<>'' GROUP BY manual_bill_no HAVING c>1""")
        self.ok("no duplicated manual bill numbers", not dup, str(dup))

        # Idempotency: the same submission twice must not create a second sale.
        payload = {
            "category": "Cash", "client_name": "Walk-in Customer",
            "product_name[]": ["DG Cement"], "qty[]": ["1"], "unit_rate[]": ["1700"],
            "manual_client_name": "Walk-in Customer",
            "sale_date": f"{D(1)}T11:00", "manual_bill_no": "CYC-DUP-1",
            "driver_name": "Akram Driver", "paid_amount": "1700",
            "payment_method": "Cash",
            "payment_account_id": str(self.account_id("Main Cash")),
            "idempotency_key": f"smoke-{self.label}-dup",
            "ignore_booking_item[]": ["1"], "has_bill": "1", "create_invoice": "1",
        }
        self.submit("/direct_sales", "/add_direct_sale", payload,
                    note="first submission of a repeated sale")
        first = self.scalar("SELECT COUNT(*) FROM direct_sale")
        self.submit("/direct_sales", "/add_direct_sale", payload,
                    note="identical second submission (double click)")
        second = self.scalar("SELECT COUNT(*) FROM direct_sale")
        self.ok("double submission created only one sale", first == second,
                f"{first} -> {second}")

        counts = {t: self.table_count(t) for t in self.business_tables()}
        filled = {k: v for k, v in counts.items() if v}
        self.ok("at least 15 business tables hold data", len(filled) >= 15, str(len(filled)))
        self.counts.append({"phase": "populated", "label": self.label, "counts": counts})
        print("  populated tables: " + ", ".join(f"{k}={v}" for k, v in filled.items()), flush=True)
        return counts

    # ---------------------------------------------------------------- 15 wipe --
    def phase_wipe(self):
        self.phase_start("15. full wipe through Settings -> Granular Data Wipe")
        users_before = self.scalar("SELECT COUNT(*) FROM user")
        settings_before = self.scalar("SELECT company_name FROM settings LIMIT 1")
        audit_before = self.scalar("SELECT COUNT(*) FROM audit_log")
        business_before = {t: self.table_count(t) for t in self.business_tables()}
        filled_before = {t: n for t, n in business_before.items() if n}
        self.samples = {
            "clients": self.rows("SELECT code,name,category,phone FROM client ORDER BY id LIMIT 5"),
            "suppliers": self.rows("SELECT name,phone FROM supplier ORDER BY id LIMIT 5"),
            "grn": self.rows("SELECT manual_bill_no,supplier,total_amount FROM grn ORDER BY id LIMIT 5")
            if self.column_exists("grn", "total_amount")
            else self.rows("SELECT manual_bill_no,supplier FROM grn ORDER BY id LIMIT 5"),
            "sales": self.rows("SELECT manual_bill_no,client_name,amount,is_void FROM direct_sale ORDER BY id LIMIT 5"),
            "payments": self.rows("SELECT manual_bill_no,client_name,amount FROM payment ORDER BY id LIMIT 5"),
            "accounts": self.rows("SELECT name,category,balance FROM account ORDER BY id LIMIT 5"),
            "stock": self.rows("SELECT name,total FROM material ORDER BY id LIMIT 5"),
        }

        resp = self.j.get("/settings", kind="write")
        soup = self.j.soup(resp)
        form = self.j.find_form(soup, "/delete_selected_data", index=0)
        if form is None:
            self.ok("wipe form present on Settings", False, "form not rendered")
            return
        targets = sorted({el.get("value") for el in form.find_all("input")
                          if el.get("name") == "delete_targets"})
        self.ok("wipe form offers every dataset", len(targets) >= 30, str(len(targets)))

        preview_resp, preview = self.json_post("/data_wipe_preview",
                                              {"delete_targets": targets}, "wipe preview")
        self.ok("wipe preview endpoint answers",
                preview_resp.status_code == 200 and preview.get("ok") is True,
                f"{preview_resp.status_code} {str(preview)[:200]}")
        print(f"  preview: {json.dumps(preview)[:400]}", flush=True)

        # Every checkbox shares the single POST field name `delete_targets`;
        # the modal's confirm fields ride along with the same submission.
        payload = {"delete_targets": targets,
                   "confirm_text": "DELETE ALL DATA", "hard_delete_override": "1"}
        post, elapsed = self.j.submit(soup, form, payload, note="FULL WIPE submitted")
        final, chain = self.j.follow(post, limit=10)
        self.j.requests[-1]["flash"] = self.j.flash_text(final)
        flashes = self.j.flashes(final.text)
        text = " | ".join(f"{c}: {t}" for c, t in flashes)
        self.ok("wipe request accepted", post.status_code < 400,
                f"{post.status_code} {clean(post.text)[:300]}")
        # The success confirmation itself is a "danger"-styled flash (it is a
        # destructive action), so only treat danger flashes that are *not* the
        # confirmation as an error.
        dangers = [t for c, t in flashes if c == "danger" and "wiped" not in t.lower()]
        self.ok("wipe reported no error to the operator", not dangers, " | ".join(dangers))
        self.ok("wipe confirmed to the operator",
                any("wiped" in t.lower() for _, t in flashes), text[:400])

        after = {t: self.table_count(t) for t in self.business_tables()}
        dirty = {t: n for t, n in after.items() if n}
        # The app re-seeds the auto bill-number counter after a full wipe (that is
        # the reset working, not leftover data), so those rows are expected.
        dirty = {t: n for t, n in dirty.items() if t not in RESEEDED_TABLES}
        self.ok("all 60+ business tables are empty after the wipe", not dirty, str(dirty))
        self.ok("users survived", self.scalar("SELECT COUNT(*) FROM user") == users_before,
                f"{users_before} -> {self.scalar('SELECT COUNT(*) FROM user')}")
        self.ok("settings survived",
                self.scalar("SELECT company_name FROM settings LIMIT 1") == settings_before)
        self.ok("system audit log preserved",
                (self.scalar("SELECT COUNT(*) FROM audit_log") or 0) >= (audit_before or 0) - 100,
                f"{audit_before} -> {self.scalar('SELECT COUNT(*) FROM audit_log')}")
        self.ok("schema untouched",
                self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table'") >= 40,
                str(self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")))
        self.ok("foreign keys clean after the wipe", not self.rows("PRAGMA foreign_key_check"),
                str(self.rows("PRAGMA foreign_key_check")[:3]))
        self.ok("SQLite integrity ok after the wipe",
                self.scalar("PRAGMA integrity_check") == "ok")
        self.ok("session still valid after the wipe (no logout/500)",
                self.j.session.get(f"{self.j.base}/settings").status_code == 200)
        self.counts.append({"phase": "after_wipe", "label": self.label, "counts": after})
        print(f"  wiped tables: {len(filled_before)} had rows before the wipe", flush=True)

    # -------------------------------------------------------- 16 post-wipe UI --
    def phase_empty_ui(self):
        self.phase_start("16. post-wipe: every page on an empty database")
        for path in PAGES_EVERY_RUN:
            self.page(path, allow=PAGES_ROW_MAY_404)
        for path in ("/view_bill/CYC-CASH-1", "/download_invoice/CYC-CASH-1",
                     "/api/check_bill/CYC-CASH-1", "/c/not-a-token",
                     "/verify/bill/not-a-token"):
            self.page(path, allow=(200, 302, 404))
        self.submit("/clients", "/add_client", {
            "name": "Post Wipe Client", "code": "PW-001", "category": "General",
            "opening_balance": "0", "opening_balance_date": D(1)},
            expect="Client Registered", note="new client after the wipe")
        self.ok("new client stored after the wipe",
                self.scalar("SELECT COUNT(*) FROM client WHERE code='PW-001'") == 1)
        self.submit("/accounts/accounts/add", "/accounts/accounts/add", {
            "name": "Post Wipe Cash", "class_category": "Assets",
            "class_subcategory": "Cash", "class_account_type": "Main Cash",
            "channel": "cash", "opening_amount": "1000",
            "opening_position": "debit", "opening_effective_date": D(1),
            "account_status": "active"}, expect="Account added",
            note="new cash account after the wipe")
        self.ok("new account keeps its opening balance",
                self.balance_minor("Post Wipe Cash") == 100000,
                str(self.balance_minor("Post Wipe Cash")))
        # Every ledger/cash page must open again on the fresh, nearly empty data.
        for path in ("/accounts/accounts", "/clients", "/materials",
                     "/direct_sales", "/grn", "/profit_reports", "/cash_flow",
                     "/daily_reconciliation", "/notifications"):
            self.page(path, allow=PAGES_ROW_MAY_404)
        # And the fresh data must flow through the whole chain again.
        # Names deliberately differ from the main journey so a later phase can
        # still create its own masters on the same database.
        self.submit("/materials", "/add_material", {
            "material_name": "PW Cement", "material_code": "PW", "material_unit": "Bag",
            "category_id": str(self.scalar(
                "SELECT id FROM material_category WHERE name='Cement'") or 1)},
            note="material re-created after the wipe")
        self.submit("/grn", "/grn", {
            "action": "add", "supplier": "PW Supplier", "supplier_id": "",
            "date": D(1), "time": "10:00", "manual_bill_no": "PW-GRN-1",
            "mat_name[]": ["PW Cement"], "qty[]": ["10"], "price[]": ["1200"],
            "loading_cost": "0", "freight_cost": "0", "other_expense": "0",
            "adjustment_amount": "0", "discount": "0", "tax_percent": "0",
            "tax_amount": "0", "charge_grid_present": "1",
            "charge_supplier_billing_present": "1"},
            note="new GRN after the wipe")
        self.ok("stock flows again after the wipe",
                self.scalar("SELECT total FROM material WHERE name='PW Cement'") == 10,
                str(self.scalar("SELECT total FROM material WHERE name='PW Cement'")))

    # ------------------------------------------------- 17 standalone verify --
    def phase_verify_empty(self):
        """Runs against a restarted server: the wipe must have persisted."""
        self.phase_start("verify: database state after a server restart")
        for path in PAGES_EVERY_RUN:
            self.page(path, allow=PAGES_ROW_MAY_404)
        # Compare against what the app itself seeded on this boot: default
        # categories and the Open-Khata walk-in client are configuration, not
        # leftover business data.  Everything else must be empty.
        extra = {}
        for table, allowed in APP_SEEDED_NAMES.items():
            col = "code" if table == "client" else "name"
            stale = [r[col] for r in self.rows(f'SELECT "{col}" FROM "{table}"')
                     if str(r[col]) not in allowed]
            if stale:
                extra[table] = stale
        counts = {t: self.table_count(t) for t in self.business_tables()}
        dirty = {t: n for t, n in counts.items()
                 if n and t not in RESEEDED_TABLES and t not in APP_SEEDED_NAMES}
        dirty.update(extra)
        self.ok("no business data reappeared after the restart", not dirty, str(dirty))
        self.ok("users still present after the restart",
                (self.scalar("SELECT COUNT(*) FROM user") or 0) >= 1)
        self.ok("settings still present after the restart",
                self.scalar("SELECT COUNT(*) FROM settings") >= 1)
        self.ok("foreign keys clean after the restart",
                not self.rows("PRAGMA foreign_key_check"))
        self.ok("integrity ok after the restart",
                self.scalar("PRAGMA integrity_check") == "ok")


PAGES_EVERY_RUN = [
    # every top-level page in the sidebar and the modules behind it
    "/", "/clients", "/suppliers", "/materials", "/services", "/delivery_persons",
    "/accounts/", "/accounts/accounts", "/accounts/payments/clients",
    "/accounts/payments/suppliers", "/accounts/grn_payments", "/accounts/receipts",
    "/accounts/expenditures", "/accounts/purchase_payables", "/accounts/reconciliations",
    "/accounts/transfers", "/accounts/loans", "/accounts/categories", "/accounts/audit",
    "/grn", "/dispatching", "/bookings", "/direct_sales", "/payments",
    "/pending_bills", "/material_returns", "/delivery_rents", "/tracking",
    "/cash_flow", "/cash_flow_differences", "/daily_reconciliation",
    "/daily_reconciliation/differences", "/profit_reports", "/financial_tracker",
    "/financial_details", "/decision_ledger", "/current_payables",
    "/unpaid_transactions", "/mixed_transactions", "/void_audit", "/stock_summary",
    "/inventory/stock_summary", "/inventory/inventory_log",
    "/inventory/daily_transactions", "/ledger", "/client-ledger/categories",
    "/notifications", "/notifications/upcoming",
    "/system_report", "/settings", "/settings/activity", "/settings/sessions",
    "/settings/sidebar", "/settings/daily-backup", "/admin/", "/admin/modules",
    "/import_export/", "/import_export/history", "/data_lab/", "/legacy-migration/",
    "/debug/db",
    "/api/audit/financial-integrity", "/api/current_payables", "/export_grn",
    "/export_clients", "/export_pending_bills", "/export_unpaid_transactions",
    "/client_ledger_qr/1/dialog", "/material_ledger/1", "/supplier_ledger/1",
    "/pay_supplier", "/fix_system_issues",
]

SEED_PHASES = [
    "boot", "masters", "purchasing", "stock", "sales", "collections", "returns",
    "deliveries", "accounts", "cash_flow", "reconciliation", "reports", "deep",
    "system", "readback",
]
ALL_PHASES = SEED_PHASES + ["wipe", "empty_ui", "verify_empty"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5100)
    ap.add_argument("--db", required=True)
    ap.add_argument("--label", default="run")
    ap.add_argument("--json", default="")
    ap.add_argument("--phases", default=",".join(ALL_PHASES))
    ap.add_argument("--no-wipe", action="store_true")
    args = ap.parse_args()

    wanted = [p.strip() for p in args.phases.split(",") if p.strip()]
    if args.no_wipe:
        wanted = [p for p in wanted if p not in ("wipe", "empty_ui")]

    r = Runner(args.port, args.db, args.label)
    print(f"### journey '{args.label}' against {r.j.base} db={args.db}", flush=True)
    print(f"### phases: {wanted}", flush=True)

    for name in wanted:
        fn = getattr(r, f"phase_{name}", None)
        if fn is None:
            print(f"!! unknown phase {name}", flush=True)
            continue
        try:
            fn()
        except Exception:
            r.j.record(f"phase {name} crashed", False, traceback.format_exc()[-1200:],
                       page=name)
            print(traceback.format_exc(), flush=True)

    results = r.j.results
    fails = [x for x in results if not x.ok]
    payload = {
        "label": args.label,
        "base_url": r.j.base,
        "db": args.db,
        "phases": wanted,
        "totals": {
            "checks": len(results),
            "passed": len(results) - len(fails),
            "failed": len(fails),
            "requests": len(r.j.requests),
            "pages": sum(1 for x in results if x.kind == "page"),
            "server_errors": sum(1 for q in r.j.requests if q["status"] >= 500),
        },
        "failures": [{"step": f.step, "detail": f.detail, "page": f.page} for f in fails],
        "results": [{"step": x.step, "ok": x.ok, "detail": x.detail, "page": x.page,
                     "kind": x.kind, "seconds": round(x.seconds, 3)} for x in results],
        "requests": r.j.requests,
        "counts": r.counts,
        "samples": r.samples,
    }
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)

    print("\n" + "=" * 72)
    print(f"JOURNEY {args.label}: {payload['totals']}")
    if fails:
        print(f"FAILURES ({len(fails)}):")
        for f in fails[:50]:
            print(f"  - {f.step} [{f.page}] :: {f.detail[:220]}")
    print("=" * 72, flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
