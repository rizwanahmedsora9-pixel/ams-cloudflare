"""Assertions for the full-cycle run.

Each check returns ``(id, label, ok, observed, expected, known_defect)``.
A *known defect* means the check documents a real deviation that is expected to
fail until the code is fixed — it is reported separately and does not turn the
run red.

Numbers come from ``data.EXPECT``; nothing is duplicated.
"""
from __future__ import annotations

from data import EXPECT, PERIOD

# defect ids referenced by checks (see 2.skills/*-defect-register.md)
D_CASHFLOW_SCOPE = "KF-001"
D_RECEIPTS_MISMATCH = "KF-002"
D_ZERO_AMOUNT_BD = "KF-003"
D_FIN_DETAILS_TYPE = "KF-004"
D_CFFORM_MARKUP = "KF-005"
D_STOCK_KPI = "KF-006"
D_MARKUP_HIDDEN = "KF-007"
D_MUTATE_GAP = "KF-008"      # mechanism gap: seed.mutate() is never called


class Results:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, cid: str, label: str, ok: bool, observed, expected,
            known: str | None = None) -> bool:
        self.rows.append({
            "id": cid, "label": label, "ok": bool(ok),
            "observed": str(observed)[:400], "expected": str(expected)[:400],
            "known_defect": known,
        })
        mark = "PASS" if ok else ("KNOWN" if known else "FAIL")
        print(f"  [{mark:5}] {cid} {label}"
              + ("" if ok else f" | got {observed!r} want {expected!r}"))
        return ok

    def near(self, cid, label, observed, expected, tol=0.51, known=None):
        try:
            ok = abs(float(observed) - float(expected)) <= tol
        except (TypeError, ValueError):
            ok = False
        return self.add(cid, label, ok, observed, expected, known)

    def truth(self, cid, label, ok, observed=True, expected=True, known=None):
        return self.add(cid, label, ok, observed, expected, known)

    @property
    def failures(self):
        return [r for r in self.rows if not r["ok"] and not r["known_defect"]]

    @property
    def knowns(self):
        return [r for r in self.rows if not r["ok"] and r["known_defect"]]

    def score(self) -> dict:
        total = len(self.rows)
        known_fail = len(self.knowns)
        hard_fail = len(self.failures)
        passed = total - known_fail - hard_fail
        return {
            "total": total, "passed": passed,
            "known_defects": known_fail, "failures": hard_fail,
            "pass_rate": round(100.0 * passed / total, 2) if total else 0.0,
        }


def number_near(text: str, label: str, value: float, window: int = 90) -> bool:
    """True when ``label`` is followed by ``value`` formatted with separators.

    Accepts both ``8,500.00`` and ``8500.0`` so the check survives a change of
    number format.
    """
    from harness import money

    index = text.find(label)
    if index < 0:
        return False
    window_text = text[index:index + window]
    variants = {
        money(value),                      # 8,500.00
        f"{value:,.0f}",                   # 8,500
        f"{value:.2f}",                    # 8500.00
        f"{value:.0f}",                    # 8500
        str(value),                        # 8500.0
        str(int(value)) if float(value).is_integer() else str(value),
    }
    return any(v in window_text for v in variants)


# ----------------------------------------------------------------------
# Read-only sections.  Each takes (session, db, results) and never writes.
# ----------------------------------------------------------------------
def check_stock(session, db, R: Results) -> None:
    print("\n== stock & inventory ==")
    stock = {row["name"]: row["total"] for row in db.rows("select name,total from material")}
    R.near("S-01", "DG stock", stock.get("DG Cement"), EXPECT["stock_dg"])
    R.near("S-02", "Pioneer stock", stock.get("Pioneer Cement"), EXPECT["stock_pioneer"])
    R.near("S-03", "Sand stock", stock.get("Chenab Sand"), EXPECT["stock_sand"])
    R.near("S-04", "Sheet stock (rent-word trap)", stock.get("TRANSPARENT SHEET"),
           EXPECT["stock_sheet"])

    status, text = session.page(
        f"/inventory/stock_summary?date_from={PERIOD['start']}&date_to={PERIOD['end']}")
    R.truth("S-05", "stock_summary renders", status == 200, status, 200)
    R.truth("S-06", "Total Received 530", number_near(text, "Total Received",
                                                      EXPECT["stock_received"]),
            "see text", EXPECT["stock_received"])
    R.truth("S-07", "Total Delivered 35", number_near(text, "Total Delivered",
                                                      EXPECT["stock_delivered"]),
            "see text", EXPECT["stock_delivered"])
    R.truth("S-08", "Net Movement 495", number_near(text, "Net Movement",
                                                    EXPECT["stock_total"]),
            "see text", EXPECT["stock_total"])

    status, text = session.page(
        f"/tracking?start_date={PERIOD['start']}&end_date={PERIOD['end']}")
    R.truth("S-09", "tracking TOTAL BAGS 495",
            number_near(text, "TOTAL BAGS", EXPECT["stock_total"], window=60),
            "see text", EXPECT["stock_total"])


