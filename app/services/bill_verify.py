"""Scan-and-verify for the Urdu receipt's QR code.

The A5 receipt carries a QR in its header.  A 51pt square cannot hold a whole
15-line bill as text (that is ~770 bytes, and anything past ~250 bytes stops
being scannable at print size), so the QR holds a *signed link* instead:
scanning it opens the complete bill - shop, bill number and type, date and
time, client name and ID, delivery person, every line item and the money
figures - on the phone that scanned it.

What the link carries
---------------------
Only the bill's identity (type, id and number) plus an HMAC signature made
with the application's ``SECRET_KEY``.  No amount, name or price is trusted
from the URL: the page re-reads the bill from the database after verifying the
signature, so a tampered link cannot show a forged total.  The page is public
(the customer scanning a paper bill has no login) and read-only.

Where it is printed
-------------------
:func:`bill_urdu.build_document` calls :func:`qr_payload` when it has an app
context; the link is built from the current request's host so the same code
works on a yard PC (``http://192.168.1.10:5000``) and on a hosted domain.
Without an app context (unit tests, a frozen PDF) the QR falls back to the
in-line bill summary built by :mod:`app.services.bill_urdu`.
"""
from __future__ import annotations

from flask import current_app, has_app_context, url_for

# Route that renders the bill behind the QR.
VERIFY_ENDPOINT = 'sales.verify_bill'

# Bill types the verifier knows, in the spelling used by the rest of the app.
BILL_TYPES = {
    'directsale': 'DirectSale',
    'sale': 'DirectSale',
    'direct_sale': 'DirectSale',
    'booking': 'Booking',
    'payment': 'Payment',
    'invoice': 'Invoice',
    'grn': 'GRN',
    'pendingbill': 'PendingBill',
    'pending': 'PendingBill',
}

# Hosts that are only meaningful on the machine itself.  A receipt printed
# from one of these still gets a link - to the machine's LAN address, which is
# what a customer's phone can actually open while standing in the shop.
_LOOPBACK = {'localhost', 'localhost.localdomain', '127.0.0.1', '::1',
             '0.0.0.0'}
_UNUSABLE = {'', 'testserver'}
_LAN_ADDRESS = None


def _reachable(address):
    """True when a phone on the shop's Wi-Fi could open *address*.

    Loopback (127.) and link-local (169.254.) addresses are only meaningful on
    the machine itself - a QR pointing at one is a dead link, so those are
    rejected and the sheet prints its self-contained summary instead.
    """
    if not address or not isinstance(address, str):
        return False
    if address.startswith('127.') or address.startswith('169.254.'):
        return False
    if address in ('0.0.0.0', '::1', '::'):
        return False
    return True


def _lan_address():
    """This machine's routable LAN address, or '' when there is none."""
    global _LAN_ADDRESS
    if _LAN_ADDRESS is not None:
        return _LAN_ADDRESS
    _LAN_ADDRESS = ''
    candidates = []
    try:
        import socket
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No packet is sent: the call only selects the outbound interface.
            probe.connect(('192.0.2.1', 9))
            candidates.append(probe.getsockname()[0])
        finally:
            probe.close()
    except Exception:
        pass
    try:
        import socket
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            candidates.append(info[4][0])
    except Exception:
        pass
    for candidate in candidates:
        if _reachable(candidate):
            _LAN_ADDRESS = candidate
            break
    return _LAN_ADDRESS


# ---------------------------------------------------------------------------
# Signed tokens
# ---------------------------------------------------------------------------

def _serializer():
    from itsdangerous import URLSafeSerializer
    secret = current_app.config.get('SECRET_KEY')
    return URLSafeSerializer(secret, salt='ams-bill-verify')


def make_token(bill_type, bill_id, bill_no, posted=None):
    """Signed token naming one bill; raises outside an app context."""
    posted = posted or ''
    return _serializer().dumps({
        't': BILL_TYPES.get(str(bill_type or '').lower(), str(bill_type or '')),
        'i': str(bill_id or ''),
        'n': str(bill_no or ''),
        'd': posted,
    })


def read_token(token):
    """``{'type', 'id', 'no', 'posted'}`` or ``None`` when the token is bad."""
    try:
        raw = _serializer().loads(token or '')
    except Exception:
        return None
    if not isinstance(raw, dict) or not raw.get('t'):
        return None
    return {'type': raw.get('t') or '', 'id': str(raw.get('i') or ''),
            'no': raw.get('n') or '', 'posted': raw.get('d') or ''}


def base_url():
    """Origin the printed link should use.

    ``PUBLIC_BASE_URL`` wins (a deployed install behind a proxy knows its own
    address); otherwise the current request's origin is used.  A yard PC that
    reaches the app on ``192.168.x.x`` therefore prints a link the customer's
    phone can open while standing next to the counter.
    """
    configured = ''
    try:
        configured = (current_app.config.get('PUBLIC_BASE_URL') or '').strip()
    except Exception:
        configured = ''
    if configured:
        return configured.rstrip('/')
    try:
        from flask import request
        if request:
            host = (request.host or '').strip()
            name = host.split(':')[0].lower()
            scheme = (request.headers.get('X-Forwarded-Proto')
                      or request.scheme or 'http').split(',')[0].strip()
            if name in _LOOPBACK:
                # Reached on the server itself: a phone cannot open
                # "localhost", so print the machine's LAN address instead.
                lan = _lan_address()
                if lan:
                    port = host.rsplit(':', 1)[1] if ':' in host else ''
                    return f'{scheme}://{lan}{":" + port if port else ""}'
            elif name not in _UNUSABLE and _reachable(name):
                return f'{scheme}://{host}'
            server = (current_app.config.get('SERVER_NAME') or '').strip()
            if server:
                return f'{scheme}://{server}'
    except Exception:
        pass
    return ''


