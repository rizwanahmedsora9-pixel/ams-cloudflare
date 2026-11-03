"""Purchase -> landed charges -> Accounts settlement -> customer sale -> P&L.

All business documents in this test go through the real HTTP routes and use a
fresh database.  The supplier's material debt, each cost payee, stock, COGS,
profit, report HTML and Excel must agree without counting a settlement twice.
"""
from __future__ import annotations

from io import BytesIO
import re

import pytest
from openpyxl import load_workbook

from app.services.financial_ledgers import build_supplier_financial_ledger
from app.services.grn_consumption import build_grn_consumption
from app.services.grn_costing import grn_breakdown
from app.services.profit_loss import build_profit_loss_report
from app.services.profit_loss_exports import build_profit_loss_excel
from models import (
    Account, AccountTransaction, Client, DirectSale, GRN, GRNAllocation,
    Material, Supplier, SupplierPayment, db,
)
from tests.conftest import make_csrf_client

START, END = "2026-10-01", "2026-11-30"


@pytest.fixture()
def shop(app_factory, tmp_path):
    app = app_factory(tmp_path / "landed-e2e.db", AUTO_RECONCILE_ENABLED="0")
    app.config["TESTING"] = True
    client = make_csrf_client(app)
    assert client.post("/login", data={
        "username": "Admin", "password": "Admin@fbm12345",
    }).status_code in (302, 303)
    return app, client


def seed(client):
    for url, data, expected in [
        ("/add_supplier", {"name": "Cement Supplier"}, "Supplier Added"),
        ("/add_client", {"name": "Client One", "code": "E2E-1", "category": "Credit Customer"}, "Client Registered"),
        ("/add_material", {"material_name": "Cement", "material_unit": "Bags"}, "Brand Added"),
    ]:
        response = client.post(url, data=data, follow_redirects=True)
        assert expected in response.get_data(as_text=True), (url, response.get_data(as_text=True)[:1000])
    response = client.post("/accounts/accounts/add", data={
        "name": "E2E Cash", "class_category": "Assets",
        "class_subcategory": "Cash", "class_account_type": "Main Cash",
        "account_status": "active", "opening_amount": "500000",
        "opening_position": "debit", "opening_effective_date": START,
    }, follow_redirects=True)
    assert response.status_code == 200


