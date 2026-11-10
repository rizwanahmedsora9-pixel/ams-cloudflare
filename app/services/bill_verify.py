"""Scan-and-verify for the Urdu receipt's QR code.

The A5 receipt carries a QR in its header.  A 51pt square cannot hold a whole
15-line bill as text (that is ~770 bytes, and anything past ~140 bytes stops
being scannable at print size), so the QR holds a *short signed link* instead:
scanning it opens the complete bill - shop, bill number and type, date and
time, client name and ID, delivery person, every line item and the money
figures - on the phone that scanned it, laid out exactly like the printed
sheet.

Why the link is kept short
--------------------------
The printed block is 51pt (18mm) wide, so every byte of payload costs module
size: a 166-byte payload needs a 61x61 symbol (0.26mm modules) which a phone
camera only resolves on a perfect, high-resolution print, while an ~80-byte
link needs a 37x37 symbol (0.40mm modules) that scans from an ordinary laser
print.  The token is therefore hand-rolled: ``<bill id>.<what>.<signature>``
where ``what`` is a short bill number, and the signature is a truncated
HMAC-SHA256 of that pair, rendered in *alphanumeric* mode (upper-case letters
and digits) because that lets the encoder pack 5.5 bits into every module
instead of 8.

What the link carries
---------------------
Only the bill's identity (type, id and number) plus the signature.  No amount,
name or price is trusted from the URL: the page re-reads the bill from the
database after verifying the signature, so a tampered link cannot show a
forged total.  The page is public (the customer scanning a paper bill has no
login) and read-only.

Where it is printed
-------------------
:func:`bill_urdu.build_document` calls :func:`qr_payload` when it has an app
context; the link is built from the current request's host so the same code
works on a yard PC (``http://192.168.1.10:5000``) and on a hosted domain.
Without an app context (unit tests, a frozen PDF) the QR falls back to the
in-line bill summary built by :mod:`app.services.bill_urdu`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from flask import current_app, has_app_context, url_for

# Route that renders the bill behind the QR.  ``/b/<token>`` is the short form
# the printed code uses (see :func:`verify_url`); the long ``/verify/bill/``
# rule stays registered so links already printed keep working.
VERIFY_ENDPOINT = 'sales.verify_bill_short'

# Hard ceiling on the printed link.  Measured on the real sheet: an 84-character
# link needs a 37-module symbol (0.40mm modules, scans at 200dpi and up), a
# 104-character one needs 41 modules, and past ~124 the modules get too fine
# for a phone camera.  :mod:`app.services.bill_urdu` applies the module budget;
# this is the cheap sanity check in front of it (a deployment with a very long
# host name then prints its text summary instead of an unscannable code).
MAX_LINK_CHARS = 96

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

# One letter per bill type, so the token stays inside the QR's alphanumeric
# mode (upper-case + digits only) - see :func:`make_token`.
_TYPE_LETTER = {
    'DirectSale': 'S',
    'Booking': 'B',
    'Payment': 'P',
    'Invoice': 'I',
    'GRN': 'G',
    'PendingBill': 'N',
}
_LETTER_TYPE = {letter: kind for kind, letter in _TYPE_LETTER.items()}

# Token salt: changing it invalidates every QR already printed, so it is a
# constant, not a setting.
_TOKEN_SALT = b'ams-bill-qr-v2'
# 8 bytes = 64 bits of signature, printed as 13 base32 characters.  A forged
# link needs a 2^64 search, and every extra byte would cost QR module size on
# the paper.
_SIGNATURE_BYTES = 8
_SIGNATURE_CHARS = 13

# How much of the bill number is printed inside the QR.  The page re-reads the
# real number from the database; this copy only makes an offline scan show the
# bill reference instead of a meaningless token.
_BILL_NO_IN_TOKEN = 16

# Hosts that are only meaningful on the machine itself.  A receipt printed
# from one of these still gets a link - pinned to the host this install is
# configured with (``SERVER_NAME``/``PUBLIC_BASE_URL``) or to the machine's LAN
# address, which is what a customer's phone can actually open in the shop.
_LOOPBACK = {'localhost', 'localhost.localdomain', '127.0.0.1', '::1',
             '0.0.0.0'}
_UNUSABLE = {'', 'testserver'}
# Cloud hosts address each deployment by name: <project>-<preview>.e2b.app is
# served by a proxy that routes on the original Host header, so the link must
# keep that name instead of inventing a LAN address.
_DEPLOY_HOST_SUFFIXES = ('.e2b.app', '.vercel.app', '.onrender.com',
                         '.herokuapp.com', '.fly.dev', '.ngrok.io',
                         '.ngrok-free.app', '.loca.lt', '.trycloudflare.com',
                         '.pythonanywhere.com')
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
# The token is the whole payload of a QR printed 18mm wide, so its length is a
# physical constraint rather than a style choice:  ``23.SBSL1008.X7k2-mQ9bT1``
# (21 characters) needs a 29x29 symbol at 0.49mm per module, where the
# itsdangerous-signed JSON blob of the first implementation (98 characters)
# needed 45x45 at 0.34mm and the "readable" Urdu summary (166 bytes) needed
# 61x61 at 0.26mm - too fine for a phone camera on a laser print, which is why
# scanning showed nothing at all.
#
# The trade is deliberate: the guarantee people rely on (a forged link cannot
# show a forged bill) is kept at 60 bits of HMAC, and the saving is spent on
# a symbol three times the area, i.e. a QR that actually scans.


def _secret():
    """The bytes the signature is keyed with (raises outside an app)."""
    secret = current_app.config.get('SECRET_KEY') or ''
    return secret.encode('utf-8') if isinstance(secret, str) else bytes(secret)


def _signature(payload, secret):
    """Base32 of a truncated HMAC.

    Base32 is ``A-Z2-7`` - entirely inside QR alphanumeric mode - and unlike
    base64url it needs no character substitutions (``-``/``_`` are two bytes
    each in byte mode and are not in the alphanumeric set at all).
    """
    digest = hmac.new(secret, _TOKEN_SALT + payload.encode('utf-8'),
                      hashlib.sha256).digest()[:_SIGNATURE_BYTES]
    return base64.b32encode(digest).decode('ascii').rstrip('=')


def _clean_bill_no(value):
    """Bill number squeezed into QR alphanumeric mode: ``SB-SL-1008`` ->
    ``SBSL1008``.  The page always prints the stored number, so dropping the
    punctuation costs nothing; it only shortens the token."""
    return ''.join(ch for ch in str(value or '').upper()
                   if ch.isalnum() or ch in '-.$%*+/:')[-_BILL_NO_IN_TOKEN:]


def make_token(bill_type, bill_id, bill_no='', posted=None):
    """Short signed token naming one bill; raises outside an app context.

    ``posted`` is accepted for backwards compatibility and ignored: the date
    is re-read from the database, and a timestamp in the token would only make
    the symbol bigger.
    """
    kind = BILL_TYPES.get(str(bill_type or '').lower(), str(bill_type or ''))
    letter = _TYPE_LETTER.get(kind, 'S')
    try:
        ident = int(str(bill_id).strip())
    except (TypeError, ValueError):
        ident = 0
    body = f'{ident}.{_clean_bill_no(bill_no)}'
    if not ident:
        # Nothing to point at: sign the caller's raw values so the page still
        # answers "not found" instead of "tampered".
        body = f'0.{letter}{_clean_bill_no(bill_no)}'
    payload = f'{letter}.{body}'
    return f'{payload}.{_signature(payload, _secret())}'


def read_token(token):
    """``{'type', 'id', 'no', 'posted'}`` or ``None`` when the token is bad."""
    token = str(token or '').strip()
    payload, _, signature = token.rpartition('.')
    if not payload or len(signature) != _SIGNATURE_CHARS:
        return None
    try:
        secret = _secret()
    except Exception:
        return None
    if not secret:
        return None
    if not hmac.compare_digest(signature.upper(),
                               _signature(payload, secret)):
        return None
    letter, _, rest = payload.partition('.')
    kind = _LETTER_TYPE.get(letter)
    if not kind:
        return None
    ident, _, bill_no = rest.partition('.')
    if not ident.isdigit():
        return None
    return {'type': kind, 'id': str(int(ident)), 'no': bill_no,
            'posted': ''}


def base_url():
    """Origin the printed link should use.

    ``PUBLIC_BASE_URL`` wins (a deployed install behind a proxy knows its own
    address); otherwise the current request's origin is used.  A yard PC that
    reaches the app on ``192.168.x.x`` therefore prints a link the customer's
    phone can open while standing next to the counter.  A cloud host that is
    addressed by name keeps that name: its proxy routes on the Host header, so
    substituting a LAN address would break the link.
    """
    from app.services.public_url import resolve_public_base_url

    configured = resolve_public_base_url(allow_http=True)
    if configured:
        return configured
    try:
        from flask import request
        if request:
            host = (request.host or '').strip()
            name = host.split(':')[0].lower()
            scheme = (request.headers.get('X-Forwarded-Proto')
                      or request.scheme or 'http').split(',')[0].strip()
            if name in _LOOPBACK:
                # Reached on the server itself: a phone cannot open
                # "localhost", so print the configured name if there is one,
                # else the machine's LAN address.
                server = (current_app.config.get('SERVER_NAME') or '').strip()
                if server:
                    port = host.rsplit(':', 1)[1] if ':' in host else ''
                    return f'{scheme}://{server}{":" + port if port else ""}'
                lan = _lan_address()
                if lan:
                    port = host.rsplit(':', 1)[1] if ':' in host else ''
                    return f'{scheme}://{lan}{":" + port if port else ""}'
            elif name not in _UNUSABLE and (_reachable(name) or
                                            name.endswith(_DEPLOY_HOST_SUFFIXES)):
                return f'{scheme}://{host}'
            server = (current_app.config.get('SERVER_NAME') or '').strip()
            if server:
                return f'{scheme}://{server}'
    except Exception:
        pass
    return ''


def verify_path(bill_type, bill_id, bill_no='', posted=None):
    """The token alone - what :func:`verify_url` puts after ``/b/``."""
    return make_token(bill_type, bill_id, bill_no, posted)


def verify_url(bill_type, bill_id, bill_no='', posted=None):
    """Absolute URL the QR should open, or '' when no host is known."""
    root = base_url()
    if not root:
        return ''
    token = verify_path(bill_type, bill_id, bill_no, posted)
    if not token:
        return ''
    try:
        path = url_for(VERIFY_ENDPOINT, token=token)
    except Exception:
        path = f'/b/{token}'
    url = f'{root}{path}'
    if len(url) > MAX_LINK_CHARS:
        # A very long host name would need modules too fine to print.  Nothing
        # else in the link can shrink (the token is identity + signature), so
        # give up on the link and let the sheet print its summary instead -
        # that is still the bill, it just cannot be scanned.
        return ''
    return url


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
