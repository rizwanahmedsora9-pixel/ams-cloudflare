"""The page behind the QR code printed on an Urdu bill.

A customer scans the code on the A5 receipt with a phone and lands here.  The
page is deliberately **public** - it must open without a login, because the
person holding the paper bill has no account - but it is not open: the link
carries an HMAC signature made with the app's secret key, and every figure on
the page is re-read from the database by bill id.  Nothing in the URL is
trusted except which bill to show.

It is also read-only and never lists bills: a wrong or edited link simply
reports that the bill could not be verified.
"""
from __future__ import annotations

from ._common import *  # noqa
from app.services import bill_verify


@bp.route('/verify/bill/<token>')
def verify_bill(token):
    """Show one bill to whoever scanned its QR code (no login)."""
    from app.services.bill_verify import load_bill, read_token

    claim = read_token(token)
    if not claim:
        return render_template('bill_verify.html', verified=False,
                               reason='link'), 404
    loaded = load_bill(claim['type'], claim['id'])
    if not loaded:
        return render_template('bill_verify.html', verified=False,
                               reason='missing'), 404
    bill = loaded['bill']

    amount = float(getattr(bill, 'amount', 0) or 0)
    paid = float(getattr(bill, 'paid_amount', 0) or 0)
    discount = float(getattr(bill, 'discount', 0) or 0)
    previous = float(loaded.get('previous_balance') or 0)
    if loaded['type'] == 'Invoice':
        amount = float(getattr(bill, 'total_amount', 0) or 0)
        paid = amount - float(getattr(bill, 'balance', 0) or 0)
        previous = 0.0
    if loaded['type'] == 'Payment':
        amount = float(getattr(bill, 'amount', 0) or 0)
        paid = amount
        previous = 0.0

    outstanding = previous + amount - paid - discount
    lines = []
    total = 0.0
    for index, item in enumerate(loaded['items'], start=1):
        qty = float(item.get('qty') or 0)
        rate = float(item.get('rate') or 0)
        line_total = qty * rate
        total += line_total
        lines.append({'index': index, 'name': item.get('name_ur') or item.get('name'),
                      'name_latin': item.get('name'),
                      'qty': bill_verify._money(qty),
                      'rate': bill_verify._money(rate),
                      'amount': bill_verify._money(line_total)})

    posted = (getattr(bill, 'date_posted', None)
              or getattr(bill, 'created_at', None)
              or getattr(bill, 'date', None))
    if isinstance(posted, str) and posted:
        posted_text = posted
    elif posted is not None:
        posted_text = posted.strftime('%d-%m-%Y %I:%M %p')
    else:
        posted_text = ''

    bill_no = (getattr(bill, 'manual_bill_no', '') or
               getattr(bill, 'auto_bill_no', '') or
               getattr(bill, 'invoice_no', '') or
               getattr(bill, 'bill_no', '') or claim.get('no') or '')
    delivery = (getattr(bill, 'driver_name', '') or '').strip()
    delivery_ur = ''
    if delivery:
        saved_driver_ur = ''
        try:
            driver = DeliveryPerson.query.filter(
                func.lower(func.trim(DeliveryPerson.name)) == delivery.lower()
            ).first()
            saved_driver_ur = (getattr(driver, 'name_ur', None) or '').strip()
        except Exception:
            saved_driver_ur = ''
        delivery_ur = loaded['urdu_name'](delivery, saved_driver_ur)

    return render_template(
        'bill_verify.html',
        verified=True,
        bill_type=loaded['type'],
        bill_no=bill_no,
        posted_text=posted_text,
        client_name=loaded['client_name'],
        client_name_ur=loaded['client_name_ur'],
        client_id=loaded['client_id'],
        client_phone=loaded['client_phone'],
        delivery=delivery,
        delivery_ur=delivery_ur,
        lines=lines,
        money=bill_verify._money,
        amount=bill_verify._money(amount),
        paid=bill_verify._money(paid),
        discount=bill_verify._money(discount),
        previous=bill_verify._money(previous),
        outstanding=bill_verify._money(outstanding),
        note=(getattr(bill, 'note', '') or '').strip(),
        claim=claim,
    )
