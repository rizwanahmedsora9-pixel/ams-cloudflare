from __future__ import annotations

from sqlalchemy import inspect, text

from app.services.full_wipe import BUSINESS_TABLES, FULL_WIPE_TARGETS, PRESERVED_TABLES
from models import (db, Account, AccountTransaction, CashFlowEntry, CashFlowEntryAudit,
                    GRN, Supplier, SupplierPayment, Client, ClientCategory, User,
                    AccountingAuditLog, MigrationRun, MigrationMapping)


def login(client):
    assert client.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'}).status_code == 302


def create_account(client, name='Fresh cash', **kw):
    payload = {'name': name, 'class_category': 'Assets', 'class_subcategory': 'Cash',
               'class_account_type': 'Main Cash', 'channel': 'cash', 'opening_amount': '125.50',
               'opening_position': 'debit'}
    payload.update(kw)
    return client.post('/accounts/accounts/add', data=payload, follow_redirects=True)


def test_schema_and_ui_classification_are_complete(app):
    from pathlib import Path
    import re
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names()) - {'sqlite_sequence'}
        assert tables == BUSINESS_TABLES | PRESERVED_TABLES
    html = (Path(__file__).resolve().parents[1] / 'templates/settings.html').read_text()
    assert set(re.findall(r'name="delete_targets" value="([^"]+)"', html)) == FULL_WIPE_TARGETS


def test_full_wipe_linked_records_and_create_new_account(app, client):
    login(client)
    response = create_account(client, 'Old cash')
    assert 'Account added successfully' in response.get_data(as_text=True)
    with app.app_context():
        account = Account.query.filter_by(name='Old cash').one()
        supplier = Supplier(name='Old supplier')
        db.session.add_all([supplier, ClientCategory(name='Old category')])
        db.session.flush()
        grn = GRN(supplier_id=supplier.id)
        db.session.add(grn); db.session.flush()
        tx = AccountTransaction(from_account_id=account.id, grn_id=grn.id, amount=10)
        db.session.add(tx); db.session.flush()
        cf = CashFlowEntry(account_id=account.id, account_tx_id=tx.id, direction='out', amount=10)
        db.session.add(cf); db.session.flush()
        db.session.add_all([CashFlowEntryAudit(entry_id=cf.id, action='Create'),
                            SupplierPayment(supplier_id=supplier.id, grn_id=grn.id, payment_account_id=account.id)])
        old_client = Client(name='Old customer', code='OLD001')
        db.session.add(old_client)
        run = MigrationRun(run_key='old-run', filename='old.csv', source_hash='hash', template_type='clients')
        db.session.add(run); db.session.flush()
        db.session.add(MigrationMapping(template_type='clients', legacy_reference='OLD', entity_type='Client', entity_id=old_client.id, run_id=run.id))
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}, follow_redirects=True)
    assert 'Full Wipe' in response.get_data(as_text=True)
    assert 'data error' not in response.get_data(as_text=True)
    with app.app_context():
        for table in BUSINESS_TABLES - {'bill_counter'}:
            assert db.session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() == 0, table
        assert User.query.filter_by(username='Admin').count() == 1
        assert not db.session.execute(text('PRAGMA foreign_key_check')).all()
    response = client.post('/add_client', data={'name': 'New client', 'code': 'NEW01', 'category': 'General'}, follow_redirects=True)
    assert 'Client Registered' in response.get_data(as_text=True)
    with app.app_context():
        assert Client.query.filter_by(code='NEW01').count() == 1
    response = create_account(client)
    assert 'Account added successfully' in response.get_data(as_text=True)
    with app.app_context():
        account = Account.query.filter_by(name='Fresh cash').one()
        assert account.balance_minor == account.opening_balance_minor == 12550
        assert AccountingAuditLog.query.filter_by(entity_type='Account', entity_id=account.id).count() == 1


def test_full_wipe_unknown_tables_fails_without_deleting(app, client):
    login(client)
    with app.app_context():
        db.session.add(Client(name='Keep me', code='KEEP001'))
        db.session.execute(text('CREATE TABLE extension_table (id INTEGER PRIMARY KEY)'))
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}, follow_redirects=True)
    assert 'Wipe failed' in response.get_data(as_text=True)
    with app.app_context():
        assert Client.query.filter_by(name='Keep me').count() == 1


def test_missing_checkbox_does_not_trigger_full_wipe(app, client):
    login(client)
    with app.app_context():
        db.session.add(ClientCategory(name='Preserved category'))
        db.session.commit()
    # No override: the selective request must be blocked before any deletion.
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS - {'services'}),
                        'confirm_text': 'DELETE SELECTED'}, follow_redirects=True)
    assert 'Hard delete blocked' in response.get_data(as_text=True)
    with app.app_context():
        assert ClientCategory.query.filter_by(name='Preserved category').count() == 1


def test_wipe_is_rolled_back_if_delete_fails(app, client):
    login(client)
    with app.app_context():
        db.session.add(Client(name='Protected by rollback', code='ROLLBACK01'))
        db.session.execute(text("CREATE TRIGGER refuse_account_delete BEFORE DELETE ON account BEGIN SELECT RAISE(ABORT, 'test failure'); END"))
        db.session.add(Account(name='Do not remove', account_type='company'))
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}, follow_redirects=True)
    assert 'No changes were saved' in response.get_data(as_text=True)
    with app.app_context():
        assert Client.query.filter_by(code='ROLLBACK01').count() == 1
        assert Account.query.filter_by(name='Do not remove').count() == 1


def test_account_creation_rolls_back_new_category_if_audit_fails(app, client, monkeypatch):
    from models import AccountCategory
    import utils.accounting_audit
    login(client)
    def fail(*args, **kwargs):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(utils.accounting_audit, 'record_accounting_audit', fail)
    response = create_account(client, 'Not saved', source_category='Temporary category')
    assert 'Unable to add account' in response.get_data(as_text=True)
    with app.app_context():
        assert Account.query.filter_by(name='Not saved').count() == 0
        assert AccountCategory.query.filter_by(name='Temporary category').count() == 0


def test_full_wipe_blocks_active_import(app, client):
    from models import ImportJob, ImportUpload
    login(client)
    with app.app_context():
        upload = ImportUpload(upload_id='active-upload', filename='data.xlsx', stored_filename='data.xlsx', size_bytes=1)
        db.session.add(upload)
        db.session.flush()
        db.session.add(ImportJob(upload_id=upload.id, status='processing'))
        db.session.add(Client(name='Import in progress', code='INPROGRESS'))
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}, follow_redirects=True)
    assert 'data import is still running or queued' in response.get_data(as_text=True)
    with app.app_context():
        assert Client.query.filter_by(code='INPROGRESS').count() == 1
        assert ImportJob.query.count() == 1


def test_selective_reconciliation_wipe_handles_self_references(app, client):
    from datetime import date
    from models import AccountReconciliation
    login(client)
    with app.app_context():
        account = Account(name='Account', account_type='company')
        db.session.add(account); db.session.flush()
        first = AccountReconciliation(account_id=account.id, reconciliation_date=date(2026, 1, 1))
        db.session.add(first); db.session.flush()
        db.session.add(AccountReconciliation(account_id=account.id, previous_reconciliation_id=first.id,
                                             reconciliation_date=date(2026, 1, 2)))
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': ['account_reconciliations'],
                        'confirm_text': 'DELETE SELECTED'}, follow_redirects=True)
    assert 'Account Reconciliations' in response.get_data(as_text=True)
    with app.app_context():
        assert AccountReconciliation.query.count() == 0
        assert Account.query.filter_by(name='Account').count() == 1
