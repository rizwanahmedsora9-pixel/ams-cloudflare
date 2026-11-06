"""Tests for the legacy dual-language (English + Urdu / Jameel Noori) layer.

Non-bill exports (ledgers, statements, reports) still carry both languages in
the same document: English labels get an Urdu translation rendered in the
bundled Jameel Noori Nastaleeq font.  Bills and receipts are intentionally
single-language now; see ``tests/test_bill_language_versions.py``.

Both rendering paths are covered - the WeasyPrint HTML path
(``bilingual.apply_bilingual`` injection) and the ReportLab fallback /
direct supplier-statement path (shaped Urdu in the registered TTF).
"""
import io
import re

import pytest

from app.services import bilingual as B
from app.services.pdf_fallback import render_html_to_pdf


def test_label_dictionary_is_pure_urdu():
    assert len(B.LABELS) > 100
    for en, ur in B.LABELS.items():
        assert any('\u0600' <= ch <= '\u06ff' for ch in ur), (en, ur)
        probe = ur
        for tok in ('GRN', 'PDF', 'FIFO', 'AMS', 'ID', 'IN', 'OUT'):
            probe = probe.replace(tok, '')
        assert not re.search(r'[A-Za-z]', probe), (en, ur)
        assert not re.search(r'[^\u0600-\u06FF\uFB50-\uFEFF0-9 \u060C\u061B\u061F/()#.,+\-]', probe), (en, ur)


def test_urdu_font_file_bundled():
    assert B.urdu_font_available()
    assert B.JAMEEL_NOORI_TTF.endswith('JameelNooriNastaleeq.ttf')


def test_injection_translates_labels_only():
    html = (
        '<p>Bill No: <b>BK-1</b></p>'
        '<th>Date</th>'
        '<span>Notes</span>'
        '<span>SPECIAL BOOKING NOTE 5544</span>'
        '<td>Total Paid: 500</td>'
        '<td>Stock In</td>'
    )
    out = B.apply_bilingual(html)
    urdu_spans = re.findall(r'<span class="ur"[^>]*>([^<]*)</span>', out)
    # labels translated
    assert B.LABELS['Bill No'] in urdu_spans
    assert B.LABELS['Date'] in urdu_spans
    assert B.LABELS['Notes'] in urdu_spans
    assert B.LABELS['Total Paid'] in urdu_spans
    # free text (notes / material-ish words) untouched
    assert 'SPECIAL BOOKING NOTE 5544' in out
    assert 'Booking' not in ''.join(urdu_spans)
    assert 'Stock In' in out


def test_injection_idempotent_and_skips_style():
    html = '<style>.x { color: red; } /* Date */</style><p>Date</p>'
    out = B.apply_bilingual(html)
    assert B.apply_bilingual(out) == out
    assert '/* Date */' in out  # style content not translated
    assert '<p>Date<span class="ur"' in out


def test_bilingual_css_references_jameel_font():
    css = B.bilingual_css()
    assert '@font-face' in css
    assert 'JameelNooriNastaleeq.ttf' in css
    assert '.ur' in css and 'rtl' in css


def test_shape_urdu_produces_shaped_glyphs():
    shaped = B.shape_urdu('بل نمبر')
    assert shaped != 'بل نمبر'  # transformed (HarfBuzz glyph ids as PUA, or presentation forms)
    if B._hb() is not None:
        # HarfBuzz path: private-use codepoints U+F0000+gid
        assert all(0xF0000 <= ord(ch) <= 0xFFFFF or ch == ' ' for ch in shaped)
    else:
        assert all('\uFB50' <= ch <= '\uFEFF' or ch == ' ' for ch in shaped)


def test_reportlab_fallback_renders_bilingual_pdf():
    html = '<h2>SUPPLIER LEDGER</h2><p>Bill No: BK-9</p><p>Client Name: ABC Traders</p>'
    data = render_html_to_pdf(B.apply_bilingual(html), title='bilingual-test')
    assert data and data.startswith(b'%PDF-')
    # the Jameel Noori font must be embedded in the fallback output
    assert b'Jameel-Noori' in data


def test_supplier_ledger_pdf_is_bilingual():
    from datetime import datetime
    from types import SimpleNamespace
    from app.services.supplier_ledger_pdf import render_supplier_ledger_pdf
    sup = SimpleNamespace(name='Test Supplier', address='Gujrat', phone='0300-1234567')
    rows = [{
        'date': datetime(2026, 11, 1), 'type': 'GRN', 'reference': 'GRN-1',
        'description': 'Cement purchase', 'account': 'Purchases', 'note': '',
        'debit': 0, 'credit': 50000, 'balance': 50000, 'supplier_invoice_no': 'INV-9',
        'item_lines': [{'name': 'Cement', 'qty': 100, 'rate': 500, 'amount': 50000}],
    }]
    pdf = render_supplier_ledger_pdf(
        supplier=sup, rows=rows, settings=None, period='01 Nov 2026 to 05 Nov 2026',
        balance_brought_forward=0, total_debit=0, total_credit=50000,
        closing_balance=50000, generated_at=datetime(2026, 11, 5, 10, 0),
        statement_no='ST-1',
    )
    assert pdf.startswith(b'%PDF-')
    assert b'Jameel-Noori' in pdf


def test_choke_point_returns_pdf(app):
    """_try_render_weasy_pdf must always return a real PDF (either engine)."""
    from app.services.files_pdf import _try_render_weasy_pdf
    html = '<div><h2>BOOKING</h2><p>Bill No: BK-1</p><p>Amount: 1000</p></div>'
    with app.test_request_context():
        resp = _try_render_weasy_pdf(html, 'BILL-bilingual.pdf')
        body = resp.get_data()
    assert body.startswith(b'%PDF-')
    assert resp.headers['Content-Type'] == 'application/pdf'
    assert 'BILL-bilingual.pdf' in resp.headers['Content-Disposition']
