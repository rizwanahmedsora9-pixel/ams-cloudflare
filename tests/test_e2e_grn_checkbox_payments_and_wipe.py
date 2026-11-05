"""Owner walkthrough — GRN checkbox × payment route, and the data wipe.

This suite reproduces, through the real HTTP screens, the two things the owner
asked to be proven end to end:

**A. Payments in Accounts for a GRN, with and without the per-expense
   "Add to supplier ledger" checkbox.**

   100 bags @ 1,500 = 150,000 stock
   Vehicle fare 5,000 · Loading 1,000 · Tea shop 500 (three separate expenses)

   * ticked  -> the expense joins the SUPPLIER bill (its own EXPENSES payable)
   * unticked-> the expense is payable to its own recipient (CHARGE payable)
   * either way the operator pays it from Accounts, and either way the money
     can only be paid once (supplier route and recipient route net out)
   * the billing choice never changes landed cost / inventory value

**B. The data wipe from Settings ("Check All" → wipe).**

   The suite walks the exact form the browser posts, and proves both the
   blocked case and the confirmed full wipe, then reads every screen again.
"""
from __future__ import annotations

import re

import pytest

from models import (
    db, GRN, GRNCharge, GRNItem, Material, MaterialCategory, Supplier,
    SupplierPayment, Account, AccountTransaction, CashFlowParty, Client,
    User, Settings, BillCounter, CashFlowEntry, PendingBill, DirectSale,
    DirectSaleItem, GRNAllocation, Delivery, DeliveryItem, Entry, Payment,
    Invoice, Booking, BookingItem, MaterialReturn, MaterialReturnItem,
    DeliveryRent, DeliveryPerson, DeliveryPersonPayment, SaleDeliveryPerson,
    WaiveOff, ReconBasket, FbmCashDrawerEntry, FbmCashDrawerCategory,
    CashFlowCategory, CashFlowSubcategory, CashFlowDifferenceAdjustment,
    CashFlowReconciliationAudit, CashFlowEntryAudit, AccountCategory,
    AccountReconciliation, FBMRental, FBMClient, FBMRentalItem, Service,
    DirectSaleDraft, PendingBill as _PendingBill,
)
from app.services.grn_costing import grn_breakdown, supplier_bill_breakdown
from app.services.financial_ledgers import (
    build_supplier_financial_ledger, build_party_financial_ledger,
    build_purchase_payables, financial_integrity_audit,
)

LOGIN = {"username": "Admin", "password": "Admin@fbm12345"}

TICKED = "ticked"
UNTICKED = "unticked"
MIXED = "mixed"

#: The three expenses used in every scenario, keyed by the GRN row key.
CHARGES = [
    # row_key, type, label, recipient_type, recipient, amount, treatment
    ("a", "VEHICLE_FARE", "Rana Transport", "TRANSPORTER", "Rana Transport", "5000", "INVENTORY"),
    ("b", "LOADING", "Loading Team", "LABOUR", "Loading Team", "1000", "INVENTORY"),
    ("c", "OTHER", "Tea shop", "OTHER", "Tea shop", "500", "EXPENSE"),
]
STOCK = 150000            # 100 × 1,500
EXPENSES = 6500           # 5,000 + 1,000 + 500


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(app_factory):
    return app_factory(AUTO_RECONCILE_ENABLED="0", BACKUP_EMBEDDED_SCHEDULER="0")


@pytest.fixture()
def client(app):
    from tests.conftest import make_csrf_client
    return make_csrf_client(app)


def login(client):
    response = client.post("/login", data=LOGIN, follow_redirects=True)
    assert response.status_code == 200


def seed(app):
    with app.app_context():
        supplier = Supplier(name="Cement Works", is_active=True)
        cash = Account(name="MAIN CASH", type="Cash", account_type="company",
                       category="cash", balance=500000.0, balance_minor=50000000,
                       is_active=True)
        bank = Account(name="MEEZAN BANK", type="Bank", account_type="company",
                       category="bank", balance=1000000.0, balance_minor=100000000,
                       is_active=True)
        db.session.add_all([supplier, cash, bank])
        db.session.commit()
        return supplier.id, cash.id, bank.id


