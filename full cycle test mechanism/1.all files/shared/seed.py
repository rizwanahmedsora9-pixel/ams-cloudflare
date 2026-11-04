"""Seed the canonical dataset **through the UI**, never with SQL.

Every write in here is an HTTP form post, exactly like a human clicking the
form.  That is deliberate: the point of the full-cycle run is to prove the
*write paths* work, so a seeded row must come from a POST or the run proves
nothing about that endpoint.

Returns a ``Context`` dict with the ids the checks need.
"""
from __future__ import annotations

import json
import os

from data import (BANK_ACCOUNT, BOOKING, CASH_ACCOUNT, CF_CATEGORY, CF_ENTRY,
                  CLIENT, CLIENT_RECEIPTS, DRIVER, DRIVER_PAYMENT,
                  EXTRA_CATEGORIES, GRNS, GRN_PAYMENT, MATERIALS, PENDING_BILL,
                  RECON_DATE, RETURN, SALES, SERVICE, SUPPLIERS, SUPPLIER_PAYMENT)

STAGES = []


def log(stage: str, ok: bool, detail: str = "") -> None:
    STAGES.append({"stage": stage, "ok": bool(ok), "detail": detail})
    print(f"  [{'ok ' if ok else 'FAIL'}] {stage}{(' — ' + detail) if detail else ''}")


def _flash_ok(session, response, needle: str) -> tuple[bool, str]:
    text = session.flash_text(response)
    return (needle.lower() in text.lower()), text[:200]


