"""The PAY GRN screen (Accounts → PAY GRN (STOCK / EXPENSES)).

Owner contract (A3): the stock value of a GRN (qty × rate) and the GRN
expenses that were ticked "add to supplier ledger" are TWO separate payables.
This suite pins the operator-visible halves:

  * the screen offers a stock box, a supplier-billed expenses box and one box
    per expense with its own recipient, each with its own amount and "Pay full";
  * expenses that were NOT ticked never appear in the supplier box — they stay
    payable to their own recipient on Pay GRN Expenses;
  * posting the stock box settles stock only and leaves the expenses due;
  * posting the expenses box settles expenses only and leaves stock due;
  * posting only one line in a two-line run is honoured (no silent waterfall);
  * the supplier ledger shows the stock row and the expenses row apart.
"""
import re

import pytest

from models import db, GRN, GRNCharge, Supplier, Account, SupplierPayment
from app.services.grn_costing import grn_breakdown
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
    """A supplier with a cash account: 100 × 1500 stock.

    Expenses: 5,000 vehicle fare TICKED for the supplier and 500 tea-shop
    expense NOT ticked (paid to its own recipient).
    """
    with app.app_context():
        supplier = Supplier(name="Cement Works", is_active=True)
        cash = Account(name="MAIN CASH", type="Cash", account_type="company",
                       category="cash", balance=500000.0, balance_minor=50000000,
                       is_active=True)
        db.session.add_all([supplier, cash])
        db.session.commit()
        return supplier.id, cash.id


