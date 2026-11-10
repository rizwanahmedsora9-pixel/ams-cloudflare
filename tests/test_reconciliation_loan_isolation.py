from datetime import date, datetime

import pytest

from models import (
    Account, AccountTransaction, CashDayDifference, LoanMovement, LoanParty,
    Settings, db,
)
from app.services.loan_register import outstanding_minor, record_principal_movement
from app.services.recon_counter import ensure_counter_accounts, post_difference
from utils.money import to_minor


def _login(client):
    response = client.post(
        '/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _cash_account(name='Register Test Cash', balance=1000):
    account = Account(
        name=name, type='company', account_type='company', category='cash',
        source_category='Company', balance=float(balance), balance_minor=to_minor(balance),
        opening_balance=float(balance), opening_balance_minor=to_minor(balance),
        opening_balance_date=datetime(2026, 1, 1), is_active=True,
    )
    db.session.add(account)
    db.session.flush()
    return account


def test_reconciliation_postings_and_resolutions_are_excluded_from_profit_loss(app):
    with app.app_context():
        cash = _cash_account(balance=1000)
        db.session.add(Settings())
        db.session.flush()
        difference = CashDayDifference(
            position_date=date(2026, 11, 8), account_id=cash.id,
            account_name=cash.name, kind='less', expected=1000,
            counted=900, difference=-100,
        )
        db.session.add(difference)
        db.session.commit()

        ok, _ = post_difference(difference, actor='test')
        assert ok
        db.session.commit()
        posted_ids = {difference.posted_out_tx_id, difference.posted_in_tx_id}
        assert len(posted_ids) == 2
        assert cash.balance_minor == to_minor(900)

        from app.services.recon_counter import resolve_difference
        resolution = resolve_difference(
            difference, kind='recovered_less', note='Cash found and returned', actor='test'
        )
        db.session.commit()
        posted_ids.add(resolution.id)

        from app.services.profit_loss import _Projection
        projection = _Projection().build()
        assert not any(
            row.get('document_type') == 'AccountTransaction'
            and row.get('document_id') in posted_ids
            for row in projection.rows
        )
        assert cash.balance_minor == to_minor(1000)


def test_counter_accounts_are_hidden_and_rejected_by_manual_accounts_entry(app, client):
    _login(client)
    with app.app_context():
        db.session.add(Settings())
        db.session.flush()
        less, excess = ensure_counter_accounts()
        db.session.commit()
        counter_id = less.id

    response = client.get('/accounts/accounts')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Counter Less Account' not in html
    assert 'Counter Excess Account' not in html

    response = client.post('/accounts/transactions/new', data={
        'tx_mode': 'pay', 'pay_target': 'other_expense',
        'pay_from_account_id': str(counter_id), 'amount': '1',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert 'system-only' in response.get_data(as_text=True).lower()
    with app.app_context():
        assert AccountTransaction.query.count() == 0


def test_loan_register_records_principal_cash_movements_without_pnl(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(balance=1000)
        lender = LoanParty(name='Test Lender', opening_principal_minor=to_minor(50), is_active=True)
        db.session.add(lender)
        db.session.commit()
        cash_id, lender_id = cash.id, lender.id

        received, created = record_principal_movement(
            loan_party_id=lender_id, movement_type='received', amount='500',
            cash_account_id=cash_id, date_posted=datetime(2026, 11, 9),
            reference='LN-1', idempotency_key='loan-test-receive', actor='test',
        )
        assert created
        db.session.commit()
        replay, created_again = record_principal_movement(
            loan_party_id=lender_id, movement_type='received', amount='500',
            cash_account_id=cash_id, date_posted=datetime(2026, 11, 9),
            reference='LN-1', idempotency_key='loan-test-receive', actor='test',
        )
        assert replay.id == received.id and not created_again
        db.session.commit()

        repaid, created = record_principal_movement(
            loan_party_id=lender_id, movement_type='repaid', amount='125',
            cash_account_id=cash_id, date_posted=datetime(2026, 11, 9),
            reference='LN-2', idempotency_key='loan-test-repay', actor='test',
        )
        assert created
        db.session.commit()

        assert outstanding_minor(lender_id) == to_minor(425)
        assert db.session.get(Account, cash_id).balance_minor == to_minor(1375)
        loan_txs = AccountTransaction.query.filter_by(source_type='LoanPrincipal').order_by(AccountTransaction.id).all()
        assert len(loan_txs) == 2
        assert {tx.transaction_type for tx in loan_txs} == {'Receipt', 'Payment'}

        legacy_loan = Account(
            name='Legacy Lender Account', type='loan', account_type='loan',
            category='ledger', source_category='Loan', balance=-100,
            balance_minor=to_minor(-100), is_active=True,
        )
        db.session.add(legacy_loan)
        db.session.flush()
        legacy_tx = AccountTransaction(
            from_account_id=cash_id, to_account_id=legacy_loan.id, amount=10,
            amount_minor=to_minor(10), description='Principal settlement',
            transaction_type='Payment', date_posted=datetime(2026, 11, 9),
        )
        legacy_receipt = AccountTransaction(
            to_account_id=cash_id, amount=20, amount_minor=to_minor(20),
            description='Money received from loan from Test Lender',
            transaction_type='Receipt', date_posted=datetime(2026, 11, 9),
        )
        db.session.add_all([legacy_tx, legacy_receipt])
        db.session.commit()

        from app.services.profit_loss import _Projection
        projection = _Projection().build()
        excluded_ids = {tx.id for tx in loan_txs} | {legacy_tx.id, legacy_receipt.id}
        assert not any(
            row.get('document_type') == 'AccountTransaction'
            and row.get('document_id') in excluded_ids
            for row in projection.rows
        )

        with pytest.raises(ValueError, match='greater than the outstanding'):
            record_principal_movement(
                loan_party_id=lender_id, movement_type='repaid', amount='1000',
                cash_account_id=cash_id, date_posted=datetime(2026, 11, 9), actor='test',
            )
        db.session.rollback()

    response = client.get('/accounts/loans')
    assert response.status_code == 200
    assert 'Test Lender' in response.get_data(as_text=True)


def test_legacy_lender_accounts_are_not_company_account_documents(app, client):
    _login(client)
    with app.app_context():
        legacy_loan = Account(
            name='Outside Lender Legacy', type='loan', account_type='loan',
            category='ledger', source_category='Loan', class_subcategory='Loans Payable',
            balance=-100, balance_minor=to_minor(-100), is_active=True,
        )
        db.session.add(legacy_loan)
        db.session.commit()
        legacy_id = legacy_loan.id

    response = client.get('/accounts/accounts?show=all')
    assert response.status_code == 200
    assert 'Outside Lender Legacy' not in response.get_data(as_text=True)
    assert client.get(f'/accounts/ledger/{legacy_id}').status_code == 404
    assert client.get(f'/accounts/{legacy_id}/edit').status_code == 404


def test_loan_register_routes_record_opening_balance_and_new_movements(app, client):
    _login(client)
    with app.app_context():
        cash = _cash_account(name='Loan Route Cash', balance=0)
        db.session.commit()
        cash_id = cash.id

    response = client.post('/accounts/loans/parties/add', data={
        'name': 'Route Lender', 'opening_principal': '200',
        'opening_date': '2026-01-31', 'note': 'Verified opening balance',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert 'Route Lender' in response.get_data(as_text=True)
    with app.app_context():
        lender = LoanParty.query.filter_by(name='Route Lender').one()
        assert lender.opening_principal_minor == to_minor(200)
        lender_id = lender.id

    response = client.post('/accounts/loans/movements/add', data={
        'loan_party_id': str(lender_id), 'movement_type': 'received',
        'amount': '75', 'cash_account_id': str(cash_id),
        'date_posted': '2026-02-01', 'reference': 'DRAW-1',
        'idempotency_key': 'loan-route-1',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert 'Rs. 275.00' in response.get_data(as_text=True)
    with app.app_context():
        assert LoanMovement.query.count() == 1
        assert db.session.get(Account, cash_id).balance_minor == to_minor(75)