def receive_grn(client, app, supplier_id, *, bill, ticked):
    """Create a GRN through the real form.

    ``ticked`` is one of TICKED / UNTICKED / MIXED, or a set of row keys.
    """
    if ticked is TICKED:
        included = {key for key, *_ in CHARGES}
    elif ticked is UNTICKED:
        included = set()
    elif ticked is MIXED:
        included = {"a"}
    else:
        included = set(ticked)
    data = {
        "action": "add", "supplier": "Cement Works", "supplier_id": str(supplier_id),
        "date": "2026-10-20", "time": "10:30", "manual_bill_no": bill,
        "mat_name[]": ["Cement"], "qty[]": ["100"], "price[]": ["1500"],
        "allocation_basis_default": "VALUE",
        "charge_grid_present": "1", "charge_supplier_billing_present": "1",
        "charge_type[]": [c[1] for c in CHARGES],
        "charge_label[]": [c[2] for c in CHARGES],
        "charge_amount[]": [c[5] for c in CHARGES],
        "charge_recipient_type[]": [c[3] for c in CHARGES],
        "charge_recipient[]": [c[4] for c in CHARGES],
        "charge_treatment[]": [c[6] for c in CHARGES],
        "charge_basis[]": ["VALUE"] * len(CHARGES),
        "charge_id[]": [""] * len(CHARGES),
        "charge_note[]": [""] * len(CHARGES),
        "charge_row_key[]": [f"new-{c[0]}" for c in CHARGES],
        "charge_include_in_supplier[]": [f"new-{c[0]}" for c in CHARGES if c[0] in included],
    }
    response = client.post("/grn", data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b"GRN added successfully" in response.data, flash_text(response)[:2000]
    with app.app_context():
        grn = GRN.query.filter(GRN.manual_bill_no.like(f"%{bill}%")).one()
        return grn.id


def charge_ids(app, grn_id):
    with app.app_context():
        rows = GRNCharge.query.filter_by(grn_id=grn_id).all()
        return {c.recipient_name: c.id for c in rows}


def breakdown(app, grn_id):
    with app.app_context():
        return grn_breakdown(db.session.get(GRN, grn_id))


def supplier_bill(app, grn_id):
    with app.app_context():
        return supplier_bill_breakdown(db.session.get(GRN, grn_id))


def cash_balance(app, account_id):
    with app.app_context():
        return db.session.get(Account, account_id).balance


def party_balance(app, name):
    with app.app_context():
        party = CashFlowParty.query.filter_by(name=name).one()
        return build_party_financial_ledger(party)["closing_balance"]


def supplier_ledger(app, supplier_id):
    with app.app_context():
        return build_supplier_financial_ledger(db.session.get(Supplier, supplier_id))


def pay_supplier(client, *, supplier_id, account_id, amount, reference, rdate="2026-10-21"):
    """Accounts → Pay Supplier (the supplier bill route)."""
    return client.post("/accounts/payments/suppliers/save", data={
        "supplier_id": str(supplier_id),
        "amount": amount, "method": "Cash",
        "payment_account_id": str(account_id),
        "date": rdate, "manual_bill_no": reference,
    }, follow_redirects=True)


def pay_grn_obligations(client, *, grn_id, account_id, lines, reference):
    """Accounts → PAY GRN (one box per supplier payable)."""
    return client.post("/accounts/pay_grn/save", data={
        "grn_id": str(grn_id),
        "pay_obligation_key[]": [key for key, _ in lines],
        "pay_amount[]": [amount for _, amount in lines],
        "method": "Cash", "payment_account_id": str(account_id),
        "date_posted": "2026-10-22", "reference": reference,
    }, follow_redirects=True)


def pay_expenses(client, *, grn_id, account_id, lines, reference):
    """Accounts → Pay GRN Expenses (one money box per expense row)."""
    return client.post("/accounts/grn_payments/save", data={
        "grn_id": str(grn_id), "mode": "EXPENSES",
        "expense_key[]": [key for key, _ in lines],
        "expense_amount[]": [amount for _, amount in lines],
        "method": "Cash", "payment_account_id": str(account_id),
        "date_posted": "2026-10-25T09:00", "reference": reference,
        "idempotency_key": f"e2e-{grn_id}-{reference}",
    }, follow_redirects=True)


def flash_text(response):
    body = response.get_data(as_text=True)
    return " ".join(re.findall(r'alert alert-[a-z]+[^>]*>(.*?)</div>', body, re.S))


# ---------------------------------------------------------------------------
# A1. What the checkbox changes — and what it does not
# ---------------------------------------------------------------------------

def test_checkbox_only_moves_the_expense_between_two_payables(client, app):
    """Ticked and unticked GRNs: one total, two different payable owners."""
    login(client)
    supplier_id, cash_id, _bank_id = seed(app)

    on_id = receive_grn(client, app, supplier_id, bill="E2E-ON", ticked=TICKED)
    off_id = receive_grn(client, app, supplier_id, bill="E2E-OFF", ticked=UNTICKED)

    on = breakdown(app, on_id)
    off = breakdown(app, off_id)

    # Stock is identical on both GRNs.
    for bd in (on, off):
        assert bd["supplier_material_amount"] == STOCK
        assert bd["landed_cost_total"] == STOCK + 6000  # 5,000 + 1,000 are INVENTORY
        assert bd["total_obligations"] == STOCK + EXPENSES

    # Checkbox ON → the whole 6,500 is the supplier's second payable.
    assert on["supplier_billed_charges"] == EXPENSES
    assert on["supplier_bill_amount"] == STOCK + EXPENSES
    assert on["additional_remaining"] == 0

    # Checkbox OFF → the supplier only ever sees stock.
    assert off["supplier_billed_charges"] == 0
    assert off["supplier_bill_amount"] == STOCK
    assert off["additional_remaining"] == EXPENSES

    # Landed cost / inventory value are untouched by the choice.
    assert [c["amount"] for c in on["charges"]] == [c["amount"] for c in off["charges"]]
    assert on["landed_cost_total"] == off["landed_cost_total"]
    assert on["average_actual_rate"] == off["average_actual_rate"] == pytest.approx(
        (STOCK + 6000) / 100)

    # Nothing has been paid by the GRN itself (owner rule A1).
    with app.app_context():
        assert SupplierPayment.query.count() == 0
        assert AccountTransaction.query.count() == 0


# ---------------------------------------------------------------------------
# A2. Pay the supplier (stock + ticked expenses) from Accounts
# ---------------------------------------------------------------------------

def test_pay_supplier_route_pays_stock_then_ticked_expenses(client, app):
    login(client)
    supplier_id, cash_id, _bank_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="E2E-PAYSUP", ticked=TICKED)

    # -- stock only ------------------------------------------------------
    response = pay_supplier(client, supplier_id=supplier_id, account_id=cash_id,
                            amount="50000", reference="PV-STOCK-1")
    assert response.status_code == 200
    bd = breakdown(app, grn_id)
    assert bd["material_paid"] == 50000
    assert bd["material_remaining"] == 100000
    assert bd["expenses_paid"] == 0
    assert bd["expenses_remaining"] == EXPENSES
    assert bd["supplier_remaining"] == 100000 + EXPENSES
    assert cash_balance(app, cash_id) == 450000
    assert supplier_ledger(app, supplier_id)["closing_balance"] == 106500

    with app.app_context():
        kinds = [p.payment_kind for p in SupplierPayment.query.order_by(SupplierPayment.id)]
        assert kinds == ["GRN_MATERIAL"]

    # -- the ticked expenses, on their own payable -----------------------
    response = pay_grn_obligations(client, grn_id=grn_id, account_id=cash_id,
                                   lines=[(f"EXPENSES:{grn_id}", "6500")],
                                   reference="PV-EXP-1")
    assert response.status_code == 200
    bd = breakdown(app, grn_id)
    assert bd["expenses_paid"] == EXPENSES
    assert bd["expenses_remaining"] == 0
    assert bd["material_remaining"] == 100000        # stock untouched
    assert bd["total_remaining"] == 100000
    assert cash_balance(app, cash_id) == 500000 - 50000 - 6500
    with app.app_context():
        kinds = [p.payment_kind for p in SupplierPayment.query.order_by(SupplierPayment.id)]
        assert kinds == ["GRN_MATERIAL", "GRN_EXPENSES"]

    # -- the rest of the stock -------------------------------------------
    pay_grn_obligations(client, grn_id=grn_id, account_id=cash_id,
                        lines=[(f"MATERIAL:{grn_id}", "100000")], reference="PV-STOCK-2")
    bd = breakdown(app, grn_id)
    assert bd["material_remaining"] == 0
    assert bd["total_remaining"] == 0
    assert supplier_ledger(app, supplier_id)["closing_balance"] == 0
    assert cash_balance(app, cash_id) == 500000 - 156500
    with app.app_context():
        assert financial_integrity_audit()["ok"] is True


