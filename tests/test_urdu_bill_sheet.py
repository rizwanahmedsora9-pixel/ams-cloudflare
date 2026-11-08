"""The Urdu bill is its own sheet — not the English receipt with translated labels.

The approved Urdu bill is defined by ``app/services/urdu_receipt.py``: an A5
page with a three-row meta header, a company block, a note strip + two-column
panel, a navy item table, a navy total bar and a sign-off footer.  These tests
pin that document so a later change to the English receipt (or to the label
dictionary) cannot quietly reshape it, and so "Urdu Print" and "Urdu PDF" stay
the same page.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from app.services import bill_urdu
from app.services import urdu_receipt as R


ITEMS = [
    {'name_ur': 'ڈی جی', 'qty': 1, 'price_at_time': 2000},
    {'name_ur': 'سیمنٹ ٹھیکہ', 'qty': 50, 'price_at_time': 1290},
    {'name_ur': '12 ملی میٹر سریا', 'qty': 1964, 'price_at_time': 224},
    {'name_ur': 'چناب بریٹ ٹرالی', 'qty': 2, 'price_at_time': 12500},
    {'name_ur': 'بجری ٹرالی', 'qty': 2, 'price_at_time': 14000},
    {'name_ur': 'اینٹ 1000', 'qty': 3, 'price_at_time': 18000},
    {'name_ur': 'کرایہ سیمنٹ', 'qty': 50, 'price_at_time': 30},
]

NOTE = ('سیمنٹ، سریا، اینٹ، ٹائل، چوگھٹ پیٹی، اینگل، بجری، '
        'چناب بریٹ وغیرہ تعمیراتی سامان دستیاب ہے')


def _bill(**over):
    data = dict(
        manual_bill_no='SB-SL-1008',
        amount=614936,
        paid_amount=0,
        discount=0,
        date_posted=datetime(2026, 11, 7, 12, 20),
        method='Cash',
        account_name='Drawer Cash',
        account_no='',
        bank_name='',
        payment_type='Receipt',
        note=NOTE,
        client_name='Muhammad Shafiq',
        client_code='FBMCL-00002',
        driver_name='عدنان احمد',
    )
    data.update(over)
    return SimpleNamespace(**data)


def _settings(**over):
    data = dict(
        company_name='FAZAL BUILDING MATERIALS',
        company_address='JALAL PUR SOBTIAN GUJRAT',
        company_phone='+92331-0000993 | +92340-3872722',
        proprietor_name_ur='عدنان احمد',
        company_note_ur='',
    )
    data.update(over)
    return SimpleNamespace(**data)


def _document(**over):
    options = dict(
        bill_type='DirectSale',
        bill=_bill(),
        items=ITEMS,
        previous_balance=31700,
        client_name_ur='محمد شفیق',
        delivery_people=['عدنان احمد'],
        driver_name_ur='عدنان احمد',
        settings=_settings(),
    )
    options.update(over)
    return bill_urdu.build_document(**options)


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


# ---------------------------------------------------------------------------
# Geometry: one A5 sheet, every block at its approved anchor
# ---------------------------------------------------------------------------

def test_sheet_is_one_a5_page_with_the_approved_blocks():
    doc = _document()
    data = bill_urdu.render_pdf(doc)
    assert data and data.startswith(b'%PDF-')

    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert round(float(box.width), 1) == round(R.PAGE_W, 1)
    assert round(float(box.height), 1) == round(R.PAGE_H, 1)


def test_sheet_anchors_match_the_approved_bill():
    """The header, panel, item table, summary and footer keep their places."""
    sheets = R.layout_document(_document())
    assert len(sheets) == 1
    ops = sheets[0].ops

    rects = [op for op in ops if op['op'] == 'rect']
    # the closing double rule under the header
    assert any(abs(op['y'] - R.Y_RULE_1) < 0.1 and abs(op['h'] - 1.5) < 0.1
               for op in rects), 'header double rule missing'
    # the info panel and its note strip
    assert any(abs(op['y'] - R.Y_PANEL) < 0.1 for op in rects), 'panel missing'
    note_edge = R.Y_PANEL + R.Y_NOTE_H
    assert any(op['op'] == 'line' and abs(op['y0'] - note_edge) < 0.1
               for op in ops), 'note strip divider missing'
    # the navy item header row and the total bar
    assert any(abs(op['y'] - R.Y_ITEMS_HEAD) < 0.1 and op['fill'] == R.NAVY
               for op in rects), 'item header missing'
    assert any(op['y'] >= R.Y_ITEMS_HEAD and op['fill'] == R.GRID_ROW
               for op in rects), 'pale row hairlines missing'
    assert any(op['fill'] == R.NAVY and abs(op['w'] - 192.8) < 0.5
               for op in rects), 'navy total bar missing'
    # the dashed stamp box and the footer rule
    assert any(op.get('dash') for op in ops), 'dashed stamp box missing'
    assert any(op['op'] == 'line' and abs(op['y0'] - R.Y_FOOT_RULE) < 0.1
               for op in ops), 'footer rule missing'

    lines = [op for op in ops if op['op'] == 'line']
    assert any(abs(op['x0'] - 224.5) < 0.1 for op in lines), \
        'panel column divider missing'
    assert any(abs(op['x0'] - 121.6) < 0.1 for op in lines), \
        'summary column divider missing'


def test_item_table_columns_are_the_approved_widths():
    columns = R._item_columns()
    assert [c['label'] for c in columns] == [
        'رقم (روپے)', 'ریٹ', 'مقدار', 'تفصیل / میٹیریل', 'نمبر']
    assert [round(c['x0'], 1) for c in columns] == [
        R.LEFT, 107.2, 169.4, 218.1, 365.1]
    assert round(columns[-1]['x1'], 1) == round(R.RIGHT, 1)


def test_sheet_text_holds_the_urdu_furniture_and_every_figure():
    op_text = ' '.join(op['text'] for op in R.layout_document(_document())[0].ops
                       if op['op'] == 'text')
    for label in ('بل نمبر', 'تاریخ', 'وقت', 'فون', 'آئٹمز', 'کل فروخت',
                  'پچھلا بقایا', 'ادا شدہ رقم', 'کل بقایا رقم',
                  'کمپنی مہر', 'وصول کنندہ / مجاز دستخط'):
        assert label in op_text, label
    # the bill's own figures, copied verbatim
    for value in ('SB-SL-1008', '614,936', '31,700', '2,000', '1,964', '224'):
        assert value in op_text, value
    # English furniture must not survive on an Urdu sheet
    for english in ('INVOICE', 'Bill To', 'Transaction Details', 'Items',
                    'Total Sales'):
        assert english not in op_text, english


# ---------------------------------------------------------------------------
# Numbers and dates agree with the bill
# ---------------------------------------------------------------------------

def test_summary_figures_come_straight_from_the_bill():
    doc = _document()
    values = {row['label']: row['value'] for row in doc['summary']}
    assert values['کل فروخت'] == '614,936'
    assert values['پچھلا بقایا'] == '31,700'
    assert values['ادا شدہ رقم'] == '0'
    # outstanding = previous + this bill - paid
    assert values['کل بقایا رقم'] == '646,636'
    assert doc['summary'][-1]['total'] is True


def test_summary_without_a_previous_balance_has_no_carry_forward_row():
    doc = _document(previous_balance=0)
    labels = [row['label'] for row in doc['summary']]
    assert labels == ['کل فروخت', 'ادا شدہ رقم', 'کل بقایا رقم']


def test_urdu_date_and_clock_read_like_the_sheet():
    assert R._urdu_date(datetime(2026, 11, 7)) == '07 نومبر 2026'
    assert R._urdu_time(datetime(2026, 11, 7, 12, 20)) == '12:20 دوپہر'
    assert R._urdu_time(datetime(2026, 11, 7, 8, 38)) == '8:38 صبح'
    assert R._urdu_time(datetime(2026, 11, 7, 20, 5)) == '8:05 رات'


def test_phone_line_is_split_into_two_numbers():
    assert R.split_phones('+92331-0000993 | +92340-3872722') == [
        '+92 331 0000993', '+92 340 3872722']
    # settings are typed free-hand: spaces are a separator too
    assert R.split_phones('+92331 0000993 +92340 3872722') == [
        '+92 331 0000993', '+92 340 3872722']


def test_item_amounts_are_quantity_times_rate_as_posted():
    rows = bill_urdu._item_rows(ITEMS)
    assert [row['amount'] for row in rows] == [
        '2,000', '64,500', '439,936', '25,000', '28,000', '54,000', '1,500']
    assert [row['index'] for row in rows] == [1, 2, 3, 4, 5, 6, 7]


def test_receipt_bill_shows_received_and_remaining_balance():
    bill = _bill(amount=25000, payment_type='Receipt', manual_bill_no='MB NO.9102')
    doc = bill_urdu.build_document(bill_type='Payment', bill=bill,
                                   previous_balance=100000)
    labels = [row['label'] for row in doc['summary']]
    assert labels == ['وصول شدہ رقم', 'پچھلا بقایا', 'بقایا رقم']
    assert doc['summary'][-1]['value'] == '75,000'


# ---------------------------------------------------------------------------
# Urdu print is the same page as the Urdu PDF
# ---------------------------------------------------------------------------

def test_print_page_is_the_same_rtl_sheet():
    html = bill_urdu.render_html(_document())
    assert html.startswith('<!DOCTYPE html>')
    assert 'dir="rtl"' in html
    assert '/static/fonts/JameelNooriNastaleeq.ttf' in html
    assert '/static/fonts/Inter-Bold.ttf' in html
    # one absolutely positioned page per PDF page
    assert html.count('<div class="pg">') == 1
    assert '@page { size: 419.53pt 595.28pt; margin: 0; }' in html
    # the same labels and figures as the PDF
    for text in ('بل نمبر', 'آئٹمز', 'کل بقایا رقم', '614,936', 'FBMCL-00002'):
        assert text in html, text
    # the browser must not be left to reflow or re-translate anything
    assert 'INVOICE' not in html
    assert '@page' in html


def test_print_page_escapes_user_text():
    doc = _document(bill=_bill(note='<script>alert(1)</script>'))
    html = bill_urdu.render_html(doc)
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html


def test_english_text_in_an_urdu_sheet_keeps_its_word_order():
    """``Cash`` / product codes must not be reversed by the RTL pass."""
    words = R.rtl_words('Drawer Cash')
    assert [w for w, _u in words] == ['Drawer', 'Cash'][::-1]
    sheet = R.Sheet()
    sheet.text(100, 50, 'Drawer Cash', 9, urdu=True)
    op = sheet.ops[-1]
    assert op['urdu'] is False          # pure Latin -> drawn left to right
    assert op['text'] == 'Drawer Cash'


def test_mixed_urdu_line_puts_its_first_word_at_the_right():
    """``rtl_words`` returns visual order: the last item is drawn rightmost."""
    words = R.rtl_words('07 نومبر 2026')
    assert words[-1] == ('07', False)      # first word of the line, hard right
    assert words[0] == ('2026', False)     # last word of the line, hard left
    assert [w for w, _u in words] == ['2026', 'نومبر', '07']


# ---------------------------------------------------------------------------
# Real bill through the real route
# ---------------------------------------------------------------------------

def _login(client):
    resp = client.post('/login', data={'username': 'Admin',
                                       'password': 'Admin@fbm12345'},
                       follow_redirects=False)
    assert resp.status_code in (302, 303)


@pytest.fixture()
def sale(app, client):
    """A real DirectSale posted through the real route, in Urdu."""
    from app import db
    from models import Client, DirectSale, Entry, Material, Settings
    from app.services.void_rebuild import _rebuild_material_totals

    _login(client)

    with app.app_context():
        settings = Settings.query.first() or Settings()
        settings.allow_global_negative_stock = True
        db.session.add(settings)
        db.session.commit()

    names = ['ڈی جی', 'سیمنٹ ٹھیکہ']
    for name in names:
        client.post('/add_material',
                    data={'material_name': name, 'material_unit': 'Bags'},
                    follow_redirects=True)
    client.post('/add_client', data={'name': 'Muhammad Shafiq',
                                     'code': 'FBMCL-00009',
                                     'category': 'General',
                                     'opening_balance': '0'},
                follow_redirects=True)
    client.post('/accounts/accounts/add', data={
        'name': 'URDU CASH COUNTER', 'class_category': 'Assets',
        'class_subcategory': 'Cash', 'class_account_type': 'Main Cash',
        'account_status': 'active', 'opening_amount': '0',
        'opening_position': 'debit',
        'opening_effective_date': '2026-01-01'}, follow_redirects=True)

    with app.app_context():
        from models import Account
        mats = [(m.id, m.name) for m in Material.query.filter(
            Material.name.in_(names)).all()]
        client_row = Client.query.filter_by(code='FBMCL-00009').first()
        account = Account.query.filter(Account.name.like('%URDU CASH%')).first()
        client_row.name_ur = 'محمد شفیق'
        db.session.add(Entry(date='2026-06-01', time='09:00:00', type='IN',
                             material='ڈی جی', qty=5000, bill_no='MB NO.9001',
                             client_category='Stock In'))
        _rebuild_material_totals()
        db.session.commit()
        payload = {'client_code': client_row.code,
                   'client_name': client_row.name,
                   'account': account.id,
                   'materials': {name: mid for mid, name in mats}}

    rows = [('ڈی جی', 1, 2000), ('سیمنٹ ٹھیکہ', 50, 1290)]
    resp = client.post('/add_direct_sale', data={
        'client_code': payload['client_code'],
        'client_name': payload['client_name'],
        'category': 'Credit Customer',
        'manual_bill_no': 'SB-SL-2001',
        'driver_name': 'عدنان احمد',
        'paid_amount': '0',
        'note': NOTE,
        'product_name[]': [row[0] for row in rows],
        'material_id[]': [str(payload['materials'][row[0]]) for row in rows],
        'qty[]': [str(row[1]) for row in rows],
        'unit_rate[]': [str(row[2]) for row in rows],
        'payment_method': 'Cash',
        'payment_account_id': str(payload['account']),
    }, follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Direct sale added successfully' in body, 'the sale was rejected'

    with app.app_context():
        row = DirectSale.query.order_by(DirectSale.id.desc()).first()
        assert row is not None, 'the sale was not posted'
        return {'id': row.id, 'bill_no': row.manual_bill_no}


def test_route_serves_the_urdu_sheet_as_pdf(client, sale):
    url = (f"/download_invoice/{sale['bill_no']}?src=direct_sale"
           f"&src_id={sale['id']}&lang=ur&tc=0")
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.data.startswith(b'%PDF-')
    assert '-UR.pdf' in resp.headers['Content-Disposition']
    # the sheet embeds its own two faces
    assert b'Jameel' in resp.data
    reader = PdfReader(io.BytesIO(resp.data))
    assert len(reader.pages) == 1
    assert round(float(reader.pages[0].mediabox.width), 1) == round(R.PAGE_W, 1)


def test_route_print_is_the_same_urdu_sheet(client, sale):
    url = (f"/download_invoice/{sale['bill_no']}?src=direct_sale"
           f"&src_id={sale['id']}&lang=ur&action=print&tc=0")
    resp = client.get(url)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '-UR.html' in resp.headers['Content-Disposition']
    assert 'dir="rtl"' in html
    assert '<div class="pg">' in html
    # English receipt furniture must never leak into the Urdu sheet
    for english in ('rcpt-header', 'rcpt-table', 'English PDF'):
        assert english not in html, english
    assert 'آئٹمز' in html


def test_english_download_is_untouched(client, sale):
    url = (f"/download_invoice/{sale['bill_no']}?src=direct_sale"
           f"&src_id={sale['id']}")
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.data.startswith(b'%PDF-')
    assert '-EN.pdf' in resp.headers['Content-Disposition']
    text = _pdf_text(resp.data).upper()
    assert 'INVOICE' in text or 'RECEIPT' in text
    assert 'بل نمبر' not in text