# ----------------------------------------------------------------------
def seed(session, db, artifact_dir: str | None = None) -> dict:
    ctx: dict = {}

    # ---------------------------------------------------------- suppliers
    print("\n== masters ==")
    for sup in SUPPLIERS:
        r = session.post("/add_supplier", {
            **sup, "opening_balance": "0", "opening_balance_date": "2026-10-01"})
        ok, txt = _flash_ok(session, r, "Supplier Added")
        log(f"supplier {sup['name']}", ok, txt)

    # ------------------------------------------------------- categories
    for cat in EXTRA_CATEGORIES:
        r = session.post("/material_categories/add", {"category_name": cat})
        log(f"category {cat}", *_flash_ok(session, r, "Category added"))

    cat_ids = {row["name"]: row["id"] for row in db.rows("select id,name from material_category")}
    ctx["categories"] = cat_ids

    # -------------------------------------------------------- materials
    for mat in MATERIALS:
        r = session.post("/add_material", {
            "material_name": mat["name"],
            "category_id": str(cat_ids[mat["category"]]),
            "material_unit": mat["unit"],
            "material_code": mat["code"],
        })
        log(f"brand {mat['name']}", *_flash_ok(session, r, "Brand Added"))

    mat_ids = {row["name"]: row["id"] for row in db.rows("select id,name from material")}
    ctx["materials"] = mat_ids
    ctx["material"] = mat_ids

    r = session.post("/services/add", {
        "service_name": SERVICE["name"], "service_unit": SERVICE["unit"],
        "service_code": SERVICE["code"]})
    log(f"service {SERVICE['name']}", *_flash_ok(session, r, "added"))
    ctx["service_id"] = db.scalar("select id from service where name=?", (SERVICE["name"],))

    # ------------------------------------------------------ client+driver
    r = session.post("/add_client", {
        **CLIENT, "opening_balance": "0", "opening_balance_date": "2026-10-01"})
    log(f"client {CLIENT['name']}", *_flash_ok(session, r, "Client Registered"))
    ctx["client_id"] = db.scalar("select id from client where code=?", (CLIENT["code"],))

    r = session.post("/delivery_persons/add", DRIVER)
    log(f"driver {DRIVER['name']}", *_flash_ok(session, r, "Delivery person saved"))
    ctx["driver_id"] = db.scalar("select id from delivery_person where name=?", (DRIVER["name"],))

    # ----------------------------------------------------------- accounts
    for acc in (CASH_ACCOUNT, BANK_ACCOUNT):
        payload = {
            "name": acc["name"], "class_category": acc["cls"],
            "class_subcategory": acc["sub"], "class_account_type": acc["kind"],
            "account_status": "active",
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
        log(f"account {acc['name']}", *_flash_ok(session, r, "Account added"))
    acc_ids = {row["name"]: row["id"] for row in db.rows("select id,name from account")}
    ctx["accounts"] = acc_ids

    # --------------------------------------------------------------- GRN
    print("\n== stock ==")
    for bill, sup_id, sup_name, date, material, qty, price in GRNS:
        r = session.post("/grn", {
            "action": "add", "supplier": sup_name, "supplier_id": str(sup_id),
            "date": date, "time": "09:00", "manual_bill_no": bill,
            "mat_name[]": material, "qty[]": str(qty), "price[]": str(price),
            "allocation_basis_default": "VALUE",
        })
        log(f"GRN {bill} {qty}x{price}", *_flash_ok(session, r, "GRN added"))
    ctx["grn_ids"] = [row["id"] for row in db.rows("select id from grn order by id")]

    # ----------------------------------------------------------- booking
    print("\n== sales ==")
    r = session.post("/add_booking", {
        "client_code": CLIENT["code"], "date": BOOKING["date"],
        "material_name[]": "DG Cement", "material_id[]": str(mat_ids["DG Cement"]),
        "qty[]": str(BOOKING["qty"]), "unit_rate[]": str(BOOKING["rate"]),
        "amount": str(int(BOOKING["qty"] * BOOKING["rate"])),
        "paid_amount": str(int(BOOKING["paid"])),
        "payment_method": "Cash", "payment_account_id": str(acc_ids["Main Cash"]),
        "manual_bill_no": BOOKING["bill"], "note": BOOKING["note"],
    })
    log("booking CYC-BK-1", *_flash_ok(session, r, "Booking added successfully"))
    ctx["booking_id"] = db.scalar("select id from booking")

    # ------------------------------------------------------------- sales
    for sale in SALES:
        payload = {
            "category": sale["category"],
            "has_bill": "on",
            "sale_date": sale["date"],
            "delivery_person_id[]": str(ctx["driver_id"]),
            "delivery_bags[]": str(sale["qty"]),
            "delivery_rent_amount[]": str(int(sale["rent"])),
            "material_id[]": str(mat_ids["DG Cement"]),
            "product_name[]": "DG Cement",
            "qty[]": str(sale["qty"]),
            "unit_rate[]": str(sale["rate"]),
            "ignore_booking_item[]": sale["ignore_booking"],
            "delivery_rent": str(int(sale["rent"])),
            "manual_bill_no": sale["bill"],
            "amount": str(int(sale["amount"])),
            "discount": "0",
            "paid_amount": str(int(sale["paid"])),
            "payment_method": "Cash",
            "payment_account_id": str(acc_ids["Main Cash"]),
            "idempotency_key": sale["idem"],
        }
        if sale["client"]:
            payload["client_code"] = sale["client"]
        else:
            payload["manual_client_name"] = sale["client_name"]
        r = session.post("/add_direct_sale", payload)
        log(f"sale {sale['bill']} {sale['category']}", *_flash_ok(session, r, "Direct sale added"))
    ctx["sale_ids"] = [row["id"] for row in db.rows("select id from direct_sale order by id")]

    # ---------------------------------------------------------- payments
    print("\n== money ==")
    for receipt in CLIENT_RECEIPTS:
        r = session.post("/accounts/payments/clients/save", {
            "client_code": CLIENT["code"],
            "payment_type": "Receipt",
            "amount": str(int(receipt["amount"])),
            "discount": "0",
            "method": receipt["method"],
            "payment_account_id": str(acc_ids[receipt["account"]]),
            "manual_bill_no": receipt["bill"],
            "date": receipt["date"],
            "note": receipt["note"],
            "idempotency_key": receipt["idem"],
        })
        log(f"receipt {receipt['bill']}", *_flash_ok(session, r, "Payment saved"))

    grn_id = ctx["grn_ids"][GRN_PAYMENT["grn_index"]]
    supplier_of_grn = db.scalar("select supplier_id from grn where id=?", (grn_id,))
    r = session.post("/accounts/grn_payments/save", {
        "grn_id": str(grn_id),
        "obligation_key": f"SUPPLIER:{supplier_of_grn}",
        "amount": str(int(GRN_PAYMENT["amount"])),
        "method": GRN_PAYMENT["method"],
        "payment_account_id": str(acc_ids[GRN_PAYMENT["account"]]),
        "date_posted": GRN_PAYMENT["date"],
        "reference": GRN_PAYMENT["reference"],
        "note": "GRN payment",
        "idempotency_key": "cyc-grnpay-1",
    })
    log("GRN payment 60,000", *_flash_ok(session, r, "GRN payment"))

    r = session.post("/accounts/payments/suppliers/save", {
        "supplier_id": str(SUPPLIER_PAYMENT["supplier_id"]),
        "amount": str(int(SUPPLIER_PAYMENT["amount"])),
        "method": SUPPLIER_PAYMENT["method"],
        "payment_account_id": str(acc_ids[SUPPLIER_PAYMENT["account"]]),
        "manual_bill_no": SUPPLIER_PAYMENT["bill"],
        "date": SUPPLIER_PAYMENT["date"],
        "note": SUPPLIER_PAYMENT["note"],
        "idempotency_key": "cyc-suppay-1",
    })
    log("supplier payment 20,000", *_flash_ok(session, r, "Supplier payment"))

    r = session.post(f"/delivery_person_ledger/{ctx['driver_id']}/pay", {
        "paid_amount": str(int(DRIVER_PAYMENT["amount"])),
        "waive_off_amount": "0",
        "method": DRIVER_PAYMENT["method"],
        "payment_account_id": str(acc_ids[DRIVER_PAYMENT["account"]]),
        "date": DRIVER_PAYMENT["date"],
        "reference": DRIVER_PAYMENT["reference"],
        "note": DRIVER_PAYMENT["note"],
        "idempotency_key": DRIVER_PAYMENT["idem"],
    })
    log("driver settlement 1,000", r.status_code == 200, session.flash_text(r)[:140])

    # --------------------------------------------------------- cash flow
    r = session.post("/cash_flow", {
        "action": "add_category",
        "new_category_name": CF_CATEGORY["name"],
        "new_category_direction": CF_CATEGORY["direction"],
    })
    log("cash-flow category", *_flash_ok(session, r, "Category saved"))
    cf_cat_id = db.scalar("select id from cash_flow_category where name=?",
                          (CF_CATEGORY["name"],))

    r = session.post("/cash_flow", {
        "action": "record_movement",
        "direction": CF_ENTRY["direction"],
        "amount": str(int(CF_ENTRY["amount"])),
        "cash_account_id": str(acc_ids[CF_ENTRY["account"]]),
        "category_id": str(cf_cat_id),
        "description": CF_ENTRY["description"],
        "movement_date": CF_ENTRY["date"],
        "reference": CF_ENTRY["reference"],
        "idempotency_key": CF_ENTRY["idem"],
    })
    log("cash-flow entry 5,000", r.status_code == 200, session.flash_text(r)[:160])

    ctx["db_counts"] = db.counts()
    if artifact_dir:
        os.makedirs(artifact_dir, exist_ok=True)
        with open(os.path.join(artifact_dir, "seed-context.json"), "w") as fh:
            json.dump({k: v for k, v in ctx.items() if not isinstance(v, dict) or
                       all(not isinstance(x, dict) for x in v.values())}, fh, indent=1, default=str)
    return ctx


# ----------------------------------------------------------------------
def mutate(session, db, ctx: dict) -> dict:
    """Phase-2 write flows: corrections that change the canonical numbers.

    These run *after* the read-only assertions so the assertions measure the
    clean canonical state that ``full-app-work-test.md`` documents.  Each one
    then gets its own post-mutation check.
    """
    mat_ids = ctx["material"]
    acc_ids = ctx["accounts"]

    # ------------------------------------------------------------ return
    r = session.post("/add_material_return", {
        "return_type": "normal",
        "client_code": RETURN["client"],
        "date": RETURN["date"],
        "material_name[]": RETURN["material"],
        "material_id[]": str(mat_ids[RETURN["material"]]),
        "qty[]": str(RETURN["qty"]),
        "unit_rate[]": str(int(RETURN["rate"])),
        "manual_bill_no": RETURN["bill"],
        "note": RETURN["note"],
    })
    log("material return", *_flash_ok(session, r, "Material return saved"))

    # ----------------------------------------------------- pending bill
    r = session.post("/add_pending_bill", {
        "client_code": PENDING_BILL["client"],
        "bill_no": PENDING_BILL["bill"],
        "amount": str(int(PENDING_BILL["amount"])),
        "reason": PENDING_BILL["reason"],
        "is_manual": "1",
    })
    log("pending bill", r.status_code == 200, session.flash_text(r)[:160])

    # ------------------------------------------------------------- recon
    r = session.post("/cash_flow", {
        "action": "save_reconciliation",
        "from_date": "2026-10-01", "to_date": "2026-10-31",
        "adjustment_date": RECON_DATE,
        "physical_cash_available": "175500",
        "reconciliation_reason": "full-cycle run",
    })
    log("reconciliation", *_flash_ok(session, r, "Reconciliation saved"))

    # ------------------------------------------------- idempotency replays
    r = session.post("/add_direct_sale", {
        "category": "Cash", "manual_client_name": "Walk-in Customer", "has_bill": "on",
        "sale_date": SALES[0]["date"],
        "material_id[]": str(mat_ids["DG Cement"]), "product_name[]": "DG Cement",
        "qty[]": "5", "unit_rate[]": "1700", "ignore_booking_item[]": "1",
        "manual_bill_no": SALES[0]["bill"], "amount": "8500", "paid_amount": "8500",
        "payment_method": "Cash", "payment_account_id": str(acc_ids["Main Cash"]),
        "idempotency_key": SALES[0]["idem"],
    })
    replay_txt = session.flash_text(r).lower()
    log("idempotent replay rejected", ("already" in replay_txt or "duplicate" in replay_txt
                                      or "exists" in replay_txt), session.flash_text(r)[:140])
    ctx["replay_flash"] = session.flash_text(r)[:200]

    # ------------------------------------------------- shift / toggles
    r = session.post("/toggle_bill_paid/1")
    log("toggle bill paid", r.status_code in (200, 302), str(r.status_code))
    session.post("/toggle_bill_paid/1")   # put it back

    ctx["db_counts"] = db.counts()
    return ctx


def summary() -> dict:
    failed = [s for s in STAGES if not s["ok"]]
    return {"total": len(STAGES), "failed": len(failed), "failed_stages": failed}