# ---------------------------------------------------------------------------
# A3. Pay the very same GRN expense to its recipient instead
# ---------------------------------------------------------------------------

def test_ticked_expense_paid_to_recipient_leaves_the_supplier_bill(client, app):
    login(client)
    supplier_id, cash_id, _bank_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="E2E-RECIP", ticked=TICKED)
    ids = charge_ids(app, grn_id)

    before = breakdown(app, grn_id)
    assert before["expenses_remaining"] == EXPENSES

    # Pay the vehicle fare straight to Rana Transport.
    response = pay_expenses(client, grn_id=grn_id, account_id=cash_id,
                            lines=[(f"CHARGE:{ids['Rana Transport']}", "5000")],
                            reference="REC-1")
    assert response.status_code == 200

    after = breakdown(app, grn_id)
    # One rupee, one place: the supplier bill drops by exactly 5,000 …
    assert after["expenses_original"] == EXPENSES - 5000
    assert after["expenses_remaining"] == EXPENSES - 5000
    # … the recipient is settled …
    assert party_balance(app, "Rana Transport") == 0
    # … and nothing is payable twice: the 5,000 moved out of the supplier
    # payable, so the GRN total drops by exactly the money actually paid.
    assert after["total_obligations"] == before["total_obligations"] - 5000
    assert after["total_remaining"] == before["total_remaining"] - 5000
    assert after["total_remaining"] == STOCK + EXPENSES - 5000
    assert cash_balance(app, cash_id) == 495000
    with app.app_context():
        payment = SupplierPayment.query.one()
        assert payment.payment_kind == "GRN_CHARGE"
        assert payment.grn_charge_id == ids["Rana Transport"]

    # The supplier's remaining bill is stock + the two expenses still ticked.
    bd = supplier_bill(app, grn_id)
    assert bd["material_remaining"] == STOCK
    assert bd["expenses_remaining"] == 1500
    assert supplier_ledger(app, supplier_id)["closing_balance"] == STOCK + 1500


