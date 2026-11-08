"""The page behind the QR code printed on an Urdu bill.

A customer scans the code on the A5 receipt with a phone and lands here.  The
page is deliberately **public** - it must open without a login, because the
person holding the paper bill has no account - but it is not open: the link
carries an HMAC signature made with the app's secret key, and every figure on
the page is re-read from the database by bill id.  Nothing in the URL is
trusted except which bill to show.

What the scanner sees
---------------------
The page shows the *same receipt that was printed*: the identical Urdu A5
sheet from :mod:`app.services.urdu_receipt`, rebuilt through the same data
loader the print action uses (``bills.bill_document_source``).  So the client
name, bill number, delivery person, every material line, the quantities, rates
and all the totals match the paper in the customer's hand - there is no second,
hand-written summary that could drift from the bill.  A scanned bill can also
be downloaded as the same A5 PDF the office prints.

It is read-only and never lists bills: a wrong or edited link simply reports
that the bill could not be verified.
"""
from __future__ import annotations

from ._common import *  # noqa
from app.services import bill_verify


@bp.route('/b/<token>')
def verify_bill_short(token):
    """Short link form the printed QR uses (alphanumeric mode, fewer bytes)."""
    return verify_bill(token)


@bp.route('/verify/bill/<token>')
def verify_bill(token):
    """Show one bill to whoever scanned its QR code (no login)."""
    claim = bill_verify.read_token(token)
    if not claim:
        return render_template('bill_verify.html', verified=False,
                               reason='link'), 404
    source = _verified_source(claim)
    if not source:
        return render_template('bill_verify.html', verified=False,
                               reason='missing'), 404

    # One loader, one sheet: whatever the print action would produce for this
    # bill is what the scanner sees (both symbols come from the wired package).
    document = urdu_bill_document(source)  # noqa: F821
    bill_no = document.get('bill_no') or claim.get('no') or ''
    return render_template(
        'bill_verify.html',
        verified=True,
        # The sheet is passed as data (strings used as text) and rendered by
        # ``bill_receipt.html``; see _render_sheet() below.
        sheet=_sheet_context(document),
        bill_type=source['bill_type'],
        bill_no=bill_no,
        claim=claim,
        pdf_path=url_for('sales.verify_bill_pdf', token=token),
    )


@bp.route('/b/<token>.pdf')
@bp.route('/verify/bill/<token>.pdf')
def verify_bill_pdf(token):
    """The verified bill as the same A5 PDF the office prints."""
    from app.services import bill_urdu

    claim = bill_verify.read_token(token)
    if not claim:
        abort(404)
    source = _verified_source(claim)
    if not source:
        abort(404)
    data = bill_urdu.render_pdf(urdu_bill_document(source))
    if not data:
        abort(404)
    response = make_response(data)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Cache-Control'] = 'no-store'
    name = (source.get('bill_number') or 'bill').replace('/', '-')
    response.headers['Content-Disposition'] = f'inline; filename={name}-UR.pdf'
    return response


def _sheet_context(document):
    """Everything the scanned page needs to draw the printed sheet.

    Labels come from the sheet's own vocabulary (Urdu, matching the paper);
    pages are the composed A5 pages as ``[{'w','h'}]`` plus their primitives,
    rendered by ``bill_receipt.html`` from plain data - no pre-built HTML is
    passed to a template.
    """
    from app.services import urdu_receipt

    return {
        'pages': urdu_receipt.page_fragments(document),
        'caption': 'بل تصدیق شدہ',
        'sublabel': 'Verified',
        'pdf_label': 'PDF ڈاؤن لوڈ',
        'print_label': 'پرنٹ کریں',
        'note': ('یہ بل کمپنی کے لیجر سے تصدیق شدہ ہے اور پرنٹ شدہ بل کے '
                 'عین مطابق ہے'),
    }


def _verified_source(claim):
    """Load the bill a signed token names, or ``None``.

    Only the type and id in the token are trusted (they are signed); the bill
    number is passed along as a lookup hint and the page always prints the
    number stored on the bill.
    """
    from models import Booking, DirectSale, GRN, Invoice, Payment, PendingBill
    from app import db

    model = {'DirectSale': DirectSale, 'Booking': Booking,
             'Payment': Payment, 'Invoice': Invoice, 'GRN': GRN,
             'PendingBill': PendingBill}.get(claim.get('type') or '')
    if model is None or not str(claim.get('id') or '').isdigit():
        return None
    row = db.session.get(model, int(claim['id']))
    if row is None or getattr(row, 'is_void', False):
        return None
    # The number inside the token is a clipped copy; the lookup uses the stored
    # one so a long or punctuated reference still resolves.
    bill_no = bill_number_of(claim['type'], row)  # noqa: F821
    try:
        source = bill_document_source(  # noqa: F821  (wired package symbol)
            bill_no,
            hint_type=claim.get('type'),
            hint_id=claim.get('id'),
        )
    except Exception:
        return None
    if not source or not source.get('bill') or source.get('ambiguous'):
        return None
    source['bill_number'] = bill_number_of(source['bill_type'], source['bill'])
    return source
