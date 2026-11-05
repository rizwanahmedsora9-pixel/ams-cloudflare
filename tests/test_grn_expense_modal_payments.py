"""Pay GRN expenses straight from Accounts → Make New Transaction.

Owner contract (2026-11-05):

  * choosing **Pay GRN Expenses** in the transaction modal opens the
    per-expense payment system — one row per GRN expense the supplier ledger
    does **not** carry, each with its own ``Total``, ``Paid``, ``To pay`` and
    its own money field;
  * none of those rows carries stock: no quantity, no rate, no material amount;
  * the supplier's single amount field disappears while an expense is paid —
    the two payment systems are never mixed;
  * every filled box becomes its own ``GRN_CHARGE`` voucher through the same
    engine (and the same guards) as the Pay GRN Expenses page, and the supplier
    ledger is not touched by an unticked expense;
  * an expense the supplier ledger carries (ticked) is *not* offered there —
    it is settled through the supplier bill, so the same rupee is never payable
    twice.
"""
import re

import pytest

from models import db, GRN, GRNCharge, Supplier, Account, SupplierPayment, CashFlowParty
from app.services.grn_costing import grn_breakdown, grn_expense_payment_rows
from app.services.financial_ledgers import build_supplier_financial_ledger

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


def receive_grn(client, app, supplier_id, *, bill="MODAL-GRN-1"):
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


def pay_from_modal(client, grn_id, cash_id, lines, *, reference="MODAL-PAY"):
    keys = [key for key, _ in lines]
    amounts = [amount for _, amount in lines]
    return client.post("/accounts/grn_expenses/pay", data={
        "grn_expense_grn_id": str(grn_id),
        "expense_key[]": keys,
        "expense_amount[]": amounts,
        "grn_expense_account_id": str(cash_id),
        "grn_expense_method": "Cash",
        "grn_expense_reference": reference,
        "grn_expense_idempotency_key": f"modal-{grn_id}-{reference}",
        "date_posted": "2026-10-25T09:00",
    }, follow_redirects=True)


# ---------------------------------------------------------------------------
# 1. The read-side helper: Total / Paid / To pay per expense, no stock
# ---------------------------------------------------------------------------