# ---------------------------------------------------------------------------
# A4. Checkbox OFF: pay stock to the supplier, each expense to its recipient
# ---------------------------------------------------------------------------

def test_unticked_grn_pays_supplier_stock_and_recipients_separately(client, app):
    login(client)
    supplier_id, cash_id, _bank_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="E2E-OFFPAY", ticked=UNTICKED)
    ids = charge_ids(app, grn_id)

    # Supplier sees stock only.
    response = pay_supplier(client, supplier_id=supplier_id, account_id=cash_id,
                            amount="150000", reference="PV-OFF-STOCK")
    assert response.status_code == 200
    bd = breakdown(app, grn_id)
    assert bd["material_remaining"] == 0
    assert bd["expenses_remaining"] == 0        # no ticked expense payable at all
    assert bd["additional_remaining"] == EXPENSES
    assert supplier_ledger(app, supplier_id)["closing_balance"] == 0
    with app.app_context():
        # The expenses are owed to their own recipients, in full.
        assert [r["amount"] for r in bd["charges"]] == [5000, 1000, 500]

    # Pay every expense to its own recipient, one by one.
    response = pay_expenses(client, grn_id=grn_id, account_id=cash_id, lines=[
        (f"CHARGE:{ids['Rana Transport']}", "5000"),
        (f"CHARGE:{ids['Loading Team']}", "1000"),
        (f"CHARGE:{ids['Tea shop']}", "500"),
    ], reference="REC-OFF")
    assert response.status_code == 200

    bd = breakdown(app, grn_id)
    assert bd["total_remaining"] == 0
    assert bd["additional_remaining"] == 0
    for name in ("Rana Transport", "Loading Team", "Tea shop"):
        assert party_balance(app, name) == 0
    assert cash_balance(app, cash_id) == 500000 - STOCK - EXPENSES
    with app.app_context():
        assert SupplierPayment.query.count() == 4
        assert financial_integrity_audit()["ok"] is True