def check_clients(session, db, R: Results) -> None:
    print("\n== clients ==")
    status, text = session.page("/clients")
    R.truth("C-01", "clients page renders", status == 200, status, 200)
    R.truth("C-02", "Payable (This Page) 20,500",
            number_near(text, "Payable (This Page)", EXPECT["client_net"]),
            "see text", EXPECT["client_net"])

    status, text = session.page("/ledger/2")
    R.truth("C-03", "ledger Total Due 46,500",
            number_near(text, "Total Due (Debit)", EXPECT["client_due"]),
            "see text", EXPECT["client_due"])
    R.truth("C-04", "ledger Total Paid 26,000",
            number_near(text, "Total Paid / Credit", EXPECT["client_paid"]),
            "see text", EXPECT["client_paid"])
    R.truth("C-05", "ledger Net Balance 20,500",
            number_near(text, "Net Balance", EXPECT["client_net"]),
            "see text", EXPECT["client_net"])


def check_suppliers(session, db, R: Results) -> None:
    print("\n== suppliers ==")
    status, text = session.page("/suppliers")
    R.truth("P-01", "suppliers page renders", status == 200, status, 200)
    R.truth("P-02", "Total Purchase 418,500",
            number_near(text, "Total Purchase", EXPECT["purchase_total"]),
            "see text", EXPECT["purchase_total"])
    R.truth("P-03", "Outstanding 338,500",
            number_near(text, "Outstanding", EXPECT["supplier_payable"]),
            "see text", EXPECT["supplier_payable"])

    status, text = session.page("/supplier_ledger/1")
    R.truth("P-04", "Ravi payable 215,500",
            number_near(text, "Closing balance", EXPECT["ravi_payable"]),
            "see text", EXPECT["ravi_payable"])

    status, text = session.page("/accounts/purchase_payables")
    R.truth("P-05", "payables Kohat 123,000",
            number_near(text, "Kohat Traders", EXPECT["kohat_payable"], window=120),
            "see text", EXPECT["kohat_payable"])


def check_accounts(session, db, R: Results) -> None:
    print("\n== accounts ==")
    balances = {row["name"]: row["balance"] for row in db.rows("select name,balance from account")}
    R.near("A-01", "Main Cash balance", balances.get("Main Cash"), EXPECT["cash_closing"])
    R.near("A-02", "Meezan Bank balance", balances.get("Meezan Bank"), EXPECT["bank_closing"])
    R.near("A-03", "company total", sum(balances.values()), EXPECT["company_total"])

    status, text = session.page("/accounts/")
    R.truth("A-04", "accounts dashboard renders", status == 200, status, 200)
    R.truth("A-05", "company KPI 658,500",
            number_near(text, "Total Money Available in Company", EXPECT["company_total"],
                        window=80), "see text", EXPECT["company_total"])

    status, text = session.page("/daily_reconciliation")
    R.truth("A-06", "daily recon expected 658,500",
            number_near(text, "Total Expected Ledger Balance", EXPECT["company_total"],
                        window=80), "see text", EXPECT["company_total"])

    txn = db.scalar("select count(*) from account_transaction where is_void=0")
    R.truth("A-07", "account transactions = 11", int(txn) == 11, txn, 11)


def check_rent(session, db, R: Results) -> None:
    print("\n== delivery rent ==")
    status, text = session.page("/delivery_rents")
    R.truth("R-01", "rent page renders", status == 200, status, 200)
    R.truth("R-02", "rent earned 1,400",
            number_near(text, "Rent earned", EXPECT["rent_earned"]), "see text",
            EXPECT["rent_earned"])
    R.truth("R-03", "rent paid 1,000",
            number_near(text, "Paid", EXPECT["rent_paid"], window=40), "see text",
            EXPECT["rent_paid"])
    R.truth("R-04", "rent remaining 400",
            number_near(text, "Remaining", EXPECT["rent_due"], window=40), "see text",
            EXPECT["rent_due"])

    status, text = session.page("/delivery_person_ledger/1")
    R.truth("R-05", "driver ledger closing 400",
            number_near(text, "Closing balance", EXPECT["rent_due"], window=60),
            "see text", EXPECT["rent_due"])


