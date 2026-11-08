"""Build the Urdu bill document from a real bill.

This is the bridge between the app's domain objects and
:mod:`app.services.urdu_receipt`, which owns the approved sheet layout.  Every
figure printed here is read from the bill exactly as stored - the module never
recomputes a total, so the Urdu sheet cannot disagree with the ledger.

The sheet is the *only* Urdu bill the app produces: "Urdu PDF" and "Urdu
Print" both render this document, so what is previewed is what prints.
"""
from __future__ import annotations

from app.services import urdu_receipt as R
from app.services.bilingual import LABELS, _URDU_TX

# Labels used by the Urdu sheet, in the sheet's own words.  They are collected
# here (not inline) so a wording change happens in one place.
L_BILL_NO = 'بل نمبر'
L_DATE = 'تاریخ'
L_TIME = 'وقت'
L_PHONE = 'فون'
L_CODE = 'کوڈ'
L_ITEMS = 'آئٹمز'
L_COL_INDEX = 'نمبر'
L_COL_NAME = 'تفصیل / میٹیریل'
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
L_STAMP = 'کمپنی مہر'
L_SIGN = 'وصول کنندہ / مجاز دستخط'
L_THANKS = 'آپ کے کاروبار کا شکریہ'
L_CREDIT = 'سافٹ ویئر: اے ایم ایس سسٹم فار ایز'

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
        rows.append(('اکاؤنٹ کا نام', account_name))
    account_no = (getattr(bill, 'account_no', '') or '').strip()
    if account_no:
        rows.append(('اکاؤنٹ نمبر', account_no))

    people = [p for p in (delivery_people or []) if p]
    if not people and driver_name_ur:
        people = [driver_name_ur]
    if people:
        label = 'ڈلیوری پرسن' if len(people) == 1 else 'ڈلیوری پرسنز'
        rows.append((label, '، '.join(people)))
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


def build_document(*, bill_type='DirectSale', bill=None, items=None, client=None,
                   previous_balance=0, client_balance=0, delivery_people=None,
                   driver_name_ur='', client_name_ur='', transaction_label='',
                   transaction_note='', settings=None, terms=None,
                   grn_bd=None, party_label=''):
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

    company_name = _settings_value(settings, 'company_name',
                                   default='FAZAL BUILDING MATERIALS')
    company_address = _settings_value(settings, 'company_address',
                                      default='JALAL PUR SOBTIAN GUJRAT')
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
        detail_rows=_detail_rows(bill_type, bill, delivery_people,
                                 driver_name_ur, grn_bd=grn_bd),
        items=_item_rows(items),
        summary=_summary_rows(bill_type, amount, paid, discount, previous),
        terms=term_rows,
        footer_thanks=L_THANKS,
        footer_credit=L_CREDIT,
        signature_left=L_STAMP,
        signature_right=L_SIGN,
        items_title=L_ITEMS,
    )


def render_pdf(document, title='Urdu Bill'):
    """PDF bytes for *document* (``None`` when ReportLab cannot run)."""
    return R.render_pdf(document, title=title)


def render_html(document, title='Urdu Bill', auto_print=False):
    """Full print page for *document* (same sheet as the PDF)."""
    return R.render_html(document, title=title, auto_print=auto_print)