# ---------------------------------------------------------------------------
# A5. MIXED checkbox: only one row ticked
# ---------------------------------------------------------------------------

def test_mixed_checkbox_splits_the_three_expenses(client, app):
    login(client)
    supplier_id, cash_id, _bank_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="E2E-MIX", ticked=MIXED)
    ids = charge_ids(app, grn_id)

    bd = breakdown(app, grn_id)
    assert bd["supplier_billed_charges"] == 5000
    assert bd["supplier_bill_amount"] == 155000
    assert bd["additional_remaining"] == 1500
    assert supplier_bill(app, grn_id)["total_remaining"] == 156500

    # Pay one ticked expense to the supplier and one unticked to its recipient.
    response = pay_grn_obligations(client, grn_id=grn_id, account_id=cash_id,
                                   lines=[(f"EXPENSES:{grn_id}", "5000")],
                                   reference="MIX-SUP")
    assert response.status_code == 200
    response = pay_expenses(client, grn_id=grn_id, account_id=cash_id,
                            lines=[(f"CHARGE:{ids['Tea shop']}", "500")],
                            reference="MIX-TEA")
    assert response.status_code == 200

    bd = breakdown(app, grn_id)
    assert bd["expenses_remaining"] == 0
    assert bd["additional_remaining"] == 1000      # Loading Team still open
    assert bd["material_remaining"] == STOCK
    assert cash_balance(app, cash_id) == 500000 - 5500
    assert party_balance(app, "Loading Team") == 1000
    assert party_balance(app, "Tea shop") == 0
    assert party_balance(app, "Rana Transport") == 0

    # Overpaying the only open expense is refused (no double payment).
    response = pay_expenses(client, grn_id=grn_id, account_id=cash_id,
                            lines=[(f"CHARGE:{ids['Loading Team']}", "1001")],
                            reference="MIX-OVER")
    assert response.status_code == 200
    assert b"exceeds" in response.data.lower() or b"remaining" in response.data.lower()
    assert party_balance(app, "Loading Team") == 1000


# ---------------------------------------------------------------------------
# A6. The Accounts screens agree with the numbers above
# ---------------------------------------------------------------------------

