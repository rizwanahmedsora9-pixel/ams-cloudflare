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


def test_full_wipe_preserves_and_reports_unrecognized_tables(app, client):
    login(client)
    with app.app_context():
        db.session.add(Client(name='Remove me', code='REMOVE001'))
        db.session.execute(text('CREATE TABLE extension_table (id INTEGER PRIMARY KEY, note TEXT)'))
        db.session.execute(text("INSERT INTO extension_table VALUES (1, 'keep')"))
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert 'Full Wipe' in html
    assert 'Unrecognized tables were preserved' in html and 'extension_table' in html
    with app.app_context():
        assert Client.query.filter_by(code='REMOVE001').count() == 0
        assert db.session.execute(text('SELECT note FROM extension_table')).scalar() == 'keep'


def test_full_wipe_refuses_to_cascade_into_extension(app, client):
    login(client)
    with app.app_context():
        db.session.add(Client(name='Keep me', code='KEEP001'))
        db.session.flush()
        client_id = Client.query.filter_by(code='KEEP001').one().id
        db.session.execute(text('CREATE TABLE extension_table (id INTEGER PRIMARY KEY, client_id INTEGER REFERENCES client(id) ON DELETE CASCADE)'))
        db.session.execute(text('INSERT INTO extension_table VALUES (1, :id)'), {'id': client_id})
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}, follow_redirects=True)
    assert 'wipe was stopped to protect it' in response.get_data(as_text=True)
    with app.app_context():
        assert Client.query.filter_by(code='KEEP001').count() == 1
        assert db.session.execute(text('SELECT COUNT(*) FROM extension_table')).scalar() == 1


def test_full_wipe_rolls_back_if_trigger_repopulates_data(app, client):
    login(client)
    with app.app_context():
        db.session.add(Client(name='Keep on failure', code='KEEP002'))
        db.session.execute(text("""CREATE TRIGGER repopulate_client AFTER INSERT ON bill_counter
                               BEGIN INSERT INTO client (name, code) VALUES ('ghost', 'GHOST01'); END"""))
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}, follow_redirects=True)
    assert 'could not clear all business data' in response.get_data(as_text=True)
    with app.app_context():
        assert Client.query.filter_by(code='KEEP002').count() == 1
        assert Client.query.filter_by(code='GHOST01').count() == 0


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


