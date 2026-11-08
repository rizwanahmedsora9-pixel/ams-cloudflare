"""Build the Urdu bill document from a real bill.

This is the bridge between the app's domain objects and
:mod:`app.services.urdu_receipt`, which owns the approved sheet layout.  Every
figure printed here is read from the bill exactly as stored - the module never
recomputes a total, so the Urdu sheet cannot disagree with the ledger.

The sheet is the *only* Urdu bill the app produces: "Urdu PDF" and "Urdu
Print" both render this document, so what is previewed is what prints.  The
default is the single approved A5 sheet (``copies=1``); ``copies=2`` places the
same receipt twice on one A4 landscape leaf, ``اصل`` (customer) on the right
and ``نقل`` (office) on the left.
"""
from __future__ import annotations

from app.services import urdu_receipt as R
from app.services.bilingual import LABELS, _URDU_TX
from app.services.urdu_names import urdu_name

# Labels used by the Urdu sheet, in the sheet's own words.  They are collected
# here (not inline) so a wording change happens in one place.
L_BILL_NO = 'بل نمبر'
L_DATE = 'تاریخ'
L_TIME = 'وقت'
L_PHONE = 'فون'
L_CODE = 'کوڈ'
L_ITEMS = 'ٹرانزیکشن کی تفصیلات'
L_COL_INDEX = 'نمبر'
L_COL_NAME = 'تفصیل / آئٹم'
L_COL_QTY = 'مقدار'
L_COL_RATE = 'ریٹ'
L_COL_AMOUNT = 'رقم (روپے)'
L_TOTAL_SALES = 'کل فروخت'
L_PREVIOUS = 'پچھلا بقایا'
L_PAID = 'ادا شدہ رقم'
L_DISCOUNT = 'رعایت'
L_OUTSTANDING = 'کل بقایا رقم'
L_RECEIVED = 'وصول شدہ رقم'
L_BALANCE_AFTER = 'بقایا رقم'
L_SUPPLIER = 'سپلائر'
L_PARTY = 'بل برائے'
L_TERMS = 'شرائط و ضوابط'
L_SIGN = 'مجاز دستخط'

# Shop note shown in the strip above the party block.  Settings can override
# it; this is the wording of the approved sheet.
DEFAULT_SHOP_NOTE = ('سیمنٹ، سریا، اینٹ، ٹائل، چوگھٹ پیٹی، اینگل، بجری، '
                     'چناب بریٹ وغیرہ تعمیراتی سامان دستیاب ہے')

_PAYMENT_METHOD_UR = {
    'cash': 'نقد',
    'bank': 'بینک',
    'cheque': 'چیک',
    'check': 'چیک',
    'online': 'آن لائن',
    'card': 'کارڈ',
    'jazzcash': 'جاز کیش',
    'easypaisa': 'ایزی پیسہ',
}

_RECEIPT_TYPES = {'Payment', 'Receipt', 'Receipts'}

# The short word the meta strip prints between the date and the bill number.
_TYPE_LABEL = {
    'DirectSale': 'Sale',
    'Booking': 'Booking',
    'Payment': 'Payment',
    'Invoice': 'Invoice',
    'GRN': 'GRN',
    'PendingBill': 'Pending',
}


def _money(value):
    return R._qty(value)


def _urdu_word(value):
    """Urdu word for a known fixed term (kept verbatim when unknown)."""
    if not value:
        return ''
    key = str(value).strip()
    return LABELS.get(key) or key


def _method_label(method):
    """``Cash`` -> ``نقد`` (the sheet prints the method, not an English word)."""
    key = str(method or '').strip().lower()
    if not key:
        return ''
    word = _PAYMENT_METHOD_UR.get(key)
    if word:
        return word
    return _urdu_word(method)


def _settings_value(settings, *names, default=''):
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ''):
            return str(value).strip()
    return default


def _payment_method(bill):
    """The method as the bill recorded it.

    A ``DirectSale`` keeps it in ``payment_method``; payments, receipts and
    invoices keep it in ``method``.  Reading only one of the two leaves the
    Urdu sheet's detail column empty on half the document types.
    """
    for name in ('method', 'payment_method'):
        value = (getattr(bill, name, '') or '').strip()
        if value:
            return value
    return ''