def receive(client, *, bill="E2E-GRN", date="2026-10-20", qty=100, rate=1500,
            charges=None, edit_id=None, include_charges_in_supplier=False):
    charges = charges if charges is not None else [
        ("VEHICLE_FARE", "Vehicle rent", 5000, "TRANSPORTER", "Transport Person"),
        ("LOADING", "Loading", 1000, "LABOUR", "Loading Team"),
        ("UNLOADING", "Unloading", 500, "LABOUR", "Unloading Team"),
    ]
    data = {
        "action": "add", "supplier": "Cement Supplier", "supplier_id": "1",
        "date": date, "time": "09:00", "manual_bill_no": bill,
        "mat_name[]": ["Cement"], "qty[]": [str(qty)], "price[]": [str(rate)],
        "allocation_basis_default": "VALUE", "charge_grid_present": "1",
        "charge_id[]": ["" for _ in charges],
        "charge_type[]": [c[0] for c in charges],
        "charge_label[]": [c[1] for c in charges],
        "charge_amount[]": [str(c[2]) for c in charges],
        "charge_recipient_type[]": [c[3] for c in charges],
        "charge_recipient[]": [c[4] for c in charges],
        "charge_treatment[]": [c[5] if len(c) > 5 else "INVENTORY" for c in charges],
        "charge_basis[]": ["VALUE" for _ in charges],
        "charge_status[]": [c[6] if len(c) > 6 else "UNPAID" for c in charges],
    }
    if include_charges_in_supplier:
        data["include_charges_in_supplier"] = "1"
    url = f"/edit_grn/{edit_id}" if edit_id else "/grn"
    if edit_id:
        data.update({"grn_item_id[]": [str(edit_id)]})
        # The edit form uses the existing line id, not a new stock line.
        with_items = GRNItemIds(client.application, edit_id)
        data["grn_item_id[]"] = [str(i) for i in with_items]
        from models import GRNCharge
        with client.application.app_context():
            charge_ids = [c.id for c in GRNCharge.query.filter_by(grn_id=edit_id, is_void=False).order_by(GRNCharge.id).all()]
        data["charge_id[]"] = [str(charge_ids[i]) if i < len(charge_ids) else "" for i in range(len(charges))]
    response = client.post(url, data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b"already has payments" not in response.data
    return response


def GRNItemIds(app, grn_id):
    from models import GRNItem
    with app.app_context():
        return [i.id for i in GRNItem.query.filter_by(grn_id=grn_id).order_by(GRNItem.id).all()]


def sell(client, *, qty=40, rate=1800, bill="E2E-SALE", date="2026-11-03", category="Credit Customer"):
    response = client.post("/add_direct_sale", data={
        "client_name": "Client One", "client_code": "E2E-1",
        "driver_name": "E2E Driver", "category": category,
        "product_name[]": ["Cement"], "qty[]": [str(qty)],
        "unit_rate[]": [str(rate)], "paid_amount": "0",
        "manual_bill_no": bill, "sale_date": date,
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Sale added successfully" in response.data or b"successfully" in response.data


def pay_obligations(client, grn_id):
    with client.application.app_context():
        obligations = grn_breakdown(db.session.get(GRN, grn_id))["obligations"]
        account = Account.query.filter_by(name="E2E Cash").one()
        account_id = account.id
    for obligation in obligations:
        response = client.post("/accounts/grn_payments/save", data={
            "grn_id": str(grn_id), "obligation_key": obligation["key"],
            "amount": str(obligation["remaining"]), "method": "Cash",
            "payment_account_id": str(account_id), "date_posted": "2026-11-03",
            "reference": f"PAY-{obligation['key']}",
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b"GRN payment" in response.data


def report(app, **filters):
    with app.app_context():
        return build_profit_loss_report(start_date=START, end_date=END, **filters)


def test_full_landed_cycle_profit_survives_all_settlements(shop):
    app, client = shop
    seed(client)
    receive(client)
    with app.app_context():
        grn = GRN.query.one()
        gid = grn.id
        bd = grn_breakdown(grn)
        assert bd["supplier_material_amount"] == 150000
        assert bd["capitalised_charge_total"] == 6500
        assert bd["average_actual_rate"] == 1565
        assert bd["total_cash_paid"] == 0
        assert SupplierPayment.query.count() == 0
        assert AccountTransaction.query.count() == 0
        supplier = Supplier.query.one()
        assert build_supplier_financial_ledger(supplier)["closing_balance"] == 150000

    before_payments = report(app)
    assert before_payments["summary"]["total_cogs"] == 0
    assert before_payments["summary"]["total_profit"] == 0
    sell(client)
    rep = report(app)
    assert rep["summary"]["total_revenue"] == 72000
    assert rep["summary"]["total_cogs"] == 62600, "40 sold x (1500 + 6500/100)"
    assert rep["summary"]["total_profit"] == 9400
    assert rep["breakdown"]["reconcile"]["goods_cost"] == 62600
    assert rep["breakdown"]["reconcile"]["gross_profit"] == 9400
    assert rep["breakdown"]["reconcile"]["matches"]
    assert rep["summary"]["formula_difference"] == 0
    row = next(r for r in rep["rows"] if r["entry_type"] == "material_sale")
    assert row["cost_status"] == "actual"
    assert row["cost_rate"] == 1565
    assert row["material_cost"] == 62600
    with app.app_context():
        assert Material.query.one().total == 60
        inventory = build_grn_consumption()
        assert inventory["inventory"]["total_value"] == 93900
        sale = DirectSale.query.one()
        alloc = GRNAllocation.query.filter_by(sale_id=sale.id).one()
        assert alloc.qty == 40 and alloc.cost_rate == 1565

    pay_obligations(client, gid)
    after = report(app)
    assert after["summary"] == rep["summary"], "paying a payable cannot create a second expense"
    with app.app_context():
        bd = grn_breakdown(db.session.get(GRN, gid))
        assert bd["total_cash_paid"] == 156500
        assert bd["total_remaining"] == 0
        assert bd["average_actual_rate"] == 1565
        assert build_supplier_financial_ledger(Supplier.query.one())["closing_balance"] == 0
        assert Account.query.filter_by(name="E2E Cash").one().balance == 343500

    # Remaining 60 bags are sold from the same landed lot.  The two deliveries
    # must recognize exactly the original 156,500 purchase cost, not more.
    sell(client, qty=60, bill="E2E-SALE-2", date="2026-11-05")
    final = report(app)
    assert final["summary"]["total_revenue"] == 180000
    assert final["summary"]["total_cogs"] == 156500
    assert final["summary"]["total_profit"] == 23500
    with app.app_context():
        assert Material.query.one().total == 0
        assert build_grn_consumption()["inventory"]["total_value"] == 0


def test_report_separates_supplier_cost_landed_cogs_and_separate_expense(shop):
    app, client = shop
    seed(client)
    receive(client, charges=[
        ("VEHICLE_FARE", "Vehicle rent", 5000, "TRANSPORTER", "Transport Person"),
        ("LOADING", "Loading", 1000, "LABOUR", "Loading Team"),
        ("UNLOADING", "Unloading", 500, "LABOUR", "Unloading Team"),
        ("OTHER", "Office refreshments", 700, "OTHER", "Tea Shop", "EXPENSE"),
    ])
    sell(client)
    rep = report(app)
    assert rep["summary"]["total_cogs"] == 62600
    assert rep["summary"]["total_expenses"] == 700
    assert rep["summary"]["total_profit"] == 8700
    row = next(r for r in rep["rows"] if r["entry_type"] == "material_sale")
    assert row["profit"] == 9400, "sale gross profit excludes a separately classified expense"

    html = client.get(f"/profit_reports?start_date={START}&end_date={END}").get_data(as_text=True)
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    assert "COGS" in text
    assert "60,000.00" in text, "supplier material component of sold goods must be visible"
    assert "2,600.00" in text, "landed costs in sold goods must be visible"
    assert "62,600.00" in text
    assert "9,400.00" in text
    assert "8,700.00" in text
    assert "3,900.00" in text, "capitalised cost in unsold stock is not a current expense"

    with app.app_context():
        payload = build_profit_loss_excel(rep)
    wb = load_workbook(BytesIO(payload.getvalue()), data_only=True)
    assert "COGS Bridge" in wb.sheetnames
    bridge = {r[0]: r[1] for r in wb["COGS Bridge"].iter_rows(min_row=2, values_only=True)}
    assert bridge["Supplier material cost in goods sold"] == 60000
    assert bridge["Capitalised purchase costs in goods sold"] == 2600
    assert bridge["COGS — cost of goods sold"] == 62600
    assert bridge["Direct service costs (not goods COGS)"] == 0
    assert bridge["Separate GRN operating expenses (not COGS)"] == 700

    pdf = client.get(f"/profit_reports/export/pdf?start_date={START}&end_date={END}")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    from pypdf import PdfReader
    pdf_text = " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf.data)).pages)
    assert "COGS" in pdf_text
    assert "60,000.00" in pdf_text
    assert "2,600.00" in pdf_text


def test_two_landed_lots_are_consumed_fifo_not_at_latest_average(shop):
    app, client = shop
    seed(client)
    receive(client, bill="E2E-OLD", date="2026-10-10", qty=10, rate=1000,
            charges=[("LOADING", "Old loading", 500, "LABOUR", "Old Labour")])
    receive(client, bill="E2E-NEW", date="2026-10-12", qty=30, rate=1200,
            charges=[("VEHICLE_FARE", "New fare", 3000, "TRANSPORTER", "New Transport")])
    sell(client, qty=40, rate=1400)
    rep = report(app)
    assert rep["summary"]["total_revenue"] == 56000
    assert rep["summary"]["total_cogs"] == 49500
    assert rep["summary"]["total_profit"] == 6500
    rows = [r for r in rep["rows"] if r["entry_type"] == "material_sale"]
    assert [(r["qty"], r["cost_rate"], r["material_cost"]) for r in rows] == [
        (10, 1050, 10500), (30, 1300, 39000),
    ]


def test_cost_edit_after_delivery_cannot_rewrite_stock_or_frozen_cogs(shop):
    app, client = shop
    seed(client)
    receive(client)
    with app.app_context():
        gid = GRN.query.one().id
    sell(client)
    before = report(app)["summary"]
    # Header-only edits remain allowed.  A charge edit must not silently
    # revalue the 60 unsold bags while the delivered 40 stay frozen at 1,565.
    response = receive(client, edit_id=gid, charges=[
        ("VEHICLE_FARE", "Vehicle rent", 6000, "TRANSPORTER", "Transport Person"),
        ("LOADING", "Loading", 1000, "LABOUR", "Loading Team"),
        ("UNLOADING", "Unloading", 500, "LABOUR", "Unloading Team"),
    ])
    assert b"No changes were saved" in response.data
    assert report(app)["summary"] == before
    with app.app_context():
        grn = db.session.get(GRN, gid)
        assert grn_breakdown(grn)["average_actual_rate"] == 1565
        assert build_grn_consumption()["inventory"]["total_value"] == 93900
        assert GRNAllocation.query.one().cost_rate == 1565
    # Re-submitting the identical cost grid is not a cost change and remains allowed.
    unchanged = receive(client, edit_id=gid)
    assert b"No changes were saved" not in unchanged.data
    assert report(app)["summary"] == before


def test_booking_delivery_uses_landed_cogs_and_advance_is_not_profit(shop):
    app, client = shop
    seed(client)
    receive(client)
    response = client.post("/add_booking", data={
        "client_code": "E2E-1", "material_name[]": ["Cement"], "qty[]": ["40"],
        "unit_rate[]": ["1800"], "amount": "72000", "paid_amount": "10000",
        "payment_method": "Cash", "payment_account_id": "1", "manual_bill_no": "E2E-BOOK", "date": "2026-11-01",
    }, follow_redirects=True)
    with app.app_context():
        from models import Booking
        assert Booking.query.count() == 1, response.get_data(as_text=True)[:2000]
        material_id = Material.query.one().id
    before = report(app)
    assert before["summary"]["total_profit"] == 0
    assert before["summary"]["total_goods_cogs"] == 0
    response = client.post("/add_record", data={
        "type": "OUT", "date": "2026-11-03", "client": "Client One",
        "material": "Cement", "material_id": str(material_id), "qty": "40",
        "driver_name": "Booking Driver",
    }, follow_redirects=True)
    assert b"Record Saved" in response.data
    after = report(app)
    assert after["summary"]["total_revenue"] == 72000
    assert after["summary"]["total_goods_cogs"] == 62600
    assert after["summary"]["total_profit"] == 9400
    assert after["summary"]["formula_difference"] == 0
    with app.app_context():
        assert Material.query.one().total == 60
        assert build_grn_consumption()["inventory"]["total_value"] == 93900


def test_not_applicable_charge_is_neither_inventory_cost_expense_nor_payable(shop):
    app, client = shop
    seed(client)
    receive(client, charges=[
        ("LOADING", "Not applicable loading", 999, "LABOUR", "Labour", "INVENTORY", "NOT_APPLICABLE"),
    ])
    rep = report(app)
    assert rep["summary"]["total_expenses"] == 0
    with app.app_context():
        bd = grn_breakdown(GRN.query.one())
        assert bd["average_actual_rate"] == 1500
        assert bd["total_obligations"] == 150000
    sell(client)
    assert report(app)["summary"]["total_goods_cogs"] == 60000


def test_separate_grn_expense_is_filterable_and_has_working_detail(shop):
    app, client = shop
    seed(client)
    receive(client, charges=[
        ("OTHER", "Site tea", 700, "OTHER", "Tea Shop", "EXPENSE"),
    ])
    filtered = report(app, supplier="Cement Supplier")
    assert filtered["summary"]["total_grn_expenses"] == 700
    assert filtered["summary"]["total_profit"] == -700
    row = next(r for r in filtered["rows"] if r["source"] == "GRNCharge")
    response = client.get(f"/profit_reports/transaction/{row['document_type']}/{row['document_id']}")
    assert response.status_code == 200
    assert b"Site tea" in response.data
    assert b"Tea Shop" in response.data


def test_fractional_landed_cost_reconciles_to_the_paisa(shop):
    app, client = shop
    seed(client)
    receive(client, qty=3, rate=10, charges=[
        ("VEHICLE_FARE", "Small fare", 1, "TRANSPORTER", "Transport"),
    ])
    sell(client, qty=1, rate=20)
    rep = report(app)
    # 31 / 3 is rounded to 10.333333 per unit for display/rates, while the
    # allocated line money is exact paisa.  One delivered unit costs 10.33.
    assert rep["summary"]["total_goods_cogs"] == pytest.approx(10.33)
    bridge = rep["breakdown"]["cogs_bridge"]
    assert bridge["supplier_material_cost"] == 10
    assert bridge["landed_charge_cost"] == pytest.approx(0.33)
    assert bridge["matches"]


def test_supplier_billing_checkbox_moves_grn_costs_into_supplier_ledger_and_accounts(shop):
    app, client = shop
    seed(client)
    receive(client, include_charges_in_supplier=True)
    with app.app_context():
        grn = GRN.query.one()
        gid = grn.id
        bd = grn_breakdown(grn)
        assert bd["supplier_material_amount"] == 150000
        assert bd["supplier_billed_charges"] == 6500
        assert bd["supplier_bill_amount"] == 156500
        assert bd["average_actual_rate"] == 1565
        assert len(bd["obligations"]) == 1
        assert bd["obligations"][0]["kind"] == "SUPPLIER"
        assert bd["obligations"][0]["original"] == 156500
        assert bd["total_remaining"] == 156500
        supplier = Supplier.query.one()
        assert build_supplier_financial_ledger(supplier)["closing_balance"] == 156500
        from app.services.financial_ledgers import build_purchase_payables, build_party_financial_ledger
        from models import CashFlowParty
        payables = build_purchase_payables()
        assert payables["suppliers"][0]["outstanding"] == 156500
        assert payables["parties"] == []
        for party in CashFlowParty.query.all():
            assert build_party_financial_ledger(party)["closing_balance"] == 0

    sell(client)
    rep = report(app)
    assert rep["summary"]["total_goods_cogs"] == 62600
    assert rep["summary"]["total_profit"] == 9400
    pay_obligations(client, gid)
    with app.app_context():
        bd = grn_breakdown(db.session.get(GRN, gid))
        assert bd["total_remaining"] == 0
        assert bd["total_cash_paid"] == 156500
        assert build_supplier_financial_ledger(Supplier.query.one())["closing_balance"] == 0
        assert AccountTransaction.query.count() == 1
    assert report(app)["summary"] == rep["summary"]


def test_unchecked_grn_keeps_costs_out_of_supplier_ledger(shop):
    app, client = shop
    seed(client)
    receive(client, include_charges_in_supplier=False)
    with app.app_context():
        bd = grn_breakdown(GRN.query.one())
        assert bd["supplier_bill_amount"] == 150000
        assert bd["total_obligations"] == 156500
        assert len(bd["obligations"]) == 4
        assert build_supplier_financial_ledger(Supplier.query.one())["closing_balance"] == 150000
