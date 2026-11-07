"""Urdu receipts: dates and phone numbers must not be mirrored or mis-spaced.

These pin the three defects users report on an Urdu bill:

* the Urdu receipt date must read ``05:31 شام 06 نومبر 2026`` - the English
  order, written right to left, so the clock sits nearest the right edge - with
  the figures in the requested order and the pieces of the line not touching;
* a phone number / account number / amount sat on the wrong side or in the
  middle of the sheet, because every figure line was treated as right-to-left;
* ``مینول بل:`` and ``MB NO.9102`` (and ``06`` / ``نومبر``) collided because
  the bundled Nastaleeq face gives U+0020 a 5-unit advance, so a literal space
  is a quarter of a point wide.

The first block exercises the text engine directly (deterministic, no PDF
rendering).  The second block renders a real Urdu receipt from the app and
checks the *geometry of the ink*, because PDF text extraction merges the
Latin and Nastaleeq runs of one line and cannot be trusted for ordering.
"""
from __future__ import annotations

import pytest

from app.services import urdu_text as U


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _latin(text, size=8.0, rtl=False):
    return U.Span(text, urdu=False, font='Helvetica-Bold', size=size, rtl=rtl)


def _urdu(text, size=10.33):
    return U.Span(text, urdu=True, font='Helvetica', size=size, rtl=True)


def _para(*spans, align='right', rtl=True, width=200):
    para = U.UrduParagraph(list(spans), align=align, bidi_rtl=rtl)
    para.wrap(width)
    return para


def _runs(para, line=0):
    """``[(is_urdu, text)]`` of one line, in physical (left to right) order."""
    return [(run.span.urdu, run.text()) for run in para._lines[line]]


def _joined(para, line=0):
    return ' '.join(text for _urdu_flag, text in _runs(para, line))


# ---------------------------------------------------------------------------
# figures are their own direction
# ---------------------------------------------------------------------------

def test_numeric_run_detection():
    for text in ('25,000', '03:55', '0300-1234567', '+92331-0000993',
                 '2026', '30,000/-'):
        assert U.is_numeric_run(text), text
    for text in ('MB NO.9102', 'LTC-001', 'نومبر', 'Cash', '06 نومبر'):
        assert not U.is_numeric_run(text), text


def test_phone_number_line_is_not_treated_as_urdu():
    """A bare figure line must keep its left-to-right order."""
    para = _para(_latin('0300-1234567'))
    assert para._line_flags == [False]
    assert _runs(para) == [(False, '0300-1234567')]


def test_urdu_label_keeps_its_figure_left_of_the_label():
    """``کوڈ: LTC-001`` -- the code stays left, the label right."""
    para = _para(_urdu('کوڈ:'), _latin(' LTC-001'))
    assert para._line_flags == [True]
    assert [flag for flag, _t in _runs(para)] == [False, True]
    assert _runs(para)[0][1].strip() == 'LTC-001'
    assert _runs(para)[1][1].strip().startswith('کوڈ')


def test_amount_line_keeps_figure_left_of_the_urdu_label():
    para = _para(_urdu('کل بقایا رقم:'), _latin(' 30,000'))
    assert [flag for flag, _t in _runs(para)] == [False, True]
    assert _runs(para)[0][1].strip() == '30,000'


# ---------------------------------------------------------------------------
# figures keep their logical order inside an Urdu date
# ---------------------------------------------------------------------------

def test_date_line_uses_the_requested_urdu_reading_order():
    """``04:15 شام 06 نومبر 2026`` starts at the right edge of the sheet."""
    para = _para(_latin('04:15 '), _urdu('شام '), _latin('06 '),
                 _urdu('نومبر '), _latin('2026'))
    assert para._line_flags == [True]
    # The renderer's physical left-to-right placement reverses the RTL groups.
    # Reading from the right edge gives: time → شام → day → month → year, the
    # same sequence the English bill reads from its own left edge.
    assert [(flag, text.strip()) for flag, text in _runs(para)] == [
        (False, '2026'), (True, 'نومبر'), (False, '06'),
        (True, 'شام'), (False, '04:15'),
    ]


def test_time_is_the_run_nearest_the_right_edge():
    """The line opens with the clock, never with the صبح/شام label."""
    para = _para(_latin('04:15 '), _urdu('شام '), _latin('06 '),
                 _urdu('نومبر '), _latin('2026'))
    rightmost = para._lines[0][-1]          # last physical run == right edge
    assert rightmost.text().strip() == '04:15'