def test_full_wipe_can_be_repeated(app, client):
    login(client)
    data = {'delete_targets': list(FULL_WIPE_TARGETS),
            'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}
    for _ in range(2):
        response = client.post('/delete_selected_data', data=data, follow_redirects=True)
        assert 'Data Wiped: Full Wipe' in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.execute(text('SELECT COUNT(*) FROM bill_counter')).scalar() == 1
        assert User.query.filter_by(username='Admin').count() == 1


def test_full_wipe_requires_confirmation_and_admin(app, client):
    login(client)
    with app.app_context():
        db.session.add(Client(name='Protected', code='PROTECTED'))
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE SELECTED'}, follow_redirects=True)
    assert 'Incorrect confirmation text' in response.get_data(as_text=True)
    with app.app_context():
        assert Client.query.filter_by(code='PROTECTED').count() == 1
        admin = User.query.filter_by(username='Admin').one()
        admin.role = 'manager'
        db.session.commit()
    response = client.post('/delete_selected_data', data={'delete_targets': list(FULL_WIPE_TARGETS),
                        'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'}, follow_redirects=True)
    assert 'Only tenant admin or root' in response.get_data(as_text=True)
    with app.app_context():
        assert Client.query.filter_by(code='PROTECTED').count() == 1


# ---------------------------------------------------------------------------
# Contention: a second window / backup copy holding the SQLite write lock used
# to abort the reset with the masked "a data error, no changes were saved"
# flash.  The engine now retries instead, and explains itself if it cannot.
# ---------------------------------------------------------------------------
def _full_wipe_post(client):
    return client.post('/delete_selected_data',
                       data={'delete_targets': list(FULL_WIPE_TARGETS),
                             'hard_delete_override': '1', 'confirm_text': 'DELETE ALL DATA'},
                       follow_redirects=True)


def _hold_write_lock(app, seconds):
    """Take the SQLite RESERVED lock for *seconds* from another connection."""
    import sqlite3
    import threading

    db_file = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
    locker = sqlite3.connect(db_file, timeout=0.2, check_same_thread=False)
    locker.execute('BEGIN IMMEDIATE')

    def _release():
        try:
            locker.rollback()
        finally:
            locker.close()

    timer = threading.Timer(seconds, _release)
    timer.daemon = True
    timer.start()
    return locker, timer


def test_full_wipe_retries_through_a_transient_lock(app, client, monkeypatch):
    from app.services import full_wipe
    monkeypatch.setattr(full_wipe, 'BUSY_TIMEOUT_MS', 150)
    monkeypatch.setattr(full_wipe, 'LOCK_RETRIES', 8)
    monkeypatch.setattr(full_wipe, 'LOCK_RETRY_DELAY', 0.2)
    login(client)
    with app.app_context():
        db.session.add(Client(name='Blocked for a moment', code='LOCK-TRANSIENT'))
        db.session.commit()
    _hold_write_lock(app, 1.2)
    html = _full_wipe_post(client).get_data(as_text=True)
    assert 'Data Wiped: Full Wipe' in html
    assert 'data error' not in html and 'No changes were saved' not in html
    with app.app_context():
        assert Client.query.filter_by(code='LOCK-TRANSIENT').count() == 0


def test_full_wipe_explains_a_persistent_lock_and_changes_nothing(app, client, monkeypatch):
    from app.services import full_wipe, state
    monkeypatch.setattr(full_wipe, 'BUSY_TIMEOUT_MS', 100)
    monkeypatch.setattr(full_wipe, 'LOCK_RETRIES', 2)
    monkeypatch.setattr(full_wipe, 'LOCK_RETRY_DELAY', 0.05)
    login(client)
    with app.app_context():
        db.session.add(Client(name='Still here', code='LOCK-PERSISTENT'))
        db.session.commit()
    locker, timer = _hold_write_lock(app, 20)
    try:
        html = _full_wipe_post(client).get_data(as_text=True)
    finally:
        timer.cancel()
        locker.rollback()
        locker.close()
    # The operator must see the real reason, never the old masked wording.
    assert 'The database stayed in use while wiping' in html
    assert 'No changes were saved' in html
    assert 'completed due to a data error' not in html
    assert state.WIPE_IN_PROGRESS is False
    with app.app_context():
        assert Client.query.filter_by(code='LOCK-PERSISTENT').count() == 1


def test_full_wipe_clears_a_stale_import_job_but_not_a_live_one(app, client):
    from datetime import timedelta
    from models import ImportJob, ImportUpload
    from app.services.time_money import pk_now
    login(client)
    with app.app_context():
        upload = ImportUpload(upload_id='stale-upload', filename='old.xlsx',
                              stored_filename='old.xlsx', size_bytes=1)
        db.session.add(upload)
        db.session.flush()
        stale = ImportJob(upload_id=upload.id, status='queued')
        db.session.add(stale)
        db.session.flush()
        # Abandoned by a crashed import: nobody is writing these rows any more.
        db.session.execute(text('UPDATE import_job SET created_at = :ts, updated_at = :ts'),
                           {'ts': pk_now() - timedelta(hours=3)})
        db.session.add(Client(name='Left behind', code='STALE-IMPORT'))
        db.session.commit()
    html = _full_wipe_post(client).get_data(as_text=True)
    assert 'Data Wiped: Full Wipe' in html
    with app.app_context():
        assert Client.query.filter_by(code='STALE-IMPORT').count() == 0
        assert ImportJob.query.count() == 0
    with app.app_context():
        db.session.add(Client(name='New yard', code='LIVE-IMPORT'))
        upload = ImportUpload(upload_id='live-upload', filename='now.xlsx',
                              stored_filename='now.xlsx', size_bytes=1)
        db.session.add(upload)
        db.session.flush()
        db.session.add(ImportJob(upload_id=upload.id, status='processing'))
        db.session.commit()
    html = _full_wipe_post(client).get_data(as_text=True)
    assert 'A data import is still running or queued' in html
    with app.app_context():
        assert Client.query.filter_by(code='LIVE-IMPORT').count() == 1


def test_wipe_prepass_nulls_every_nullable_foreign_key(app):
    """The disconnect pass must unlink rows (legacy RESTRICT/cycles) before any delete."""
    from sqlalchemy import inspect as sa_inspect
    from app.services.full_wipe import BUSINESS_TABLES, _null_out_foreign_keys
    with app.app_context():
        first = Supplier(name='First supplier')
        db.session.add(first)
        db.session.flush()
        second = Supplier(name='Second supplier', transferred_to_id=first.id)
        db.session.add(second)
        db.session.commit()
        conn = db.session.connection()
        present = set(sa_inspect(conn).get_table_names())
        _null_out_foreign_keys(db.session, conn, BUSINESS_TABLES & present, sa_inspect(conn))
        db.session.flush()
        assert Supplier.query.filter_by(name='Second supplier').one().transferred_to_id is None
        db.session.rollback()


def test_full_wipe_handles_a_legacy_restrict_cycle(app, client):
    """Old installs can carry RESTRICT links both ways; SQLite checks those
    immediately, so a plain delete aborted the whole reset. The unlink pre-pass
    must break the cycle first."""
    login(client)
    with app.app_context():
        customer = Client(name='Cycled customer', code='CYCLE-1')
        supplier = Supplier(name='Cycled supplier')
        db.session.add_all([customer, supplier])
        db.session.commit()
        db.session.execute(text(
            'ALTER TABLE client ADD COLUMN legacy_supplier_id INTEGER '
            'REFERENCES supplier(id) ON DELETE RESTRICT'))
        db.session.execute(text(
            'ALTER TABLE supplier ADD COLUMN legacy_client_id INTEGER '
            'REFERENCES client(id) ON DELETE RESTRICT'))
        db.session.execute(text('UPDATE client SET legacy_supplier_id = :sid'),
                           {'sid': supplier.id})
        db.session.execute(text('UPDATE supplier SET legacy_client_id = :cid'),
                           {'cid': customer.id})
        db.session.commit()
        # Both directions are populated: neither table can be deleted first.
        assert db.session.execute(text(
            'SELECT legacy_supplier_id FROM client')).scalar() == supplier.id
    html = _full_wipe_post(client).get_data(as_text=True)
    assert 'Data Wiped: Full Wipe' in html
    with app.app_context():
        assert db.session.execute(text('SELECT COUNT(*) FROM client')).scalar() == 0
        assert db.session.execute(text('SELECT COUNT(*) FROM supplier')).scalar() == 0
        assert not db.session.execute(text('PRAGMA foreign_key_check')).all()