def check_pnl(session, db, R: Results) -> None:
    print("\n== profit & loss ==")
    status, text = session.page(
        f"/profit_reports?start_date={PERIOD['start']}&end_date={PERIOD['end']}")
    R.truth("L-01", "P&L renders", status == 200, status, 200)
    R.truth("L-02", "Sales 55,000",
            number_near(text, "Sales (Money In)", EXPECT["pl_sales"]), "see text",
            EXPECT["pl_sales"])
    R.truth("L-03", "COGS 43,400",
            number_near(text, "COGS + Direct Service Cost", EXPECT["pl_cogs"]), "see text",
            EXPECT["pl_cogs"])
    R.truth("L-04", "Profit 11,600",
            number_near(text, "Profit (Money Kept)", EXPECT["pl_profit"]), "see text",
            EXPECT["pl_profit"])
    R.truth("L-05", "Money Received 34,500",
            number_near(text, "Money Received", EXPECT["pl_money_received"]), "see text",
            EXPECT["pl_money_received"])
    R.truth("L-06", "margin 21.09%", "21.09" in text, "21.09" in text, True)
    R.truth("L-07", "markup_pct is computed but never rendered (known gap)",
            "26.73" in text, "26.73" in text, True, known=D_MARKUP_HIDDEN)


def check_financial_details(session, db, R: Results) -> None:
    print("\n== financial details ==")
    q = f"start_date={PERIOD['start']}&end_date={PERIOD['end']}"
    status, text = session.page(f"/financial_details?{q}&type=cash")
    R.truth("F-01", "cash detail TOTAL 34,500",
            number_near(text, "TOTAL", EXPECT["pl_money_received"]), "see text",
            EXPECT["pl_money_received"])
    status, text = session.page(f"/financial_details?{q}&type=credit")
    R.truth("F-02", "credit detail TOTAL 31,500",
            number_near(text, "TOTAL", 31_500.0), "see text", 31_500.0)
    status, text = session.page(f"/financial_details?{q}&type=DirectSale")
    R.truth("F-03", "unknown type renders empty TOTAL 0 (known defect)", "TOTAL Rs. 0" in text,
            "TOTAL Rs. 0" in text, False, known=D_FIN_DETAILS_TYPE)


def check_cash_flow(session, db, R: Results) -> None:
    print("\n== cash flow ==")
    q = f"from_date={PERIOD['start']}&to_date={PERIOD['end']}"
    status, text = session.page(f"/cash_flow?{q}")
    R.truth("W-01", "cash flow renders", status == 200, status, 200)
    R.truth("W-02", "opening 200,000",
            number_near(text, "Opening Balance", EXPECT["cf_opening"]), "see text",
            EXPECT["cf_opening"])
    R.truth("W-03", "received 39,500",
            number_near(text, "Total Received", EXPECT["cf_received"]), "see text",
            EXPECT["cf_received"])
    R.truth("W-04", "spent 81,000",
            number_near(text, "Total Spent", EXPECT["cf_spent"]), "see text",
            EXPECT["cf_spent"])
    R.truth("W-05", "closing 158,500 (cash-only opening vs all-account movement)",
            number_near(text, "Closing Balance", EXPECT["cf_closing"]), "see text",
            EXPECT["cf_closing"], known=D_CASHFLOW_SCOPE)

    # The row this reads is written by seed.mutate(), which seed.seed() never
    # calls (see KF-008).  While that is true the observed value is None, so the
    # failure belongs to the mechanism, not to KF-001 — keep the attributions
    # separate or the register slowly loses meaning (SKL-006).
    try:
        row = db.one("select * from cash_flow_difference_adjustment order by id desc limit 1")
    except Exception:
        row = None
    R.near("W-06", "reconciliation difference 17,000",
           (row or {}).get("difference"), EXPECT["cf_recon_difference"],
           known=D_MUTATE_GAP)

    status, html = session.html("/cash_flow")
    has_form = 'id="cfRecordForm"' in html
    R.truth("W-07", "record-movement form present in markup", has_form, has_form, True,
            known=D_CFFORM_MARKUP)


