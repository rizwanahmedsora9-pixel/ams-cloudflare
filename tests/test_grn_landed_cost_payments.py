"""End-to-end regression for the GRN landed-cost / payments redesign.

Owner rules under test:
  A1  A GRN NEVER pays.  All purchase money is paid from Accounts.
  A2  Supplier Ledger credit = sum(qty x rate) ONLY, and a transporter
      payment never reduces the supplier payable.

Worked example: 100 bags @ 1,500 = 150,000; fare 5,000; loading 1,000;
other 500 -> landed 156,500 / 1,565 per bag.  Pay fare 5,000, then supplier
50,000, then loading 1,000.  Cash Flow must show 56,000, never 156,000.
"""
from __future__ import annotations

import pytest

from models import (
    db, GRN, GRNItem, GRNCharge, Supplier, SupplierPayment, Material,
    Account, AccountTransaction, CashFlowParty, Entry,
)
from app.services.grn_costing import grn_breakdown, lot_cost_rate
from app.services.financial_ledgers import (
    build_supplier_financial_ledger, build_party_financial_ledger,
    financial_integrity_audit,
)
from app.services.cash_flow_svc import collect_cash_flow_rows

LOGIN = {"username": "Admin", "password": "Admin@fbm12345"}


@pytest.fixture()
def app(app_factory):
    # Keep the background reconcile worker from contending for the SQLite
    # write lock while these focused accounting tests post many payments.
    return app_factory(AUTO_RECONCILE_ENABLED='0', BACKUP_EMBEDDED_SCHEDULER='0')


@pytest.fixture()
def client(app):
    from tests.conftest import make_csrf_client
    return make_csrf_client(app)


def login(client):
    resp = client.post("/login", data=LOGIN, follow_redirects=True)
    assert resp.status_code == 200


def seed(app):
    with app.app_context():
        sup = Supplier(name="Cement Works", is_active=True)
        mat = Material(code="MAT-LC", name="Cement", total=0.0)
        cash = Account(name="MAIN CASH", type="Cash", account_type="company",
                       category="cash", balance=500000.0, balance_minor=50000000,
                       is_active=True)
        db.session.add_all([sup, mat, cash])
        db.session.commit()
        return sup.id, cash.id


def add_grn(client, supplier_id, *, charges=None, date="2026-10-20", bill="LC-GRN-001"):
    data = {
        "action": "add",
        "supplier": "Cement Works",
        "supplier_id": str(supplier_id),
        "date": date,
        "time": "10:30",
        "manual_bill_no": bill,
        "mat_name[]": ["Cement"],
        "qty[]": ["100"],
        "price[]": ["1500"],
        "allocation_basis_default": "VALUE",
        "charge_type[]": [], "charge_label[]": [], "charge_amount[]": [],
        "charge_recipient_type[]": [], "charge_recipient[]": [],
        "charge_status[]": [], "charge_treatment[]": [], "charge_basis[]": [],
        "charge_id[]": [], "charge_note[]": [],
    }
    for c in (charges or []):
        data["charge_type[]"].append(c[0])
        data["charge_label[]"].append(c[1])
        data["charge_amount[]"].append(str(c[2]))
        data["charge_recipient_type[]"].append(c[3])
        data["charge_recipient[]"].append(c[4])
        data["charge_status[]"].append(c[5] if len(c) > 5 else "UNPAID")
        data["charge_treatment[]"].append(c[6] if len(c) > 6 else "INVENTORY")
        data["charge_basis[]"].append("VALUE")
        data["charge_id[]"].append("")
        data["charge_note[]"].append("")
    resp = client.post("/grn", data=data, follow_redirects=True)
    assert resp.status_code == 200, resp.data[:500]
    assert b"GRN added successfully" in resp.data, resp.data[:1500]