def test_date_breaks_into_whole_words_never_fragments():
    """Wrapped, the date must split between runs - the words stay whole."""
    para = _para(_latin('04:15 '), _urdu('شام '), _latin('06 '),
                 _urdu('نومبر '), _latin('2026'), width=44)
    assert len(para._lines) > 1
    pieces = ' '.join(
        text for index in range(len(para._lines))
        for _flag, text in _runs(para, index)
    )
    for word in ('06', '2026', '04:15'):
        assert word in pieces, f'{word} was split across the wrap'


def test_month_label_is_whole_and_not_reversed_into_the_year():
    para = _para(_urdu('نومبر'))
    assert _runs(para) == [(True, 'نومبر')]


# ---------------------------------------------------------------------------
# word gaps
# ---------------------------------------------------------------------------

def test_urdu_word_gap_is_a_real_gap():
    """Two Urdu words must not join: the font's own space is only 5 units."""
    para = _para(_urdu('مینول بل:'))
    run = para._lines[0][0]
    spaces = [word for word in run.words if word.space]
    assert spaces, 'the space between the two words was dropped'
    assert spaces[0].width >= 2.0       # ~0.24em, not the font's 0.03pt


def test_gap_between_label_and_figure_is_kept():
    para = _para(_urdu('مینول بل:'), _latin(' MB NO.9102'))
    latin_run, urdu_run = para._lines[0]
    assert latin_run.width > len('MB NO.9102') * 2   # trailing gap reserved
    assert urdu_run.starts_gap is True


def test_space_between_two_figure_runs_is_kept():
    para = _para(_latin('06 '), _latin('2026'))
    first, second = para._lines[0]
    assert first.ends_gap is True
    assert first.width > len('06') * 2      # the gap is drawn, not collapsed


def test_measure_counts_drawn_word_gaps():
    """A measured label must be as wide as the drawn one, or columns wrap."""
    plain = U.measure_run('مقدار', 10.0)
    spaced = U.measure_run('کل بقایا', 10.0)
    assert spaced > plain * 1.2
    parts = U.measure_run('کل', 10.0) + U.measure_run('بقایا', 10.0)
    assert spaced > parts       # the measured width includes the gap


def test_glyph_reach_is_measured():
    """``ریٹ`` slides a mark outside its advance; the width must include it."""
    glyphs = U.shape_glyphs('ریٹ')
    advances = sum(g[1] for g in glyphs)
    assert U.glyphs_width(glyphs) >= advances


def test_word_width_matches_measured_run():
    """The layout and the column maths must agree on an Urdu word's width."""
    para = _para(_urdu('نومبر'))
    run = para._lines[0][0]
    assert run.width == pytest.approx(U.measure_run('نومبر', 10.33), rel=0.02)


# ---------------------------------------------------------------------------
# line spacing / centring
# ---------------------------------------------------------------------------

def test_figure_lines_keep_the_tight_latin_leading():
    para = _para(_latin('25,000'))
    assert para._line_leading[0] == para._latin_leading
    assert para._latin_leading <= para._urdu_leading


def test_urdu_lines_get_the_nastaleeq_leading():
    para = _para(_latin('06 '), _urdu('نومبر'))
    assert para._urdu_leading > para._latin_leading
    assert para._height == para._urdu_leading


def test_mixed_lines_are_spaced_per_line():
    para = _para(_latin('0300-1234567'), _urdu('نومبر'), width=40)
    assert len(para._lines) >= 2
    assert set(para._line_leading) <= {para._latin_leading, para._urdu_leading}
    assert para._height == sum(para._line_leading)


def test_centred_figure_does_not_use_the_urdu_width():
    """A centred amount is centred on its own width, not the Urdu line's."""
    para = _para(_latin('25,000'), _urdu('وصول شدہ رقم'), width=36)
    assert len(para._lines) >= 2
    widths = [sum(run.width for run in line) for line in para._lines]
    assert max(widths) - min(widths) > 5
    assert sum(para._line_leading) == para._height


# ---------------------------------------------------------------------------
# the real Urdu receipt: where the ink lands on the page
# ---------------------------------------------------------------------------

