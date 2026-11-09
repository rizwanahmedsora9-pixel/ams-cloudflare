from datetime import datetime
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import text

from models import Client, FollowUpContact, FollowUpReminder, GRN, Payment, PendingBill, db


def login(client):
    assert client.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'}).status_code == 302


def test_core_excel_exports_with_legacy_null_date(app, client):
    login(client)
    with app.app_context():
        db.session.add_all([Client(name='Excel Customer', code='EXCEL-01'),
                            GRN(supplier='Example Supplier', manual_bill_no='GRN-1')])
        db.session.commit()
        db.session.execute(text("UPDATE grn SET date_posted=NULL WHERE manual_bill_no='GRN-1'"))
        db.session.commit()
    for url, sheet_name, marker in [('/export_clients', 'Clients', 'Excel Customer'),
                                    ('/export_grn', 'GRN List', 'Example Supplier')]:
        response = client.get(url)
        assert response.status_code == 200
        workbook = load_workbook(BytesIO(response.data), data_only=True)
        assert sheet_name in workbook.sheetnames
        assert any(marker in row for row in workbook[sheet_name].iter_rows(values_only=True))
        assert workbook[sheet_name].max_row >= 2


def test_spreadsheet_missing_dependency_gives_actionable_response(app, client, monkeypatch):
    import blueprints.import_export.misc_helpers as helpers
    import blueprints.import_export.validate as validate
    login(client)
    monkeypatch.setattr(helpers, 'pd', None)
    monkeypatch.setattr(validate, 'pd', None)
    for url in ['/import_export/full_raw_export', '/import_export/master/export',
                '/import_export/export?dataset=clients']:
        response = client.get(url, follow_redirects=True)
        assert response.status_code == 200
        assert b'requirements-data.txt' in response.data
    response = client.post('/import_export/transfer/export', data={'sections': 'all_business'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'requirements-data.txt' in response.data
    response = client.post('/import_export/preview', data={'file': (BytesIO(b'a,b\n1,2'), 'x.csv')})
    assert response.status_code == 503
    assert 'requirements-data.txt' in response.json['error']


def test_pdf_unavailable_gives_actionable_message(app, client, monkeypatch):
    import importlib
    reports = importlib.import_module('app.blueprints.reports._profit_profit_reports')
    login(client)
    monkeypatch.setattr(reports, '_try_render_weasy_pdf', lambda *a, **kw: None)
    response = client.get('/profit_reports/export/pdf', follow_redirects=True)
    assert response.status_code == 200
    assert b'requirements-pdf.txt' in response.data


def test_delete_payment_removes_related_bill_and_followups(app, client):
    login(client)
    with app.app_context():
        person = Client(name='Payment Customer', code='PAY-01')
        db.session.add(person)
        db.session.flush()
        payment = Payment(client_id=person.id, client_name=person.name, amount=50, manual_bill_no='RC-123')
        bill = PendingBill(client_code=person.code, client_name=person.name, bill_no='RC-123', reason='Payment received by cash', amount=50)
        other = PendingBill(client_code=person.code, client_name=person.name, bill_no='OTHER', reason='Unrelated', amount=25)
        # A legacy bill with no code but the same reference must not be
        # mistaken for this customer's receipt.
        other_customer_bill = PendingBill(client_name='Someone Else', client_code='',
                                          bill_no='RC-123', is_manual=True,
                                          reason='Payment received by cash', amount=30)
        db.session.add_all([payment, bill, other, other_customer_bill]); db.session.flush()
        reminder = FollowUpReminder(pending_bill_id=bill.id, remind_at=datetime(2026, 1, 1))
        db.session.add(reminder); db.session.flush()
        db.session.add(FollowUpContact(pending_bill_id=bill.id, reminder_id=reminder.id))
        payment_id, bill_id, other_id, other_customer_id = payment.id, bill.id, other.id, other_customer_bill.id
        db.session.commit()
        assert db.session.get(PendingBill, other_id) is not None
    response = client.post(f'/delete_transaction/Payment/{payment_id}')
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Payment, payment_id) is None
        assert db.session.get(PendingBill, bill_id) is None
        assert db.session.get(PendingBill, other_id) is not None
        assert db.session.get(PendingBill, other_customer_id) is not None
        assert not db.session.get(PendingBill, other_customer_id).is_void
        assert FollowUpContact.query.count() == 0
        assert FollowUpReminder.query.count() == 0
        assert db.session.execute(text('PRAGMA foreign_key_check')).all() == []


def test_sqlite_audit_joins_active_write_and_rollback(app):
    from models import AuditLog
    from utils.audit import audit_log
    with app.app_context():
        db.session.add(Client(name='Temporary', code='TEMP'))
        db.session.flush()  # Acquires SQLite's write lock.
        audit_log(None, 'test.rollback', 'must not block or commit the client')
        assert AuditLog.query.filter_by(action='test.rollback').count() == 1
        db.session.rollback()
        assert Client.query.filter_by(code='TEMP').count() == 0
        assert AuditLog.query.filter_by(action='test.rollback').count() == 0

        db.session.add(Client(name='Persisted', code='PERSIST'))
        db.session.flush()
        audit_log(None, 'test.commit', 'written with client')
        db.session.commit()
        assert Client.query.filter_by(code='PERSIST').count() == 1
        assert AuditLog.query.filter_by(action='test.commit').count() == 1


def test_audit_without_write_transaction_is_recorded(app):
    from models import AuditLog
    from utils.audit import audit_log
    with app.app_context():
        # Standalone logging should still persist without a subsequent commit.
        audit_log(None, 'test.standalone', 'independent')
        db.session.rollback()
        assert AuditLog.query.filter_by(action='test.standalone').count() == 1
