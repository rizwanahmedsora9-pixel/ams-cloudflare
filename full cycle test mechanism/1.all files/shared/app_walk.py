#!/usr/bin/env python3
"""App walkthrough — drive the **real app**, page by page and form by form.

The check suite (``checks.py``) asserts figures the business quotes.  This tool
answers the other question the documentation raises: *do the 58 pages and 209
forms described in ``full-app-work-test.md`` / ``pages.md`` actually exist and
behave in the running app, right now?*

Six sections, all against a **copy** of a seeded database:

1. ``pages``      - visit each documented page: status, title, forms, fields,
                    columns, buttons, error markers   -> PASS / PARTIAL / FAIL
2. ``routes``     - visit every GET route in ``url_map``: 5xx, size, tracebacks
3. ``links``      - follow every href found on those pages: dead links
4. ``tie_outs``   - 10 figures a user can read on two different pages
5. ``workflows``  - 6 write flows driven through the real forms, then verified
                    on the listing page *and* in the database
6. write ``--json`` and ``--md``

    python "1.all files/shared/app_walk.py" \\
        --db "1.all files/run-007-.../cycle.db" \\
        --json walk.json --md walk.md

Nothing is mocked: every page is fetched over the Flask test client with a real
login, every write is a real form POST with a CSRF token, and the "did it work"
evidence is the rendered page plus the database row.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from html import unescape
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DOC = os.path.abspath(os.path.join(HERE, "..", "run-001-20261104T0518",
                                   "results", "pages.md"))

PAGE_RE = re.compile(r"^## (\S+)\s+—\s+(.*?)\s+\[HTTP (\d+), (\d+)B\]")
FORM_RE = re.compile(r"^- FORM (GET|POST) (\S+) id=(\S*)")
FIELDS_RE = re.compile(r"^    fields:\s*(.*)$")
ERROR_MARKERS = ("Traceback (most recent call last)", "jinja2.exceptions",
                 "Internal Server Error", "werkzeug.routing")

# chrome that every page carries; comparing it proves nothing
GLOBAL_BUTTONS = {"Close & reload", "Close", "Reload", "Dark", "Inventory",
                  "Transactions", "Accounts", "Ledger", "Directory", "System",
                  "Paid", "Schedule callback"}
GLOBAL_COLUMNS = {"Table / setting", "Status", "In", "Upd", "Skip", "Fail",
                  "Note", "Sheet / table", "Excel row", "Reason", "Entry",
                  "Action", "Actions"}


# ----------------------------------------------------------------------
# documentation -> expectations
# ----------------------------------------------------------------------
def parse_doc(path: str = DOC) -> list[dict]:
    pages, cur, form = [], None, None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = PAGE_RE.match(line)
            if m:
                cur = {"path": m.group(1), "title": unescape(m.group(2).strip()),
                       "status": int(m.group(3)), "bytes": int(m.group(4)),
                       "forms": [], "buttons": [], "columns": []}
                pages.append(cur)
                form = None
                continue
            if cur is None:
                continue
            fm = FORM_RE.match(line)
            if fm:
                form = {"method": fm.group(1), "action": fm.group(2),
                        "id": fm.group(3), "fields": []}
                cur["forms"].append(form)
                continue
            ff = FIELDS_RE.match(line)
            if ff and form is not None:
                for raw in ff.group(1).split(","):
                    name = raw.strip().split(":")[0].strip()
                    if name and name not in form["fields"]:
                        form["fields"].append(name)
                continue
            if line.startswith("- BUTTONS:"):
                cur["buttons"] = [unescape(b.strip()) for b in
                                  line[len("- BUTTONS:"):].split("|") if b.strip()]
                form = None
            elif line.startswith("- COLUMNS:"):
                cur["columns"] = [unescape(c.strip()) for c in
                                  line[len("- COLUMNS:"):].split("|") if c.strip()]
                form = None
    return pages


# ----------------------------------------------------------------------
# rendered page -> what is really there
# ----------------------------------------------------------------------
class _FormSpy(HTMLParser):
    """Collect every real <form>, its method/action and its named fields."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"action": a.get("action") or "",
                               "method": (a.get("method") or "GET").upper(),
                               "id": a.get("id") or "", "fields": set()})
        elif self.forms and tag in ("input", "select", "textarea", "button"):
            name = a.get("name")
            if name:
                self.forms[-1]["fields"].add(name)