def check_documents(session, db, R: Results) -> None:
    print("\n== documents ==")
    docs = [
        ("D-01", f"/profit_reports/export/pdf?start_date={PERIOD['start']}&end_date={PERIOD['end']}",
         "Profit & Loss", ["55,000", "11,600"]),
        ("D-02", "/download_client_ledger/2", "Total Due", ["46,500", "20,500"]),
        ("D-03", "/download_supplier_ledger/1?scope=full&action=pdf", "SUPPLIER LEDGER",
         ["215,500"]),
        ("D-04", "/download_invoice/SB-SL-1000", "INVOICE", ["8,500"]),
        ("D-05", "/download_client_clearance/2", "Outstanding", ["20,500"]),
    ]
    for cid, path, needle, numbers in docs:
        status, size, text = session.pdf_text(path)
        missing = [n for n in numbers if n not in text]
        has_needle = needle.lower() in text.lower()
        ok = status == 200 and size > 1000 and has_needle and not missing
        detail = (f"missing numbers {missing}" if missing else
                  ("missing title" if not has_needle else "ok"))
        R.truth(cid, f"PDF {path.split('?')[0]} ({size}B) {detail}", ok,
                f"{status} {size}B {detail}", f"200 >1kB {needle} {numbers}")


def check_readonly_pages(session, db, R: Results) -> None:
    print("\n== page availability ==")
    pages = ["/", "/accounts/", "/accounts/accounts", "/accounts/payments/clients",
             "/accounts/payments/suppliers", "/accounts/grn_payments", "/pending_bills",
             "/decision_ledger", "/material_returns", "/grn", "/bookings", "/direct_sales",
             "/delivery_persons", "/materials", "/services", "/client-ledger/categories",
             "/settings", "/admin/", "/void_audit", "/notifications", "/import_export/",
             "/legacy-migration/", "/system_report"]
    for path in pages:
        status, _text = session.page(path)
        # "/" is a landing redirect; everything else must be 200
        want = (200, 302) if path == "/" else (200,)
        R.truth(f"V-{path}", f"GET {path}", status in want, status, want)


DEAD_404 = ["/dashboard", "/journal", "/call_center", "/inventory/history"]


def check_dead_links(session, db, R: Results) -> None:
    print("\n== documented dead links ==")
    for path in DEAD_404:
        status, _text = session.page(path)
        R.truth(f"X-{path}", f"{path} is 404 (documented dead link)", status == 404,
                status, 404)


def check_system_report(session, db, R: Results) -> None:
    print("\n== system report ==")
    status, text = session.page("/system_report")
    R.truth("Y-01", "system report renders", status == 200, status, 200)
    R.truth("Y-02", "missing pending bill for zero-amount delivery (known defect)",
            "CYC-BD-1" in text, "CYC-BD-1" in text, False, known=D_ZERO_AMOUNT_BD)
    R.truth("Y-03", "stock KPI/body disagree (known defect)",
            "No stock discrepancies found" in text, "see text", True,
            known=D_STOCK_KPI)


def check_receipts_mismatch(session, db, R: Results) -> None:
    print("\n== receipts page ==")
    status, text = session.page(
        f"/accounts/receipts?from={PERIOD['start']}&to={PERIOD['end']}")
    R.truth("Q-01", "receipts page renders", status == 200, status, 200)
    R.truth("Q-02", "GRN Paid is 0 despite a 60,000 GRN payment (known defect)",
            number_near(text, "GRN Paid", 0.0), "see text", 0.0,
            known=D_RECEIPTS_MISMATCH)


def check_mechanism(session, db, R: Results) -> None:
    """Assertions about the harness itself, not the app.

    A suite that silently skips a third of its write flows is a suite that
    reports 96% while measuring 86% of what it claims (KF-008).  This check
    flips green the moment ``seed.seed()`` starts calling ``seed.mutate()``;
    delete the ``known=`` flag on that day.
    """
    print("\n== mechanism ==")
    import inspect

    import seed as _seed
    body = inspect.getsource(_seed.seed)
    wired = "mutate(" in body
    phase2 = len([s for s in _seed.STAGES if s["stage"] in (
        "material return", "pending bill", "reconciliation",
        "idempotent replay rejected", "toggle bill paid")])
    R.truth("M-01", "phase-2 write flows reachable from seed.seed()",
            wired, f"phase-2 stages run: {phase2}", "5", known=D_MUTATE_GAP)


# ----------------------------------------------------------------------
def run_all(session, db, R: Results) -> Results:
    check_readonly_pages(session, db, R)
    check_stock(session, db, R)
    check_clients(session, db, R)
    check_suppliers(session, db, R)
    check_accounts(session, db, R)
    check_rent(session, db, R)
    check_pnl(session, db, R)
    check_financial_details(session, db, R)
    check_cash_flow(session, db, R)
    check_documents(session, db, R)
    check_receipts_mismatch(session, db, R)
    check_system_report(session, db, R)
    check_dead_links(session, db, R)
    check_mechanism(session, db, R)
    return R