def receive_grn(client, app, supplier_id, *, bill="PG-SCREEN-1"):
    data = {
        "action": "add", "supplier": "Cement Works", "supplier_id": str(supplier_id),
        "date": "2026-10-20", "time": "10:30", "manual_bill_no": bill,
        "mat_name[]": ["Cement"], "qty[]": ["100"], "price[]": ["1500"],
        "allocation_basis_default": "VALUE",
        "charge_grid_present": "1", "charge_supplier_billing_present": "1",
        "charge_type[]": ["VEHICLE_FARE", "OTHER"],
        "charge_label[]": ["Rana Transport", "Tea shop"],
        "charge_amount[]": ["5000", "500"],
        "charge_recipient_type[]": ["TRANSPORTER", "OTHER"],
        "charge_recipient[]": ["Rana Transport", "Tea shop"],
        "charge_treatment[]": ["INVENTORY", "EXPENSE"],
        "charge_basis[]": ["VALUE", "VALUE"],
        "charge_id[]": ["", ""], "charge_note[]": ["", ""],
        "charge_row_key[]": ["new-a", "new-b"],
        "charge_include_in_supplier[]": ["new-a"],
    }
    response = client.post("/grn", data=data, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        grn = GRN.query.filter(GRN.manual_bill_no.like(f"%{bill}%")).one()
        return grn.id


def pay(client, app, grn_id, cash_id, lines, *, method="Cash"):
    """POST the screen exactly like the browser: two parallel lists."""
    keys = [key for key, _ in lines]
    amounts = [amount for _, amount in lines]
    return client.post("/accounts/pay_grn/save", data={
        "grn_id": str(grn_id),
        "pay_obligation_key[]": keys,
        "pay_amount[]": amounts,
        "method": method,
        "payment_account_id": str(cash_id),
        "date_posted": "2026-10-25",
        "reference": "PG-SCREEN",
        "idempotency_key": f"screen-{grn_id}-{keys[0]}-{amounts[0]}",
    }, follow_redirects=True)


def test_screen_shows_stock_and_expenses_as_two_boxes(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    html = client.get(f"/accounts/pay_grn?grn_id={grn_id}").get_data(as_text=True)
    assert html.count('data-pay-block="MATERIAL"') == 1
    assert html.count('data-pay-block="EXPENSES"') == 1
    assert "Stock / material" in html
    assert "GRN expenses billed to supplier" in html
    assert html.count("Pay full") >= 4
    # One box per payable: stock, the ticked expenses, and EVERY GRN expense
    # (the ticked fare too — it is its own box, and paying it to the recipient
    # removes it from the supplier box above).
    assert html.count('name="pay_obligation_key[]"') == 4
    assert html.count('name="pay_amount[]"') == 4
    assert 'data-pay-block="CHARGE:' in html
    assert "GRN expenses not added to supplier ledger" in html
    assert "Amount to be paid" in html

    # Stock 150,000 and the ticked 5,000 are distinct figures on the page.
    assert "150,000.00" in html
    assert "5,000.00" in html
    material = re.search(r'data-pay-block="MATERIAL"\s+data-remaining="([\d.]+)"', html)
    expenses = re.search(r'data-pay-block="EXPENSES"[^>]*data-remaining="([\d.]+)"', html)
    assert material and material.group(1) == "150000.00"
    assert expenses and expenses.group(1) == "5000.00"

    # The unticked 500 belongs to the tea shop, not the supplier.
    assert "Tea shop" in html
    assert "500.00" in html


def test_screen_never_bills_unticked_expense_to_the_supplier(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    with app.app_context():
        bill = grn_breakdown(db.session.get(GRN, grn_id))
        assert bill["material_original"] == pytest.approx(150000)
        assert bill["expenses_original"] == pytest.approx(5000)
        # the 500 tea shop expense is a recipient charge, not supplier expense
        assert bill["additional_remaining"] == pytest.approx(500)
        assert bill["supplier_bill_amount"] == pytest.approx(155000)
        assert bill["total_remaining"] == pytest.approx(155500)


def test_stock_box_alone_leaves_the_expenses_due(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    pay(client, app, grn_id, cash_id, [("MATERIAL:%d" % grn_id, "150000")])
    with app.app_context():
        bill = grn_breakdown(db.session.get(GRN, grn_id))
        assert bill["material_remaining"] == 0
        assert bill["expenses_paid"] == 0
        assert bill["expenses_remaining"] == pytest.approx(5000)
        kinds = {p.payment_kind for p in SupplierPayment.query.all()}
        assert kinds == {"GRN_MATERIAL"}
        ledger = build_supplier_financial_ledger(db.session.get(Supplier, supplier_id))
        # The stock row collapses to zero and the separate GRN Expenses row
        # keeps exactly the supplier-billed 5,000 (never the tea shop's 500).
        assert ledger["closing_balance"] == pytest.approx(5000)
        # The ledger carries the two supplier payables as separate rows.
        types = [row.get("type") for row in ledger["rows"]]
        assert "GRN" in types and "GRN Expenses" in types

    # The screen now offers only the expenses box as payable.
    html = client.get(f"/accounts/pay_grn?grn_id={grn_id}").get_data(as_text=True)
    assert re.search(r'data-pay-block="MATERIAL"\s+data-remaining="0.00"', html)
    assert re.search(r'data-pay-block="EXPENSES"[^>]*data-remaining="5000.00"', html)


def test_expenses_box_alone_leaves_the_stock_due(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    pay(client, app, grn_id, cash_id, [("EXPENSES:%d" % grn_id, "5000")])
    with app.app_context():
        bill = grn_breakdown(db.session.get(GRN, grn_id))
        assert bill["expenses_remaining"] == 0
        assert bill["material_paid"] == 0
        assert bill["material_remaining"] == pytest.approx(150000)
        assert {p.payment_kind for p in SupplierPayment.query.all()} == {"GRN_EXPENSES"}


def test_only_the_filled_box_is_paid(client, app):
    """A blank stock box must not silently swallow the expenses amount."""
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    pay(client, app, grn_id, cash_id, [("MATERIAL:%d" % grn_id, "50000"), ("EXPENSES:%d" % grn_id, "")])
    with app.app_context():
        bill = grn_breakdown(db.session.get(GRN, grn_id))
        assert bill["material_paid"] == pytest.approx(50000)
        assert bill["material_remaining"] == pytest.approx(100000)
        assert bill["expenses_paid"] == 0
        assert bill["expenses_remaining"] == pytest.approx(5000)


def test_both_boxes_in_one_run_post_two_vouchers(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    response = pay(client, app, grn_id, cash_id,
                   [("MATERIAL:%d" % grn_id, "150000"), ("EXPENSES:%d" % grn_id, "5000")])
    assert response.status_code == 200
    with app.app_context():
        payments = SupplierPayment.query.order_by(SupplierPayment.id).all()
        assert [p.payment_kind for p in payments] == ["GRN_MATERIAL", "GRN_EXPENSES"]
        assert [p.amount for p in payments] == [pytest.approx(150000), pytest.approx(5000)]
        bill = grn_breakdown(db.session.get(GRN, grn_id))
        assert bill["material_remaining"] == 0
        assert bill["expenses_remaining"] == 0
        # the tea shop's 500 is still owed to the tea shop
        assert bill["total_remaining"] == pytest.approx(500)


def test_expenses_overpayment_is_refused(client, app):
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    response = pay(client, app, grn_id, cash_id, [("EXPENSES:%d" % grn_id, "6000")])
    assert response.status_code == 200
    with app.app_context():
        assert SupplierPayment.query.count() == 0
        assert grn_breakdown(db.session.get(GRN, grn_id))["expenses_remaining"] == pytest.approx(5000)


def test_unticked_expense_is_paid_to_its_own_recipient(client, app):
    """The tea shop 500 is a GRNCharge payable, not a supplier payable."""
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    with app.app_context():
        tea = GRNCharge.query.filter_by(grn_id=grn_id, recipient_name="Tea shop").one()
        key = f"CHARGE:{tea.id}"
        assert grn_breakdown(db.session.get(GRN, grn_id))["supplier_bill_amount"] == pytest.approx(155000)

    response = pay(client, app, grn_id, cash_id, [(key, "500")])
    assert b"GRN expenses to their own recipients" in response.data
    with app.app_context():
        bill = grn_breakdown(db.session.get(GRN, grn_id))
        assert bill["additional_remaining"] == 0
        # paying the recipient did not touch either supplier payable
        assert bill["material_remaining"] == pytest.approx(150000)
        assert bill["expenses_remaining"] == pytest.approx(5000)
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, supplier_id))["closing_balance"] == pytest.approx(155000)

    # The own-recipient box is now explicitly shown as settled.
    html = client.get(f"/accounts/pay_grn?grn_id={grn_id}").get_data(as_text=True)
    assert re.search(r'data-pay-block="CHARGE:%d"\s+data-remaining="0.00"' % tea.id, html)


def test_pay_existing_grn_page_lists_every_obligation(client, app):
    """Supplier payables on the supplier form, every expense in the expense form."""
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)
    html = client.get(f"/accounts/grn_payments?grn_id={grn_id}").get_data(as_text=True)
    for needle in ["Stock / material", "billed to supplier"]:
        assert needle in html, needle
    # The expenses themselves live on their own per-expense system.
    expenses_html = client.get(
        f"/accounts/grn_payments?grn_id={grn_id}&mode=EXPENSES").get_data(as_text=True)
    for needle in ["Rana Transport", "Tea shop", "one amount each"]:
        assert needle in expenses_html, needle


def test_screen_links_are_reachable_from_accounts(client, app):
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id)

    dashboard = client.get("/accounts/").get_data(as_text=True)
    assert "/accounts/pay_grn" in dashboard
    ledger = client.get(f"/supplier_ledger/{supplier_id}").get_data(as_text=True)
    assert "Pay GRN (stock / expenses)" in ledger
    assert "GRN Expenses" in ledger
    grn_page = client.get("/grn").get_data(as_text=True)
    assert "Stock due:" in grn_page
    assert "GRN expenses due to supplier:" in grn_page
    assert f"/accounts/pay_grn?grn_id={grn_id}" in grn_page


def test_dashboard_grn_picker_is_hidden_for_supplier_payment_but_exposes_due_facts(client, app):
    """The stray GRN field is only for the Pay GRN Expenses route."""
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="PG-DASH-1")

    html = client.get("/accounts/").get_data(as_text=True)
    assert '<option value="grn_payment">Pay GRN Expenses</option>' in html
    assert re.search(r'<div class="[^"]*\bd-none\b[^"]*"\s+id="grnPaymentWrap"', html)
    assert re.search(r'id="grnPaymentGrnSelect"[^>]*\bdisabled\b', html)
    assert "Amount still to be paid" in html
    assert "GRN expenses still to pay (one by one)" in html
    # The picker's server-authoritative values include every open GRN expense:
    # the ticked 5,000 (its own box too) and the unticked 500.
    assert 'data-date-label="20/Oct/2026"' in html
    assert 'data-total-due="155500.00"' in html
    assert 'data-recipient-expenses-due="5500.00"' in html
    assert f'value="{grn_id}"' in html


def test_pay_grn_expenses_shows_selected_date_and_amount_without_js(client, app):
    """An off-ledger expense opens with its real payable amount and GRN date."""
    login(client)
    supplier_id, _cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="PG-FULL-1")
    with app.app_context():
        tea = GRNCharge.query.filter_by(grn_id=grn_id, recipient_name="Tea shop").one()
        tea_id = tea.id

    html = client.get(
        f"/accounts/grn_payments?grn_id={grn_id}&charge_id={tea_id}"
    ).get_data(as_text=True)
    # Opening one expense goes straight into the per-expense payment system.
    assert "Pay GRN Expenses" in html
    assert "Selected GRN date" in html
    assert "20/Oct/2026" in html
    assert "GRN expenses — one amount each" in html
    # The tea shop box shows exactly its own 500, with its own money field...
    assert re.search(r'data-expense-box="CHARGE:%d"\s+data-remaining="500\.00"' % tea_id, html)
    assert re.search(r'id="expenseAmount%d"' % tea_id, html)
    # ... and the supplier's single amount field is not on this screen at all.
    assert 'id="grnPaymentAmount"' not in html
    assert 'data-recipient-expenses-due="5500.00"' in html


def test_pay_grn_expenses_defaults_to_an_open_payable_after_stock_is_settled(client, app):
    """A settled stock row must not hide the next GRN expense amount."""
    login(client)
    supplier_id, cash_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="PG-OPEN-1")
    pay(client, app, grn_id, cash_id, [(f"MATERIAL:{grn_id}", "150000")])

    html = client.get(f"/accounts/grn_payments?grn_id={grn_id}").get_data(as_text=True)
    assert re.search(r'id="grnPaymentPayable">\s*Rs\. 5,000\.00', html)
    assert re.search(
        r'<option value="EXPENSES:%d"[^>]*\bselected\b' % grn_id, html, re.S)