def test_receiving_never_pays_and_builds_exact_landed_cost(client, app):
    login(client)
    sup_id, cash_id = seed(app)
    add_grn(client, sup_id, charges=[
        ("VEHICLE_FARE", "Rana Transport", 5000, "TRANSPORTER", "Rana Transport"),
        ("LOADING", "Loading team", 1000, "LABOUR", "Loading Team"),
        ("OTHER", "Misc", 500, "OTHER", "Misc Party"),
    ])
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        assert grn is not None
        assert grn.costing_mode == 'LANDED'
        bd = grn_breakdown(grn)
        assert bd['supplier_material_amount'] == pytest.approx(150000.0)
        assert bd['capitalised_charge_total'] == pytest.approx(6500.0)
        assert bd['landed_cost_total'] == pytest.approx(156500.0)
        assert bd['average_actual_rate'] == pytest.approx(1565.0)
        assert bd['total_cash_paid'] == 0.0
        assert bd['supplier_remaining'] == pytest.approx(150000.0)
        assert bd['total_remaining'] == pytest.approx(156500.0)
        # A1: no payment row, no settlement, no cash movement of any kind.
        assert SupplierPayment.query.filter_by(grn_id=grn.id).count() == 0
        assert AccountTransaction.query.filter(
            AccountTransaction.grn_id == grn.id).count() == 0
        assert float(grn.paid_amount or 0) == 0.0
        assert grn.payment_account_id is None
        # Charges are separate obligations with their own recipients.
        assert GRNCharge.query.filter_by(grn_id=grn.id).count() == 3
        assert len(bd['obligations']) == 4
        # Inventory lots carry the LANDED rate, not the supplier rate.
        item = GRNItem.query.filter_by(grn_id=grn.id).first()
        assert lot_cost_rate(item) == pytest.approx(1565.0)
        assert float(item.landed_unit_cost or 0) == pytest.approx(1565.0)
        assert float(item.price_at_time or 0) == 1500.0  # never overwritten
        # A2: supplier ledger = material qty x rate ONLY.
        supplier = db.session.get(Supplier, sup_id)
        ledger = build_supplier_financial_ledger(supplier)
        assert ledger['total_credit'] == pytest.approx(150000.0)
        assert ledger['total_debit'] == pytest.approx(0.0)
        assert ledger['closing_balance'] == pytest.approx(150000.0)
        # No Cash Flow row for an unpaid receipt.
        rows = collect_cash_flow_rows('2026-01-01', '2026-12-31')
        assert not [r for r in rows if r.get('grn_id') == grn.id]


def _pay(client, grn_id, obligation_key, amount, cash_id, *, reference='', method='Cash'):
    return client.post('/accounts/grn_payments/save', data={
        'grn_id': str(grn_id),
        'obligation_key': obligation_key,
        'amount': str(amount),
        'method': method,
        'payment_account_id': str(cash_id),
        'date_posted': '2026-11-01T09:00',
        'reference': reference,
        'note': '',
        'idempotency_key': '',
    }, follow_redirects=True)