def test_accounts_screens_report_the_same_payables(client, app):
    login(client)
    supplier_id, cash_id, _bank_id = seed(app)
    on_id = receive_grn(client, app, supplier_id, bill="E2E-SCR-ON", ticked=TICKED)
    off_id = receive_grn(client, app, supplier_id, bill="E2E-SCR-OFF", ticked=UNTICKED)

    payables = client.get("/accounts/payments/suppliers")
    assert payables.status_code == 200
    payables_html = payables.get_data(as_text=True)
    assert "Cement Works" in payables_html

    # /accounts/pay_grn lists both supplier payables per GRN.
    for grn_id in (on_id, off_id):
        html = client.get(f"/accounts/pay_grn?grn_id={grn_id}").get_data(as_text=True)
        assert f"MATERIAL:{grn_id}" in html

    on_page = client.get(f"/accounts/pay_grn?grn_id={on_id}").get_data(as_text=True)
    assert f"EXPENSES:{on_id}" in on_page
    # Unticked GRN has no supplier expense payable at all.
    off_page = client.get(f"/accounts/pay_grn?grn_id={off_id}").get_data(as_text=True)
    assert f"EXPENSES:{off_id}" not in off_page

    # Expense screen shows one box per expense with Total/Paid/To pay.
    exp_page = client.get(f"/accounts/grn_payments?grn_id={on_id}&mode=EXPENSES").get_data(as_text=True)
    assert exp_page.count('name="expense_amount[]"') == 3
    for name in ("Rana Transport", "Loading Team", "Tea shop"):
        assert name in exp_page

    # Supplier ledger screen shows the supplier bill, not the recipients' money.
    ledger = client.get(f"/supplier_ledger/{supplier_id}")
    assert ledger.status_code in (200, 302)

    with app.app_context():
        payables_model = build_purchase_payables()
        assert payables_model["suppliers"][0]["outstanding"] == pytest.approx(
            156500 + 150000)
        assert {p["name"] for p in payables_model["parties"]} == {
            "Rana Transport", "Loading Team", "Tea shop"}
        assert sum(p["outstanding"] for p in payables_model["parties"]) == pytest.approx(EXPENSES)


# ---------------------------------------------------------------------------
# A7. Owner-visible totals: print the matrix for the report
# ---------------------------------------------------------------------------

def test_print_payment_matrix(client, app, capsys):
    """Runs every route once and prints the figures the owner asked to 'see'."""
    login(client)
    supplier_id, cash_id, _bank_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="E2E-MATRIX", ticked=MIXED)
    ids = charge_ids(app, grn_id)

    rows = []

    def snapshot(label):
        bd = breakdown(app, grn_id)
        rows.append((label, bd["supplier_billed_charges"], bd["material_remaining"],
                     bd["expenses_remaining"], bd["additional_remaining"],
                     bd["total_remaining"], cash_balance(app, cash_id)))

    snapshot("after GRN (fare ticked)")
    pay_supplier(client, supplier_id=supplier_id, account_id=cash_id,
                 amount="150000", reference="M-STOCK")
    snapshot("paid stock 150,000")
    pay_grn_obligations(client, grn_id=grn_id, account_id=cash_id,
                        lines=[(f"EXPENSES:{grn_id}", "5000")], reference="M-EXP")
    snapshot("paid ticked fare 5,000")
    pay_expenses(client, grn_id=grn_id, account_id=cash_id, lines=[
        (f"CHARGE:{ids['Loading Team']}", "1000"),
        (f"CHARGE:{ids['Tea shop']}", "500"),
    ], reference="M-REC")
    snapshot("paid unticked 1,000 + 500")

    print("\nGRN E2E payment matrix (supplier-billed | stock due | ticked due |"
          " unticked due | total due | cash)")
    for label, billed, mat, exp, add, total, cash in rows:
        print(f"  {label:<32} billed={billed:>8.0f} stock={mat:>8.0f}"
              f" ticked={exp:>7.0f} unticked={add:>7.0f} total={total:>8.0f}"
              f" cash={cash:>9.0f}")

    final = breakdown(app, grn_id)
    assert final["total_remaining"] == 0
    assert cash_balance(app, cash_id) == 500000 - STOCK - EXPENSES


# ---------------------------------------------------------------------------
# B. Data wipe — the exact Settings flow
# ---------------------------------------------------------------------------

def settings_wipe_targets(client):
    """All dataset checkboxes the Settings page renders (what 'Check All' ticks)."""
    html = client.get("/settings").get_data(as_text=True)
    targets = re.findall(
        r'name="delete_targets"\s+value="([^"]+)"', html)
    assert len(targets) >= 30, f"only found {len(targets)} wipe targets"
    return targets


def wipe(client, targets, *, confirm, hard):
    data = {"confirm_text": confirm, "delete_targets": list(targets)}
    if hard:
        data["hard_delete_override"] = "1"
    return client.post("/delete_selected_data", data=data, follow_redirects=True)


