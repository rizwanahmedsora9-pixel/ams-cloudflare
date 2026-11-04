"""One payment path for Accounts → stock vs GRN expenses (owner rules A1–A3).

The owner's story, end to end:

    100 bags @ 1,500 = 150,000 stock; vehicle fare 5,000 + loading 1,000
    ticked "Add to supplier ledger" (expenses 6,000); other 500 NOT ticked
    (own recipient).

  * the GRN shows stock 150,000 and supplier expenses 6,000 as TWO payables;
  * paying stock from Pay Supplier or from PAY GRN settles stock only;
  * expenses can be paid later, separately, and never touch stock;
  * Accounts → Pay Supplier can no longer post a voucher that no GRN knows
    about (the old orphan-payment bug);
  * the supplier ledger, payables page and Cash Flow agree with the GRN.
"""
from __future__ import annotations

import pytest

from models import (
    db, GRN, GRNCharge, Supplier, SupplierPayment, Account, AccountTransaction,
    CashFlowParty,
)
from app.services.grn_costing import grn_breakdown, supplier_bill_breakdown
from app.services.grn_payments import (
    open_supplier_obligations, supplier_open_obligation_total, post_supplier_payment,
)
from app.services.financial_ledgers import (
    build_supplier_financial_ledger, build_party_financial_ledger,
    build_purchase_payables, financial_integrity_audit,
)

LOGIN = {"username": "Admin", "password": "Admin@fbm12345"}


@pytest.fixture()
def app(app_factory):
    return app_factory(AUTO_RECONCILE_ENABLED='0', BACKUP_EMBEDDED_SCHEDULER='0')


@pytest.fixture()
def client(app):
    from tests.conftest import make_csrf_client
    return make_csrf_client(app)


def login(client):
    assert client.post("/login", data=LOGIN, follow_redirects=True).status_code == 200


def seed(app):
    with app.app_context():
        supplier = Supplier(name="Cement Works", is_active=True)
        cash = Account(name="MAIN CASH", type="Cash", account_type="company",
                       category="cash", balance=500000.0, balance_minor=50000000,
                       is_active=True)
        db.session.add_all([supplier, cash])
        db.session.commit()
        return supplier.id, cash.id