def verify_url(bill_type, bill_id, bill_no='', posted=None):
    """Absolute URL the QR should open, or '' when no host is known."""
    root = base_url()
    if not root:
        return ''
    try:
        path = url_for(VERIFY_ENDPOINT, token=make_token(
            bill_type, bill_id, bill_no, posted))
    except Exception:
        return ''
    return f'{root}{path}'


def qr_payload(bill_type, bill_id, bill_no='', posted=None):
    """The text to encode: the verify link, or '' when it cannot be built."""
    if not has_app_context():
        return ''
    try:
        return verify_url(bill_type, bill_id, bill_no, posted)
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# The verified bill
# ---------------------------------------------------------------------------

def _item_name_urdu(name, saved=''):
    from app.services.urdu_names import urdu_name
    if (saved or '').strip():
        return saved.strip()
    try:
        from models import Material
        row = Material.query.filter(
            Material.name.isnot(None)).filter(
            Material.name.ilike((name or '').strip())).first()
        if row is not None and (getattr(row, 'name_ur', '') or '').strip():
            return row.name_ur.strip()
    except Exception:
        pass
    return urdu_name(name, '')


def _money(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return str(value or '')
    return f'{number:,.0f}' if abs(number - round(number)) < 0.01 else f'{number:,.2f}'


def load_bill(bill_type, bill_id):
    """``(bill, items, client, previous_balance)`` for the verified page.

    Every figure is read from the database exactly as stored - the verifier
    never recomputes a total, so a re-printed bill cannot disagree with the
    ledger.
    """
    from models import (db, Booking, Client, DirectSale, GRN, Invoice,
                        Payment, PendingBill)
    from app.services.urdu_names import urdu_name

    kind = BILL_TYPES.get(str(bill_type or '').lower(), bill_type)
    try:
        ident = int(bill_id)
    except (TypeError, ValueError):
        return None
    model = {'DirectSale': DirectSale, 'Booking': Booking, 'Payment': Payment,
             'Invoice': Invoice, 'GRN': GRN, 'PendingBill': PendingBill}.get(kind)
    if model is None:
        return None
    bill = db.session.get(model, ident)
    if bill is None:
        return None

    items = []
    if kind == 'DirectSale':
        for item in getattr(bill, 'items', []) or []:
            name = (getattr(item, 'product_name', '') or '').strip()
            items.append({'name': name,
                          'name_ur': _item_name_urdu(name,
                                                     getattr(item, 'name_ur', '')),
                          'qty': item.qty or 0,
                          'rate': item.price_at_time or 0})
    elif kind == 'Booking':
        for item in getattr(bill, 'items', []) or []:
            name = (getattr(item, 'material_name', '') or '').strip()
            items.append({'name': name,
                          'name_ur': _item_name_urdu(name,
                                                     getattr(item, 'name_ur', '')),
                          'qty': item.qty or 0,
                          'rate': item.price_at_time or 0})
    elif kind == 'GRN':
        for item in getattr(bill, 'items', []) or []:
            name = (getattr(item, 'material_name', '') or
                    getattr(item, 'material', '') or '').strip()
            items.append({'name': name, 'name_ur': _item_name_urdu(name),
                          'qty': getattr(item, 'qty', 0) or 0,
                          'rate': getattr(item, 'rate', 0) or 0})
    elif kind == 'Invoice':
        for entry in getattr(bill, 'entries', []) or []:
            name = (getattr(entry, 'material', '') or '').strip()
            items.append({'name': name, 'name_ur': _item_name_urdu(name),
                          'qty': getattr(entry, 'qty', 0) or 0,
                          'rate': getattr(entry, 'rate', 0) or 0})

    client = None
    code = (getattr(bill, 'client_code', '') or '').strip()
    name = (getattr(bill, 'client_name', '') or '').strip()
    try:
        if code:
            client = Client.query.filter_by(code=code).first()
        if client is None and name:
            client = Client.query.filter_by(name=name).first()
    except Exception:
        client = None

    previous = 0.0
    if kind in ('DirectSale', 'Booking'):
        amount = float(getattr(bill, 'amount', 0) or 0)
        paid = float(getattr(bill, 'paid_amount', 0) or 0)
        discount = float(getattr(bill, 'discount', 0) or 0)
        try:
            from app.services.finance_clients import _client_balance_as_of
            if client is not None:
                balance = _client_balance_as_of(client)
                previous = balance - (amount - paid - discount)
        except Exception:
            previous = 0.0
    elif kind == 'Payment':
        previous = 0.0

    client_name = name or (getattr(client, 'name', '') if client else '')
    client_name_ur = (getattr(client, 'name_ur', '') or '').strip() if client else ''
    client_phone = (getattr(client, 'phone', '') or '').strip() if client else ''
    return {
        'type': kind,
        'bill': bill,
        'items': items,
        'client': client,
        'client_name': client_name,
        'client_name_ur': urdu_name(client_name, client_name_ur),
        'client_id': code or (getattr(client, 'code', '') if client else ''),
        'client_phone': client_phone,
        'previous_balance': previous,
        'urdu_name': urdu_name,
    }
