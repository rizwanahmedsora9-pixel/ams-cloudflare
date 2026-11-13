"""CRUD, balance invariants, and period/day lock tests for the Loan Register."""
from __future__ import annotations

from datetime import date, datetime

from app.services.cash_flow_svc import collect_cash_flow_rows
from app.services.payments_crud import ledger_balance
from app.services.profit_loss import _Projection
from models import (
    Account,
    AccountReconciliation,
    AccountTransaction,
    AccountingAuditLog,
    CashDayLock,
    LoanMovement,
    LoanParty,
    User,
    db,
)
from utils.money import to_minor


def _login(client, username='Admin', password='Admin@fbm12345'):
    resp = client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def _cash_account(name='Loan Cash', category='cash', balance=1000):
    account = Account(
        name=name,
        type='company',
        account_type='company',
        category=category,
        source_category='Company',
        balance=float(balance),
        balance_minor=to_minor(balance),
        opening_balance=float(balance),
        opening_balance_minor=to_minor(balance),
        opening_balance_date=datetime(2026, 1, 1),
        is_active=True,
    )
    db.session.add(account)
    db.session.flush()
    return account


def test_edit_loan_party_updates_fields_and_syncs_linked_transactions(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(balance=1000)
        party = LoanParty(
            name='Old Lender',
            opening_principal_minor=to_minor(500),
            opening_principal_date=date(2026, 1, 10),
            note='Initial note',
            is_active=True,
        )
        db.session.add(party)
        db.session.commit()
        cash_id, party_id = cash.id, party.id

    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(party_id),
        'movement_type': 'received',
        'amount': '300',
        'cash_account_id': str(cash_id),
        'date_posted': '2026-02-01',
    })
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(party_id),
        'movement_type': 'repaid',
        'amount': '100',
        'cash_account_id': str(cash_id),
        'date_posted': '2026-02-05',
    })

    resp = client.post(f'/accounts/loans/parties/{party_id}/edit', data={
        'name': 'Renamed Lender',
        'opening_principal': '700',
        'opening_date': '2026-01-05',
        'note': 'Updated note',
        'is_active_submitted': '1',
        'is_active': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert 'Lender updated.' in resp.get_data(as_text=True)

    with app.app_context():
        party = db.session.get(LoanParty, party_id)
        assert party.name == 'Renamed Lender'
        assert party.opening_principal_minor == to_minor(700)
        assert party.opening_principal_date == date(2026, 1, 5)
        assert party.note == 'Updated note'
        assert party.is_active is True

        # Cash account unchanged by opening principal edit: 1000 + 300 - 100 = 1200
        assert db.session.get(Account, cash_id).balance_minor == to_minor(1200)

        # Linked AccountTransaction descriptions & party_name follow the rename.
        txs = AccountTransaction.query.filter_by(source_type='LoanPrincipal').order_by(AccountTransaction.id).all()
        assert len(txs) == 2
        assert all(tx.party_name == 'Renamed Lender' for tx in txs)
        assert txs[0].description == 'Loan principal received from Renamed Lender'
        assert txs[1].description == 'Loan principal repaid to Renamed Lender'

        audits = AccountingAuditLog.query.filter_by(
            entity_type='LoanParty', entity_id=party_id, action='Edit'
        ).all()
        assert len(audits) == 1


def test_edit_loan_party_validation_guards(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(balance=1000)
        p1 = LoanParty(
            name='Lender One',
            opening_principal_minor=to_minor(500),
            opening_principal_date=date(2026, 1, 10),
            is_active=True,
        )
        p2 = LoanParty(name='Lender Two', opening_principal_minor=0, is_active=True)
        db.session.add_all([p1, p2])
        db.session.commit()
        cash_id, p1_id = cash.id, p1.id

    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(p1_id),
        'movement_type': 'repaid',
        'amount': '300',
        'cash_account_id': str(cash_id),
        'date_posted': '2026-02-01',
    })

    # Empty name
    r = client.post(f'/accounts/loans/parties/{p1_id}/edit', data={
        'name': '   ', 'opening_principal': '500', 'opening_date': '2026-01-10',
    }, follow_redirects=True)
    assert 'Lender name is required' in r.get_data(as_text=True)

    # Duplicate name (case-insensitive)
    r = client.post(f'/accounts/loans/parties/{p1_id}/edit', data={
        'name': ' lender two ', 'opening_principal': '500', 'opening_date': '2026-01-10',
    }, follow_redirects=True)
    assert 'already exists' in r.get_data(as_text=True)

    # Negative opening principal
    r = client.post(f'/accounts/loans/parties/{p1_id}/edit', data={
        'name': 'Lender One', 'opening_principal': '-10', 'opening_date': '2026-01-10',
    }, follow_redirects=True)
    assert 'cannot be negative' in r.get_data(as_text=True)

    # Positive opening principal without opening date
    r = client.post(f'/accounts/loans/parties/{p1_id}/edit', data={
        'name': 'Lender One', 'opening_principal': '500', 'opening_date': '',
    }, follow_redirects=True)
    assert 'Enter the date for the opening principal balance' in r.get_data(as_text=True)

    # Lowering opening principal below already-repaid amount (300)
    r = client.post(f'/accounts/loans/parties/{p1_id}/edit', data={
        'name': 'Lender One', 'opening_principal': '200', 'opening_date': '2026-01-10',
    }, follow_redirects=True)
    assert 'already been repaid' in r.get_data(as_text=True)

    # Moving opening date later than existing movement (2026-02-01)
    r = client.post(f'/accounts/loans/parties/{p1_id}/edit', data={
        'name': 'Lender One', 'opening_principal': '500', 'opening_date': '2026-02-02',
    }, follow_redirects=True)
    assert 'cannot be later than existing movement' in r.get_data(as_text=True)

    with app.app_context():
        p1 = db.session.get(LoanParty, p1_id)
        assert p1.name == 'Lender One'
        assert p1.opening_principal_minor == to_minor(500)
        assert p1.opening_principal_date == date(2026, 1, 10)

    # Lowering opening principal to exact repaid amount (300) succeeds
    r = client.post(f'/accounts/loans/parties/{p1_id}/edit', data={
        'name': 'Lender One', 'opening_principal': '300', 'opening_date': '2026-01-10',
    }, follow_redirects=True)
    assert 'Lender updated.' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanParty, p1_id).opening_principal_minor == to_minor(300)


