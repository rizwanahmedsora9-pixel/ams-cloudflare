"""The QR on an Urdu receipt, and the Jameel Noori face that prints it.

Three regressions are pinned here, each of which made a real printed bill
wrong:

* the header QR disappeared whenever the optional ``segno`` package was not
  installed on the host;
* the QR held only a three-field reference line, so scanning it showed
  neither the client, the time nor the bill itself;
* the bundled Nastaleeq face maps ``U+0020`` to a 5-unit advance, so Urdu
  words inside one run were drawn glued together.

The scan tests rasterise the *real* PDF and decode its QR with OpenCV, which
is what a phone camera does; they are skipped when the imaging extras are not
installed so the core suite still runs anywhere.
"""
from __future__ import annotations

import re

import pytest

from app.services import bill_urdu
from app.services import qr_code, urdu_receipt as R

import test_urdu_bill_sheet as base   # noqa: E402  (tests/ is on pythonpath)
from test_urdu_bill_sheet import sale  # noqa: E402,F401  (real posted bill fixture)


def _decode_from_pdf(pdf_bytes, dpi=600):
    """Decode the header QR of the first page of *pdf_bytes* (or '')."""
    pymupdf = pytest.importorskip('pymupdf')
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    page = pymupdf.open(stream=pdf_bytes, filetype='pdf')[0]
    clip = pymupdf.Rect(R.QR_X - 10, R.QR_Y - 10,
                        R.QR_X + R.QR_SIZE + 10, R.QR_Y + R.QR_SIZE + 10)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
    else:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    decoded, _points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return decoded


# ---------------------------------------------------------------------------
# The encoder that always exists
# ---------------------------------------------------------------------------

def test_the_bundled_encoder_is_used_when_segno_is_missing(monkeypatch):
    """A host without the optional segno extra still prints a QR."""
    import builtins
    real_import = builtins.__import__

    def no_segno(name, *args, **kwargs):
        if name == 'segno' or name.startswith('segno.'):
            raise ImportError('segno is not installed')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', no_segno)
    matrix = R.qr_matrix('SB-SL-1008 | FBMCL-00002')
    assert matrix, 'the QR vanished when segno was missing'
    assert len(matrix) >= 21
    assert any(any(row) for row in matrix)


def test_the_bundled_encoder_matches_the_qr_standard():
    """A known symbol: 'SAMPLE' in byte mode, version 1, mask 4 (ISO 18004)."""
    matrix = qr_code.make_matrix('SAMPLE', error='m', mask=4)
    assert len(matrix) == 21
    # Finder patterns: 7x7 rings in three corners, dark border and centre.
    for row, col in ((0, 0), (0, 14), (14, 0)):
        assert matrix[row][col], 'finder corner must be dark'
        assert matrix[row + 1][col + 1] is False, 'light ring'
        assert matrix[row + 3][col + 3], 'dark centre'


def test_the_bundled_encoder_rejects_nothing_it_can_encode():
    for payload in ('A', 'SAMPLE', 'x' * 200, 'x' * 700,
                    'SB-SL-1008 | FBMCL-00002 | 614,936 | 07-11-2026'):
        matrix = qr_code.make_matrix(payload, error='m')
        assert matrix, payload[:20]
        assert all(len(row) == len(matrix) for row in matrix)


# ---------------------------------------------------------------------------
# What the code says
# ---------------------------------------------------------------------------

def test_the_qr_carries_the_bill_not_only_its_number():
    """A scan must show the client, the ID, the time and the whole bill."""
    doc = base._reference_document()
    payload = doc['qr_text']
    assert doc['qr_caption'] == 'SB-SL-1008'
    assert 'SB-SL-1008' in payload, 'bill number'
    assert 'FBMCL-00002' in payload, 'client ID'
    assert 'محمد شفیق' in payload, 'client name'
    assert 'نومبر 2026' in payload, 'date'
    assert 'دوپہر' in payload, 'time of day'
    assert '1,105,636' in payload, 'bill total'
    assert '522,400' in payload, 'closing balance'
    assert 'SAMPLE' not in payload


