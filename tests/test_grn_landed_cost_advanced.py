"""Advanced scenarios: allocation, FIFO layer costs, expense charges, edits,
cancellation guards, supplier-ledger shift and historical safety."""
from __future__ import annotations

import pytest

from models import (
    db, GRN, GRNItem, GRNCharge, Supplier, Material, Account, CashFlowParty,
    SupplierPayment, AccountTransaction,
)
from app.services.grn_costing import grn_breakdown, lot_cost_rate
from app.services.financial_ledgers import build_supplier_financial_ledger

LOGIN = {"username": "Admin", "password": "Admin@fbm12345"}


@pytest.fixture()
def app(app_factory):
    return app_factory(AUTO_RECONCILE_ENABLED='0', BACKUP_EMBEDDED_SCHEDULER='0')


@pytest.fixture()
def client(app):
    from tests.conftest import make_csrf_client
    return make_csrf_client(app)


def _seed(app, extra_material=None):
    with app.app_context():
        sup = Supplier(name='Build Co', is_active=True)
        mats = [Material(code='M1', name='Cement', total=0.0)]
        if extra_material:
            mats.append(Material(code='M2', name=extra_material, total=0.0))
        cash = Account(name='CASH', type='Cash', account_type='company',
                       category='cash', balance=1000000.0,
                       balance_minor=100000000, is_active=True)
        db.session.add_all([sup, cash] + mats)
        db.session.commit()
        return sup.id, cash.id


def _login(client):
    assert client.post('/login', data=LOGIN, follow_redirects=True).status_code == 200


def _post_grn(client, sup_id, *, items, charges, bill='ADV-1', date='2026-10-20',
              edit_id=None):
    data = {
        'action': 'add',
        'supplier': 'Build Co', 'supplier_id': str(sup_id),
        'date': date, 'time': '10:00', 'manual_bill_no': bill,
        'mat_name[]': [n for n, q, r in items],
        'qty[]': [str(q) for n, q, r in items],
        'price[]': [str(r) for n, q, r in items],
        'allocation_basis_default': 'VALUE',
        'charge_type[]': [c[0] for c in charges],
        'charge_label[]': [c[1] for c in charges],
        'charge_amount[]': [str(c[2]) for c in charges],
        'charge_recipient_type[]': [c[3] for c in charges],
        'charge_recipient[]': [c[4] for c in charges],
        'charge_status[]': [c[5] if len(c) > 5 else 'UNPAID' for c in charges],
        'charge_treatment[]': [c[6] if len(c) > 6 else 'INVENTORY' for c in charges],
        'charge_basis[]': [c[7] if len(c) > 7 else 'VALUE' for c in charges],
        'charge_id[]': [''] * len(charges),
        'charge_note[]': [''] * len(charges),
    }
    if edit_id:
        return client.post(f'/edit_grn/{edit_id}', data=data, follow_redirects=True)
    return client.post('/grn', data=data, follow_redirects=True)


def test_multi_material_allocation_by_value_is_exact(client, app):
    _login(client)
    sup_id, _ = _seed(app, extra_material='Steel')
    resp = _post_grn(client, sup_id,
                     items=[('Cement', 100, 1500), ('Steel', 10, 20000)],
                     charges=[('VEHICLE_FARE', 'Transport', 7000, 'TRANSPORTER', 'Trans Co')])
    assert b'GRN added successfully' in resp.data
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        bd = grn_breakdown(grn)
        assert bd['supplier_material_amount'] == pytest.approx(350000.0)
        assert bd['landed_cost_total'] == pytest.approx(357000.0)
        assert sum(l['line_landed_cost'] for l in bd['per_line']) == pytest.approx(357000.0)
        by_name = {l['material']: l for l in bd['per_line']}
        assert by_name['Cement']['allocated_charges'] == pytest.approx(3000.0)
        assert by_name['Steel']['allocated_charges'] == pytest.approx(4000.0)
        assert by_name['Cement']['landed_unit_cost'] == pytest.approx(1530.0)
        assert by_name['Steel']['landed_unit_cost'] == pytest.approx(20400.0)
        # Supplier ledger still contains only material qty x rate.
        assert build_supplier_financial_ledger(
            db.session.get(Supplier, sup_id))['total_credit'] == pytest.approx(350000.0)


def test_fifo_keeps_each_grns_own_landed_rate(client, app):
    _login(client)
    sup_id, _ = _seed(app)
    _post_grn(client, sup_id, items=[('Cement', 100, 1500)],
              charges=[('VEHICLE_FARE', 'T', 5000, 'TRANSPORTER', 'T')],
              bill='FIFO-1', date='2026-10-10')
    _post_grn(client, sup_id, items=[('Cement', 100, 1600)],
              charges=[], bill='FIFO-2', date='2026-10-12')
    with app.app_context():
        from app.services.sales_core import _grn_fifo_lots_for_material
        lots = _grn_fifo_lots_for_material('Cement')
        rates = [round(rate, 2) for _, _, rate in lots]
        assert rates == [1550.0, 1600.0], rates
        # A sale of 150 bags must consume 100 @ 1550 and 50 @ 1600.
        from app.services.sales_core import _allocate_grn_fifo_plan
        plan = _allocate_grn_fifo_plan('Cement', 150)
        assert [round(p['cost_rate'], 2) for p in plan] == [1550.0, 1600.0]
        assert [p['qty'] for p in plan] == [100.0, 50.0]