def test_toggle_and_delete_loan_party_lifecycle(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(balance=1000)
        unused = LoanParty(name='Unused Lender', opening_principal_minor=0, is_active=True)
        used = LoanParty(name='Used Lender', opening_principal_minor=0, is_active=True)
        db.session.add_all([unused, used])
        db.session.commit()
        cash_id, unused_id, used_id = cash.id, unused.id, used.id

    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(used_id),
        'movement_type': 'received',
        'amount': '250',
        'cash_account_id': str(cash_id),
        'date_posted': '2026-11-05',
    })
    with app.app_context():
        mov_id = LoanMovement.query.filter_by(loan_party_id=used_id).one().id

    # Deactivate Used Lender
    r = client.post(f'/accounts/loans/parties/{used_id}/toggle', follow_redirects=True)
    assert 'Lender deactivated.' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanParty, used_id).is_active is False

    # Cannot record NEW movement for inactive lender
    r = client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(used_id),
        'movement_type': 'received',
        'amount': '100',
        'cash_account_id': str(cash_id),
        'date_posted': '2026-11-06',
    }, follow_redirects=True)
    assert 'Select an active lender' in r.get_data(as_text=True)

    # Cannot delete Used Lender while movements exist
    r = client.post(f'/accounts/loans/parties/{used_id}/delete', follow_redirects=True)
    assert 'cannot be deleted' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanParty, used_id) is not None

    # Can still edit existing movement of inactive lender if keeping the same lender
    r = client.post(f'/accounts/loans/movements/{mov_id}/edit', data={
        'loan_party_id': str(used_id),
        'movement_type': 'received',
        'amount': '300',
        'cash_account_id': str(cash_id),
        'date_posted': '2026-11-05',
        'note': 'Edited while inactive',
    }, follow_redirects=True)
    assert 'Loan principal movement updated.' in r.get_data(as_text=True)

    # Reactivate Used Lender
    r = client.post(f'/accounts/loans/parties/{used_id}/toggle', follow_redirects=True)
    assert 'Lender activated.' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanParty, used_id).is_active is True

    # Delete Unused Lender succeeds
    r = client.post(f'/accounts/loans/parties/{unused_id}/delete', follow_redirects=True)
    assert 'Lender deleted from the loan register.' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanParty, unused_id) is None

    # Delete Used Lender's movement, then delete Used Lender succeeds
    r = client.post(f'/accounts/loans/movements/{mov_id}/delete', follow_redirects=True)
    assert 'deleted' in r.get_data(as_text=True).lower()
    r = client.post(f'/accounts/loans/parties/{used_id}/delete', follow_redirects=True)
    assert 'Lender deleted from the loan register.' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanParty, used_id) is None
        assert db.session.get(Account, cash_id).balance_minor == to_minor(1000)


