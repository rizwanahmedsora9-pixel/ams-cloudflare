from datetime import date, datetime
from io import BytesIO

from werkzeug.datastructures import FileStorage

from models import Account, CashDayLock, Client, DirectSale, DirectSaleItem, Payment, db


def test_logout_requires_post(client):
    assert client.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'}).status_code == 302
    assert client.get('/logout').status_code == 405
    assert client.post('/logout').status_code == 302
    assert client.get('/settings').status_code in (302, 401)


def test_payment_edit_rejects_locked_day_change(app, client):
    assert client.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'}).status_code == 302
    with app.app_context():
        person = Client(name='Locked Day Client', code='LOCKED-PAY')
        account = Account(name='Locked Day Cash', type='Cash', category='cash', account_type='company', balance=1000, balance_minor=100000)
        db.session.add_all([person, account]); db.session.flush()
        payment = Payment(client_id=person.id, client_name=person.name, amount=500, method='Cash', payment_account_id=account.id, date_posted=datetime(2026, 11, 11, 10))
        db.session.add(payment)
        db.session.add(CashDayLock(lock_date=date(2026, 11, 11)))
        db.session.commit()
        payment_id = payment.id
    response = client.post(f'/edit_ledger_transaction/Payment/{payment_id}', data={
        'amount': '400', 'method': 'Cash', 'date_posted': '2026-11-11T10:00', 'note': ''
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Payment, payment_id).amount == 500


def test_client_ledger_direct_sale_edit_cannot_change_header_only(app, client):
    assert client.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'}).status_code == 302
    with app.app_context():
        sale = DirectSale(client_name='Ledger Sale Customer', category='Cash', amount=100, date_posted=datetime(2026, 11, 12, 10))
        db.session.add(sale); db.session.flush()
        db.session.add(DirectSaleItem(sale_id=sale.id, product_name='Sand', qty=1, price_at_time=100))
        db.session.commit()
        sale_id = sale.id
    response = client.post(f'/edit_ledger_transaction/DirectSale/{sale_id}', data={
        'amount': '250', 'manual_bill_no': '', 'category': 'Cash', 'payment_method': 'Cash', 'note': ''
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(DirectSale, sale_id).amount == 100
        assert db.session.query(DirectSaleItem).filter_by(sale_id=sale_id).one().price_at_time == 100


def test_photo_upload_rejects_html_disguised_as_image(app, tmp_path, monkeypatch):
    import app.services.files_pdf as files_pdf
    monkeypatch.setattr(files_pdf, 'basedir', str(tmp_path))
    upload = FileStorage(stream=BytesIO(b'<html>unsafe</html>'), filename='payload.png', content_type='image/png')
    with app.test_request_context('/'):
        assert files_pdf.save_photo(upload) is None
    assert not (tmp_path / 'static' / 'uploads').exists()


def test_photo_upload_accepts_signature_checked_png(app, tmp_path, monkeypatch):
    import app.services.files_pdf as files_pdf
    monkeypatch.setattr(files_pdf, 'basedir', str(tmp_path))
    upload = FileStorage(stream=BytesIO(b'\x89PNG\r\n\x1a\nexample'), filename='proof.png', content_type='image/png')
    with app.test_request_context('/'):
        saved = files_pdf.save_photo(upload)
    assert saved and saved.endswith('_proof.png')
    assert (tmp_path / 'static' / 'uploads' / saved).read_bytes() == b'\x89PNG\r\n\x1a\nexample'