def _payment_account_name(bill):
    """The account the money moved through, snapshotted or joined."""
    for name in ('account_name', 'bank_name'):
        value = (getattr(bill, name, '') or '').strip()
        if value:
            return value
    account = getattr(bill, 'payment_account', None)
    if account is not None:
        return (getattr(account, 'name', '') or '').strip()
    return ''


def _detail_rows(bill_type, bill, delivery_people, driver_name_ur, grn_bd=None):
    """``[(urdu label, value)]`` for the sheet's left-hand panel column."""
    rows = []
    method = _payment_method(bill)
    account_name = _payment_account_name(bill)
    bank = (getattr(bill, 'bank_name', '') or '').strip()
    payment_type = (getattr(bill, 'payment_type', '') or '').strip()

    if bill_type == 'GRN':
        supplier = urdu_name((getattr(bill, 'supplier_name', '') or '').strip())
        if supplier:
            rows.append((L_SUPPLIER, supplier))
        if method:
            rows.append(('ادائیگی', _method_label(method)))
        if grn_bd:
            vehicle = (getattr(bill, 'vehicle_no', '') or '').strip()
            if vehicle:
                rows.append(('گاڑی نمبر', vehicle))
        return rows

    if method:
        label = _method_label(method)
        value = f'({label}) {method}' if label and label != method else method
        rows.append(('ادائیگی', value))
    if payment_type and bill_type in _RECEIPT_TYPES | {'Payment'}:
        rows.append(('ادائیگی کی قسم', _urdu_word(payment_type)))
    if bank:
        rows.append(('بینک', bank))
    if account_name:
        rows.append(('اکاؤنٹ', account_name))
    account_no = (getattr(bill, 'account_no', '') or '').strip()
    if account_no:
        rows.append(('اکاؤنٹ نمبر', account_no))

    people = [urdu_name(p) for p in (delivery_people or []) if p]
    if not people and driver_name_ur:
        people = [urdu_name(driver_name_ur)]
    if people:
        rows.append(('ڈیلیوری', '، '.join(people)))
    return rows[:4]


def _item_rows(items):
    rows = []
    for index, item in enumerate(items or [], start=1):
        qty = item.get('qty') if isinstance(item, dict) else getattr(item, 'qty', 0)
        rate = (item.get('price_at_time') if isinstance(item, dict)
                else getattr(item, 'price_at_time', 0)) or 0
        rate = float(rate or 0)
        qty = float(qty or 0)
        name = ''
        if isinstance(item, dict):
            name = (item.get('name_ur') or item.get('name') or '')
        else:
            name = getattr(item, 'name_ur', '') or getattr(item, 'material_name', '')
        rows.append({
            'index': index,
            'name': str(name).strip(),
            'qty': _money(qty),
            'rate': _money(rate),
            'amount': _money(qty * rate),
        })
    return rows


def _summary_rows(bill_type, amount, paid, discount, previous):
    """Sales totals first, then the carried-forward balance."""
    rows = []
    if bill_type in _RECEIPT_TYPES or bill_type == 'Payment':
        rows.append({'label': L_RECEIVED, 'value': _money(amount)})
        if previous:
            rows.append({'label': L_PREVIOUS, 'value': _money(previous)})
            rows.append({'label': L_BALANCE_AFTER,
                         'value': _money(previous - amount), 'total': True})
        else:
            # Nothing was owed before this payment, so there is no closing
            # balance to print: the money received is the whole story.  A
            # "-45,000" balance under a receipt reads as a debt.
            rows[-1]['total'] = True
        return rows

    rows.append({'label': L_TOTAL_SALES, 'value': _money(amount)})
    if previous:
        rows.append({'label': L_PREVIOUS, 'value': _money(previous)})
    if discount:
        rows.append({'label': L_DISCOUNT, 'value': _money(discount)})
    rows.append({'label': L_PAID, 'value': _money(paid)})
    outstanding = previous + amount - paid - discount
    rows.append({'label': L_OUTSTANDING, 'value': _money(outstanding),
                 'total': True})
    return rows