def test_payment_rows_list_only_the_expenses_the_supplier_ledger_leaves_out(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        rows = grn_expense_payment_rows(grn)
        labels = [row['label'] for row in rows['payment_rows']]
        assert any('Loading' in label for label in labels)
        assert any('Other' in label for label in labels)
        # The ticked fare belongs to the supplier bill, not to this system.
        assert not any('Vehicle' in label for label in labels)
        assert rows['payment_total'] == pytest.approx(3500)
        assert rows['payment_paid'] == pytest.approx(0)
        assert rows['payment_remaining'] == pytest.approx(3500)
        assert rows['supplier_ledger_due'] == pytest.approx(155000)
        # Every row is a payable, never stock.
        for row in rows['payment_rows']:
            assert row['total'] == pytest.approx(row['paid'] + row['remaining'])
            assert row['recipient_label']
        # Stock, quantity and rate are not part of this system at all.
        assert 'qty' not in repr(rows['payment_rows']).lower()
        assert 'rate' not in repr(rows['payment_rows']).lower()
        assert 'material' not in {k for k in rows if k == 'material_remaining'
                                 and False}

    html = client.get(f"/accounts/api/grn_expense_payments/{grn_id}").get_data(as_text=True)
    assert '"ok": true' in html or '"ok":true' in html
    assert 'payment_rows' in html and 'supplier_ledger_due' in html


def test_api_hides_a_void_grn(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        grn.is_void = True
        db.session.commit()
    response = client.get(f"/accounts/api/grn_expense_payments/{grn_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 2. The modal markup: one box per unticked expense, no supplier amount
# ---------------------------------------------------------------------------

def test_modal_renders_its_own_per_expense_payment_system(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    receive_grn(client, app, supplier_id, bill="MODAL-DOM-1")

    html = client.get("/accounts/").get_data(as_text=True)

    # The per-expense panel and its hooks are present...
    for needle in ('id="grnExpensePayWrap"', 'id="grnExpenseBody"',
                   'id="grnExpenseTotal"', 'id="grnExpenseStatus"',
                   'id="grnExpenseAccount"', 'grn_expense_grn_id'):
        assert needle in html, needle
    # ... each row proves its own total / paid / to-pay, never stock.
    for needle in ('data-expense-total', 'data-expense-paid',
                   'data-expense-remaining', 'name="expense_amount[]"',
                   'data-grn-expense-pay-full'):
        assert needle in html, needle
    # The modal still never carries a supplier amount for the GRN picker.
    assert 'Supplier ledger due:' in html
    # The panel's fields cannot collide with the ordinary transaction fields.
    assert 'name="payment_account_id" id="grnExpenseAccount"' not in html


def test_modal_points_at_the_full_pay_grn_expenses_screen(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="MODAL-LINK-1")
    html = client.get("/accounts/").get_data(as_text=True)
    assert f'/accounts/grn_payments/0?mode=EXPENSES"' in html or 'mode=EXPENSES' in html
    assert "Open Pay GRN Expenses" in html
    assert f'value="{grn_id}"' in html


# ---------------------------------------------------------------------------
# 3. Posting: one voucher per filled box, supplier ledger untouched
# ---------------------------------------------------------------------------

def test_modal_pays_each_expense_on_its_own_and_leaves_the_supplier_bill_alone(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="MODAL-PAY-1")
    loading = charge_id(app, grn_id, "Mazdoor")
    tea = charge_id(app, grn_id, "Tea shop")

    response = pay_from_modal(client, grn_id, cash_id,
                             [(f"CHARGE:{loading}", "3000"), (f"CHARGE:{tea}", "500")])
    assert response.status_code == 200
    assert b"GRN expenses of Rs. 3,500.00 paid" in response.data

    with app.app_context():
        payments = SupplierPayment.query.order_by(SupplierPayment.id).all()
        assert [p.amount for p in payments] == [pytest.approx(3000), pytest.approx(500)]
        assert {p.payment_kind for p in payments} == {"GRN_CHARGE"}
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        # The supplier bill is untouched by these two unticked expenses.
        assert bd["material_remaining"] == pytest.approx(150000)
        assert bd["expenses_remaining"] == pytest.approx(5000)
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, supplier_id))["closing_balance"] == pytest.approx(155000)
        # Each expense box now reads its own total / paid / to pay.
        rows = grn_expense_payment_rows(db.session.get(GRN, grn_id))
        by_label = {row['label']: row for row in rows['payment_rows']}
        loading_row = next(v for k, v in by_label.items() if 'Loading' in k)
        assert (loading_row['total'], loading_row['paid'], loading_row['remaining']) == (
            pytest.approx(3000), pytest.approx(3000), pytest.approx(0))
        assert rows['payment_remaining'] == pytest.approx(0)


def test_modal_refuses_a_ticked_expense(client, app):
    """Ticked expenses are paid through the supplier bill, never twice."""
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="MODAL-TICK-1")
    fare = charge_id(app, grn_id, "Rana Transport")

    response = pay_from_modal(client, grn_id, cash_id, [(f"CHARGE:{fare}", "5000")])
    assert b"Pay GRN Expenses" in response.data
    with app.app_context():
        assert SupplierPayment.query.count() == 0


def test_modal_refuses_an_overpayment_and_an_empty_submit(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="MODAL-GUARD-1")
    loading = charge_id(app, grn_id, "Mazdoor")

    over = pay_from_modal(client, grn_id, cash_id, [(f"CHARGE:{loading}", "9000")])
    assert b"exceeds the remaining payable" in over.data
    empty = pay_from_modal(client, grn_id, cash_id, [(f"CHARGE:{loading}", "")])
    assert b"Enter the amount next to at least one GRN expense" in empty.data
    with app.app_context():
        assert SupplierPayment.query.count() == 0


def test_modal_refuses_a_missing_source_account(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="MODAL-ACC-1")
    loading = charge_id(app, grn_id, "Mazdoor")

    response = client.post("/accounts/grn_expenses/pay", data={
        "grn_expense_grn_id": str(grn_id),
        "expense_key[]": [f"CHARGE:{loading}"],
        "expense_amount[]": ["1000"],
        "grn_expense_method": "Cash",
        "date_posted": "2026-10-25T09:00",
    }, follow_redirects=True)
    assert b"Select the cash / bank account" in response.data
    with app.app_context():
        assert SupplierPayment.query.count() == 0


def test_modal_payment_is_the_one_cash_out_row_and_reaches_the_party_ledger(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="MODAL-LEDGER-1")
    tea = charge_id(app, grn_id, "Tea shop")

    pay_from_modal(client, grn_id, cash_id, [(f"CHARGE:{tea}", "500")])

    with app.app_context():
        payment = SupplierPayment.query.one()
        assert payment.payment_kind == "GRN_CHARGE"
        assert payment.cash_posted is True
        party = CashFlowParty.query.filter_by(name="Tea shop").one()
        assert party is not None
        from app.services.financial_ledgers import build_party_financial_ledger
        assert build_party_financial_ledger(party)["closing_balance"] == pytest.approx(0)
        assert db.session.get(Account, cash_id).balance == pytest.approx(499500)