def test_edit_loan_movement_updates_amount_type_accounts_lender_and_cash_flow(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(name='Cash Box', category='cash', balance=1000)
        bank = _cash_account(name='Meezan Bank', category='bank', balance=500)
        lender1 = LoanParty(
            name='Lender Alpha', opening_principal_minor=to_minor(100),
            opening_principal_date=date(2026, 1, 1), is_active=True,
        )
        lender2 = LoanParty(
            name='Lender Beta', opening_principal_minor=to_minor(200),
            opening_principal_date=date(2026, 1, 1), is_active=True,
        )
        db.session.add_all([lender1, lender2])
        db.session.commit()
        cash_id, bank_id, l1_id, l2_id = cash.id, bank.id, lender1.id, lender2.id

    # M1: receive 400 into Cash Box for Lender Alpha
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(l1_id),
        'movement_type': 'received',
        'amount': '400',
        'cash_account_id': str(cash_id),
        'date_posted': '2026-11-05',
        'reference': 'LN-101',
        'note': 'Initial receipt',
    })
    with app.app_context():
        m1 = LoanMovement.query.one()
        m1_id = m1.id
        orig_tx_id = m1.account_tx_id
        orig_dt = m1.date_posted
        assert db.session.get(Account, cash_id).balance_minor == to_minor(1400)

    # Edit M1: amount 400 -> 600, switch account Cash Box -> Meezan Bank, date -> 2026-11-06
    resp = client.post(f'/accounts/loans/movements/{m1_id}/edit', data={
        'loan_party_id': str(l1_id),
        'movement_type': 'received',
        'amount': '600',
        'cash_account_id': str(bank_id),
        'date_posted': '2026-11-06',
        'reference': 'LN-101-REV',
        'note': 'Moved to bank',
    }, follow_redirects=True)
    assert 'Loan principal movement updated.' in resp.get_data(as_text=True)

    with app.app_context():
        m1 = db.session.get(LoanMovement, m1_id)
        assert m1.account_tx_id == orig_tx_id
        assert m1.amount_minor == to_minor(600)
        assert m1.cash_account_id == bank_id
        assert m1.reference == 'LN-101-REV'
        assert m1.note == 'Moved to bank'
        assert db.session.get(Account, cash_id).balance_minor == to_minor(1000)
        assert db.session.get(Account, bank_id).balance_minor == to_minor(1100)
        assert ledger_balance(cash_id) == 1000.0
        assert ledger_balance(bank_id) == 1100.0
        assert AccountTransaction.query.filter_by(is_void=True).count() == 0

    # Record M2: repay 200 from Meezan Bank for Lender Alpha
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(l1_id),
        'movement_type': 'repaid',
        'amount': '200',
        'cash_account_id': str(bank_id),
        'date_posted': '2026-11-07',
        'reference': 'LN-102',
    })
    with app.app_context():
        m2 = LoanMovement.query.filter(LoanMovement.id != m1_id).one()
        m2_id = m2.id
        m2_orig_dt = m2.date_posted
        assert db.session.get(Account, bank_id).balance_minor == to_minor(900)

    # Edit M2: metadata-only edit keeps exact timestamp
    client.post(f'/accounts/loans/movements/{m2_id}/edit', data={
        'loan_party_id': str(l1_id),
        'movement_type': 'repaid',
        'amount': '200',
        'cash_account_id': str(bank_id),
        'date_posted': '2026-11-07',
        'reference': 'LN-102-A',
        'note': 'Ref updated only',
    })
    with app.app_context():
        m2 = db.session.get(LoanMovement, m2_id)
        assert m2.date_posted == m2_orig_dt

    # Edit M2: change lender to Lender Beta, flip repaid 200 -> received 150 into Cash Box
    resp = client.post(f'/accounts/loans/movements/{m2_id}/edit', data={
        'loan_party_id': str(l2_id),
        'movement_type': 'received',
        'amount': '150',
        'cash_account_id': str(cash_id),
        'date_posted': '2026-11-08',
        'reference': 'LN-102-FLIP',
        'note': 'Flipped to receipt on Beta',
    }, follow_redirects=True)
    assert 'Loan principal movement updated.' in resp.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(Account, cash_id).balance_minor == to_minor(1150)
        assert db.session.get(Account, bank_id).balance_minor == to_minor(1100)
        assert ledger_balance(cash_id) == 1150.0
        assert ledger_balance(bank_id) == 1100.0

        from app.services.loan_register import outstanding_minor
        # Lender Alpha: opening 100 + M1 600 = 700
        assert outstanding_minor(l1_id) == to_minor(700)
        # Lender Beta: opening 200 + M2 150 = 350
        assert outstanding_minor(l2_id) == to_minor(350)

        # Cash Flow sees updated rows
        cf_rows = collect_cash_flow_rows(date(2026, 11, 1), date(2026, 11, 10))
        loan_cf = [r for r in cf_rows if r.get('source_type') == 'LoanPrincipal']
        assert len(loan_cf) == 2
        assert {r['party_name'] for r in loan_cf} == {'Lender Alpha', 'Lender Beta'}
        assert sum(r['cash_in'] for r in loan_cf) == 750.0
        assert sum(r['cash_out'] for r in loan_cf) == 0.0

        # P&L still excludes all LoanPrincipal rows
        proj = _Projection().build()
        loan_tx_ids = {tx.id for tx in AccountTransaction.query.filter_by(source_type='LoanPrincipal').all()}
        assert not any(
            row.get('document_type') == 'AccountTransaction'
            and row.get('document_id') in loan_tx_ids
            for row in proj.rows
        )