@pytest.fixture()
def urdu_receipt_pdf(app):
    """Render the Urdu receipt of a real payment and return the PDF bytes."""
    import pathlib
    import sys

    from app.services import files_pdf

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from conftest import make_csrf_client   # noqa: WPS433 (shared helper)

    client = make_csrf_client(app)
    client.post('/login', data={'username': 'Admin',
                                'password': 'Admin@fbm12345'})
    client.post('/add_client', data={
        'name': 'URDU GEOMETRY CLIENT', 'code': 'UGC-001',
        'category': 'General', 'opening_balance': '0',
        'phone': '0300-1234567', 'address': 'Mohallah Islam Pura, Gujrat'},
        follow_redirects=True)
    client.post('/accounts/accounts/add', data={
        'name': 'URDU CASH', 'class_category': 'Assets',
        'class_subcategory': 'Cash', 'class_account_type': 'Main Cash',
        'account_status': 'active', 'opening_amount': '0',
        'opening_position': 'debit',
        'opening_effective_date': '2026-01-01'}, follow_redirects=True)
    with app.app_context():
        from models.cash import Account
        from models.parties import Client
        from models.sales import Payment
        account = Account.query.filter(Account.name.like('%URDU CASH%')).first()
        client_row = Client.query.filter_by(code='UGC-001').first()
        client.post('/add_payment', data={
            'client_code': client_row.code, 'amount': '25000',
            'payment_type': 'Receipt', 'method': 'Cash',
            'payment_account_id': str(account.id),
            'manual_bill_no': 'MB NO.9200'}, follow_redirects=True)
        payment = Payment.query.filter_by(manual_bill_no='MB NO.9200').first()
        payment_id = payment.id

    saved = files_pdf.state.WEASYPRINT_MODULE
    files_pdf.state.WEASYPRINT_MODULE = False      # force the ReportLab path
    try:
        response = client.get(
            f"/download_invoice/MB NO.9200?src=payment&src_id={payment_id}"
            "&lang=ur")
    finally:
        files_pdf.state.WEASYPRINT_MODULE = saved
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('application/pdf')
    return response.data


def _ink_rows(pdf_bytes, dpi=200, threshold=170):
    """``[(y0, y1, x0, x1)]`` ink bands of page one, in PDF points."""
    import numpy as np
    import pymupdf

    page = pymupdf.open('pdf', pdf_bytes)[0]
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height,
                                                              pix.width)
    scale = 72.0 / dpi
    rows = (image < threshold).any(axis=1)
    bands, start = [], None
    for index, ink in enumerate(rows):
        if ink and start is None:
            start = index
        elif not ink and start is not None:
            bands.append((start, index))
            start = None
    if start is not None:
        bands.append((start, len(rows)))
    out = []
    for top, bottom in bands:
        ink = (image[top:bottom] < threshold).any(axis=0)
        columns = np.where(ink)[0]
        if len(columns):
            out.append((top * scale, bottom * scale,
                        columns[0] * scale, columns[-1] * scale))
    return out, page.rect


def test_receipt_date_is_one_line(urdu_receipt_pdf):
    """The date used to wrap in two, stacking half-dates on top of each other."""
    bands, _rect = _ink_rows(urdu_receipt_pdf)
    # The date sits under the bill number, in the top eighth of the sheet.
    header = [band for band in bands if band[0] < 110]
    assert header, 'nothing was drawn in the receipt header'
    # Every band is a separate line of text; a wrapped date shows up as a
    # band much shorter than its neighbours at the same indent.
    tall = [band for band in header if (band[1] - band[0]) > 4]
    assert len(tall) >= 3
    for top, bottom, left, right in text_band_list(header):
        assert right - left > 12, 'a fragment of a line was left stranded'


def _date_figures(pdf_bytes):
    """``{kind: (x0, x1)}`` of the clock / day / year on the receipt date line.

    The Nastaleeq runs of the line are drawn as private-use glyph ids, which
    text extraction cannot read, so the guard works on the three figure groups
    the date is built from - all of them Latin.  PDF text extraction splits a
    Nastaleeq run and the Latin run of one visual line into two records, so
    the pieces are gathered by *vertical overlap* instead of by the
    extractor's own line grouping, and the clock is the one that shares its
    band with a four-digit year - that pair is the date and nothing else.
    """
    import re

    import pymupdf

    clock = re.compile(r'\d{1,2}:\d{2}')
    spans = []
    for block in pymupdf.open('pdf', pdf_bytes)[0].get_text('dict')['blocks']:
        for line in block.get('lines', []):
            spans.extend(line['spans'])

    def band_of(span):
        """The spans that share a visual line with *span*."""
        top, bottom = span['bbox'][1], span['bbox'][3]
        out = []
        for other in spans:
            y0, y1 = other['bbox'][1], other['bbox'][3]
            overlap = min(bottom, y1) - max(top, y0)
            if overlap > 0.5 * (y1 - y0):
                out.append(other)
        return out

    for span in spans:
        if not clock.fullmatch(span['text'].strip()):
            continue
        line = band_of(span)
        if not any(re.fullmatch(r'\d{4}', s['text'].strip()) for s in line):
            continue
        found = {}
        for member in line:
            text = member['text'].strip()
            if clock.fullmatch(text):
                found['time'] = member['bbox']
            elif re.fullmatch(r'\d{1,2}', text):
                found['day'] = member['bbox']
            elif re.fullmatch(r'\d{4}', text):
                found['year'] = member['bbox']
        return found
    return {}