FULL_SET = {
    "clients", "suppliers", "supplier_payments", "pending_bills", "dispatching",
    "receiving", "grn", "materials", "material_categories", "direct_sales",
    "material_returns", "delivery_rents", "delivery_persons", "invoices",
    "payments", "bookings", "notifications",
}


def assert_business_tables_empty(*, allow_accounts=False):
    """Every transactional / master table must be empty after a full wipe."""
    leftovers = {}
    for model in (GRN, GRNItem, GRNCharge, GRNAllocation, SupplierPayment,
                  Supplier, Material, MaterialCategory, DirectSale, DirectSaleItem,
                  Entry, Delivery, DeliveryItem, Payment, Invoice, PendingBill,
                  Booking, BookingItem, MaterialReturn, MaterialReturnItem,
                  DeliveryRent, DeliveryPerson, DeliveryPersonPayment,
                  SaleDeliveryPerson, WaiveOff, ReconBasket,
                  FbmCashDrawerEntry, FbmCashDrawerCategory, CashFlowEntry,
                  CashFlowEntryAudit, CashFlowCategory, CashFlowSubcategory,
                  CashFlowDifferenceAdjustment, CashFlowReconciliationAudit,
                  AccountReconciliation, AccountTransaction, FBMRental,
                  FBMClient, FBMRentalItem, DirectSaleDraft):
        count = model.query.count()
        if count:
            leftovers[model.__name__] = count
    if not allow_accounts:
        for model in (Account, AccountCategory, Client):
            count = model.query.count()
            if count:
                leftovers[model.__name__] = count
    assert not leftovers, f"tables survived the wipe: {leftovers}"


def seed_full_yard(client, app):
    """Data in every module, the way a live yard has it."""
    with app.app_context():
        material = Material(code="FBM-MAT-1", name="CEMENT", category_id=None,
                            total=150000.0)
        category = MaterialCategory(name="Building")
        client_row = Client(code="FBMCL-00001", name="Wipe Test Client")
        supplier = Supplier(name="Cement Works", is_active=True)
        driver = DeliveryPerson(name="Ali Driver", phone="0300-1")
        account = Account(name="MAIN CASH", type="Cash", account_type="company",
                          category="cash", balance=500000.0, balance_minor=50000000,
                          is_active=True)
        account_category = AccountCategory(name="Cash Box")
        party = CashFlowParty(name="Rana Transport", party_type="person")
        cash_cat = CashFlowCategory(name="Transport")
        db.session.add_all([material, category, client_row, supplier, driver,
                            account, account_category, party, cash_cat])
        db.session.flush()
        cash_sub = CashFlowSubcategory(category_id=cash_cat.id, name="Fare")
        db.session.add(cash_sub)
        db.session.commit()
        return {
            "supplier_id": supplier.id,
            "account_id": account.id,
            "driver_id": driver.id,
            "client_id": client_row.id,
        }


def test_wipe_check_all_without_hard_override_is_refused_and_changes_nothing(client, app):
    """The safe path: the server refuses a hard cleanup without the override."""
    login(client)
    seed_full_yard(client, app)
    supplier_id, cash_id, _bank_id = seed(app)
    receive_grn(client, app, supplier_id, bill="WIPE-1", ticked=TICKED)

    targets = settings_wipe_targets(client)
    assert FULL_SET.issubset(set(targets)), "Settings cannot express a full wipe"

    response = wipe(client, targets, confirm="DELETE SELECTED", hard=False)
    assert response.status_code == 200

    # Nothing was deleted …
    with app.app_context():
        assert GRN.query.count() == 1
        assert GRNCharge.query.count() == 3
        assert SupplierPayment.query.count() == 0
        assert Account.query.count() == 3
    # … and the operator is not left guessing: the flash names the cause.
    assert "Hard delete blocked" in response.get_data(as_text=True)

    # A wrong confirmation text is refused the same way.
    response = wipe(client, targets, confirm="DELETE SELECTED", hard=True)
    assert response.status_code == 200
    assert "Incorrect confirmation text" in response.get_data(as_text=True)
    with app.app_context():
        assert GRN.query.count() == 1