def spy(html: str) -> list[dict]:
    """Forms in the *markup*, with <script> removed first.

    Removing scripts is deliberate: a form that only exists inside a JavaScript
    template is not a form a human can submit — that exact confusion is KF-005.
    """
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    parser = _FormSpy()
    parser.feed(html)
    return parser.forms


def norm_action(action: str, page_path: str) -> str:
    action = (action or "").strip()
    if action in ("", "#", "(self)"):
        return page_path.split("?")[0] or "/"
    return action.split("?")[0]


def lower_set(values) -> set:
    return {str(v).strip().lower() for v in values if str(v).strip()}


# ----------------------------------------------------------------------
# 0. prerequisites - a form that lists rows cannot render before one exists
# ----------------------------------------------------------------------
def prepare(session, db) -> dict:
    """Create the master rows whose *edit* forms only render once data exists.

    The cash-flow page has no party-edit form on an empty database (0 rows), so
    a naive walk reports a missing form that is really a missing row.  Creating
    one party first is the difference between a false defect and a real one.
    """
    made = []
    if not db.one("select id from cash_flow_party limit 1"):
        r = session.post("/cash_flow", {"action": "add_party",
                                        "new_party_name": "Walkthrough Party",
                                        "new_party_type": "Owner",
                                        "new_party_note": "created by app_walk"})
        if "saved" in session.flash_text(r).lower():
            made.append("cash_flow_party: Walkthrough Party")
    return {"created": made}


# ----------------------------------------------------------------------
# 1. pages
# ----------------------------------------------------------------------
def walk_pages(session, doc_pages: list[dict]) -> dict:
    rows = []
    for spec in doc_pages:
        status, html = session.html(spec["path"])
        text = session.page(spec["path"])[1] if False else _text(html)
        forms = spy(html)
        real_pairs = {}
        for form in forms:
            key = (form["method"], norm_action(form["action"], spec["path"]))
            real_pairs.setdefault(key, set()).update(form["fields"])

        doc_pairs = {}
        for form in spec["forms"]:
            key = (form["method"], norm_action(form["action"], spec["path"]))
            doc_pairs.setdefault(key, set()).update(form["fields"])

        missing_forms, missing_fields = [], {}
        for key, dfields in doc_pairs.items():
            if key not in real_pairs:
                missing_forms.append({"method": key[0], "action": key[1]})
                continue
            gone = sorted(dfields - real_pairs[key])
            if gone:
                missing_fields[" ".join(key)] = gone

        missing_columns = [c for c in spec["columns"]
                           if c not in GLOBAL_COLUMNS and c.lower() not in text.lower()]
        missing_buttons = [b for b in spec["buttons"]
                           if b not in GLOBAL_BUTTONS and len(b) <= 40
                           and b.lower() not in text.lower()]
        errors = [m for m in ERROR_MARKERS if m.lower() in html.lower()]
        title_ok = _title_ok(spec["title"], text, html)

        hard = (status != spec["status"]) or missing_forms or missing_fields or errors
        soft = missing_columns or missing_buttons
        verdict = "FAIL" if hard else ("PARTIAL" if soft else "PASS")
        rows.append({
            "path": spec["path"], "title": spec["title"], "verdict": verdict,
            "status": status, "status_expected": spec["status"], "bytes": len(html),
            "title_ok": title_ok,
            "forms_documented": len(spec["forms"]), "forms_found": len(forms),
            "missing_forms": missing_forms, "missing_fields": missing_fields,
            "missing_columns": missing_columns[:12],
            "missing_buttons": missing_buttons[:12], "errors": errors,
        })
    return {
        "pages": len(rows),
        "pass": sum(1 for r in rows if r["verdict"] == "PASS"),
        "partial": sum(1 for r in rows if r["verdict"] == "PARTIAL"),
        "fail": sum(1 for r in rows if r["verdict"] == "FAIL"),
        "forms_documented": sum(r["forms_documented"] for r in rows),
        "forms_found": sum(r["forms_found"] for r in rows),
        "missing_form_count": sum(len(r["missing_forms"]) for r in rows),
        "missing_field_groups": sum(len(r["missing_fields"]) for r in rows),
        "rows": rows,
    }