def test_edit_loan_movement_rejects_invalid_balances_dates_and_repayments(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(name='Guard Cash', category='cash', balance=100)
        bank = _cash_account(name='Guard Bank', category='bank', balance=500)
        lender1 = LoanParty(
            name='Guard Lender 1', opening_principal_minor=0,
            opening_principal_date=date(2026, 2, 1), is_active=True,
        )
        lender2 = LoanParty(
            name='Guard Lender 2', opening_principal_minor=0,
            opening_principal_date=date(2026, 2, 1), is_active=True,
        )
        db.session.add_all([lender1, lender2])
        db.session.commit()
        cash_id, bank_id, l1_id, l2_id = cash.id, bank.id, lender1.id, lender2.id

    # M1: receive 500 into Guard Cash (balance 100 -> 600)
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(l1_id), 'movement_type': 'received',
        'amount': '500', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-05',
    })
    # M2: repay 300 from Guard Cash (balance 600 -> 300)
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(l1_id), 'movement_type': 'repaid',
        'amount': '300', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-06',
    })
    # Spend 200 out of Guard Cash (balance 300 -> 100) so Guard Cash only has 100 left
    with app.app_context():
        acc = db.session.get(Account, cash_id)
        acc.balance = 100.0
        acc.balance_minor = to_minor(100)
        db.session.commit()
        m1_id, m2_id = [m.id for m in LoanMovement.query.order_by(LoanMovement.id).all()]

    # 1. Zero amount rejected
    r = client.post(f'/accounts/loans/movements/{m1_id}/edit', data={
        'loan_party_id': str(l1_id), 'movement_type': 'received',
        'amount': '0', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-05',
    }, follow_redirects=True)
    assert 'greater than zero' in r.get_data(as_text=True)

    # 2. Date before lender opening balance date rejected
    r = client.post(f'/accounts/loans/movements/{m1_id}/edit', data={
        'loan_party_id': str(l1_id), 'movement_type': 'received',
        'amount': '500', 'cash_account_id': str(cash_id), 'date_posted': '2026-01-15',
    }, follow_redirects=True)
    assert 'cannot be earlier than the lender opening balance date' in r.get_data(as_text=True)

    # 3. Repay more than outstanding principal rejected (outstanding is 200 + old_repay 300 = 500)
    r = client.post(f'/accounts/loans/movements/{m2_id}/edit', data={
        'loan_party_id': str(l1_id), 'movement_type': 'repaid',
        'amount': '600', 'cash_account_id': str(bank_id), 'date_posted': '2026-11-06',
    }, follow_redirects=True)
    assert 'greater than the outstanding loan principal' in r.get_data(as_text=True)

    # 4. Reduce received amount below existing repayments (300) rejected
    r = client.post(f'/accounts/loans/movements/{m1_id}/edit', data={
        'loan_party_id': str(l1_id), 'movement_type': 'received',
        'amount': '200', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-05',
    }, follow_redirects=True)
    assert 'existing repayments' in r.get_data(as_text=True)

    # 5. Move receipt to another lender when repayments depend on it rejected
    r = client.post(f'/accounts/loans/movements/{m1_id}/edit', data={
        'loan_party_id': str(l2_id), 'movement_type': 'received',
        'amount': '500', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-05',
    }, follow_redirects=True)
    assert 'existing repayments' in r.get_data(as_text=True)

    # 6. Move receipt from Guard Cash (only 100 available) to Guard Bank -> would make Guard Cash -400 -> rejected
    # First lower repayment M2 to 0? No, test with another party/receipt directly:
    with app.app_context():
        l3 = LoanParty(name='Guard Lender 3', opening_principal_minor=0, is_active=True)
        db.session.add(l3)
        db.session.commit()
        l3_id = l3.id
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(l3_id), 'movement_type': 'received',
        'amount': '300', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-06',
    })
    # Guard Cash now has 100 + 300 = 400; simulate 350 spent leaving 50
    with app.app_context():
        acc = db.session.get(Account, cash_id)
        acc.balance = 50.0
        acc.balance_minor = to_minor(50)
        db.session.commit()
        m3_id = LoanMovement.query.filter_by(loan_party_id=l3_id).one().id

    r = client.post(f'/accounts/loans/movements/{m3_id}/edit', data={
        'loan_party_id': str(l3_id), 'movement_type': 'received',
        'amount': '300', 'cash_account_id': str(bank_id), 'date_posted': '2026-11-06',
    }, follow_redirects=True)
    assert 'Insufficient balance' in r.get_data(as_text=True)

    # 7. Increasing repayment M2 on Guard Cash (balance 50) from 300 to 400 -> rejected
    r = client.post(f'/accounts/loans/movements/{m2_id}/edit', data={
        'loan_party_id': str(l1_id), 'movement_type': 'repaid',
        'amount': '400', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-06',
    }, follow_redirects=True)
    assert 'Insufficient balance' in r.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(Account, cash_id).balance_minor == to_minor(50)
        assert db.session.get(Account, bank_id).balance_minor == to_minor(500)