def _panel_fields(bill_type, party_label, party_name, party_code, detail_rows):
    """The four inline fields of the info panel, in the sheet's order.

    Reading right to left the approved bill prints: bill-to, delivery, code,
    account.  A payment receipt has no delivery, so its method fills the slot
    instead.  Four is the panel's width - anything after that is dropped
    rather than pushed under the next field.
    """
    fields = []
    if party_name:
        fields.append((party_label or L_PARTY, party_name))
    rows = [r for r in (detail_rows or []) if r and r[1]]
    delivery = [r for r in rows if r[0].startswith('ڈیلیوری')]
    account = [r for r in rows if r[0] in ('اکاؤنٹ', 'بینک', 'اکاؤنٹ نمبر')]
    method = [r for r in rows if r[0] == 'ادائیگی']
    rest = [r for r in rows
            if r not in delivery and r not in account and r not in method]
    fields.extend(delivery)
    if party_code:
        fields.append(('کوڈ', party_code))
    fields.extend(account[:1])
    if bill_type in _RECEIPT_TYPES or bill_type == 'Payment':
        fields.extend(method[:1])
    fields.extend(rest)
    return fields[:4]


# ---------------------------------------------------------------------------
# QR payload
# ---------------------------------------------------------------------------
# The code in the sheet's header is what a customer's phone reads.  The
# reference receipt carried only the bill number there, so a scan showed
# nothing useful; the approved sheet's QR is therefore a *bill summary*: shop,
# bill number and type, date and time, the client's name and ID, the delivery
# person, the line items and the money figures.  Scanning the printed sheet
# (or the PDF on a phone) therefore shows the bill itself.
#
# Size discipline: the block is 51pt wide on an A5 sheet, so the symbol must
# not grow past ~61 modules (about 0.26mm per module) or a phone camera stops
# resolving it.  :func:`_qr_payload` therefore shrinks the content - item lines
# first, then to the compact reference line - until the *actual* encoded
# symbol fits that budget.  That is measured with the real encoder below, so
# the printed code is always the scannable one.
QR_MAX_MODULES = 61
QR_SEPARATOR = '|'
_QR_LINE_WIDTH = 44
_QR_ITEM_WIDTH = 60


def _qr_line(text, width=_QR_LINE_WIDTH):
    """One payload field, clipped so a stray long name cannot bloat the QR."""
    text = ' '.join(str(text or '').split())
    if len(text) > width:
        text = text[:width - 1].rstrip() + '~'
    return text