def test_pay_vehicle_then_supplier_then_loading(client, app):
    login(client)
    sup_id, cash_id = seed(app)
    add_grn(client, sup_id, charges=[
        ("VEHICLE_FARE", "Rana Transport", 5000, "TRANSPORTER", "Rana Transport"),
        ("LOADING", "Loading team", 1000, "LABOUR", "Loading Team"),
        ("OTHER", "Misc", 500, "OTHER", "Misc Party"),
    ])
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        bd = grn_breakdown(grn)
        fare = next(c for c in bd['charges'] if c['charge_type'] == 'VEHICLE_FARE')
        loading = next(c for c in bd['charges'] if c['charge_type'] == 'LOADING')
        grn_id, fare_id, loading_id = grn.id, fare['id'], loading['id']

    # 1. Pay the vehicle person ONLY.
    resp = _pay(client, grn_id, f'CHARGE:{fare_id}', 5000, cash_id, reference='FARE-1')
    assert resp.status_code == 200
    assert b'GRN payment' in resp.data
    with app.app_context():
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd['total_cash_paid'] == pytest.approx(5000.0)
        assert bd['supplier_paid'] == 0.0
        assert bd['supplier_remaining'] == pytest.approx(150000.0)
        assert bd['additional_paid'] == pytest.approx(5000.0)
        supplier = db.session.get(Supplier, sup_id)
        ledger = build_supplier_financial_ledger(supplier)
        assert ledger['closing_balance'] == pytest.approx(150000.0), \
            "vehicle payment must NEVER reduce the supplier payable"
        txs = AccountTransaction.query.filter(
            AccountTransaction.grn_id == grn_id,
            AccountTransaction.is_void == False).all()
        assert len(txs) == 1
        assert float(txs[0].amount or 0) == pytest.approx(5000.0)
        assert txs[0].party_type == 'TRANSPORTER'
        assert txs[0].party_name == 'Rana Transport'
        rows = collect_cash_flow_rows('2026-01-01', '2026-12-31')
        grn_rows = [r for r in rows if r.get('grn_id') == grn_id]
        assert len(grn_rows) == 1 and grn_rows[0]['cash_out'] == pytest.approx(5000.0)
        assert grn_rows[0]['section_label'] == 'GRN Payments'

    # 2. Partial supplier payment, then the rest on another voucher.
    _pay(client, grn_id, f'SUPPLIER:{grn_id}', 50000, cash_id, reference='SUP-1')
    _pay(client, grn_id, f'SUPPLIER:{grn_id}', 100000, cash_id, reference='SUP-2')
    # 3. Pay loading.
    _pay(client, grn_id, f'CHARGE:{loading_id}', 1000, cash_id, reference='LOAD-1')
    with app.app_context():
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd['supplier_paid'] == pytest.approx(150000.0)
        assert bd['supplier_remaining'] == 0.0
        assert bd['additional_paid'] == pytest.approx(6000.0)
        # Cash actually paid = 5,000 + 50,000 + 100,000 + 1,000.
        # (Only the unpaid 500 "other" charge is still due.)
        assert bd['total_cash_paid'] == pytest.approx(156000.0)
        assert bd['total_remaining'] == pytest.approx(500.0)
        assert len(bd['payment_rows']) == 4
        supplier = db.session.get(Supplier, sup_id)
        assert build_supplier_financial_ledger(supplier)['closing_balance'] == 0.0
        rows = collect_cash_flow_rows('2026-01-01', '2026-12-31')
        grn_rows = [r for r in rows if r.get('grn_id') == grn_id]
        assert len(grn_rows) == 4
        assert sum(r['cash_out'] for r in grn_rows) == pytest.approx(156000.0)
        # No single cash-flow row ever equals the whole GRN cost: each
        # outgoing is one real payment of its own amount.
        assert all(r['cash_out'] not in (156000.0, 156500.0) for r in grn_rows)
        assert [round(r['cash_out']) for r in sorted(grn_rows, key=lambda x: x['cash_out'])] == [1000, 5000, 50000, 100000]
        # Transporter ledger: 5,000 charge - 5,000 payment = 0.
        party = CashFlowParty.query.filter_by(name='Rana Transport').first()
        assert party is not None
        assert build_party_financial_ledger(party)['closing_balance'] == 0.0
        # Loading ledger: paid, other charge: still payable.
        loading_party = CashFlowParty.query.filter_by(name='Loading Team').first()
        assert build_party_financial_ledger(loading_party)['closing_balance'] == 0.0
        misc = CashFlowParty.query.filter_by(name='Misc Party').first()
        assert build_party_financial_ledger(misc)['closing_balance'] == pytest.approx(500.0)
        assert financial_integrity_audit()['ok'] is True

    # 4. The GRN Payments page renders obligations + history.
    resp = client.get(f'/accounts/grn_payments?grn_id={grn_id}')
    assert resp.status_code == 200
    assert b'PAY EXISTING GRN' in resp.data
    assert b'Rana Transport' in resp.data


def test_expense_charge_is_not_capitalised_and_payment_is_not_expensed(client, app):
    login(client)
    sup_id, cash_id = seed(app)
    add_grn(client, sup_id, charges=[
        ("VEHICLE_FARE", "Rana Transport", 5000, "TRANSPORTER", "Rana Transport"),
        ("OTHER", "Office tea", 700, "OTHER", "Tea Shop", "UNPAID", "EXPENSE"),
    ], bill="LC-GRN-002")
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        bd = grn_breakdown(grn)
        assert bd['landed_cost_total'] == pytest.approx(155000.0)
        assert bd['expense_charge_total'] == pytest.approx(700.0)
        assert bd['capitalised_charge_total'] == pytest.approx(5000.0)
        assert lot_cost_rate(GRNItem.query.filter_by(grn_id=grn.id).first()) == pytest.approx(1550.0)
        # Supplier ledger unaffected by either charge.
        supplier = db.session.get(Supplier, sup_id)
        assert build_supplier_financial_ledger(supplier)['total_credit'] == pytest.approx(150000.0)