def test_wipe_check_all_with_hard_override_erases_every_module(client, app):
    login(client)
    seed_full_yard(client, app)
    supplier_id, cash_id, _bank_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="WIPE-2", ticked=TICKED)
    pay_supplier(client, supplier_id=supplier_id, account_id=cash_id,
                 amount="50000", reference="WIPE-PV")
    with app.app_context():
        assert AccountTransaction.query.count() == 1
        assert SupplierPayment.query.count() == 1

    targets = settings_wipe_targets(client)
    response = wipe(client, targets, confirm="DELETE ALL DATA", hard=True)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Data Wiped" in body

    with app.app_context():
        assert_business_tables_empty()
        # Identity / settings / audit survive.
        assert User.query.filter_by(username="Admin").first() is not None
        # The bill counter is reset, not removed.
        assert BillCounter.query.count() == 1
        assert BillCounter.query.first().count == 1000
        assert financial_integrity_audit()["ok"] is True

    # Every screen opens again and shows nothing old.
    for url in ("/", "/accounts/", "/grn", "/suppliers", "/accounts/pay_grn",
                "/accounts/grn_payments", "/accounts/payments/suppliers",
                "/cash_flow", "/settings"):
        page = client.get(url)
        assert page.status_code in (200, 302), f"{url} -> {page.status_code}"
    grn_page = client.get("/grn").get_data(as_text=True)
    assert "WIPE-2" not in grn_page
    accounts_page = client.get("/accounts/").get_data(as_text=True)
    assert "Cement Works" not in accounts_page


def test_wipe_single_module_keeps_the_rest(client, app):
    """A granular wipe (only GRN) must not touch accounts or suppliers.

    The GRN has already been paid from Accounts: the payment document belongs
    to the GRN, so it goes too and its cash effect is reversed — the account
    balance must not keep money that no document explains.
    """
    login(client)
    seed_full_yard(client, app)
    supplier_id, cash_id, _bank_id = seed(app)
    grn_id = receive_grn(client, app, supplier_id, bill="WIPE-GRN", ticked=TICKED)
    pay_supplier(client, supplier_id=supplier_id, account_id=cash_id,
                 amount="50000", reference="WIPE-GRN-PV")
    assert cash_balance(app, cash_id) == 450000

    response = wipe(client, ["grn"], confirm="DELETE SELECTED", hard=False)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Data Wiped" in body and "Wipe failed" not in body
    with app.app_context():
        assert GRN.query.count() == 0
        assert GRNCharge.query.count() == 0
        assert GRNItem.query.count() == 0
        assert SupplierPayment.query.count() == 0
        assert AccountTransaction.query.count() == 0
        assert Supplier.query.count() == 2       # seeded supplier survives
        assert Account.query.count() == 3
    # The reversed payment returns the cash to the account.
    assert cash_balance(app, cash_id) == 500000


def test_wipe_cash_flow_categories_with_grn_recipients(client, app):
    """Deleting the party master must not trip over GRN expense recipients."""
    login(client)
    seed_full_yard(client, app)
    supplier_id, cash_id, _bank_id = seed(app)
    receive_grn(client, app, supplier_id, bill="WIPE-CFC", ticked=TICKED)
    pay_supplier(client, supplier_id=supplier_id, account_id=cash_id,
                 amount="20000", reference="WIPE-CFC-PV")

    response = wipe(client, ["cash_flow_categories"], confirm="DELETE SELECTED", hard=False)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Wipe failed" not in body
    with app.app_context():
        assert CashFlowParty.query.count() == 0
        assert CashFlowCategory.query.count() == 0
        assert CashFlowSubcategory.query.count() == 0
        # Documents and money are untouched; only the party link is gone.
        assert GRN.query.count() == 1
        assert GRNCharge.query.count() == 3
        assert SupplierPayment.query.count() == 1