def test_the_qr_payload_fits_a_scannable_symbol():
    """The code must stay inside the block's module budget on the paper."""
    for document in (base._document(), base._reference_document()):
        matrix = qr_code.make_matrix(document['qr_text'], document['qr_error'])
        assert matrix, 'payload must encode'
        assert len(matrix) <= bill_urdu.QR_MAX_MODULES
        # and the drawn symbol therefore fills the printed block exactly
        module = R.QR_SIZE / (len(matrix) + 8)
        assert module > 0.24, f'module {module:.3f}pt is too small to scan'


def test_a_short_bill_lists_its_items_in_the_qr():
    payload = base._document()['qr_text']
    assert '1.ڈی جی' in payload or '1. ڈی جی' in payload
    # the line's own qty x rate = amount, so a scan shows what was bought
    assert '1*2000=2000' in payload


def test_the_printed_pdf_qr_decodes_to_the_bill():
    """Rasterise the real PDF and read the code the way a phone does."""
    doc = base._reference_document()
    decoded = _decode_from_pdf(bill_urdu.render_pdf(doc))
    assert decoded, 'the printed QR did not decode'
    assert decoded == doc['qr_text']


# ---------------------------------------------------------------------------
# The Nastaleeq face
# ---------------------------------------------------------------------------

def test_urdu_words_keep_the_gap_the_sheet_draws():
    """The bundled face's own space is 5/2048 em: the sheet must not use it."""
    text = 'کل فروخت'
    tight = R._urdu_width('کلفروخت', 8.0)
    spaced = R._urdu_width(text, 8.0)
    assert spaced - tight > 1.3, 'word gap collapsed - words print glued'
    assert round(R.word_gap(8.0), 3) == 1.92


def test_the_pdf_draws_a_real_gap_between_urdu_words():
    """The drawn pen must advance by the word gap, not by 5 font units."""
    sheet = R._new_sheet()
    sheet.text(R.RIGHT, 100.0, 'کل فروخت', 8.0, align='right', urdu=True)
    op = next(o for o in sheet.ops if o['op'] == 'text')
    assert op['text'] == 'کل فروخت'
    assert R._urdu_width('کل فروخت', 8.0) > R._urdu_width('کلفروخت', 8.0) + 1.3


def test_the_fonttools_fallback_keeps_word_order():
    """Without uharfbuzz the words must not come out in reverse order."""
    from app.services import bilingual as B

    shaped = B._shape_with_fonttools('کل فروخت')
    assert shaped, 'fallback shaper produced nothing'
    assert shaped.count(' ') == 1, 'words were joined or split wrongly'
    # The face ligates both words into a single glyph each, so order is read
    # from the glyph ids: "کل" is its own ligature and must come first.
    from app.services import bilingual as _B
    _tt, gid, _shapes, _order = _B._fallback_font()
    plain = _B._shape_with_fonttools('کل')
    assert plain and plain in shaped, 'the words were reordered'
    assert shaped.index(plain) == 0, '"کل" must stay the first word' 


# ---------------------------------------------------------------------------
# Terms still fit one A5 sheet when a clause wraps
# ---------------------------------------------------------------------------

def test_a_wrapped_clause_never_spills_the_terms_onto_another_sheet():
    from types import SimpleNamespace

    long_clause = ('بکنگ پر خریدار کو دیا گیا ریٹ صرف اسی صورت میں لاگو ہوگا '
                   'جب وہ اس بکنگ کی پوری رقم ادا کرے اور پوری رقم کی ادائیگی '
                   'کے بعد ہی رعایت جاری رہے گی۔')
    terms = [SimpleNamespace(title='', content_ur=long_clause) for _ in range(7)]
    doc = base._document(terms=terms)
    sheets = R.layout_document(doc)
    assert len(sheets) == 1, 'a wrapped clause pushed the terms to a new page'
    # every clause is drawn (7 numbers, each exactly once)
    numbers = [op['text'] for op in sheets[0].ops
               if op['op'] == 'text' and re.fullmatch(r'\d+\.', op['text'])]
    assert numbers == [f'{n}.' for n in range(1, 8)]
    body = [op for op in sheets[0].ops if op['op'] == 'text'
            and op['y'] > 480.0 and not re.fullmatch(r'\d+\.', op['text'])]
    assert body, 'the terms block vanished'
    assert all(op['y'] <= R.PAGE_BOTTOM for op in body)