def test_urdu_date_is_written_right_to_left_on_the_page(urdu_receipt_pdf):
    """The clock must be the item nearest the right edge of the date line.

    The Urdu bill says the same thing the English one says - time, AM/PM, day,
    month, year - only written the other way.  Checking the ink, not the
    markup, is what pins both the browser print view and the saved PDF: the
    date line used to be pinned ``direction: ltr``, so the receipt opened with
    ``شام`` and the year landed on the right.
    """
    figures = _date_figures(urdu_receipt_pdf)
    assert {'time', 'day', 'year'} <= set(figures), figures

    # Right-to-left means each following piece sits further LEFT than the one
    # before it: time > day > year.
    assert figures['time'][0] > figures['day'][2], (
        f"the day is not left of the clock: {figures}")
    assert figures['day'][0] > figures['year'][2], (
        f"the year is not left of the day: {figures}")
    # Nothing of the date line may stick out past the time on its right.
    right_edge = max(box[2] for box in figures.values())
    assert figures['time'][2] == pytest.approx(right_edge, abs=0.5)


def text_band_list(bands):
    return [band for band in bands if (band[1] - band[0]) > 5]


def _template_page_css(template_name):
    """The ``@page`` rule a print template declares, straight from the file.

    Read from the template rather than restated here, so the guard band below
    can never drift away from the geometry the browser actually prints.
    """
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'templates', template_name)
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def test_receipt_ink_stays_inside_the_printable_area(urdu_receipt_pdf):
    """No glyph may be drawn outside the sheet.

    The guard band used to be a flat 20pt, which silently encoded one page
    geometry.  The exporter now honours the template's own ``@page`` rule —
    bills and receipts declare ``margin: 0`` and print edge to edge exactly as
    the browser does — so the band is derived from that rule instead.
    """
    from app.services.files_pdf import page_margins_cm

    bands, rect = _ink_rows(urdu_receipt_pdf)
    assert bands
    margin_x, margin_y = page_margins_cm(_template_page_css('view_bill.html'))
    left_edge = margin_x * 72.0 / 2.54
    right_edge = rect.width - margin_x * 72.0 / 2.54
    top_edge = margin_y * 72.0 / 2.54
    bottom_edge = rect.height - margin_y * 72.0 / 2.54
    # Nastaleeq glyphs overhang their advance width by a pixel or two; one
    # point of tolerance keeps anti-aliasing from failing the build.
    tolerance = 1.0
    for top, bottom, left, right in bands:
        assert left >= left_edge - tolerance, (
            f'ink starts left of the margin at y={top:.0f}')
        assert right <= right_edge + tolerance, (
            f'ink runs past the right margin at y={top:.0f}')
        assert top >= top_edge - tolerance, (
            f'ink starts above the top margin at y={top:.0f}')
        assert bottom <= bottom_edge + tolerance, (
            f'ink runs below the bottom margin at y={bottom:.0f}')


def test_receipt_right_edge_is_used_by_the_urdu_column(urdu_receipt_pdf):
    """The Urdu header block must sit against the right margin, not float."""
    bands, rect = _ink_rows(urdu_receipt_pdf)
    header = [band for band in bands if band[0] < 110]
    assert header
    right_most = max(band[3] for band in header)
    assert right_most > rect.width - 40.0


def test_receipt_amount_row_and_phone_are_not_squeezed(urdu_receipt_pdf):
    """No band may be a single glyph wide inside a line of figures."""
    bands, _rect = _ink_rows(urdu_receipt_pdf)
    for top, bottom, left, right in bands:
        height = bottom - top
        if height < 3 or height > 12:
            continue        # rules and tall Nastaleeq lines are not figures
        assert (right - left) > 8, f'a lone glyph at y={top:.0f}'