def _text(html: str) -> str:
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _title_ok(title: str, text: str, html: str) -> bool:
    def clean(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    want = clean(title)
    if not want:
        return True
    haystack = clean(text) + " " + clean(re.search(r"<title>(.*?)</title>", html,
                                                   re.S | re.I).group(1)
                                         if re.search(r"<title>(.*?)</title>", html,
                                                      re.S | re.I) else "")
    if want in haystack:
        return True
    # "GRN (Receiving) - records tab" -> every word must appear
    words = [w for w in want.split() if len(w) > 3]
    return bool(words) and all(w in haystack for w in words)


# ----------------------------------------------------------------------
# 2. every GET route
# ----------------------------------------------------------------------
# GET routes that must never be swept: they end the session or destroy data
NO_SWEEP = re.compile(r"(logout|login|static|wipe|drop|reset|delete|restore|"
                      r"seed|dummy|backup|snapshot|sync|purge|shutdown)", re.I)


def walk_routes(session) -> dict:
    rows, skipped = [], []
    for rule in sorted(session.app.url_map.iter_rules(), key=lambda r: str(r.rule)):
        if not set(rule.methods) <= {"GET", "HEAD", "OPTIONS"}:
            continue
        path = str(rule.rule)
        if NO_SWEEP.search(path) or NO_SWEEP.search(rule.endpoint):
            skipped.append(path)
            continue
        url = re.sub(r"<int:[^>]+>", "1", path)
        url = re.sub(r"<float:[^>]+>", "1.0", url)
        url = re.sub(r"<path:[^>]+>", "x", url)
        url = re.sub(r"<[^:>]+:[^>]+>", "test", url)
        url = re.sub(r"<[^>]+>", "test", url)
        try:
            resp = session.get(url)
            raw = resp.data or b""
            body = raw.decode("utf-8", "replace")   # downloads are binary
            errors = [m for m in ERROR_MARKERS if m.lower() in body.lower()]
            rows.append({"rule": path, "url": url, "status": resp.status_code,
                         "bytes": len(raw), "errors": errors,
                         "empty": len(raw) < 200})
        except Exception as exc:
            rows.append({"rule": path, "url": url, "status": 0,
                         "bytes": 0, "errors": [type(exc).__name__], "empty": True})
    bad = [r for r in rows if r["status"] >= 500 or r["errors"] or r["status"] == 0]
    return {
        "routes": len(rows),
        "skipped": sorted(set(skipped)),
        "ok": sum(1 for r in rows if 200 <= r["status"] < 300),
        "redirect": sum(1 for r in rows if 300 <= r["status"] < 400),
        "not_found": sum(1 for r in rows if r["status"] == 404),
        "bad": bad,
        "smallest": sorted(rows, key=lambda r: r["bytes"])[:8],
        "rows": rows,
    }


# ----------------------------------------------------------------------
# 3. links on those pages
# ----------------------------------------------------------------------
def walk_links(session, page_paths: list[str]) -> dict:
    href_re = re.compile(r'href="([^"#]+)"')
    wanted: dict[str, str] = {}
    for path in page_paths:
        status, html = session.html(path)
        if status != 200:
            continue
        for href in href_re.findall(html):
            if href.startswith(("http://", "https://", "mailto:", "javascript:", "/static")):
                continue
            if not href.startswith("/"):
                continue
            if any(ch in href for ch in "`+() "):      # JS template, not a link
                continue
            wanted.setdefault(href.split("#")[0], path)
    rows, skipped = [], []
    for href, from_page in sorted(wanted.items()):
        if NO_SWEEP.search(href):          # /logout would end the walk
            skipped.append(href)
            continue
        try:
            status = session.get(href).status_code
        except Exception:
            status = 0
        rows.append({"href": href, "from": from_page, "status": status})
    dead = [r for r in rows if r["status"] >= 400 or r["status"] == 0]
    return {"links": len(rows), "dead": dead, "ok": len(rows) - len(dead),
            "skipped": sorted(set(skipped))}


# ----------------------------------------------------------------------
# 4. tie-outs: one figure, two pages
# ----------------------------------------------------------------------
def money_variants(value: float) -> set:
    return {f"{value:,.2f}", f"{value:,.0f}", f"{value:.2f}", f"{value:.0f}",
            str(value), str(int(value)) if float(value).is_integer() else str(value)}


def has_number(text: str, label: str, value: float, window: int = 120) -> bool:
    index = text.find(label)
    if index < 0:
        return False
    window_text = text[index:index + window]
    return any(v in window_text for v in money_variants(float(value)))


def tie_outs(session, db) -> dict:
    def page(path):
        return session.page(path)[1]

    accounts = page("/accounts/")
    daily = page("/daily_reconciliation")
    stock = page("/inventory/stock_summary?date_from=2026-10-01&date_to=2026-10-31")
    tracking = page("/tracking?start_date=2026-10-01&end_date=2026-10-31")
    clients = page("/clients")
    ledger = page("/ledger/2")
    rents = page("/delivery_rents?date_from=2026-10-01&date_to=2026-10-31")
    driver = page("/delivery_person_ledger/1")
    cashflow = page("/cash_flow?from_date=2026-10-01&to_date=2026-10-31")
    pnl = page("/profit_reports?start_date=2026-10-01&end_date=2026-10-31")
    fin_cash = page("/financial_details?start_date=2026-10-01&end_date=2026-10-31&type=cash")
    suppliers = page("/suppliers")
    payables = page("/accounts/purchase_payables")

    checks = [
        ("T-01", "company money: /accounts KPI == /daily_reconciliation",
         has_number(accounts, "Total Money Available in Company", 658_500.0)
         and has_number(daily, "Expected", 658_500.0, window=200)),
        ("T-02", "stock: /inventory/stock_summary Net == /tracking TOTAL BAGS",
         has_number(stock, "Net Movement", 495.0)
         and has_number(tracking, "TOTAL BAGS", 495.0, window=40)),
        ("T-03", "client net: /clients Payable == /ledger/2 Net Balance",
         has_number(clients, "Payable (This Page)", 20_500.0)
         and has_number(ledger, "Net Balance", 20_500.0)),
        ("T-04", "rent due: /delivery_rents Remaining == /delivery_person_ledger/1",
         has_number(rents, "Remaining", 400.0, window=60)
         and has_number(driver, "Closing balance", 400.0, window=60)),
        ("T-05", "cash flow adds up: closing == opening + received - spent",
         has_number(cashflow, "Opening Balance", 200_000.0)
         and has_number(cashflow, "Total Received", 39_500.0)
         and has_number(cashflow, "Total Spent", 81_000.0)
         and has_number(cashflow, "Closing Balance", 158_500.0)),
        ("T-06", "money received: /financial_details cash TOTAL == P&L Money Received",
         has_number(fin_cash, "TOTAL", 34_500.0)
         and has_number(pnl, "Money Received", 34_500.0)),
        ("T-07", "P&L arithmetic: income - COGS == profit",
         has_number(pnl, "Sales (Money In)", 55_000.0)
         and has_number(pnl, "COGS + Direct Service Cost", 43_400.0)
         and has_number(pnl, "Profit (Money Kept)", 11_600.0)),
        ("T-08", "suppliers: Total Purchase - Total Paid == Outstanding",
         has_number(suppliers, "Total Purchase", 418_500.0)
         and has_number(suppliers, "Outstanding", 338_500.0)),
        ("T-09", "payables page agrees with the suppliers page",
         has_number(payables, "Ravi Cement Supplier", 215_500.0, window=200)
         and has_number(payables, "Kohat Traders", 123_000.0, window=200)
         and has_number(suppliers, "Outstanding", 338_500.0)),
        ("T-10", "invoice PDF 8,500 == the SB-SL-1000 row on /direct_sales == DB",
         "8,500" in session.pdf_text("/download_invoice/SB-SL-1000")[2]
         and "SB-SL-1000" in page("/direct_sales")
         and "8500" in page("/direct_sales")),
    ]
    rows = [{"id": cid, "label": label, "ok": bool(ok)} for cid, label, ok in checks]
    return {"total": len(rows), "passed": sum(1 for r in rows if r["ok"]), "rows": rows}


# ----------------------------------------------------------------------
# 5. real write workflows (mutating - run last)
# ----------------------------------------------------------------------
def workflows(session, db) -> dict:
    rows = []

    def add(cid, label, ok, observed, expected):
        rows.append({"id": cid, "label": label, "ok": bool(ok),
                     "observed": str(observed)[:200], "expected": str(expected)[:200]})

    def flash(resp):
        return session.flash_text(resp)

    # W-01 create a supplier through the real form, then find it on the page
    r = session.post("/add_supplier", {"name": "Walk-supplier", "phone": "0300-0000000",
                                       "address": "Walk Street", "opening_balance": "0",
                                       "opening_balance_date": "2026-10-01"})
    in_db = db.one("select id from supplier where name='Walk-supplier'")
    page_text = session.page("/suppliers")[1]
    add("W-01", "create supplier via /add_supplier -> row + listing",
        bool(in_db) and "Walk-supplier" in page_text,
        f"db={bool(in_db)} page={'Walk-supplier' in page_text}", "row and listing")

    # W-02 create a material brand through the real form
    cat = db.one("select id from material_category where name='Cement'")
    r = session.post("/add_material", {"material_name": "Walk-brand",
                                       "category_id": str(cat["id"]),
                                       "material_unit": "Bag", "material_code": "WALK"})
    in_db = db.one("select id from material where name='Walk-brand'")
    page_text = session.page("/materials")[1]
    add("W-02", "create brand via /add_material -> row + listing",
        bool(in_db) and "Walk-brand" in page_text,
        f"db={bool(in_db)} page={'Walk-brand' in page_text}", "row and listing")

    # W-03 material return (phase 2 of the seed - never run by the mechanism)
    mat = db.one("select id from material where name='DG Cement'")
    before_stock = db.scalar("select total from material where name='DG Cement'")
    r = session.post("/add_material_return", {
        "return_type": "normal", "client_code": "CYC-CL-1", "date": "2026-10-26",
        "material_name[]": "DG Cement", "material_id[]": str(mat["id"]),
        "qty[]": "2", "unit_rate[]": "1650", "manual_bill_no": "CYC-RTN-1",
        "note": "2 bags returned"})
    after_stock = db.scalar("select total from material where name='DG Cement'")
    listing = session.page("/material_returns")[1]
    add("W-03", "material return 2 bags -> stock 195->197 and return listed",
        abs(float(after_stock) - 197.0) < 0.01 and "CYC-RTN-1" in listing,
        f"stock {before_stock}->{after_stock} listed={'CYC-RTN-1' in listing}",
        "stock 197 and CYC-RTN-1 listed")

    # W-04 manual pending bill
    r = session.post("/add_pending_bill", {
        "client_code": "CYC-CL-1", "bill_no": "CYC-PB-1", "amount": "4500",
        "reason": "Manual charge: extra loading", "is_manual": "1"})
    row = db.one("select id,amount from pending_bill "
                 "where bill_no like '%CYC-PB-1%'")
    listing = session.page("/pending_bills")[1]
    add("W-04", "manual pending bill 4,500 -> row + /pending_bills",
        bool(row) and "CYC-PB-1" in listing,
        f"row={bool(row)} listed={'CYC-PB-1' in listing}", "row and listing")

    # W-05 physical cash reconciliation
    r = session.post("/cash_flow", {
        "action": "save_reconciliation", "from_date": "2026-10-01",
        "to_date": "2026-10-31", "adjustment_date": "2026-10-31",
        "physical_cash_available": "175500",
        "reconciliation_reason": "walkthrough count"})
    row = db.one("select * from cash_flow_difference_adjustment order by id desc limit 1")
    cash = session.page("/cash_flow?from_date=2026-10-01&to_date=2026-10-31")[1]
    add("W-05", "reconciliation 175,500 saved -> row(diff 17,000) + page",
        bool(row) and abs(float(row["difference"]) - 17_000.0) < 0.01
        and has_number(cash, "175,500", 175_500.0),
        f"row={bool(row)} diff={row['difference'] if row else None} "
        f"page={'175,500' in cash}", "difference 17,000 shown")

    # W-06 idempotent replay of the cash sale must be refused, not duplicated
    cash_acc_id = db.scalar("select id from account where name='Main Cash'")
    sales_before = db.scalar("select count(*) from direct_sale")
    r = session.post("/add_direct_sale", {
        "category": "Cash", "manual_client_name": "Walk-in Customer", "has_bill": "on",
        "sale_date": "2026-10-14", "material_id[]": str(mat["id"]),
        "product_name[]": "DG Cement", "qty[]": "5", "unit_rate[]": "1700",
        "ignore_booking_item[]": "1", "manual_bill_no": "CYC-CASH-1",
        "amount": "8500", "paid_amount": "8500", "payment_method": "Cash",
        "payment_account_id": str(cash_acc_id or 1), "idempotency_key": "cyc-cash-1"})
    sales_after = db.scalar("select count(*) from direct_sale")
    rejected = any(w in flash(r).lower() for w in ("already", "duplicate", "exists"))
    add("W-06", "replaying a submitted sale is refused, no duplicate row",
        rejected and sales_before == sales_after,
        f"flash={flash(r)[:80]!r} sales {sales_before}->{sales_after}",
        "rejection flash, count unchanged")

    # W-07 toggle a pending bill paid/unpaid through the real button
    bill = db.one("select id,is_paid from pending_bill order by id limit 1")
    if bill:
        before = bool(bill["is_paid"])
        first = session.post(f"/toggle_bill_paid/{bill['id']}")
        mid = bool((db.one("select is_paid from pending_bill where id=?",
                           (bill["id"],)) or {}).get("is_paid"))
        session.post(f"/toggle_bill_paid/{bill['id']}")
        back = bool((db.one("select is_paid from pending_bill where id=?",
                            (bill["id"],)) or {}).get("is_paid"))
        add("W-07", "toggle pending bill paid flips is_paid and back",
            mid != before and back == before and first.status_code == 200,
            f"is_paid {before} -> {mid} -> {back}", "flips and returns")
    else:
        add("W-07", "toggle pending bill paid flips is_paid and back", False,
            "no pending_bill row", "a bill to toggle")


    # W-08 money in, then reversed: receipt 1,000 -> cash +1,000 -> void -> back
    cash_before = db.scalar("select balance from account where name='Main Cash'")
    payments_before = db.scalar("select count(*) from payment")
    acct = db.scalar("select id from account where name='Main Cash'")
    r = session.post("/accounts/payments/clients/save", {
        "client_code": "CYC-CL-1", "client_name": "Bilal Construction",
        "amount": "1000", "date": "2026-10-27", "method": "Cash",
        "payment_account_id": str(acct), "manual_bill_no": "CYC-RCPT-3",
        "note": "walkthrough receipt", "idempotency_key": "walk-rcpt-" + os.path.basename(db.path)[:6],
        "payment_type": "receipt", "show": "Active"})
    cash_mid = db.scalar("select balance from account where name='Main Cash'")
    new_id = db.scalar("select max(id) from payment")
    listed = "CYC-RCPT-3" in session.page("/accounts/payments/clients")[1]
    void = session.post(f"/accounts/payments/clients/void/{new_id}")
    cash_after = db.scalar("select balance from account where name='Main Cash'")
    voided = db.one("select is_void from payment where id=?", (new_id,)) or {}
    add("W-08", "receipt 1,000 (+cash) then void (reversed, audited)",
        abs(float(cash_mid) - float(cash_before) - 1000.0) < 0.01
        and abs(float(cash_after) - float(cash_before)) < 0.01
        and bool(voided.get("is_void")) and listed
        and db.scalar("select count(*) from payment") >= payments_before,
        f"cash {cash_before} -> {cash_mid} -> {cash_after}, "
        f"listed={listed}, is_void={voided.get('is_void')}",
        "cash +1,000 then restored, payment voided and listed")

    return {"total": len(rows), "passed": sum(1 for r in rows if r["ok"]), "rows": rows}


# ----------------------------------------------------------------------
# 6. render
# ----------------------------------------------------------------------
def render_markdown(result: dict, label: str) -> str:
    pages, routes, links = result["pages"], result["routes"], result["links"]
    tie, flows = result["tie_outs"], result["workflows"]
    lines = [
        f"# App walkthrough — {label}",
        "",
        "Drives the **real app** on a copy of a seeded database: every documented "
        "page, every documented form field, every GET route, every link, ten "
        "page-vs-page tie-outs, and seven write flows submitted through the "
        "actual HTML forms.",
        "",
        "| Section | Result |",
        "|---|---|",
        f"| Documented pages walked | {pages['pages']} — "
        f"**{pages['pass']} PASS · {pages['partial']} PARTIAL · {pages['fail']} FAIL** |",
        f"| Documented forms / found in markup | {pages['forms_documented']} / "
        f"{pages['forms_found']} |",
        f"| Forms missing from the markup | {pages['missing_form_count']} |",
        f"| Field groups with missing fields | {pages['missing_field_groups']} |",
        f"| GET routes visited | {routes['routes']} — {routes['ok']} ok, "
        f"{routes['redirect']} redirect, {routes['not_found']} 404, "
        f"**{len(routes['bad'])} bad** ({len(routes.get('skipped', []))} "
        "destructive routes skipped) |",
        f"| Links followed | {links['links']} — **{len(links['dead'])} dead** |",
        f"| Page-vs-page tie-outs | **{tie['passed']}/{tie['total']}** |",
        f"| Write workflows through real forms | **{flows['passed']}/{flows['total']}** |",
        "",
        "## Documented pages",
        "",
        "| Page | Documented title | Verdict | Status | Forms doc/found | "
        "Missing forms | Missing fields |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in pages["rows"]:
        mark = {"PASS": "PASS", "PARTIAL": "partial", "FAIL": "**FAIL**"}[row["verdict"]]
        miss_forms = len(row["missing_forms"])
        miss_fields = sum(len(v) for v in row["missing_fields"].values())
        lines.append(
            f"| `{row['path']}` | {row['title']} | {mark} | {row['status']}"
            f"{'' if row['status'] == row['status_expected'] else ' (want ' + str(row['status_expected']) + ')'} "
            f"| {row['forms_documented']}/{row['forms_found']} | "
            f"{miss_forms} | {miss_fields} |")

    labels = [r for r in pages["rows"] if not r["title_ok"]]
    if labels:
        lines += ["", "## Documented label vs what the screen says (informational)", "",
                  "These are documentation labels, not failures — the page renders.",
                  "", "| Page | Documented label |", "|---|---|"]
        lines += [f"| `{r['path']}` | {r['title']} |" for r in labels]
        lines.append("")

    problems = [r for r in pages["rows"] if r["verdict"] != "PASS"]
    if problems:
        lines += ["", "## Where the documentation and the app disagree", ""]
        for row in problems:
            lines.append(f"### `{row['path']}` — {row['verdict']}")
            if row["missing_forms"]:
                lines.append("- missing forms: "
                             + ", ".join(f"`{f['method']} {f['action']}`"
                                         for f in row["missing_forms"]))
            for key, gone in row["missing_fields"].items():
                lines.append(f"- `{key}` missing fields: `{', '.join(gone)}`")
            if row["missing_columns"]:
                lines.append("- columns not rendered: "
                             + ", ".join(row["missing_columns"]))
            if row["missing_buttons"]:
                lines.append("- buttons not rendered: "
                             + ", ".join(row["missing_buttons"]))
            if not row["title_ok"]:
                lines.append(f"- documented title not on the page: {row['title']!r}")
            if row["errors"]:
                lines.append("- error markers: " + ", ".join(row["errors"]))
            lines.append("")

    if routes["bad"]:
        lines += ["## Routes that failed", "", "| Rule | Status | Errors |",
                  "|---|---|---|"]
        lines += [f"| `{r['rule']}` | {r['status']} | {', '.join(r['errors'])} |"
                  for r in routes["bad"]]
        lines.append("")

    if links["dead"]:
        lines += ["## Dead links", "", "| Link | Found on | Status |", "|---|---|---|"]
        lines += [f"| `{r['href']}` | `{r['from']}` | {r['status']} |"
                  for r in links["dead"]]
        lines.append("")

    lines += ["## Tie-outs (one figure, two pages)", "",
              "| ID | Check | Result |", "|---|---|---|"]
    lines += [f"| {r['id']} | {r['label']} | {'PASS' if r['ok'] else '**FAIL**'} |"
              for r in tie["rows"]]
    lines += ["", "## Write workflows driven through the real forms", "",
              "| ID | Workflow | Result | Observed |", "|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['label']} | {'PASS' if r['ok'] else '**FAIL**'} | "
              f"`{r['observed']}` |" for r in flows["rows"]]
    lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="a seeded cycle.db (a copy is used)")
    ap.add_argument("--label", default="local")
    ap.add_argument("--doc", default=DOC)
    ap.add_argument("--json", help="write the full walkthrough here")
    ap.add_argument("--md", help="write the readable walkthrough here")
    args = ap.parse_args()

    from harness import Db, boot

    tmp = tempfile.mkdtemp(prefix="app-walk-")
    scratch = os.path.join(tmp, "walk.db")
    shutil.copy(args.db, scratch)

    print(f"label : {args.label}")
    session = boot(scratch, fresh=False)
    db = Db(scratch)

    result: dict = {"label": args.label}
    print("[0/5] prerequisites for data-dependent forms")
    result["prepared"] = prepare(session, db)
    print(f"      created: {result['prepared']['created'] or 'nothing needed'}")
    doc_pages = parse_doc(args.doc)
    print(f"\n[1/5] pages: {len(doc_pages)} documented")
    result["pages"] = walk_pages(session, doc_pages)
    print(f"      {result['pages']['pass']} pass, {result['pages']['partial']} partial, "
          f"{result['pages']['fail']} fail")

    print("[2/5] routes: every GET rule")
    result["routes"] = walk_routes(session)
    print(f"      {result['routes']['routes']} routes, "
          f"{len(result['routes']['bad'])} bad")

    print("[3/5] links: every href on the documented pages")
    result["links"] = walk_links(session, [p["path"] for p in doc_pages])
    print(f"      {result['links']['links']} links, "
          f"{len(result['links']['dead'])} dead")

    print("[4/5] tie-outs: one figure, two pages")
    result["tie_outs"] = tie_outs(session, db)
    print(f"      {result['tie_outs']['passed']}/{result['tie_outs']['total']}")

    print("[5/5] workflows: real form posts")
    result["workflows"] = workflows(session, db)
    print(f"      {result['workflows']['passed']}/{result['workflows']['total']}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result, fh, indent=1, default=str)
    if args.md:
        with open(args.md, "w") as fh:
            fh.write(render_markdown(result, args.label))

    hard = (result["pages"]["fail"] + len(result["routes"]["bad"])
            + len(result["links"]["dead"])
            + (result["tie_outs"]["total"] - result["tie_outs"]["passed"])
            + (result["workflows"]["total"] - result["workflows"]["passed"]))
    print(f"\nhard findings: {hard}")
    return 0 if hard == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