# ---------------------------------------------------------------------------
# The scan-and-verify page
# ---------------------------------------------------------------------------

def test_the_qr_on_a_real_bill_is_a_signed_link_to_that_bill(client, sale, app):
    """A real Urdu PDF carries a link that opens the whole posted bill.

    The host is the one thing a test cannot know (a shop PC's LAN address), so
    it is configured here the way a deployment behind a proxy would.
    """
    app.config['PUBLIC_BASE_URL'] = 'http://bill-test.local'
    url = (f"/download_invoice/{sale['bill_no']}?src=direct_sale"
           f"&src_id={sale['id']}&lang=ur&tc=0")
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'

    decoded = _decode_from_pdf(resp.data)
    assert decoded, 'the printed QR must decode'
    assert '/verify/bill/' in decoded, decoded

    # Follow exactly what the phone would open.
    from urllib.parse import urlsplit
    path = urlsplit(decoded).path
    page = client.get(path)
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert sale['bill_no'] in html
    assert 'FBMCL-00009' in html
    assert 'ڈی جی' in html and 'سیمنٹ ٹھیکہ' in html
    assert '1,290' in html
    assert 'Verified' in html


def test_a_tampered_link_never_shows_a_bill(client):
    resp = client.get('/verify/bill/not-a-real-token')
    assert resp.status_code == 404
    assert 'could not be verified' in resp.get_data(as_text=True)


def test_the_verify_page_needs_no_login(app):
    """The customer holding the paper bill has no account."""
    from app.services import bill_verify
    with app.app_context():
        token = bill_verify.make_token('DirectSale', 1, 'X-1')
    raw = app.test_client()
    resp = raw.get(f'/verify/bill/{token}')
    # 404 because bill 1 does not exist here - never a redirect to /login
    assert resp.status_code == 404
    assert 'login' not in (resp.headers.get('Location') or '')


def test_a_loopback_request_never_prints_a_link_a_phone_cannot_open(app):
    """A link to localhost/link-local is dead on a phone, so it is not used.

    Printing from the server itself either resolves the machine's LAN address
    or leaves the QR to the self-contained summary - never a dead link.
    """
    from app.services import bill_verify
    with app.test_request_context('http://localhost:5000/download_invoice/X'):
        url = bill_verify.verify_url('DirectSale', 7, 'SB-7')
    if url:
        host = url.split('://', 1)[1].split('/', 1)[0]
        assert bill_verify._reachable(host.split(':')[0]), host
    # A link-local request host is rejected the same way.
    with app.test_request_context('http://169.254.0.21:5000/x'):
        assert bill_verify.verify_url('DirectSale', 7, 'SB-7') in ('', None) or \
            not bill_verify.verify_url('DirectSale', 7, 'SB-7').startswith('http://169.254.')


def test_the_public_base_url_overrides_the_request_host(app):
    from app.services import bill_verify
    with app.test_request_context('http://yard-pc:5000/download_invoice/X'):
        bill_verify.current_app.config['PUBLIC_BASE_URL'] = 'https://erp.example.com/'
        try:
            url = bill_verify.verify_url('DirectSale', 7, 'SB-7')
        finally:
            bill_verify.current_app.config['PUBLIC_BASE_URL'] = ''
    assert url.startswith('https://erp.example.com/verify/bill/')