def test_expense_charge_is_one_pnl_expense_row_and_never_cogs(client, app):
    _login(client)
    sup_id, cash_id = _seed(app)
    _post_grn(client, sup_id, items=[('Cement', 100, 1500)],
              charges=[('OTHER', 'Office supplies', 900, 'OTHER', 'Shop', 'UNPAID', 'EXPENSE')])
    with app.app_context():
        from app.services.profit_loss import _Projection
        proj = _Projection().build()
        expense_rows = [r for r in proj.rows if r.get('source') == 'GRNCharge']
        assert len(expense_rows) == 1
        assert expense_rows[0]['expense'] == pytest.approx(900.0)
        assert expense_rows[0]['entry_type'] == 'expense'
        # No cash movement was generated by the GRN.
        assert AccountTransaction.query.filter(
            AccountTransaction.grn_id == proj.grns[0].id).count() == 0
        grn = proj.grns[0]
        assert grn_breakdown(grn)['landed_cost_total'] == pytest.approx(150000.0)


def test_charge_cannot_be_edited_after_it_has_been_paid(client, app):
    _login(client)
    sup_id, cash_id = _seed(app)
    _post_grn(client, sup_id, items=[('Cement', 100, 1500)],
              charges=[('VEHICLE_FARE', 'T', 5000, 'TRANSPORTER', 'T')])
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        gid, charge_id = grn.id, grn_breakdown(grn)['charges'][0]['id']
    resp = client.post('/accounts/grn_payments/save', data={
        'grn_id': str(gid), 'obligation_key': f'CHARGE:{charge_id}',
        'amount': '2000', 'method': 'Cash', 'payment_account_id': str(cash_id),
        'date_posted': '2026-11-01T09:00',
    }, follow_redirects=True)
    assert resp.status_code == 200
    # Attempt to change the charge amount on the GRN.
    resp = _post_grn(client, sup_id, items=[('Cement', 100, 1500)],
                     charges=[('VEHICLE_FARE', 'T', 9000, 'TRANSPORTER', 'T')],
                     edit_id=gid)
    assert b'already has payments' in resp.data
    with app.app_context():
        charge = db.session.get(GRNCharge, charge_id)
        assert float(charge.amount or 0) == pytest.approx(5000.0)
        assert SupplierPayment.query.filter_by(grn_id=gid).count() == 1


def test_cancel_blocked_when_payment_is_active(client, app):
    _login(client)
    sup_id, cash_id = _seed(app)
    _post_grn(client, sup_id, items=[('Cement', 100, 1500)],
              charges=[('VEHICLE_FARE', 'T', 5000, 'TRANSPORTER', 'T')])
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        gid, charge_id = grn.id, grn_breakdown(grn)['charges'][0]['id']
    client.post('/accounts/grn_payments/save', data={
        'grn_id': str(gid), 'obligation_key': f'CHARGE:{charge_id}',
        'amount': '5000', 'method': 'Cash', 'payment_account_id': str(cash_id),
        'date_posted': '2026-11-01T09:00',
    }, follow_redirects=True)
    resp = client.post('/grn', data={'action': 'delete', 'id': str(gid)},
                       follow_redirects=True)
    assert b'payment(s) recorded in Accounts' in resp.data
    with app.app_context():
        grn = db.session.get(GRN, gid)
        assert grn.is_void is False
        assert Material.query.filter_by(name='Cement').first().total == pytest.approx(100.0)


def test_supplier_shift_does_not_move_transporter_payment(client, app):
    _login(client)
    sup_id, cash_id = _seed(app)
    _post_grn(client, sup_id, items=[('Cement', 100, 1500)],
              charges=[('VEHICLE_FARE', 'T', 5000, 'TRANSPORTER', 'Rana')])
    with app.app_context():
        target = Supplier(name='Build Co 2', is_active=True)
        db.session.add(target)
        db.session.commit()
        target_id = target.id
        grn = GRN.query.order_by(GRN.id.desc()).first()
        gid, charge_id = grn.id, grn_breakdown(grn)['charges'][0]['id']
    client.post('/accounts/grn_payments/save', data={
        'grn_id': str(gid), 'obligation_key': f'CHARGE:{charge_id}',
        'amount': '5000', 'method': 'Cash', 'payment_account_id': str(cash_id),
        'date_posted': '2026-11-01T09:00',
    }, follow_redirects=True)
    with app.app_context():
        from app.services.supplier_ledger_shift import preview_supplier_ledger_shift
        source = db.session.get(Supplier, sup_id)
        preview = preview_supplier_ledger_shift(source, db.session.get(Supplier, target_id))
        # Only the supplier's own material obligation is in scope; the
        # transporter payment must not be listed as a payment to move.
        assert preview['payments_total'] == pytest.approx(0.0)
        payment = SupplierPayment.query.filter_by(grn_id=gid).one()
        assert payment.recipient_type == 'TRANSPORTER'
        assert payment.supplier_id == sup_id  # context FK only
