"""Build the Urdu bill document from a real bill.

This is the bridge between the app's domain objects and
:mod:`app.services.urdu_receipt`, which owns the approved sheet layout.  Every
figure printed here is read from the bill exactly as stored - the module never
recomputes a total, so the Urdu sheet cannot disagree with the ledger.

The sheet is the *only* Urdu bill the app produces: "Urdu PDF" and "Urdu
Print" both render this document, so what is previewed is what prints.  It is
printed as a carbon copy by default - the same A5 receipt twice on one A4
landscape leaf, ``اصل`` (customer) on the right and ``نقل`` (office) on the
left - and as a single A5 page when ``copies=1``.
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
        supplier = (getattr(bill, 'supplier_name', '') or '').strip()
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

    people = [p for p in (delivery_people or []) if p]
    if not people and driver_name_ur:
        people = [driver_name_ur]
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
        party_name = (getattr(bill, 'supplier_name', '') or '').strip()
        label = label or L_SUPPLIER
    else:
        party_name = client_name_ur or (getattr(bill, 'client_name', '') or '')
        party_code = (getattr(client, 'code', '') if client is not None else '') or ''
        if not party_code:
            party_code = (getattr(bill, 'client_code', '') or '')
        label = label or L_PARTY

    # The sheet's head is Urdu, so an English shop name is transliterated the
    # same way client and driver names are (a curated entry wins when the
    # settings already hold Urdu text - urdu_name keeps it untouched).
    company_name = urdu_name(_settings_value(
        settings, 'company_name', default='FAZAL BUILDING MATERIALS'), '')
    company_address = urdu_name(_settings_value(
        settings, 'company_address', default='JALAL PUR SOBTIAN GUJRAT'), '')
    company_phone = _settings_value(settings, 'company_phone',
                                    default='+92331-0000993 | +92340-3872722')
    proprietor = _settings_value(settings, 'proprietor_name_ur')
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
    # The QR code carries the scan-and-verify line of the bill: number, party
    # code, the amount and the date, pipe separated so any phone reader shows
    # the same four facts.
    qr_parts = [bill_no]
    if party_code:
        qr_parts.append(str(party_code))
    if bill_type in _RECEIPT_TYPES or bill_type == 'Payment':
        qr_parts.append(_money(amount))
    else:
        qr_parts.append(_money(amount))
    if date_posted is not None:
        try:
            qr_parts.append(date_posted.strftime('%d-%m-%Y'))
        except Exception:
            pass
    if qr_text is None:
        qr_text = ' | '.join(p for p in qr_parts if p)
    if qr_caption is None:
        qr_caption = bill_no

    return R.build_document(
        bill_no=bill_no,
        date_posted=date_posted,
        company_name=company_name,
        company_address=company_address,
        company_phone=company_phone,
        proprietor=proprietor,
        note=note,
        party_name=party_name,
        party_code=party_code,
        party_label=label,
        detail_rows=detail_rows,
        fields=_panel_fields(bill_type, label, party_name, party_code,
                             detail_rows),
        type_label=_TYPE_LABEL.get(bill_type, ''),
        qr_text=qr_text,
        qr_caption=qr_caption,
        items=_item_rows(items),
        summary=_summary_rows(bill_type, amount, paid, discount, previous),
        terms=term_rows,
        signature_label=L_SIGN,
        items_title=L_ITEMS,
    )


def render_pdf(document, title='Urdu Bill', copies=2):
    """PDF bytes for *document* (``None`` when ReportLab cannot run).

    ``copies=2`` (the default) is the carbon-copy leaf: the same A5 bill twice
    on one A4 landscape page, original on the right and copy on the left.
    """
    return R.render_pdf(document, title=title, copies=copies)


def render_html(document, title='Urdu Bill', auto_print=False, copies=2):
    """Full print page for *document* (same pages as the PDF)."""
    return R.render_html(document, title=title, auto_print=auto_print,
                         copies=copies)
