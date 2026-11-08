"""The Urdu bill is its own sheet — not the English receipt with translated labels.

The sheet is defined by ``app/services/urdu_receipt.py`` and measured off the
approved reference PDF ("max possible.pdf"): an A5 page whose header carries a
QR block, the Nastaleeq shop name, the proprietor and the phones over a thick
navy rule; a four-cell meta strip; a pale panel with the four inline fields and
the shop note; a roof-ruled item table; the summary box on the right with the
signature rule beside it; and the terms in two numbered columns.

These tests pin that document, so a later change to the English receipt (or to
the label dictionary) cannot quietly reshape it, and so "Urdu Print" and
"Urdu PDF" stay the same page.  They also pin the carbon copy: two identical
A5 copies on one A4 landscape leaf.
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

TERMS = [
    'بینک پر خریدار کو دیا گیا ریٹ صرف اسی صورت میں لاگو ہوگا جب وہ اس بینک کی پوری رقم ادا کرے۔',
    'اگر بینک کی رقم جزوی ادا کی جائے تو بینک کا ریٹ صرف ادا شدہ رقم کے مطابق مال پر لاگو ہوگا۔',
    'بقیہ رقم/بینک کے بقیہ مال پر مارکیٹ کا نیا ریٹ لاگو ہوگا۔',
    'اگر کسی قسم کا کوئی فرق پاپا جائے تو 10 دن کے اندر رابطہ کریں۔',
    'مال واپس یا تبدیل نہیں ہوگا، سوائے ڈیلیوری کے وقت ثابت شدہ نقص کے۔',
    'اتروائی کے بعد مال کی ٹوٹ پھوٹ، نقصان یا چوری کی ذمہ داری کمپنی پر نہیں۔',
    'ادھار کی صورت میں بقایا رقم باہمی طے شدہ مدت میں ادا کرنا لازم ہے۔',
]


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


def _ops(sheet, kind):
    return [op for op in sheet.ops if op['op'] == kind]


# ---------------------------------------------------------------------------
# Paper: one A5 sheet, or the carbon-copy A4 leaf
# ---------------------------------------------------------------------------

def test_single_copy_is_one_a5_page():
    data = bill_urdu.render_pdf(_document(), copies=1)
    assert data and data.startswith(b'%PDF-')

    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert round(float(box.width), 1) == round(R.PAGE_W, 1)
    assert round(float(box.height), 1) == round(R.PAGE_H, 1)


def test_carbon_copy_is_two_a5_copies_on_one_a4_leaf():
    data = bill_urdu.render_pdf(_document())          # copies default to 2
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 1, 'a carbon copy is one leaf, not two pages'
    box = reader.pages[0].mediabox
    assert round(float(box.width), 1) == round(R.A4_W, 1)
    assert round(float(box.height), 1) == round(R.A4_H, 1)
    # A4 landscape holds two A5 portraits side by side, with even margins
    assert R.A4_W >= 2 * R.PAGE_W
    assert R.A4_W - 2 * R.PAGE_W < 4.0


def test_both_copies_hold_the_very_same_marks():
    doc = _document()
    content = R.layout_document(doc)[0]
    page = R.compose_document(doc, copies=2)[0]

    offset = (R.A4_W - 2 * R.PAGE_W) / 2.0
    text_ops = [op for op in page.ops if op['op'] == 'text']
    for op in content.ops:
        if op['op'] != 'text':
            continue
        for dx in (offset, offset + R.PAGE_W):
            assert any(abs(t['y'] - op['y']) < 1e-6
                       and abs(t['x'] - (op['x'] + dx)) < 1e-6
                       and t['text'] == op['text'] for t in text_ops), op


def test_copies_carry_the_original_and_the_carbon_marks():
    page = R.compose_document(_document(), copies=2)[0]
    labels = [op['text'] for op in page.ops if op['op'] == 'text']
    assert R.COPY_ORIGINAL in labels
    assert R.COPY_CARBON in labels


def test_single_copy_has_no_cut_line_or_copy_marks():
    page = R.compose_document(_document(), copies=1)[0]
    labels = [op['text'] for op in page.ops if op['op'] == 'text']
    assert R.COPY_ORIGINAL not in labels
    assert not [op for op in page.ops
                if op.get('dash') and op['op'] in ('line', 'seg')
                and abs(op['x0'] - op['x1']) < 0.01], 'no cut line on one copy'


# ---------------------------------------------------------------------------
# Geometry: every block at its reference anchor
# ---------------------------------------------------------------------------

def test_sheet_anchors_match_the_reference_bill():
    ops = R.layout_document(_document())[0].ops
    rects = _ops(R.layout_document(_document())[0], 'rect')
    lines = _ops(R.layout_document(_document())[0], 'line')

    # the thick navy rule and its thin companion under the header
    assert any(abs(op['y'] - 75.0) < 0.1 and abs(op['h'] - 2.9) < 0.1
               and op['fill'] == R.NAVY for op in rects), 'header rule missing'
    assert any(abs(op['y'] - 79.2) < 0.1 and op['fill'] == R.NAVY
               for op in rects), 'second header rule missing'
    # the four-cell meta strip
    assert any(abs(op['y'] - 80.7) < 0.1 and abs(op['h'] - 16.2) < 0.1
               for op in rects), 'meta strip missing'
    # the info panel and its dotted divider
    assert any(abs(op['y'] - 99.7) < 0.1 and abs(op['h'] - 39.9) < 0.1
               for op in rects), 'info panel missing'
    assert any(op['op'] == 'line' and abs(op['y0'] - 121.4) < 0.1
               and op.get('dash') for op in lines), 'dotted divider missing'
    # the navy item header row
    assert any(abs(op['y'] - 158.7) < 0.1 and abs(op['h'] - 15.9) < 0.1
               and op['fill'] == R.NAVY for op in rects), 'item header missing'
    # the summary box on the right half, closed by the navy total bar
    assert any(abs(op['x'] - 229.4) < 0.1
               and abs(op['w'] - (397.4 - 229.4)) < 0.2
               and op['fill'] == R.NAVY for op in rects), 'summary bar missing'
    # the signature rule beside the summary
    assert any(abs(op['y0'] - op['y1']) < 0.01
               and abs(op['x0'] - 66.5) < 0.1 and abs(op['x1'] - 208.3) < 0.1
               for op in lines), 'signature rule missing'
    assert ops, 'the sheet is empty'


def test_item_table_columns_are_the_reference_widths():
    columns = R._item_columns()
    assert [c['label'] for c in columns] == [
        'رقم (روپے)', 'ریٹ', 'مقدار', 'تفصیل / آئٹم', 'نمبر']
    assert [round(c['x0'], 1) for c in columns] == [
        R.LEFT, 114.8, 187.0, 243.9, 369.3]
    assert round(columns[-1]['x1'], 1) == round(R.RIGHT, 1)


def test_fifteen_rows_end_where_the_reference_table_ends():
    items = [{'name_ur': 'اینٹ', 'qty': 1, 'price_at_time': 10}] * 15
    sheet = R.layout_document(_document(items=items))[0]
    lines = _ops(sheet, 'line')
    # the reference's ruled table closes at y = 404.6 and the summary starts
    # 6.9pt under it
    assert any(abs(op['y0'] - 404.6) < 0.2 for op in lines)
    # summary box: 58.6pt tall under a 6.9pt gap, closed by the navy bar
    total = [op for op in _ops(sheet, 'rect')
             if op['fill'] == R.NAVY and abs(op['x'] - 229.4) < 0.1]
    assert total and abs(total[0]['y'] - 455.7) < 0.4


def test_row_height_and_zebra_tint_are_the_reference_ones():
    sheet = R.layout_document(_document())[0]
    zebra = [op for op in _ops(sheet, 'rect') if op['fill'] == R.BAR
             and abs(op['x'] - R.LEFT) < 0.1 and abs(op['h'] - R.ROW_H) < 0.1]
    assert len(zebra) == 3, 'every second row of seven is tinted'
    tops = sorted(op['y'] for op in zebra)
    assert abs(tops[1] - tops[0] - 2 * R.ROW_H) < 0.1


def test_sheet_text_holds_the_urdu_furniture_and_every_figure():
    op_text = ' '.join(op['text'] for op in R.layout_document(_document())[0].ops
                       if op['op'] == 'text')
    for label in ('بل نمبر', 'تاریخ', 'وقت', 'فضل بلڈنگ میٹیریلز',
                  'ٹرانزیکشن کی تفصیلات', 'کل فروخت', 'پچھلا بقایا',
                  'ادا شدہ رقم', 'کل بقایا رقم', 'مجاز دستخط'):
        assert label in op_text, label
    # the bill's own figures, copied verbatim
    for value in ('SB-SL-1008', '614,936', '31,700', '2,000', '1,964', '224'):
        assert value in op_text, value
    # English furniture must not survive on an Urdu sheet
    for english in ('INVOICE', 'Bill To', 'Transaction Details', 'Items',
                    'Total Sales'):
        assert english not in op_text, english


def test_panel_prints_the_four_inline_fields_in_reading_order():
    doc = _document()
    assert [label for label, _value in doc['fields']] == [
        'بل برائے', 'ڈیلیوری', 'کوڈ', 'اکاؤنٹ']
    values = [value for _label, value in doc['fields']]
    assert values[0] == 'محمد شفیق'
    assert values[1] == 'عدنان احمد'
    assert values[2] == 'FBMCL-00002'
    assert values[3] == 'Drawer Cash'


# ---------------------------------------------------------------------------
# QR block
# ---------------------------------------------------------------------------

def test_qr_block_is_drawn_from_the_bill_and_captioned():
    doc = _document()
    assert doc['qr_text'], 'a bill always carries its QR payload'
    sheet = R.layout_document(doc)[0]
    modules = [op for op in _ops(sheet, 'rect')
               if op['fill'] == R.NAVY and op['x'] >= R.QR_X - 0.1
               and op['x'] < R.QR_X + R.QR_SIZE]
    assert len(modules) > 40, 'the QR matrix was not drawn'
    assert all(op['y'] >= R.QR_Y - 0.1 for op in modules)
    assert any(op['op'] == 'text' and op['text'] == doc['qr_caption']
               for op in sheet.ops)


def test_no_qr_is_drawn_without_a_payload():
    doc = _document(qr_text='', qr_caption='')
    sheet = R.layout_document(doc)[0]
    modules = [op for op in _ops(sheet, 'rect')
               if op['fill'] == R.NAVY and R.QR_X <= op['x'] < R.QR_X + R.QR_SIZE
               and op['y'] < R.QR_Y + R.QR_SIZE]
    assert not modules


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
    doc = _document(previous_balance=0, bill=_bill(amount=5000))
    labels = [row['label'] for row in doc['summary']]
    assert 'پچھلا بقایا' not in labels
    assert labels[-1] == 'کل بقایا رقم'


def test_urdu_date_and_clock_read_like_the_sheet():
    assert R._urdu_date(datetime(2026, 11, 7)) == '07 نومبر 2026'
    assert R._urdu_time(datetime(2026, 11, 7, 12, 20)) == '12:20 دوپہر'
    assert R._urdu_time(datetime(2026, 11, 7, 9, 5)) == '9:05 صبح'


def test_phone_line_is_split_into_two_numbers():
    assert R.split_phones('+92331-0000993 | +92340-3872722') == [
        '+92 331 0000993', '+92 340 3872722']


def test_item_amounts_are_quantity_times_rate_as_posted():
    rows = bill_urdu._item_rows(ITEMS)
    assert rows[0] == {'index': 1, 'name': 'ڈی جی', 'qty': '1',
                       'rate': '2,000', 'amount': '2,000'}
    assert rows[2]['amount'] == '439,936'


def test_receipt_bill_shows_received_and_remaining_balance():
    doc = bill_urdu.build_document(bill_type='Payment', bill=_bill(),
                                   items=[], previous_balance=1000,
                                   settings=_settings())
    labels = [row['label'] for row in doc['summary']]
    assert labels[0] == 'وصول شدہ رقم'
    assert labels[-1] == 'بقایا رقم'


# ---------------------------------------------------------------------------
# Terms & conditions
# ---------------------------------------------------------------------------

def test_terms_are_two_numbered_columns():
    doc = _document(terms=[SimpleNamespace(title='', content_ur=text)
                           for text in TERMS])
    sheet = R.layout_document(doc)[0]
    numbers = [op for op in sheet.ops
               if op['op'] == 'text' and re.fullmatch(r'\d+\.', op['text'])]
    assert [op['text'] for op in numbers] == [f'{n}.' for n in range(1, 8)]
    # right column starts at x = 399.7, left column at 204.1
    assert {round(op['x'], 1) for op in numbers} == {204.1, 399.7}
    right = [op for op in numbers if op['x'] > 300]
    left = [op for op in numbers if op['x'] < 300]
    assert (len(right), len(left)) == (4, 3)


def test_a_terms_clause_is_numbered_once_however_it_wraps():
    doc = _document(terms=[SimpleNamespace(title='', content_ur=TERMS[0])])
    sheet = R.layout_document(doc)[0]
    numbers = [op for op in sheet.ops
               if op['op'] == 'text' and re.fullmatch(r'\d+\.', op['text'])]
    assert len(numbers) == 1, 'a wrapped clause keeps one number'


def test_terms_heading_sits_under_the_summary_rule():
    doc = _document(terms=[SimpleNamespace(title='', content_ur=t)
                           for t in TERMS])
    sheet = R.layout_document(doc)[0]
    heading = [op for op in sheet.ops
               if op['op'] == 'text' and op['text'] == 'شرائط و ضوابط']
    assert heading, 'terms heading missing'
    assert heading[0]['color'] == R.NAVY


# ---------------------------------------------------------------------------
# Print page
# ---------------------------------------------------------------------------

def test_print_page_is_the_same_rtl_sheet():
    html = bill_urdu.render_html(_document())
    assert 'dir="rtl"' in html
    assert '<div class="pg"' in html
    # the carbon copy is one A4 leaf holding both copies
    assert 'width:841.89pt' in html
    assert R.COPY_ORIGINAL in html and R.COPY_CARBON in html


def test_print_page_escapes_user_text():
    doc = _document(bill=_bill(note='<script>alert(1)</script>'))
    html = bill_urdu.render_html(doc)
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html


def test_english_text_in_an_urdu_sheet_keeps_its_word_order():
    words = R.rtl_words('FBMCL-00002 Drawer Cash')
    assert words == [('Cash', False), ('Drawer', False), ('FBMCL-00002', False)]


def test_mixed_urdu_line_puts_its_first_word_at_the_right():
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


def test_route_serves_the_carbon_copy_pdf_by_default(client, sale):
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
    box = reader.pages[0].mediabox
    assert round(float(box.width), 1) == round(R.A4_W, 1)
    assert round(float(box.height), 1) == round(R.A4_H, 1)


def test_route_serves_a_single_a5_sheet_when_asked(client, sale):
    url = (f"/download_invoice/{sale['bill_no']}?src=direct_sale"
           f"&src_id={sale['id']}&lang=ur&tc=0&copies=1")
    resp = client.get(url)
    assert resp.status_code == 200
    reader = PdfReader(io.BytesIO(resp.data))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert round(float(box.width), 1) == round(R.PAGE_W, 1)
    assert round(float(box.height), 1) == round(R.PAGE_H, 1)


def test_route_print_is_the_same_urdu_sheet(client, sale):
    url = (f"/download_invoice/{sale['bill_no']}?src=direct_sale"
           f"&src_id={sale['id']}&lang=ur&action=print&tc=0")
    resp = client.get(url)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '-UR.html' in resp.headers['Content-Disposition']
    assert 'dir="rtl"' in html
    assert '<div class="pg"' in html
    assert R.COPY_ORIGINAL in html and R.COPY_CARBON in html
    # English receipt furniture must never leak into the Urdu sheet
    for english in ('rcpt-header', 'rcpt-table', 'English PDF'):
        assert english not in html, english
    assert 'ٹرانزیکشن کی تفصیلات' in html


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