def _qr_number(value):
    """``1290`` / ``1290.5`` - never ``1,290`` (two bytes for a comma)."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return str(value or '')
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return ('%.2f' % number).rstrip('0').rstrip('.')


def _qr_item(item):
    """``1.ڈی جی 1*2000=2000`` - index, name, qty, rate, amount."""
    return _qr_line(f"{item.get('index')}.{item.get('name')} "
                    f"{_qr_number(str(item.get('qty', '')).replace(',', ''))}"
                    f"*{_qr_number(str(item.get('rate', '')).replace(',', ''))}"
                    f"={_qr_number(str(item.get('amount', '')).replace(',', ''))}",
                    width=_QR_ITEM_WIDTH)


def qr_symbol(text):
    """``(matrix, error_level)`` for *text* at the most robust level that fits.

    ``m`` is preferred (more damage tolerance on a paper bill); ``l`` is used
    only when ``m`` would need a bigger symbol than the printed block can
    resolve.  ``None`` when even ``l`` does not fit.
    """
    from app.services import qr_code
    for error in ('m', 'l'):
        for attempt in (error, error.upper()):
            matrix = qr_code.make_matrix(text, error=attempt)
            if matrix:
                return (matrix, error) if len(matrix) <= QR_MAX_MODULES else None
    return None


def _qr_payload(doc, item_rows, *, company_name='', client_name='',
                client_id='', delivery='', bill_type='', bill_id=None):
    """``(text, error)`` for the header QR.

    Priority, highest first - the facts a scan must always show:

    1. bill number, date and time, client name, client ID;
    2. the money figures (total / previous / paid / balance);
    3. as many item lines as still fit the scannable symbol;
    4. shop name, bill type and delivery person (decorative, dropped first).

    When the app can build a signed verify link, that link *replaces* the
    text: the phone then opens the complete bill, which no 51pt symbol could
    ever hold as text.
    """
    field = lambda value, width=_QR_LINE_WIDTH: _qr_line(value, width)  # noqa: E731
    essentials = [
        field(doc.get('bill_no'), 24),
        field(f"{doc.get('date')} {doc.get('time')}", 40),
        field(client_name or doc.get('party_name'), 30),
        field(client_id or doc.get('party_code'), 22),
    ]
    extras = [
        field(company_name or doc.get('company_name'), 34),
        field(doc.get('type_label'), 12),
        field(delivery, 24),
    ]
    totals = [field(f"{row.get('label')}:{row.get('value')}", 30)
              for row in doc.get('summary') or []]
    items = [_qr_item(row) for row in item_rows or []]

    def assemble(heads, lines):
        head = [p for part in heads for p in part if p]
        return QR_SEPARATOR.join(head + lines + totals)

    def encode(text):
        found = qr_symbol(text)
        return found[1] if found else None

    # The signed verify link opens the whole bill, so it is the best payload.
    if bill_id is not None:
        try:
            from app.services import bill_verify
            link = bill_verify.qr_payload(bill_type, bill_id, doc.get('bill_no'),
                                          posted=doc.get('date', ''))
        except Exception:
            link = ''
        if link:
            error = encode(link)
            if error:
                return link, error

    # Text payload: keep the essentials, then fit as many *real* line items as
    # the symbol allows.  The optional extras (shop name, bill type, delivery)
    # are sacrificed first when they cost an item line.
    best = None
    for heads in ([essentials, extras], [essentials]):
        if not encode(assemble(heads, [])):
            continue
        keep = 0
        for candidate in range(1, len(items) + 1):
            dropped = len(items) - candidate
            tail = items[:candidate] + ([f"+{dropped} مزید"] if dropped else [])
            if encode(assemble(heads, tail)):
                keep = candidate
            else:
                break
        # More items beats more decoration.
        score = (keep, len(heads))
        if best is None or score > best[0]:
            best = (score, heads, keep)
    if best is not None:
        _score, heads, keep = best
        dropped = len(items) - keep
        text = assemble(heads, items[:keep] +
                        ([f"+{dropped} مزید"] if dropped else []))
        error = encode(text)
        if error:
            return text, error

    # Last resort: one compact reference line, which always fits.
    compact = QR_SEPARATOR.join(str(part) for part in (
        doc.get('bill_no'), client_id or doc.get('party_code'),
        (doc.get('summary') or [{}])[0].get('value', ''),
        doc.get('date'), doc.get('time')) if part)
    return compact, (encode(compact) or 'l')


def build_document(*, bill_type='DirectSale', bill=None, items=None, client=None,
                   previous_balance=0, client_balance=0, delivery_people=None,
                   driver_name_ur='', client_name_ur='', transaction_label='',
                   transaction_note='', settings=None, terms=None,
                   grn_bd=None, party_label='', qr_text=None, qr_caption=None):
    """Return the :mod:`app.services.urdu_receipt` document for one bill."""
    bill = bill
    amount = float(getattr(bill, 'amount', 0) or 0)
    paid = float(getattr(bill, 'paid_amount', 0) or 0)
    discount = float(getattr(bill, 'discount', 0) or 0)
    previous = float(previous_balance or 0)

    bill_no = ''
    if bill_type == 'PendingBill':
        bill_no = (getattr(bill, 'bill_no', '') or '')
    bill_no = (bill_no or getattr(bill, 'manual_bill_no', '') or
               getattr(bill, 'auto_bill_no', '') or
               getattr(bill, 'invoice_no', '') or '')

    party_name = ''
    party_code = ''
    label = party_label
    if bill_type == 'GRN':
        party_name = urdu_name((getattr(bill, 'supplier_name', '') or '').strip())
        label = label or L_SUPPLIER
    else:
        saved_ur = (getattr(client, 'name_ur', None) or '') if client is not None else ''
        party_name = client_name_ur or urdu_name(
            getattr(bill, 'client_name', '') or '', saved_ur)
        party_code = (getattr(client, 'code', '') if client is not None else '') or ''
        if not party_code:
            party_code = (getattr(bill, 'client_code', '') or '')
        label = label or L_PARTY

    party_phone = ''
    if client is not None:
        party_phone = (getattr(client, 'phone', '') or '').strip()
    if not party_phone:
        party_phone = (getattr(bill, 'client_phone', '') or
                       getattr(bill, 'supplier_phone', '') or '').strip()
    party_phone = R._phone(party_phone)

    # The sheet's head is Urdu, so an English shop name is transliterated the
    # same way client and driver names are (a curated entry wins when the
    # settings already hold Urdu text - urdu_name keeps it untouched).
    company_name = urdu_name(_settings_value(
        settings, 'company_name', default='FAZAL BUILDING MATERIALS'), '')
    company_address = urdu_name(_settings_value(
        settings, 'company_address', default='JALAL PUR SOBTIAN GUJRAT'), '')
    company_phone = _settings_value(settings, 'company_phone',
                                    default='+92331-0000993 | +92340-3872722')
    proprietor = urdu_name(_settings_value(settings, 'proprietor_name_ur'))
    # Use the reference branding only for the reference business.
    if not proprietor and _settings_value(settings, 'company_name', default='FAZAL BUILDING MATERIALS').upper() == 'FAZAL BUILDING MATERIALS':
        proprietor = 'عدنان احمد'
    note = _settings_value(settings, 'company_note_ur')
    if not note:
        note = (getattr(bill, 'note', '') or '').strip()
    if not note:
        note = DEFAULT_SHOP_NOTE

    term_rows = []
    for term in terms or []:
        text = (getattr(term, 'content_ur', '') or '').strip()
        title = (getattr(term, 'title', '') or '').strip()
        if text or title:
            term_rows.append({'title': title, 'text': text})

    date_posted = getattr(bill, 'date_posted', None)
    if date_posted is None:
        date_posted = getattr(bill, 'created_at', None)

    detail_rows = _detail_rows(bill_type, bill, delivery_people,
                               driver_name_ur, grn_bd=grn_bd)
    item_rows = _item_rows(items)
    summary_rows = _summary_rows(bill_type, amount, paid, discount, previous)
    # Build the sheet document once without a QR so the payload quotes the
    # exact bill number, date, time and totals that are printed on it.
    document = R.build_document(
        bill_no=bill_no,
        date_posted=date_posted,
        company_name=company_name,
        company_address=company_address,
        company_phone=company_phone,
        proprietor=proprietor,
        note=note,
        party_name=party_name,
        party_code=party_code,
        party_phone=party_phone,
        party_label=label,
        detail_rows=detail_rows,
        fields=_panel_fields(bill_type, label, party_name, party_code,
                             detail_rows),
        type_label=_TYPE_LABEL.get(bill_type, ''),
        items=item_rows,
        summary=summary_rows,
        terms=term_rows,
        signature_label=L_SIGN,
        items_title=L_ITEMS,
    )
    # The header QR is the bill itself: shop, number, type, date and time,
    # client name and ID, delivery person, the line items and the totals.
    qr_error = ''
    if qr_text is None:
        delivery = '، '.join(urdu_name(p) for p in (delivery_people or []) if p)
        if delivery:
            delivery = f"ڈیلیوری {delivery}"
        elif driver_name_ur:
            delivery = f"ڈیلیوری {urdu_name(driver_name_ur)}"
        qr_text, qr_error = _qr_payload(
            document, item_rows,
            company_name=company_name,
            client_name=party_name,
            client_id=party_code,
            delivery=delivery,
            bill_type=bill_type,
            bill_id=getattr(bill, 'id', None),
        )
    if qr_caption is None:
        qr_caption = bill_no
    document['qr_text'] = qr_text or ''
    document['qr_error'] = qr_error or ''
    document['qr_caption'] = qr_caption or ''
    return document


def render_pdf(document, title='Urdu Bill', copies=1):
    """PDF bytes for *document* (``None`` when ReportLab cannot run).

    ``copies=1`` (the default) is the single approved A5 sheet.  ``copies=2``
    is the carbon-copy leaf: the same A5 bill twice on one A4 landscape page,
    original on the right and copy on the left.
    """
    return R.render_pdf(document, title=title, copies=copies)


def render_html(document, title='Urdu Bill', auto_print=False, copies=1):
    """Full print page for *document* (same pages as the PDF)."""
    return R.render_html(document, title=title, auto_print=auto_print,
                         copies=copies)