def receive_grn(client, app, supplier_id, *, bill="SPLIT-1"):
    """100 @ 1,500 + fare 5,000 + loading 1,000 ticked + other 500 unticked."""
    data = {
        "action": "add", "supplier": "Cement Works", "supplier_id": str(supplier_id),
        "date": "2026-10-20", "time": "10:30", "manual_bill_no": bill,
        "mat_name[]": ["Cement"], "qty[]": ["100"], "price[]": ["1500"],
        "allocation_basis_default": "VALUE",
        "charge_grid_present": "1", "charge_supplier_billing_present": "1",
        "charge_type[]": ["VEHICLE_FARE", "LOADING", "OTHER"],
        "charge_label[]": ["Rana Transport", "Loading Team", "Tea shop"],
        "charge_amount[]": ["5000", "1000", "500"],
        "charge_recipient_type[]": ["TRANSPORTER", "LABOUR", "OTHER"],
        "charge_recipient[]": ["Rana Transport", "Loading Team", "Tea shop"],
        "charge_treatment[]": ["INVENTORY", "INVENTORY", "EXPENSE"],
        "charge_basis[]": ["VALUE", "VALUE", "VALUE"],
        "charge_id[]": ["", "", ""], "charge_note[]": ["", "", ""],
        "charge_row_key[]": ["new-a", "new-b", "new-c"],
        "charge_include_in_supplier[]": ["new-a", "new-b"],
    }
    response = client.post("/grn", data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b"GRN added successfully" in response.data
    with app.app_context():
        return GRN.query.filter(GRN.manual_bill_no.like(f"%{bill}%")).one().id


# ---- 1. the GRN itself shows two supplier payables ----------------------

def test_grn_splits_stock_and_supplier_expenses(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        bd = grn_breakdown(grn)
        assert bd["supplier_material_amount"] == 150000
        assert bd["supplier_billed_charges"] == 6000
        assert bd["supplier_bill_amount"] == 156000
        assert bd["material_original"] == 150000
        assert bd["expenses_original"] == 6000
        # Unticked 500 stays with its own recipient and is in no supplier number.
        charge = GRNCharge.query.filter_by(grn_id=grn_id, charge_type="OTHER").one()
        assert charge.include_in_supplier is False
        keys = [o["key"] for o in bd["obligations"]]
        assert keys[0] == f"MATERIAL:{grn_id}"
        assert keys[1] == f"EXPENSES:{grn_id}"
        assert keys[2] == f"CHARGE:{charge.id}"
        split = supplier_bill_breakdown(grn)
        assert split["material_remaining"] == 150000
        assert split["expenses_remaining"] == 6000
        assert split["recipient_remaining"] == 500
        assert split["total_remaining"] == 156500
        # A1: the GRN itself paid nothing.
        assert SupplierPayment.query.count() == 0
        assert AccountTransaction.query.count() == 0


# ---- 2. Pay Supplier settles stock only, and the GRN agrees -------------

def test_pay_supplier_settles_stock_only(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    response = client.post("/accounts/payments/suppliers/save", data={
        "supplier_id": str(supplier_id),
        "obligation_key": f"MATERIAL:{grn_id}",
        "amount": "50000", "method": "Cash", "payment_account_id": str(cash_id),
        "date": "2026-10-21", "manual_bill_no": "PV-1",
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        payment = SupplierPayment.query.one()
        assert payment.grn_id == grn_id
        assert payment.payment_kind == "GRN_MATERIAL"
        assert payment.source_type == "GRN_PAYMENT"
        assert payment.amount == 50000
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd["material_paid"] == 50000
        assert bd["material_remaining"] == 100000
        assert bd["expenses_paid"] == 0
        assert bd["expenses_remaining"] == 6000
        # One cash-out row, attributed to the GRN.
        assert AccountTransaction.query.count() == 1
        assert AccountTransaction.query.one().grn_id == grn_id
        assert db.session.get(Account, cash_id).balance == 450000
        supplier_ledger = build_supplier_financial_ledger(db.session.get(Supplier, supplier_id))
        assert supplier_ledger["closing_balance"] == 106000


# ---- 3. expenses are paid on their own, later --------------------------

def test_expenses_are_paid_separately_and_never_share_stock(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    response = client.post("/accounts/pay_grn/save", data={
        "grn_id": str(grn_id),
        "pay_obligation_key[]": [f"EXPENSES:{grn_id}"],
        "pay_amount[]": ["6000"],
        "method": "Cash", "payment_account_id": str(cash_id),
        "date_posted": "2026-10-22", "reference": "EXP-1",
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        payment = SupplierPayment.query.one()
        assert payment.payment_kind == "GRN_EXPENSES"
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd["expenses_paid"] == 6000
        assert bd["expenses_remaining"] == 0
        assert bd["material_paid"] == 0
        assert bd["material_remaining"] == 150000
        # The supplier ledger total is unchanged by HOW it was split.
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, supplier_id))["closing_balance"] == 150000


def test_pay_grn_page_can_pay_both_payables_in_one_voucher_run(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    page = client.get(f"/accounts/pay_grn?grn_id={grn_id}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "PAY GRN" in html
    assert "Stock / material" in html
    assert "GRN expenses billed to supplier" in html
    assert f"MATERIAL:{grn_id}" in html and f"EXPENSES:{grn_id}" in html

    response = client.post("/accounts/pay_grn/save", data={
        "grn_id": str(grn_id),
        "pay_obligation_key[]": [f"MATERIAL:{grn_id}", f"EXPENSES:{grn_id}"],
        "pay_amount[]": ["150000", "6000"],
        "method": "Cash", "payment_account_id": str(cash_id),
        "date_posted": "2026-10-23",
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        assert SupplierPayment.query.count() == 2
        assert AccountTransaction.query.count() == 2
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd["material_remaining"] == 0
        assert bd["expenses_remaining"] == 0
        # Only the unticked 500 is left, and it belongs to its own recipient.
        assert bd["total_remaining"] == 500
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, supplier_id))["closing_balance"] == 0
        tea_shop = CashFlowParty.query.filter_by(name="Tea shop").one()
        assert build_party_financial_ledger(tea_shop)["closing_balance"] == 500


# ---- 4. the old bug: a voucher that no GRN knew about -------------------

def test_auto_pay_supplier_payment_reaches_the_grn(client, app):
    """No obligation chosen → oldest open payable, never an orphan voucher."""
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    # 156,000 is exactly stock 150,000 + the 6,000 of ticked expenses.
    response = client.post("/accounts/payments/suppliers/save", data={
        "supplier_id": str(supplier_id), "amount": "156000",
        "method": "Cash", "payment_account_id": str(cash_id),
        "date": "2026-10-24",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"more than the open GRN payable" not in response.data
    assert b"paid \xe2\x80\x94" in response.data or b"paid" in response.data
    with app.app_context():
        payments = SupplierPayment.query.order_by(SupplierPayment.id).all()
        # Every rupee lands on a GRN obligation; nothing floats free.
        assert all(p.grn_id == grn_id for p in payments)
        assert {p.payment_kind for p in payments} == {"GRN_MATERIAL", "GRN_EXPENSES"}
        assert sum(p.amount for p in payments) == pytest.approx(156000)
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd["material_remaining"] == 0
        assert bd["expenses_remaining"] == 0
        assert bd["total_remaining"] == 500
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, supplier_id))["closing_balance"] == 0
        assert financial_integrity_audit()["ok"] is True


def test_extra_money_needs_the_advance_tick(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    response = client.post("/accounts/payments/suppliers/save", data={
        "supplier_id": str(supplier_id), "amount": "200000",
        "method": "Cash", "payment_account_id": str(cash_id),
        "date": "2026-10-24",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"more than the open GRN payable" in response.data
    with app.app_context():
        assert SupplierPayment.query.count() == 0
    # Ticking the advance keeps every rupee traceable: 156,000 on the GRN,
    # the rest as a supplier advance.
    response = client.post("/accounts/payments/suppliers/save", data={
        "supplier_id": str(supplier_id), "amount": "160000", "allow_advance": "1",
        "method": "Cash", "payment_account_id": str(cash_id),
        "date": "2026-10-24",
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        advance = SupplierPayment.query.filter_by(payment_kind="ADVANCE").one()
        assert advance.amount == pytest.approx(4000)
        assert advance.grn_id is None
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd["material_remaining"] == 0
        assert bd["expenses_remaining"] == 0


def test_pay_supplier_refuses_a_supplier_with_no_open_grn_payable(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    response = client.post("/accounts/payments/suppliers/save", data={
        "supplier_id": str(supplier_id), "amount": "5000",
        "method": "Cash", "payment_account_id": str(cash_id),
        "date": "2026-10-24",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"no open GRN payable" in response.data
    with app.app_context():
        assert SupplierPayment.query.count() == 0
        assert AccountTransaction.query.count() == 0


# ---- 5. overpayment guards stay per-payable ----------------------------

def test_stock_voucher_cannot_eat_the_expense_payable(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    response = client.post("/accounts/grn_payments/save", data={
        "grn_id": str(grn_id), "obligation_key": f"MATERIAL:{grn_id}",
        "amount": "150001", "method": "Cash", "payment_account_id": str(cash_id),
        "date_posted": "2026-10-25",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"exceeds the remaining payable" in response.data
    with app.app_context():
        assert SupplierPayment.query.count() == 0


def test_legacy_lumped_supplier_key_still_pays_free_and_allocates(client, app):
    """Old links using SUPPLIER:<id> keep working: material first, then expenses."""
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    response = client.post("/accounts/grn_payments/save", data={
        "grn_id": str(grn_id), "obligation_key": f"SUPPLIER:{grn_id}",
        "amount": "152000", "method": "Cash", "payment_account_id": str(cash_id),
        "date_posted": "2026-10-26",
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd["material_remaining"] == 0
        assert bd["expenses_remaining"] == 4000
        # A second lumped voucher can only settle the open expense part.
        assert bd["total_remaining"] == 4500


# ---- 6. service helpers and read models --------------------------------

def test_open_obligation_list_and_total_match_the_grn(app):
    with app.app_context():
        supplier = Supplier(name="Acme", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        grn = GRN(supplier="Acme", supplier_id=supplier.id, costing_mode="LANDED",
                  manual_bill_no="OB-1")
        db.session.add(grn)
        db.session.flush()
        from models import GRNItem
        db.session.add(GRNItem(grn_id=grn.id, mat_name="Cement", qty=10, price_at_time=1000))
        db.session.add(GRNCharge(grn_id=grn.id, charge_type="LOADING", label="Loading",
                                 amount=400, amount_minor=40000, cost_treatment="INVENTORY",
                                 include_in_supplier=True, recipient_name="Team"))
        db.session.commit()
        from app.services.grn_costing import recompute_landed_costs
        recompute_landed_costs(grn)
        db.session.commit()
        rows = open_supplier_obligations(supplier.id)
        assert [r["key"] for r in rows] == [f"MATERIAL:{grn.id}", f"EXPENSES:{grn.id}"]
        assert supplier_open_obligation_total(supplier.id) == pytest.approx(10400)
        payables = build_purchase_payables()
        assert payables["suppliers"][0]["outstanding"] == pytest.approx(10400)
        assert payables["parties"] == []


def test_post_supplier_payment_rejects_overpayment_without_advance(app):
    with app.app_context():
        supplier = Supplier(name="Acme", is_active=True)
        cash = Account(name="C", type="Cash", account_type="company", category="cash",
                       balance=1000, balance_minor=100000, is_active=True)
        db.session.add_all([supplier, cash])
        db.session.flush()
        grn = GRN(supplier="Acme", supplier_id=supplier.id, costing_mode="LANDED",
                  manual_bill_no="OB-2")
        db.session.add(grn)
        db.session.flush()
        from models import GRNItem
        db.session.add(GRNItem(grn_id=grn.id, mat_name="Cement", qty=1, price_at_time=100))
        db.session.commit()
        with pytest.raises(ValueError, match="open GRN payable"):
            post_supplier_payment(supplier_id=supplier.id, amount=500,
                                  payment_account_id=cash.id, actor=None)
        db.session.rollback()
        assert SupplierPayment.query.count() == 0