def test_delete_loan_movement_reverses_balances_and_hard_deletes_without_voids(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(name='Delete Test Cash', category='cash', balance=100)
        party = LoanParty(name='Delete Test Lender', opening_principal_minor=0, is_active=True)
        db.session.add(party)
        db.session.commit()
        cash_id, party_id = cash.id, party.id

    # Receive 500 -> balance 600, then repay 200 -> balance 400
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(party_id), 'movement_type': 'received',
        'amount': '500', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-05',
    })
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(party_id), 'movement_type': 'repaid',
        'amount': '200', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-06',
    })
    with app.app_context():
        m_recv, m_rep = LoanMovement.query.order_by(LoanMovement.id).all()
        recv_id, rep_id = m_recv.id, m_rep.id
        recv_tx_id, rep_tx_id = m_recv.account_tx_id, m_rep.account_tx_id
        assert db.session.get(Account, cash_id).balance_minor == to_minor(400)

    # Cannot delete receipt while repayment still depends on it
    r = client.post(f'/accounts/loans/movements/{recv_id}/delete', follow_redirects=True)
    assert 'repayments would exceed' in r.get_data(as_text=True)

    # Delete repayment first -> cash returns to 600, outstanding returns to 500
    r = client.post(f'/accounts/loans/movements/{rep_id}/delete', follow_redirects=True)
    assert 'deleted and cash/bank balance reversed' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanMovement, rep_id) is None
        assert db.session.get(AccountTransaction, rep_tx_id) is None
        assert db.session.get(Account, cash_id).balance_minor == to_minor(600)
        assert ledger_balance(cash_id) == 600.0
        from app.services.loan_register import outstanding_minor
        assert outstanding_minor(party_id) == to_minor(500)
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).fetchall() == []

    # Simulate cash balance dropping below 500 -> deleting receipt must be rejected
    with app.app_context():
        acc = db.session.get(Account, cash_id)
        acc.balance = 200.0
        acc.balance_minor = to_minor(200)
        db.session.commit()
    r = client.post(f'/accounts/loans/movements/{recv_id}/delete', follow_redirects=True)
    assert 'only has' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanMovement, recv_id) is not None

    # Restore cash balance to 600 -> deleting receipt succeeds cleanly with zero voided leftovers
    with app.app_context():
        acc = db.session.get(Account, cash_id)
        acc.balance = 600.0
        acc.balance_minor = to_minor(600)
        db.session.commit()
    r = client.post(f'/accounts/loans/movements/{recv_id}/delete', follow_redirects=True)
    assert 'deleted and cash/bank balance reversed' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanMovement, recv_id) is None
        assert db.session.get(AccountTransaction, recv_tx_id) is None
        assert AccountTransaction.query.count() == 0
        assert db.session.get(Account, cash_id).balance_minor == to_minor(100)
        assert ledger_balance(cash_id) == 100.0
        assert AccountingAuditLog.query.filter_by(entity_type='LoanMovement', action='Delete').count() == 2
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).fetchall() == []


