"""Driver overpayments remain ordinary ledger credits, not separate advances."""
from datetime import datetime

import pytest

from models import (
    Account,
    AccountTransaction,
    DeliveryPerson,
    DeliveryPersonPayment,
    DirectSale,
    SaleDeliveryPerson,
    db,
)
from app.services.driver_payments import (
    delete_driver_payment,
    driver_outstanding,
    restore_driver_payment,
    save_driver_payment,
    settle_driver_fifo,
)
from utils.money import to_minor


def _cash_account():
    account = Account(
        name="Driver Ledger Cash", type="company", account_type="company",
        category="cash", source_category="Company", balance=1000,
        balance_minor=to_minor(1000), opening_balance=1000,
        opening_balance_minor=to_minor(1000),
        opening_balance_date=datetime(2026, 1, 1), is_active=True,
    )
    db.session.add(account)
    db.session.flush()
    return account


def _rent(person, amount, reference):
    sale = DirectSale(client_name="Test Client", manual_bill_no=reference,
                      date_posted=datetime(2026, 2, 1), is_void=False)
    db.session.add(sale)
    db.session.flush()
    allocation = SaleDeliveryPerson(
        sale_id=sale.id, delivery_person_id=person.id, rent_amount=amount,
        created_at=datetime(2026, 2, 1), is_void=False,
    )
    db.session.add(allocation)
    db.session.flush()
    return allocation


def test_excess_payment_is_carried_and_offset_by_future_rent(app):
    with app.app_context():
        account = _cash_account()
        person = DeliveryPerson(name="Ledger Driver", opening_balance=100, is_active=True)
        db.session.add(person)
        db.session.flush()

        rows = settle_driver_fifo(
            delivery_person_id=person.id, amount_paid="150", method="Cash",
            payment_account_id=account.id, date_posted=datetime(2026, 1, 15),
            idempotency_key="driver-overpayment-1", actor="test",
        )
        db.session.commit()

        assert len(rows) == 1
        assert rows[0].allocation_id is None
        assert driver_outstanding(person.id) == pytest.approx(-50)
        assert db.session.get(Account, account.id).balance_minor == to_minor(850)
        assert AccountTransaction.query.filter_by(
            source_type="DeliveryPersonPayment", transaction_type="Driver Payment"
        ).count() == 1

        # New rent is a normal debit against the same running balance.  No
        # advance document or manual allocation is needed to consume the excess.
        _rent(person, 75, "FUTURE-RENT-1")
        db.session.commit()
        assert driver_outstanding(person.id) == pytest.approx(25)


def test_edit_and_restore_keep_overpayment_but_waive_cannot_create_credit(app):
    with app.app_context():
        account = _cash_account()
        person = DeliveryPerson(name="Editable Driver", opening_balance=100, is_active=True)
        db.session.add(person)
        db.session.flush()
        payment, _ = save_driver_payment(
            delivery_person_id=person.id, amount_paid=125, method="Cash",
            payment_account_id=account.id, date_posted=datetime(2026, 1, 15),
            actor="test",
        )
        db.session.commit()
        assert driver_outstanding(person.id) == pytest.approx(-25)

        save_driver_payment(
            payment_id=payment.id, amount_paid=175, method="Cash",
            payment_account_id=account.id, date_posted=datetime(2026, 1, 15),
            expected_revision=payment.revision, actor="test",
        )
        db.session.commit()
        assert driver_outstanding(person.id) == pytest.approx(-75)
        assert db.session.get(Account, account.id).balance_minor == to_minor(825)

        assert delete_driver_payment(payment, actor="test")
        assert driver_outstanding(person.id) == pytest.approx(100)
        assert restore_driver_payment(payment, actor="test")
        db.session.commit()
        assert driver_outstanding(person.id) == pytest.approx(-75)

        with pytest.raises(ValueError, match="Waive-off exceeds"): 
            save_driver_payment(
                delivery_person_id=person.id, amount_paid=0, waive_off_amount=1,
                date_posted=datetime(2026, 1, 16), actor="test",
            )
        db.session.rollback()
        assert DeliveryPersonPayment.query.filter_by(is_void=False).count() == 1