def test_overpayment_blocked_void_reverses_and_cancel_preserves_history(client, app):
    login(client)
    sup_id, cash_id = seed(app)
    add_grn(client, sup_id, charges=[
        ("VEHICLE_FARE", "Rana Transport", 5000, "TRANSPORTER", "Rana Transport"),
    ], bill="LC-GRN-003")
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        bd = grn_breakdown(grn)
        fare_id = bd['charges'][0]['id']
        grn_id = grn.id

    resp = _pay(client, grn_id, f'CHARGE:{fare_id}', 6000, cash_id)
    assert b'exceeds the remaining payable' in resp.data
    with app.app_context():
        assert SupplierPayment.query.filter_by(grn_id=grn_id).count() == 0

    _pay(client, grn_id, f'CHARGE:{fare_id}', 5000, cash_id, reference='FARE-3')
    with app.app_context():
        payment = SupplierPayment.query.filter_by(grn_id=grn_id).first()
        payment_id = payment.id
        cash_before = float(db.session.get(Account, cash_id).balance or 0)
    resp = client.post(f'/accounts/grn_payments/{payment_id}/void',
                       data={'reason': 'wrong voucher'}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert float(db.session.get(Account, cash_id).balance or 0) == pytest.approx(cash_before + 5000.0)
        assert db.session.get(SupplierPayment, payment_id).is_void is True
        assert AccountTransaction.query.filter(
            AccountTransaction.source_type == 'GRN_PAYMENT',
            AccountTransaction.source_id == payment_id,
            AccountTransaction.is_void == False).count() == 0
        bd = grn_breakdown(db.session.get(GRN, grn_id))
        assert bd['total_cash_paid'] == 0.0
        assert bd['total_remaining'] == pytest.approx(155000.0)

    # Cancel with a voided payment still present: history preserved.
    resp = client.post('/grn', data={'action': 'delete', 'id': str(grn_id),
                                     'cancel_reason': 'duplicate receipt'},
                       follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        assert grn is not None and grn.is_void is True and grn.is_cancelled is True
        assert db.session.get(SupplierPayment, payment_id) is not None
        assert Material.query.filter_by(name='Cement').first().total == pytest.approx(0.0)


def test_legacy_grn_keeps_historical_cost_and_clean_supplier_ledger(client, app):
    """Migration backfill: legacy charges become unassigned party payables,
    never supplier payables; frozen FIFO cost stays at the supplier rate."""
    login(client)
    with app.app_context():
        sup = Supplier(name='Legacy Supplier', is_active=True)
        db.session.add(sup)
        db.session.flush()
        grn = GRN(supplier='Legacy Supplier', supplier_id=sup.id,
                  manual_bill_no='LEGACY-1', costing_mode='LEGACY',
                  freight_cost=2000.0, loading_cost=500.0,
                  date_posted=__import__('datetime').datetime(2026, 9, 1, 10, 0))
        db.session.add(grn)
        db.session.flush()
        db.session.add(GRNItem(grn_id=grn.id, mat_name='Cement', qty=10, price_at_time=1000))
        db.session.commit()
        sup_id, grn_id = sup.id, grn.id
    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        bd = grn_breakdown(grn)
        assert bd['supplier_material_amount'] == pytest.approx(10000.0)
        assert bd['capitalised_charge_total'] == 0.0  # legacy charges not capitalised
        assert bd['landed_cost_total'] == pytest.approx(10000.0)
        assert lot_cost_rate(grn.items[0]) == pytest.approx(1000.0)
        supplier = db.session.get(Supplier, sup_id)
        assert build_supplier_financial_ledger(supplier)['total_credit'] == pytest.approx(10000.0)


def test_grn_payment_modal_target_redirects_to_dedicated_page(client, app):
    login(client)
    sup_id, cash_id = seed(app)
    add_grn(client, sup_id, bill='LC-GRN-004')
    resp = client.post('/accounts/transactions/new', data={
        'tx_mode': 'pay', 'pay_target': 'grn_payment',
        'amount': '100', 'method': 'Cash',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/accounts/grn_payments' in resp.headers['Location']
    with app.app_context():
        assert SupplierPayment.query.count() == 0
        assert AccountTransaction.query.count() == 0
