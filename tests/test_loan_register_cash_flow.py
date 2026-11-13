"""Cash Flow, Financial Tracker, Daily Reconciliation, and export integration tests for Loan Register."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from werkzeug.security import generate_password_hash

from app.services.cash_day_recon import account_positions_for_date
from app.services.cash_flow_svc import (
    CF_SOURCE_LABELS,
    apply_running_balance,
    cf_section_label,
    collect_cash_flow_rows,
    filter_cash_flow_rows,
    summarize_cash_flow_rows,
)
from app.services.loan_register import record_principal_movement
from app.services.payments_crud import ledger_balance
from models import (
    Account,
    AccountTransaction,
    CashFlowCategory,
    CashFlowEntry,
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


def _account(name='CF Cash', category='cash', balance=1000):
    acc = Account(
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
    db.session.add(acc)
    db.session.flush()
    return acc


def test_loan_principal_rows_keep_in_out_types_and_clean_attribution(app):
    with app.app_context():
        cash = _account(name='Drawer Cash', category='cash', balance=1000)
        bank = _account(name='HBL Main', category='bank', balance=5000)
        lender = LoanParty(name='Zaid Finance', opening_principal_minor=0, is_active=True)
        db.session.add(lender)
        db.session.commit()

        m_in, _ = record_principal_movement(
            loan_party_id=lender.id,
            movement_type='received',
            amount='2500',
            cash_account_id=cash.id,
            date_posted=datetime(2026, 11, 10, 9, 30),
            reference='LN-REF-01',
            note='Working capital draw',
            actor='loan_officer',
        )
        m_out, _ = record_principal_movement(
            loan_party_id=lender.id,
            movement_type='repaid',
            amount='1000',
            cash_account_id=bank.id,
            date_posted=datetime(2026, 11, 10, 14, 15),
            reference='',
            note='Partial principal repayment',
            actor='loan_officer',
        )
        # Clear created_by on the linked AccountTransaction of m_out to verify fallback lookup
        tx_out = db.session.get(AccountTransaction, m_out.account_tx_id)
        tx_out.created_by = None
        db.session.commit()

        assert cf_section_label('LoanPrincipal') == 'Loan Register'
        assert cf_section_label('loan_principal') == 'Loan Register'
        assert cf_section_label('LoanMovement') == 'Loan Register'
        assert CF_SOURCE_LABELS['LoanPrincipal'] == 'Loan Register'

        rows = collect_cash_flow_rows('2026-11-10', '2026-11-10')
        assert len(rows) == 2

        by_tx = {r['tx_id']: r for r in rows}
        r_in = by_tx[m_in.account_tx_id]
        r_out = by_tx[m_out.account_tx_id]

        # Received -> standard Cash Flow IN row
        assert r_in['type'] == 'in'
        assert r_in['tx_type_label'] == 'Received'
        assert r_in['cash_in'] == 2500.0
        assert r_in['cash_out'] == 0.0
        assert r_in['source_type'] == 'LoanPrincipal'
        assert r_in['section_label'] == 'Loan Register'
        assert r_in['origin'] == 'derived'
        assert r_in['origin_label'] == 'From Accounts · Loan Register'
        assert r_in['party_type'] == 'loan_lender'
        assert r_in['party_name'] == 'Zaid Finance'
        assert r_in['reference'] == 'LN-REF-01'
        assert r_in['account_category'] == 'cash'
        assert r_in['method'] == 'Cash'
        assert r_in['created_by'] == 'loan_officer'

        # Repaid -> standard Cash Flow OUT row, fallback reference TX-<id> & creator fallback
        assert r_out['type'] == 'out'
        assert r_out['tx_type_label'] == 'Spent'
        assert r_out['cash_in'] == 0.0
        assert r_out['cash_out'] == 1000.0
        assert r_out['source_type'] == 'LoanPrincipal'
        assert r_out['section_label'] == 'Loan Register'
        assert r_out['origin'] == 'derived'
        assert r_out['origin_label'] == 'From Accounts · Loan Register'
        assert r_out['party_type'] == 'loan_lender'
        assert r_out['party_name'] == 'Zaid Finance'
        assert r_out['reference'] == f'TX-{m_out.account_tx_id}'
        assert r_out['account_category'] == 'bank'
        assert r_out['method'] == 'Bank'
        assert r_out['created_by'] == 'loan_officer'

        # Summarize & running balance treat LoanPrincipal exactly like other IN/OUT rows
        summary = summarize_cash_flow_rows(rows)
        assert summary['total_cash_in'] == 2500.0
        assert summary['total_cash_out'] == 1000.0
        assert 'Loan Lender · Zaid Finance' in summary['breakdown_party']
        assert 'loan_lender · Zaid Finance' not in summary['breakdown_party']
        assert summary['breakdown_party']['Loan Lender · Zaid Finance']['in'] == 2500.0
        assert summary['breakdown_party']['Loan Lender · Zaid Finance']['out'] == 1000.0

        closing = apply_running_balance(rows, opening_balance=6000.0)
        assert closing == 7500.0
        assert ledger_balance(cash.id) + ledger_balance(bank.id) == 7500.0

        # Filtering by origin=loanprincipal, direction, party_type, reference
        assert len(filter_cash_flow_rows(rows, {'origin': 'loanprincipal'})) == 2
        assert len(filter_cash_flow_rows(rows, {'origin': 'loanprincipal', 'filter_type': 'in'})) == 1
        assert len(filter_cash_flow_rows(rows, {'origin': 'loanprincipal', 'filter_type': 'out'})) == 1
        assert len(filter_cash_flow_rows(rows, {'party_type': 'loan_lender', 'reference': 'LN-REF-01'})) == 1

        # Daily reconciliation agrees with ledger balances across IN and OUT loan movements
        positions = {p['account_id']: p for p in account_positions_for_date(date(2026, 11, 10))}
        assert positions[cash.id]['opening'] == 1000.0
        assert positions[cash.id]['in'] == 2500.0
        assert positions[cash.id]['out'] == 0.0
        assert positions[cash.id]['expected_closing'] == 3500.0
        assert positions[bank.id]['opening'] == 5000.0
        assert positions[bank.id]['in'] == 0.0
        assert positions[bank.id]['out'] == 1000.0
        assert positions[bank.id]['expected_closing'] == 4000.0


def test_cash_flow_financial_tracker_filters_and_csv_exports_for_loans(app, client):
    _login(client)
    with app.app_context():
        cash = _account(name='Office Cash', category='cash', balance=1000)
        bank = _account(name='Meezan Bank', category='bank', balance=5000)
        lender_a = LoanParty(name='Al-Noor Lenders', opening_principal_minor=0, is_active=True)
        lender_b = LoanParty(
            name='Crescent Capital',
            opening_principal_minor=to_minor(2000),
            opening_principal_date=date(2026, 1, 1),
            is_active=True,
        )
        exp_cat = CashFlowCategory(name='Utilities', direction='out', is_active=True)
        db.session.add_all([lender_a, lender_b, exp_cat])
        db.session.flush()

        record_principal_movement(
            loan_party_id=lender_a.id,
            movement_type='received',
            amount='3000',
            cash_account_id=cash.id,
            date_posted=datetime(2026, 11, 10, 10, 0),
            reference='LN-ALN-1',
            note='Cash loan received',
            actor='Admin',
        )
        record_principal_movement(
            loan_party_id=lender_b.id,
            movement_type='repaid',
            amount='1200',
            cash_account_id=bank.id,
            date_posted=datetime(2026, 11, 10, 11, 0),
            reference='LN-CRC-2',
            note='Bank repayment',
            actor='Admin',
        )

        # Also post a Bank CashFlowEntry so we verify method='cash' does not match
        # a Bank entry merely because origin_label says "Recorded on Cash Flow".
        bank_exp_tx = AccountTransaction(
            from_account_id=bank.id,
            to_account_id=None,
            amount=400.0,
            amount_minor=to_minor(400),
            description='Electricity Bill',
            note='Online bill',
            transaction_type='Expense',
            source_type='CashFlowEntry',
            date_posted=datetime(2026, 11, 10, 12, 0),
            created_by='Admin',
        )
        db.session.add(bank_exp_tx)
        db.session.flush()
        bank_entry = CashFlowEntry(
            direction='out',
            amount=400.0,
            amount_minor=to_minor(400),
            account_id=bank.id,
            category_id=exp_cat.id,
            description='Electricity Bill',
            reference='UTIL-9',
            date_posted=datetime(2026, 11, 10, 12, 0),
            source_type='MANUAL_CASH_FLOW',
            account_tx_id=bank_exp_tx.id,
            created_by='Admin',
        )
        db.session.add(bank_entry)
        db.session.commit()

    # 1. /cash_flow includes LoanPrincipal IN/OUT totals, Loan Lender breakdown, and Loan Register option
    cf_resp = client.get('/cash_flow?from_date=2026-11-10&to_date=2026-11-10')
    assert cf_resp.status_code == 200
    cf_html = cf_resp.get_data(as_text=True)
    assert 'Loan Lender · Al-Noor Lenders' in cf_html
    assert 'Loan Lender · Crescent Capital' in cf_html
    assert 'Loan Register' in cf_html
    assert 'LN-ALN-1' in cf_html
    assert 'LN-CRC-2' in cf_html

    # 2. /cash_flow CSV export includes Loan Register section and reference
    cf_csv_resp = client.get('/cash_flow?from_date=2026-11-10&to_date=2026-11-10&export_csv=1')
    assert cf_csv_resp.status_code == 200
    cf_rows = list(csv.DictReader(io.StringIO(cf_csv_resp.get_data(as_text=True))))
    assert len(cf_rows) == 3
    aln_row = next(r for r in cf_rows if r['Reference'] == 'LN-ALN-1')
    assert aln_row['Type'] == 'Received'
    assert aln_row['Section'] == 'Loan Register'
    assert aln_row['Party'] == 'Al-Noor Lenders'
    assert aln_row['Source'] == 'From Accounts · Loan Register'
    assert float(aln_row['Received']) == 3000.0

    # 3. Standalone /financial_tracker filters by Section, Loan Lender, and Payment Method
    ft_all = client.get('/financial_tracker?preset=all')
    assert ft_all.status_code == 200
    ft_html = ft_all.get_data(as_text=True)
    assert 'name="section"' in ft_html
    assert 'name="lender"' in ft_html
    assert 'Al-Noor Lenders' in ft_html
    assert 'Crescent Capital' in ft_html
    assert 'ALL TRANSACTIONS (3)' in ft_html

    ft_section = client.get('/financial_tracker?preset=all&section=Loan+Register')
    assert ft_section.status_code == 200
    ft_sec_html = ft_section.get_data(as_text=True)
    assert 'ALL TRANSACTIONS (2)' in ft_sec_html
    assert 'LN-ALN-1' in ft_sec_html
    assert 'LN-CRC-2' in ft_sec_html
    assert 'UTIL-9' not in ft_sec_html

    ft_lender = client.get('/financial_tracker?preset=all&lender=Crescent+Capital')
    assert ft_lender.status_code == 200
    ft_lender_html = ft_lender.get_data(as_text=True)
    assert 'ALL TRANSACTIONS (1)' in ft_lender_html
    assert 'LN-CRC-2' in ft_lender_html
    assert 'LN-ALN-1' not in ft_lender_html

    # Payment Method='cash' includes only cash row (LN-ALN-1), excluding Bank repayment & Bank expense
    ft_cash = client.get('/financial_tracker?preset=all&method=cash')
    assert ft_cash.status_code == 200
    ft_cash_html = ft_cash.get_data(as_text=True)
    assert 'ALL TRANSACTIONS (1)' in ft_cash_html
    assert 'LN-ALN-1' in ft_cash_html
    assert 'LN-CRC-2' not in ft_cash_html
    assert 'UTIL-9' not in ft_cash_html

    # Payment Method='bank' includes both bank rows (LN-CRC-2 and UTIL-9)
    ft_bank = client.get('/financial_tracker?preset=all&method=bank')
    assert ft_bank.status_code == 200
    ft_bank_html = ft_bank.get_data(as_text=True)
    assert 'ALL TRANSACTIONS (2)' in ft_bank_html
    assert 'LN-CRC-2' in ft_bank_html
    assert 'UTIL-9' in ft_bank_html
    assert 'LN-ALN-1' not in ft_bank_html

    # 4. /financial_tracker CSV export respects Section & Lender filters
    ft_csv_resp = client.get('/financial_tracker?preset=all&section=Loan+Register&lender=Al-Noor+Lenders&export_csv=1')
    assert ft_csv_resp.status_code == 200
    ft_csv_rows = list(csv.DictReader(io.StringIO(ft_csv_resp.get_data(as_text=True))))
    assert len(ft_csv_rows) == 1
    assert ft_csv_rows[0]['Reference'] == 'LN-ALN-1'
    assert ft_csv_rows[0]['Section'] == 'Loan Register'
    assert ft_csv_rows[0]['Party'] == 'Al-Noor Lenders'
    assert float(ft_csv_rows[0]['In']) == 3000.0

    # 5. Embedded Cash Flow Transactions tab with ft_section & ft_lender filters
    embedded = client.get('/cash_flow?ft_preset=all&ft_section=Loan+Register&ft_lender=Crescent+Capital')
    assert embedded.status_code == 200
    emb_html = embedded.get_data(as_text=True)
    assert 'ALL TRANSACTIONS (1)' in emb_html
    assert 'LN-CRC-2' in emb_html
    assert 'const serverTab = "transactions"' in emb_html


def test_cash_flow_viewer_without_accounts_permission_sees_loan_rows_safely(app, client):
    with app.app_context():
        cash = _account(name='Viewer Cash', category='cash', balance=500)
        lender = LoanParty(name='Viewer Lender', opening_principal_minor=0, is_active=True)
        cf_viewer = User(
            username='cfviewer',
            role='user',
            status='active',
            password_hash=generate_password_hash('Viewer@12345'),
            can_view_cash_flow=True,
            can_manage_accounts=False,
            can_manage_payments=False,
        )
        db.session.add_all([lender, cf_viewer])
        db.session.flush()
        record_principal_movement(
            loan_party_id=lender.id,
            movement_type='received',
            amount='700',
            cash_account_id=cash.id,
            date_posted=datetime(2026, 11, 10, 9, 0),
            reference='LN-VIEW-1',
            actor='Admin',
        )
        db.session.commit()

    _login(client, username='cfviewer', password='Viewer@12345')
    resp = client.get('/cash_flow?from_date=2026-11-10&to_date=2026-11-10&ft_preset=all')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Loan Lender · Viewer Lender' in html
    assert 'LN-VIEW-1' in html

    ft_resp = client.get('/financial_tracker?preset=all&section=Loan+Register')
    assert ft_resp.status_code == 200
    assert 'LN-VIEW-1' in ft_resp.get_data(as_text=True)