def test_loan_movement_edit_and_delete_respect_reconciled_period_and_locked_day(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(name='Lock Loan Cash', category='cash', balance=1000)
        party = LoanParty(name='Lock Loan Lender', opening_principal_minor=0, is_active=True)
        db.session.add(party)
        db.session.commit()
        cash_id, party_id = cash.id, party.id

    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(party_id), 'movement_type': 'received',
        'amount': '400', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-05',
    })
    with app.app_context():
        mov_id = LoanMovement.query.one().id
        db.session.add(AccountReconciliation(
            account_id=cash_id,
            reconciliation_date=date(2026, 11, 6),
            expected_balance=1400.0,
            actual_balance=1400.0,
            difference=0.0,
            difference_type='Matched',
        ))
        db.session.commit()

    # Accounting edit in reconciled period is blocked
    r = client.post(f'/accounts/loans/movements/{mov_id}/edit', data={
        'loan_party_id': str(party_id), 'movement_type': 'received',
        'amount': '450', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-05',
    }, follow_redirects=True)
    assert 'reconciled period' in r.get_data(as_text=True)

    # Delete in reconciled period is blocked
    r = client.post(f'/accounts/loans/movements/{mov_id}/delete', follow_redirects=True)
    assert 'reconciled period' in r.get_data(as_text=True)

    # Metadata-only note/ref edit still allowed
    r = client.post(f'/accounts/loans/movements/{mov_id}/edit', data={
        'loan_party_id': str(party_id), 'movement_type': 'received',
        'amount': '400', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-05',
        'reference': 'VCH-9', 'note': 'Label fix only',
    }, follow_redirects=True)
    assert 'Loan principal movement updated.' in r.get_data(as_text=True)

    # Now test CashDayLock on a new open-period movement
    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(party_id), 'movement_type': 'received',
        'amount': '200', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-08',
    })
    with app.app_context():
        mov2_id = LoanMovement.query.order_by(LoanMovement.id.desc()).first().id
        db.session.add(CashDayLock(
            lock_date=date(2026, 11, 8),
            total_expected=1600.0,
            total_counted=1600.0,
            difference=0.0,
            locked_by='Admin',
        ))
        db.session.commit()

    r = client.post(f'/accounts/loans/movements/{mov2_id}/edit', data={
        'loan_party_id': str(party_id), 'movement_type': 'received',
        'amount': '250', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-08',
    }, follow_redirects=True)
    assert 'finalised in the daily reconciliation' in r.get_data(as_text=True)

    r = client.post(f'/accounts/loans/movements/{mov2_id}/delete', follow_redirects=True)
    assert 'finalised in the daily reconciliation' in r.get_data(as_text=True)

    # Creating a new movement inside the locked day is also blocked
    r = client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(party_id), 'movement_type': 'received',
        'amount': '100', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-08',
    }, follow_redirects=True)
    assert 'finalised in the daily reconciliation' in r.get_data(as_text=True)


