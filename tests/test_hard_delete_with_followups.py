"""Regression: hard-deleting a sale/booking that owns follow-up rows.

A pending bill owns ``follow_up_reminder`` and ``follow_up_contact`` rows.  Both
of those carry a foreign key back to ``pending_bill.id``, so deleting the bill
row with a bulk ``DELETE`` used to raise ``FOREIGN KEY constraint failed`` and
abort the whole operation: the operator saw the generic "data error" flash and
the sale stayed on the books.  The delete path must take the children with it.
"""
from datetime import date, datetime

from models import (
    Booking, BookingItem, Client, DirectSale, FollowUpContact, FollowUpReminder,
    PendingBill, db,
)
from app.services.void_rebuild import hard_delete_transaction


def _pending_bill_with_followups(source_table, source_id, client, bill_no):
    bill = PendingBill(
        client_code=client.code,
        client_name=client.name,
        bill_no=bill_no,
        bill_kind='MB',
        amount=1000,
        is_paid=False,
        is_cash=False,
        is_manual=False,
        created_at='2026-11-10',
        is_void=False,
        source_module='sales',
        source_table=source_table,
        source_id=source_id,
        transaction_type=source_table,
    )
    db.session.add(bill)
    db.session.flush()
    reminder = FollowUpReminder(
        pending_bill_id=bill.id,
        remind_at=datetime(2026, 11, 12, 9, 0),
        note='call the site office',
    )
    db.session.add(reminder)
    db.session.flush()
    db.session.add(FollowUpContact(
        pending_bill_id=bill.id,
        reminder_id=reminder.id,
        contacted_at=datetime(2026, 11, 10, 9, 0),
        channel='Call',
        response='promised to pay',
    ))
    db.session.commit()
    return bill.id


def _login(client):
    response = client.post(
        '/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def test_hard_delete_sale_with_follow_up_reminders(app, client):
    with app.app_context():
        customer = Client(code='HD-1', name='Hard Delete Customer',
                          category='General', is_active=True)
        db.session.add(customer)
        db.session.commit()

        sale = DirectSale(
            manual_bill_no='HD-SALE-1',
            client_code=customer.code,
            client_name=customer.name,
            category='Credit Customer',
            amount=1000,
            date_posted=date(2026, 11, 10),
            payment_method='Credit',
        )
        db.session.add(sale)
        db.session.commit()
        sale_id = sale.id
        bill_id = _pending_bill_with_followups('direct_sale', sale_id, customer,
                                               'HD-SALE-1')

    _login(client)
    response = client.post(f'/delete_transaction/DirectSale/{sale_id}',
                           data={'reason': 'wrong customer'})
    assert response.status_code in (200, 302, 303)

    with app.app_context():
        assert db.session.get(DirectSale, sale_id) is None
        assert db.session.get(PendingBill, bill_id) is None
        assert FollowUpReminder.query.filter_by(pending_bill_id=bill_id).count() == 0
        assert FollowUpContact.query.filter_by(pending_bill_id=bill_id).count() == 0
        # And the delete left no dangling references behind.
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).fetchall() == []


def test_hard_delete_booking_with_follow_up_reminders(app, client):
    with app.app_context():
        customer = Client(code='HD-2', name='Booking Customer',
                          category='General', is_active=True)
        db.session.add(customer)
        db.session.commit()

        booking = Booking(
            client_name=customer.name,
            amount=1000,
            paid_amount=1000,
            manual_bill_no='HD-BOOK-1',
            date_posted=datetime(2026, 11, 10, 9, 0),
        )
        db.session.add(booking)
        db.session.flush()
        db.session.add(BookingItem(booking_id=booking.id, material_name='DG Cement',
                                   qty=10, price_at_time=100))
        db.session.commit()
        booking_id = booking.id
        bill_id = _pending_bill_with_followups('booking', booking_id, customer,
                                               'HD-BOOK-1')

    _login(client)
    response = client.post(f'/delete_transaction/Booking/{booking_id}', data={})
    assert response.status_code in (200, 302, 303)

    with app.app_context():
        assert db.session.get(Booking, booking_id) is None
        assert db.session.get(PendingBill, bill_id) is None
        assert FollowUpReminder.query.filter_by(pending_bill_id=bill_id).count() == 0
        assert FollowUpContact.query.filter_by(pending_bill_id=bill_id).count() == 0
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).fetchall() == []
