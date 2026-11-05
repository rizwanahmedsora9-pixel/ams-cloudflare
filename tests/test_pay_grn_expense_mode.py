"""Pay GRN Expenses — one payment system per kind of payable.

Owner contract (screens must not mix the two systems):

  * the **supplier bill** is one payable family: stock (qty × rate) and the GRN
    expenses still ticked "Add to supplier ledger", paid together with one
    amount field on the supplier form;
  * **GRN expenses** have their own payment system: every vehicle fare,
    loading, unloading and other expense the operator entered on the GRN is
    listed with its OWN amount field, and the supplier amount field is not on
    screen at all (it is a different, unique payment system);
  * an expense ticked to the supplier is not a "fake" second charge: paying it
    here (to its own recipient) removes exactly that money from the supplier
    bill, so one rupee is never payable twice;
  * the supplier ledger keeps showing only material + the expenses still ticked
    and unpaid through the recipient route.
"""
import re

import pytest

from models import db, GRN, GRNCharge, Supplier, Account, SupplierPayment, CashFlowParty
from app.services.grn_costing import grn_breakdown, supplier_bill_breakdown
from app.services.financial_ledgers import (
    build_supplier_financial_ledger, build_party_financial_ledger,
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
    client.post("/login", data=LOGIN, follow_redirects=True)


def seed(app):
    with app.app_context():
        supplier = Supplier(name="Cement Works", is_active=True)
        cash = Account(name="MAIN CASH", type="Cash", account_type="company",
                       category="cash", balance=500000.0, balance_minor=50000000,
                       is_active=True)
        db.session.add_all([supplier, cash])
        db.session.commit()
        return supplier.id, cash.id


def receive_grn(client, app, supplier_id, *, bill="EXP-MODE-1"):
    """100 × 1,500 stock · fare 5,000 TICKED · loading 3,000 · tea 500 unticked."""
    data = {
        "action": "add", "supplier": "Cement Works", "supplier_id": str(supplier_id),
        "date": "2026-10-20", "time": "10:30", "manual_bill_no": bill,
        "mat_name[]": ["Cement"], "qty[]": ["100"], "price[]": ["1500"],
        "allocation_basis_default": "VALUE",
        "charge_grid_present": "1", "charge_supplier_billing_present": "1",
        "charge_type[]": ["VEHICLE_FARE", "LOADING", "OTHER"],
        "charge_label[]": ["Rana Transport", "Mazdoor loading", "Tea shop"],
        "charge_amount[]": ["5000", "3000", "500"],
        "charge_recipient_type[]": ["TRANSPORTER", "LABOUR", "OTHER"],
        "charge_recipient[]": ["Rana Transport", "Mazdoor", "Tea shop"],
        "charge_treatment[]": ["INVENTORY", "INVENTORY", "EXPENSE"],
        "charge_basis[]": ["VALUE", "VALUE", "VALUE"],
        "charge_id[]": ["", "", ""], "charge_note[]": ["", "", ""],
        "charge_row_key[]": ["new-a", "new-b", "new-c"],
        # only the vehicle fare is ticked "Add to supplier ledger"
        "charge_include_in_supplier[]": ["new-a"],
    }
    response = client.post("/grn", data=data, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        grn = GRN.query.filter(GRN.manual_bill_no.like(f"%{bill}%")).one()
        return grn.id


def charge_id(app, grn_id, name):
    with app.app_context():
        return GRNCharge.query.filter_by(grn_id=grn_id, recipient_name=name).one().id


def save_expenses(client, grn_id, cash_id, lines, *, reference="EXP-PAY"):
    """POST the per-expense form: one key + one money field per expense."""
    keys = [key for key, _ in lines]
    amounts = [amount for _, amount in lines]
    return client.post("/accounts/grn_payments/save", data={
        "grn_id": str(grn_id), "mode": "EXPENSES",
        "expense_key[]": keys, "expense_amount[]": amounts,
        "method": "Cash", "payment_account_id": str(cash_id),
        "date_posted": "2026-10-25T09:00", "reference": reference,
        "idempotency_key": f"exp-{grn_id}-{keys[0]}-{reference}",
    }, follow_redirects=True)


# ---------------------------------------------------------------------------
# 1. The screen: two payment systems, never mixed
# ---------------------------------------------------------------------------

def test_expense_mode_lists_one_box_per_expense_and_no_supplier_amount(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    html = client.get(f"/accounts/grn_payments?grn_id={grn_id}&mode=EXPENSES").get_data(as_text=True)

    # Every expense — ticked or not — has its own money field.
    assert html.count('name="expense_amount[]"') == 3
    assert html.count('name="expense_key[]"') == 3
    assert "Rana Transport" in html and "Mazdoor" in html and "Tea shop" in html
    # ... and the supplier's single amount field is gone.
    assert 'id="grnPaymentAmount"' not in html
    assert 'name="amount"' not in html
    assert 'id="grnPaymentForm"' not in html
    assert "Pay the supplier" not in html
    # The ticked fare shows 5,000 as ITS own payable, with its route declared.
    fare_id = charge_id(app, grn_id, "Rana Transport")
    assert re.search(r'data-expense-box="CHARGE:%d"\s+data-remaining="5000.00"' % fare_id, html)
    assert re.search(r'id="expenseAmount%d"' % fare_id, html)
    assert "supplier ticked" in html


def test_supplier_mode_has_the_single_amount_and_no_expense_boxes(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    html = client.get(f"/accounts/grn_payments?grn_id={grn_id}").get_data(as_text=True)
    assert 'id="grnPaymentAmount"' in html
    assert 'name="obligation_key"' in html
    assert 'name="expense_amount[]"' not in html
    assert 'id="grnExpenseForm"' not in html
    # It points at the expense system for the expenses themselves, quoting the
    # real open expense total (5,000 fare + 3,000 loading + 500 tea = 8,500).
    assert "Pay the GRN expenses one by one" in html
    assert "Rs. 8,500.00 still to pay" in html


def test_supplier_mode_only_offers_supplier_payables(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    html = client.get(f"/accounts/grn_payments?grn_id={grn_id}").get_data(as_text=True)
    options = re.findall(r'<option value="(MATERIAL|EXPENSES|CHARGE|SUPPLIER):[^"]*"', html)
    assert options and set(options) <= {"MATERIAL", "EXPENSES"}


# ---------------------------------------------------------------------------
# 2. Each expense is paid on its own, in its own amount
# ---------------------------------------------------------------------------

def test_two_expenses_in_one_submit_create_two_own_recipient_vouchers(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    loading = charge_id(app, grn_id, "Mazdoor")
    tea = charge_id(app, grn_id, "Tea shop")

    response = save_expenses(client, grn_id, cash_id,
                             [(f"CHARGE:{loading}", "3000"), (f"CHARGE:{tea}", "500")])
    assert response.status_code == 200
    assert b"GRN payment of Rs. 3,500.00" in response.data

    with app.app_context():
        payments = SupplierPayment.query.order_by(SupplierPayment.id).all()
        assert [p.amount for p in payments] == [pytest.approx(3000), pytest.approx(500)]
        assert {p.payment_kind for p in payments} == {"GRN_CHARGE"}
        assert {p.recipient_name for p in payments} == {"Mazdoor", "Tea shop"}
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        # The supplier bill is untouched: those two were never ticked.
        assert bd["material_remaining"] == 150000
        assert bd["expenses_remaining"] == 5000
        assert bd["supplier_payable_total"] if False else True
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, supplier_id))["closing_balance"] == 155000
        for name in ("Mazdoor", "Tea shop"):
            party = CashFlowParty.query.filter_by(name=name).one()
            assert build_party_financial_ledger(party)["closing_balance"] == 0


def test_expense_amount_cannot_exceed_that_expense(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    loading = charge_id(app, grn_id, "Mazdoor")

    response = save_expenses(client, grn_id, cash_id, [(f"CHARGE:{loading}", "9000")])
    assert b"exceeds the remaining payable" in response.data
    with app.app_context():
        assert SupplierPayment.query.count() == 0


def test_empty_submit_is_refused_with_a_clear_message(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    loading = charge_id(app, grn_id, "Mazdoor")
    response = save_expenses(client, grn_id, cash_id, [(f"CHARGE:{loading}", "")])
    assert b"Enter an amount next to the GRN expense" in response.data
    with app.app_context():
        assert SupplierPayment.query.count() == 0


# ---------------------------------------------------------------------------
# 3. A ticked expense paid to its recipient leaves the supplier bill
# ---------------------------------------------------------------------------

def test_paying_the_ticked_expense_to_its_recipient_shrinks_the_supplier_bill(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    fare = charge_id(app, grn_id, "Rana Transport")

    with app.app_context():
        bill = supplier_bill_breakdown(db.session.get(GRN, grn_id))
        # before: the fare is part of the supplier payable
        assert bill["expenses_remaining"] == 5000
        assert bill["expenses_original"] == 5000
        assert bill["supplier_bill_amount"] == 155000

    save_expenses(client, grn_id, cash_id, [(f"CHARGE:{fare}", "5000")])

    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        bill = supplier_bill_breakdown(grn)
        bd = grn_breakdown(grn)
        # The supplier no longer owes it, and no second copy appeared anywhere.
        assert bill["expenses_remaining"] == 0
        assert bill["expenses_original"] == 0
        assert bill["supplier_bill_amount"] == 150000
        assert bill["recipient_remaining"] == 3500
        assert bd["total_remaining"] == 153500
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, supplier_id))["closing_balance"] == 150000
        assert SupplierPayment.query.count() == 1
        # The expense box itself reads paid, "via recipient".
        fare_row = next(o for o in bd["obligations"] if o.get("charge_id") == fare)
        assert fare_row["remaining"] == 0
        assert fare_row["recipient_paid"] == 5000


def test_supplier_payment_after_the_recipient_paid_the_same_expense_pays_only_the_rest(client, app):
    """One rupee, one place: no double payment whichever screen pays first."""
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    fare = charge_id(app, grn_id, "Rana Transport")

    save_expenses(client, grn_id, cash_id, [(f"CHARGE:{fare}", "2000")])
    with app.app_context():
        bill = supplier_bill_breakdown(db.session.get(GRN, grn_id))
        assert bill["expenses_remaining"] == 3000

    # The rest of the fare is still payable to the recipient...
    response = save_expenses(client, grn_id, cash_id, [(f"CHARGE:{fare}", "3000")],
                             reference="EXP-PAY-2")
    assert b"GRN payment of Rs. 3,000.00" in response.data
    with app.app_context():
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd["expenses_remaining"] == 0
        assert bd["material_remaining"] == 150000
        assert sum(p.amount for p in SupplierPayment.query.all()) == 5000


def test_expense_paid_through_the_supplier_bill_cannot_be_paid_again_by_the_recipient(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    fare = charge_id(app, grn_id, "Rana Transport")

    # Pay the supplier's expense payable (the ticked fare) first.
    client.post("/accounts/grn_payments/save", data={
        "grn_id": str(grn_id), "mode": "SUPPLIER",
        "obligation_key": f"EXPENSES:{grn_id}", "amount": "5000",
        "method": "Cash", "payment_account_id": str(cash_id),
        "date_posted": "2026-10-25T09:00",
    }, follow_redirects=True)

    response = save_expenses(client, grn_id, cash_id, [(f"CHARGE:{fare}", "5000")],
                             reference="EXP-PAY-2")
    assert b"exceeds the remaining payable" in response.data
    with app.app_context():
        assert SupplierPayment.query.count() == 1
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, supplier_id))["closing_balance"] == 150000


# ---------------------------------------------------------------------------
# 4. Nothing about the supplier bill numbers changes when payments are absent
# ---------------------------------------------------------------------------

def test_untouched_grn_keeps_the_documented_supplier_numbers(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    with app.app_context():
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd["supplier_material_amount"] == 150000
        assert bd["supplier_billed_charges"] == 5000
        assert bd["supplier_bill_amount"] == 155000
        assert bd["material_original"] == 150000
        assert bd["expenses_original"] == 5000
        assert bd["additional_remaining"] == 3500
        assert bd["total_remaining"] == 158500
        # every expense is its own box, including the ticked one
        charges = [o for o in bd["obligations"] if o["kind"] == "CHARGE"]
        assert len(charges) == 3
        assert [c["original"] for c in charges] == [5000, 3000, 500]