def test_loan_register_ui_account_ledger_links_and_read_only_guard(app, client):
    from werkzeug.security import generate_password_hash

    _login(client)
    with app.app_context():
        cash = _cash_account(name='UI Cash', category='cash', balance=1000)
        lender = LoanParty(name='UI Lender', opening_principal_minor=0, is_active=True)
        unused_lender = LoanParty(name='UI Unused Lender', opening_principal_minor=0, is_active=True)
        ro_user = User(
            username='viewer',
            role='user',
            status='active',
            password_hash=generate_password_hash('Viewer@12345'),
            can_manage_accounts=True,
            access_mode='read_only',
        )
        db.session.add_all([lender, unused_lender, ro_user])
        db.session.commit()
        cash_id, lender_id, unused_lender_id = cash.id, lender.id, unused_lender.id

    client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(lender_id), 'movement_type': 'received',
        'amount': '250', 'cash_account_id': str(cash_id), 'date_posted': '2026-11-10',
        'reference': 'UI-1',
    })
    with app.app_context():
        mov = LoanMovement.query.one()
        mov_id, tx_id = mov.id, mov.account_tx_id

    page = client.get('/accounts/loans')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert f'/accounts/loans/parties/{lender_id}/edit' in html
    assert f'/accounts/loans/parties/{lender_id}/toggle' in html
    assert f'/accounts/loans/parties/{unused_lender_id}/delete' in html
    assert "Delete this lender&#39;s movements first" in html or "Delete this lender's movements first" in html
    assert f'/accounts/loans/movements/{mov_id}/edit' in html
    assert f'/accounts/loans/movements/{mov_id}/delete' in html
    assert 'editLoanPartyModal' in html
    assert 'editLoanMovementModal' in html

    filtered = client.get(f'/accounts/loans?party_id={lender_id}')
    assert filtered.status_code == 200
    assert 'UI-1' in filtered.get_data(as_text=True)

    ledger = client.get(f'/accounts/ledger/{cash_id}')
    assert ledger.status_code == 200
    ledger_html = ledger.get_data(as_text=True)
    assert 'Manage in Loan Register' in ledger_html
    assert f'/accounts/transactions/{tx_id}/void' not in ledger_html

    # Direct AccountTransaction delete/edit still blocked for LoanPrincipal
    r = client.post(f'/accounts/transactions/{tx_id}/delete', follow_redirects=True)
    assert 'dedicated module' in r.get_data(as_text=True)

    # Read-only user cannot mutate loan parties or movements
    client.post('/logout')
    _login(client, username='viewer', password='Viewer@12345')
    r = client.post(f'/accounts/loans/parties/{lender_id}/edit', data={
        'name': 'Hacked Name', 'opening_principal': '0',
    }, follow_redirects=True)
    assert 'READ-ONLY' in r.get_data(as_text=True)
    r = client.post(f'/accounts/loans/movements/{mov_id}/delete', follow_redirects=True)
    assert 'READ-ONLY' in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(LoanParty, lender_id).name == 'UI Lender'
        assert db.session.get(LoanMovement, mov_id) is not None
