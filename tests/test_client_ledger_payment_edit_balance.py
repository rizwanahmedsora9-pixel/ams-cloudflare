from models import Account, Client, Payment, db


def test_client_ledger_payment_edit_cannot_remove_more_than_account_balance(app, client):
    assert client.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'}).status_code == 302
    with app.app_context():
        person = Client(name='Balance Guard Client', code='BAL-GUARD')
        account = Account(name='Balance Guard Cash', type='Cash', category='cash',
                          account_type='company', balance=1050, balance_minor=105000)
        db.session.add_all([person, account])
        db.session.flush()
        payment = Payment(client_id=person.id, client_name=person.name, amount=5000,
                          method='Cash', payment_account_id=account.id)
        db.session.add(payment)
        db.session.commit()
        payment_id = payment.id
        account_id = account.id

    response = client.post(
        f'/edit_ledger_transaction/Payment/{payment_id}',
        data={'amount': '0', 'method': 'Cash', 'date_posted': '2026-11-12T10:00',
              'manual_bill_no': '', 'note': ''},
    )

    assert response.status_code == 302
    with app.app_context():
        payment = db.session.get(Payment, payment_id)
        account = db.session.get(Account, account_id)
        assert payment.amount == 5000
        assert account.balance == 1050
        assert account.balance_minor == 105000
