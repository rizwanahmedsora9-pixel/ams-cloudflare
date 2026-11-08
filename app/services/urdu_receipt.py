"""The Urdu bill: one fixed sheet, drawn the same on paper and in the PDF.

Every Urdu document the app produces - download or print - is this module's
output and nothing else.  The sheet is measured off the approved reference
PDF (``New Receipt.pdf``):

* A5 portrait, 419.53 x 595.28 pt, white paper, 19.84pt side margins.
* Header: QR block on the left, the company name centred in Nastaleeq with the
  address under it, the proprietor and the phone numbers hard right, closed by
  a thick navy rule and a light dashed companion.
* The shop note sits above a four-cell meta strip (time / date / type / bill).
* Two pale party panels: bill-to + contact + code on the right, delivery +
  account on the left.
* ``ٹرانزیکشن کی تفصیلات`` heading with a small "prices in rupees" note, then
  the navy item header and the ruled, zebra-tinted item rows.
* Summary box on the left closed by the solid navy total bar; the signature
  rule on the right.
* Terms & conditions in two numbered columns under a hairline.

Carbon copy
-----------
``copies=1`` (the default) prints the single A5 sheet exactly as approved.
``copies=2`` places two identical A5 copies side by side on one A4 landscape
leaf - the original (``اصل``) on the right, the carbon (``نقل``) on the left -
with a dashed cut line between them.

Geometry is written once, in points, as a list of drawing primitives.  Both
backends consume that list:

* :func:`render_pdf` draws it on a ReportLab canvas (used for "Urdu PDF").
* :func:`render_html` lays the same primitives out absolutely in an HTML page
  (used for "Urdu Print"), so the browser preview, the printed sheet and the
  downloaded PDF are the same page.

Urdu is split into directional runs, shaped with HarfBuzz and drawn glyph by
glyph at the positions HarfBuzz computed.  Embedded figures stay left to
right; Nastaleeq marks live outside their advance width, so a naive
``drawString`` of a shaped string stacks them on the baseline.  The Latin face
is DejaVu Sans, matching the reference document.
"""
from __future__ import annotations

import io
import os
import re

# ---------------------------------------------------------------------------
# Palette / geometry of the approved sheet
# ---------------------------------------------------------------------------

NAVY = '#1A3A5C'
INK = '#14263B'
MUTED = '#66788D'
SUBTLE = '#788A9D'
ADDRESS = '#33465C'
PANEL = '#EEF3F9'
BAR = '#F4F7FB'
BORDER = '#C4D1E0'
GRID = '#AEBED0'
DOT = '#B5C4D6'
WHITE = '#FFFFFF'
NOTE_COLOR = '#5A6B80'
TERMS_RED = '#C0392B'
TERMS_ACCENT = '#E0E7F0'

HAIRLINE = BORDER
GRID_ROW = BAR

PAGE_W = 419.5276
PAGE_H = 595.2756
A4_W = 841.8898
A4_H = 595.2756

LEFT = 19.8425
RIGHT = 399.6851
CONTENT_W = RIGHT - LEFT
PAGE_BOTTOM = 575.0

# -- header ---------------------------------------------------------------
QR_X, QR_Y, QR_SIZE = 20.5925, 14.9232, 51.0236
QR_CAPTION_Y = 70.6008
COMPANY_CENTER = 200.275
Y_COMPANY = 43.3516
Y_ADDRESS = 62.7863
Y_PROPRIETOR = 32.892
Y_PHONE_1 = 47.221
PHONE_STEP = 12.918
Y_RULE_1, RULE_1_H = 75.0315, 2.8346
Y_RULE_2, RULE_2_H = 81.0758, 0.75
Y_NOTE = 90.742
Y_META, META_H = 94.9596, 16.2
META_BASELINE = 105.161
META_CELLS = ((111.1997, 110.452), (217.3456, 216.598),
              (278.0004, 277.25), (RIGHT, 393.267))

# -- party panels ---------------------------------------------------------
Y_PANEL, PANEL_H = 116.8289, 43.3293
PANEL_GAP = 7.5969
PANEL_BOX_W = (CONTENT_W - PANEL_GAP) / 2.0
PANEL_RIGHT_X = LEFT + PANEL_BOX_W + PANEL_GAP
PANEL_INNER_PAD = 6.415
PANEL_LABEL_SIZE = 8.6
PANEL_PARTY_SIZE = 14.0
PANEL_DELIVERY_SIZE = 10.0
PANEL_LATIN_SIZE = 7.4
PANEL_RIGHT_TOP = 135.291
PANEL_RIGHT_BOTTOM = 151.952
PANEL_LEFT_TOP = 131.040
PANEL_LEFT_BOTTOM = 145.552

# -- items ----------------------------------------------------------------
Y_SECTION_TITLE = 174.807
Y_SECTION_NOTE = 174.413
SECTION_NOTE = 'تمام قیمتیں روپے میں ہیں'
Y_ITEMS_HEAD, ITEMS_HEAD_H = 183.3102, 15.8740
Y_ITEMS_ROWS = Y_ITEMS_HEAD + ITEMS_HEAD_H
ROW_H = 15.3071
CONT_HEAD_TOP = 74.0
ROWS_FIRST_PAGE = 15
ROWS_CONT_PAGE = 23
ITEMS_TITLE = 'ٹرانزیکشن کی تفصیلات'

# -- summary / signature / terms -----------------------------------------
SUMMARY_GAP = 6.877
SUM_LEFT, SUM_RIGHT, SUM_DIVIDER = 17.5925, 185.5866, 116.8509
SUM_LABEL_X, SUM_VALUE_X = 179.1732, 24.0118
SUM_ROW_H = 14.4508
SIG_LINE_X0, SIG_LINE_X1 = 302.3917, PAGE_W
SIG_LABEL_X = 373.258
SIG_LABEL_OFFSET = 9.0764
TERMS_GAP = 6.502
TERMS_SIZE = 7.0
TERMS_STEP = 11.670
TERMS_RIGHT_TEXT_X, TERMS_RIGHT_NUM_X = 392.700, RIGHT
TERMS_LEFT_TEXT_X, TERMS_LEFT_NUM_X = 197.120, 204.095
# Two equal 184.25pt columns with a 3mm gutter; the number sits in the
# right-hand 6.99pt of each column, leaving the same text measure on both sides.
TERMS_COLUMN_W = (CONTENT_W - 11.3386) / 2.0
TERMS_RIGHT_WIDTH = TERMS_COLUMN_W - (TERMS_RIGHT_NUM_X - TERMS_RIGHT_TEXT_X)
TERMS_LEFT_WIDTH = TERMS_COLUMN_W - (TERMS_LEFT_NUM_X - TERMS_LEFT_TEXT_X)
TERMS_ACCENT_X = 14.173

FONT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'static', 'fonts')
)

# DejaVu Sans is the sheet's Latin face, matching the reference PDF.  It is
# bundled (Bitstream Vera / DejaVu license, see static/fonts/DejaVu-LICENSE.txt)
# because a shared host has no system fonts.
SANS = 'DejaVu Sans'
SANS_BOLD = 'DejaVu Sans-Bold'
LATIN_FILES = {
    SANS: 'DejaVuSans.ttf',
    SANS_BOLD: 'DejaVuSans-Bold.ttf',
}
URDU_FAMILY = "'Jameel Noori'"
URDU_FONT_FILE = 'JameelNooriNastaleeq.ttf'

# Where a browser puts the baseline inside a ``line-height: 1`` line box, as a
# fraction of the type size.  Measured from Chromium PDF output so the HTML
# backend can turn the PDF's baseline anchors into the same visual line.
_BASELINE_RATIO = {
    SANS: 0.8125,
    SANS_BOLD: 0.825,
    'ur': 0.7627,
}

COPY_ORIGINAL = 'اصل'
COPY_CARBON = 'نقل'

_latin_registered = False


def _font_path(name):
    return os.path.join(FONT_DIR, LATIN_FILES[name])


def register_latin_fonts():
    """Register the bundled DejaVu faces with ReportLab (idempotent)."""
    global _latin_registered
    if _latin_registered:
        return True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        for name, filename in LATIN_FILES.items():
            path = os.path.join(FONT_DIR, filename)
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
        _latin_registered = True
        return True
    except Exception:
        return False


def urdu_font_name():
    """Register (and return) the ReportLab name of the Nastaleeq face."""
    try:
        from app.services.bilingual import register_urdu_font
        return register_urdu_font()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Text shaping helpers
# ---------------------------------------------------------------------------

_ARABIC = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFEFE]')


def has_arabic(text):
    """True when *text* carries Arabic-script letters."""
    return bool(_ARABIC.search(text or ''))


def rtl_words(text):
    """Split *text* into ``[(word, is_urdu)]`` in visual (left to right) order."""
    text = (text or '').strip()
    if not text:
        return []
    words = [w for w in re.split(r'\s+', text) if w]
    return list(reversed([(w, has_arabic(w)) for w in words]))


def _shape(text):
    """``[(gid, advance, x_offset, y_offset)]`` for an RTL Urdu run, or None."""
    try:
        from app.services.urdu_text import shape_glyphs
        return shape_glyphs(text)
    except Exception:
        return None


def _shape_dir(text, direction='rtl'):
    """Shape *text* in its own bidi direction with the Nastaleeq face."""
    if direction == 'rtl':
        return _shape(text)
    try:
        from app.services import bilingual as B
        from app.services.urdu_text import UPEM
        font = B._hb()
        if font is None:
            return _shape(text)
        import uharfbuzz as hb
        font.scale = (int(UPEM), int(UPEM))
        buf = hb.Buffer()
        buf.add_str(text)
        buf.direction = 'ltr'
        buf.script = 'Arab'
        hb.shape(font, buf, {})
        return [(info.codepoint, pos.x_advance, pos.x_offset, pos.y_offset)
                for info, pos in zip(buf.glyph_infos, buf.glyph_positions)]
    except Exception:
        return _shape(text)


_ARABIC_RUN = r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFEFE]+'
_LTR_RUN = r'[0-9A-Za-z]+(?:[×xX/:.\-+][0-9A-Za-z]+)*'
_RUN_TOKEN = re.compile(_ARABIC_RUN + '|' + _LTR_RUN + r'|\s+|.')
_BIDI_MIRROR = str.maketrans({'(': ')', ')': '(', '[': ']', ']': '[',
                              '{': '}', '}': '{', '<': '>', '>': '<',
                              '«': '»', '»': '«'})


def _urdu_runs(text):
    """Logical runs in visual (left-to-right) order for an RTL Urdu line.

    HarfBuzz shapes one directional run at a time; a browser applies the bidi
    algorithm first.  The sheet's mixed strings are Urdu words with embedded
    figures/Latin codes (``07 نومبر 2026``, ``12 ملی میٹر سریا``, ``12×18``),
    so the visual order is the reverse of the logical tokens while each figure
    keeps its own left-to-right order.  Arabic tokens are shaped RTL, figures
    and Latin tokens LTR, all with the Nastaleeq face.
    """
    text = text or ''
    if not text:
        return []
    tokens = _RUN_TOKEN.findall(text)
    runs = []
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index]
        if re.fullmatch(_ARABIC_RUN, token):
            runs.append((token, 'rtl'))
        else:
            # Browsers mirror paired punctuation at an RTL embedding level.
            # HarfBuzz does not do that for us.  Only mirror next to Urdu;
            # brackets inside an embedded Latin/figure run keep their face.
            if len(token) == 1 and token in '()[]{}<>«»':
                before = next((t for t in reversed(tokens[:index]) if not t.isspace()), '')
                after = next((t for t in tokens[index + 1:] if not t.isspace()), '')
                if has_arabic(before) or has_arabic(after):
                    token = token.translate(_BIDI_MIRROR)
            runs.append((token, 'ltr'))
    return [(chunk, direction) for chunk, direction in runs if chunk]


def _urdu_width(text, size):
    """Advance width in points of a bidi-ordered Urdu run at *size*."""
    from app.services.urdu_text import glyphs_width, UPEM
    total = 0.0
    for chunk, direction in _urdu_runs(text):
        glyphs = _shape_dir(chunk, direction)
        if glyphs:
            total += glyphs_width(glyphs) * size / UPEM
    return total


def _latin_width(text, font, size):
    try:
        from reportlab.pdfbase import pdfmetrics
        return pdfmetrics.stringWidth(text or '', font, size)
    except Exception:
        return len(text or '') * size * 0.45


def _fit(text, size, width, urdu=True):
    """*text* on one line, ellipsised when it cannot fit *width*."""
    text = (text or '').strip()
    if not text:
        return ''
    measure = _urdu_width if urdu else (lambda t, s: _latin_width(t, SANS, s))
    if measure(text, size) <= width:
        return text
    while text and measure(text + '…', size) > width:
        text = text.rsplit(' ', 1)[0] if ' ' in text else text[:-1]
    return (text + '…') if text else ''


# ---------------------------------------------------------------------------
# Primitive canvas
# ---------------------------------------------------------------------------

class Sheet:
    """One physical page: an ordered list of drawing primitives."""

    def __init__(self, w=PAGE_W, h=PAGE_H):
        self.w = float(w)
        self.h = float(h)
        self.ops = []

    def rect(self, x, y, w, h, fill=None, stroke=None, width=1.0, dash=None,
             radius=0.0):
        self.ops.append({'op': 'rect', 'x': x, 'y': y, 'w': w, 'h': h,
                         'fill': fill, 'stroke': stroke, 'width': width,
                         'dash': dash, 'radius': radius})

    def outline(self, x, y, w, h, color=BORDER, width=0.9, dash=(3, 3),
                radius=0.0):
        for y0, y1 in ((y, y), (y + h, y + h)):
            self.ops.append({'op': 'seg', 'x0': x, 'y0': y0, 'x1': x + w,
                             'y1': y1, 'color': color, 'width': width,
                             'dash': dash})
        for x0, x1 in ((x, x), (x + w, x + w)):
            self.ops.append({'op': 'seg', 'x0': x0, 'y0': y, 'x1': x1,
                             'y1': y + h, 'color': color, 'width': width,
                             'dash': dash})

    def hline(self, x0, x1, y, color=BORDER, width=0.8, dash=None):
        self.ops.append({'op': 'line', 'x0': x0, 'y0': y, 'x1': x1,
                         'y1': y, 'color': color, 'width': width,
                         'dash': dash})

    def vline(self, x, y0, y1, color=BORDER, width=0.8, dash=None):
        self.ops.append({'op': 'line', 'x0': x, 'y0': y0, 'x1': x,
                         'y1': y1, 'color': color, 'width': width,
                         'dash': dash})

    def text(self, x, baseline, value, size, color=INK, font=SANS,
             align='left', urdu=False, bold=False, spacing=0.0, nowrap=True):
        if value is None or str(value).strip() == '':
            return
        if urdu and not has_arabic(value) and str(value) != '____':
            urdu = False
        self.ops.append({
            'op': 'text', 'x': float(x), 'y': float(baseline),
            'text': str(value), 'size': float(size), 'color': color,
            'font': 'ur' if urdu else font, 'align': align,
            'urdu': bool(urdu), 'bold': bool(bold),
            'spacing': float(spacing or 0.0), 'nowrap': bool(nowrap),
        })

    def copy_to(self, page, dx=0.0, dy=0.0):
        for op in self.ops:
            moved = dict(op)
            if op['op'] == 'rect':
                moved['x'] = op['x'] + dx
                moved['y'] = op['y'] + dy
            elif op['op'] in ('line', 'seg'):
                moved['x0'] = op['x0'] + dx
                moved['x1'] = op['x1'] + dx
                moved['y0'] = op['y0'] + dy
                moved['y1'] = op['y1'] + dy
            else:
                moved['x'] = op['x'] + dx
                moved['y'] = op['y'] + dy
            page.ops.append(moved)


def wrap_urdu(text, size, width, max_lines=3):
    """Greedy word wrap for a right-to-left run, in logical order."""
    text = re.sub(r'\s+', ' ', (text or '').strip())
    if not text:
        return []
    words = text.split(' ')
    lines, current = [], ''
    for word in words:
        probe = (current + ' ' + word).strip()
        if current and _urdu_width(probe, size) > width:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        else:
            current = probe
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and sum(len(x) for x in lines) < len(text) - 4:
        last = lines[-1]
        while last and _urdu_width(last + '…', size) > width:
            last = last.rsplit(' ', 1)[0] if ' ' in last else last[:-1]
        lines[-1] = last + '…'
    return lines


# ---------------------------------------------------------------------------
# QR code (vector modules, drawn by both backends)
# ---------------------------------------------------------------------------

def qr_matrix(text):
    text = (text or '').strip()
    if not text:
        return None
    try:
        import segno
        for error in ('m', 'l'):
            try:
                qr = segno.make(text, error=error)
                return [[bool(cell) for cell in row] for row in qr.matrix]
            except Exception:
                continue
    except Exception:
        return None
    return None


def _draw_qr(sheet, doc):
    matrix = qr_matrix(doc.get('qr_text'))
    if matrix:
        rows, cols = len(matrix), len(matrix[0])
        pad = 1.6
        side = QR_SIZE - 2 * pad
        module = side / max(rows, cols)
        x0, y0 = QR_X + pad, QR_Y + pad
        for r, row in enumerate(matrix):
            c = 0
            while c < cols:
                if not row[c]:
                    c += 1
                    continue
                start = c
                while c < cols and row[c]:
                    c += 1
                sheet.rect(x0 + start * module, y0 + r * module,
                           (c - start) * module + 0.06, module + 0.06,
                           fill=NAVY)
    caption = (doc.get('qr_caption') or doc.get('bill_no') or '').strip()
    if caption:
        sheet.text(QR_X, QR_CAPTION_Y, caption, 5.5, color=INK, align='left',
                   urdu=has_arabic(caption))


# ---------------------------------------------------------------------------
# The document model
# ---------------------------------------------------------------------------

def _qty(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return str(value or '')
    if abs(number - round(number)) < 1e-9:
        return f'{int(round(number)):,}'
    return f'{number:,.2f}'.rstrip('0').rstrip('.')


def _phone(value):
    digits = re.sub(r'[^0-9+]', '', str(value or ''))
    if not digits:
        return ''
    if digits.startswith('+92') and len(digits) > 5:
        rest = digits[3:]
        return '+92 ' + rest[:3] + (' ' + rest[3:] if len(rest) > 3 else '')
    if digits.startswith('0') and len(digits) > 6:
        return digits[:4] + ' ' + digits[4:]
    return digits


def split_phones(value):
    raw = str(value or '')
    groups = re.findall(r'\+?[0-9][0-9\-\s]{6,}[0-9]', raw)
    if not groups:
        groups = [p for p in re.split(r'[|,؛;]+', raw) if p.strip()]
    out = []
    for group in groups:
        number = _phone(group)
        if number and number not in out:
            out.append(number)
    return out[:2]


def _urdu_date(dt):
    if dt is None:
        return ''
    try:
        from app.services.bilingual import _URDU_MONTHS
        month = _URDU_MONTHS.get(dt.strftime('%b'), dt.strftime('%b'))
    except Exception:
        month = dt.strftime('%b')
    return f'{dt.strftime("%d")} {month} {dt.strftime("%Y")}'


def _urdu_time(dt):
    if dt is None:
        return ''
    hour = dt.hour
    if hour < 12:
        period = 'صبح'
    elif hour < 16:
        period = 'دوپہر'
    elif hour < 19:
        period = 'شام'
    else:
        period = 'رات'
    return f'{dt.strftime("%I:%M").lstrip("0")} {period}'


def _default_fields(party_label, party_name, party_code, detail_rows):
    rows = [r for r in (detail_rows or []) if r and r[1]]
    delivery = [r for r in rows if 'ڈلیوری' in r[0] or 'ڈیلیوری' in r[0]]
    account = [r for r in rows if 'اکاؤنٹ' in r[0] or 'بینک' in r[0]]
    middle = [r for r in rows if r not in delivery and r not in account]
    fields = []
    if party_name:
        fields.append((party_label or 'بل برائے', party_name))
    fields.extend(delivery)
    fields.extend(middle)
    if party_code:
        fields.append(('کوڈ', party_code))
    fields.extend(account)
    return fields[:4]


def build_document(*, bill_no='', date_posted=None, company_name='',
                   company_address='', company_phone='', proprietor='',
                   note='', party_name='', party_code='', party_label='بل برائے',
                   party_phone='', fields=None, detail_rows=None, items=None,
                   summary=None, terms=None, type_label='', qr_text='',
                   qr_caption='', signature_label='مجاز دستخط',
                   items_title=ITEMS_TITLE, continuation_label='جاری',
                   show_items=True, footer_thanks='', footer_credit='',
                   signature_left='', signature_right=''):
    """Assemble the data the sheet needs, copied verbatim from the bill."""
    if fields is None:
        fields = _default_fields(party_label, party_name, party_code, detail_rows)
    return {
        'bill_no': bill_no or '',
        'date': _urdu_date(date_posted),
        'time': _urdu_time(date_posted),
        'company_name': company_name or '',
        'company_address': company_address or '',
        'phones': split_phones(company_phone),
        'proprietor': proprietor or '',
        'note': note or '',
        'party_name': party_name or '',
        'party_code': party_code or '',
        'party_phone': party_phone or '____',
        'party_label': party_label or 'بل برائے',
        'fields': [f for f in (fields or []) if f and f[1]],
        'type_label': type_label or '',
        'qr_text': qr_text or '',
        'qr_caption': qr_caption or '',
        'detail_rows': [r for r in (detail_rows or []) if r and r[1]],
        'items': list(items or []),
        'summary': list(summary or []),
        'terms': list(terms or []),
        'signature_label': signature_label or signature_right or 'مجاز دستخط',
        'footer_thanks': footer_thanks,
        'footer_credit': footer_credit,
        'show_items': bool(show_items and items),
        'items_title': items_title or ITEMS_TITLE,
        'continuation_label': continuation_label,
    }


# ---------------------------------------------------------------------------
# Layout: data -> pages of primitives
# ---------------------------------------------------------------------------

def layout_document(doc):
    """Return ``[Sheet, ...]`` - the A5 content pages both backends draw."""
    sheets = []
    sheet = _new_sheet()
    sheets.append(sheet)
    state = {'sheet': sheet, 'y': 0.0, 'summary_top': 0.0, 'summary_h': 0.0}
    _draw_header(state, doc, first=True)
    _draw_panel(state, doc)
    if doc['show_items']:
        _draw_items(state, doc, sheets)
    _draw_summary(state, doc, sheets)
    _draw_signature(state, doc)
    if doc.get('terms'):
        _draw_terms(state, doc, sheets)
    return sheets


def compose_document(doc, copies=1):
    """Physical pages: one A5 sheet, or two A5 copies on one A4 leaf."""
    content = layout_document(doc)
    copies = 2 if int(copies or 1) >= 2 else 1
    if copies == 1:
        pages = []
        for sheet in content:
            page = Sheet(PAGE_W, PAGE_H)
            page.rect(0, 0, PAGE_W, PAGE_H, fill=WHITE)
            sheet.copy_to(page)
            pages.append(page)
        return pages

    offset = (A4_W - 2 * PAGE_W) / 2.0
    pages = []
    for sheet in content:
        page = Sheet(A4_W, A4_H)
        page.rect(0, 0, A4_W, A4_H, fill=WHITE)
        left_x = offset
        right_x = offset + PAGE_W
        sheet.copy_to(page, dx=left_x)
        sheet.copy_to(page, dx=right_x)
        seam = offset + PAGE_W
        page.vline(seam, 10.0, PAGE_H - 10.0, color=BORDER, width=0.6,
                   dash=(2, 3))
        _copy_label(page, right_x, COPY_ORIGINAL, 'گاہک کے لیے')
        _copy_label(page, left_x, COPY_CARBON, 'دفتر کے لیے')
        pages.append(page)
    return pages


def _copy_label(page, dx, title, subtitle):
    page.text(dx + RIGHT, 579.0, title, 7.6, color=NAVY, align='right',
              urdu=True, bold=True)
    page.text(dx + RIGHT, 587.0, subtitle, 6.2, color=MUTED, align='right',
              urdu=True)


def _new_sheet(w=PAGE_W, h=PAGE_H):
    sheet = Sheet(w, h)
    sheet.rect(0, 0, w, h, fill=WHITE)
    return sheet


def _content_bottom():
    return PAGE_BOTTOM


def _draw_header(state, doc, first=True):
    sheet = state['sheet']
    if first:
        _draw_qr(sheet, doc)
        name = doc['company_name']
        name_size = 25.0
        if has_arabic(name):
            while name_size > 13.0 and _urdu_width(name, name_size) > 232.0:
                name_size -= 0.5
        sheet.text(COMPANY_CENTER, Y_COMPANY, name, name_size, color=NAVY,
                   align='center', urdu=True)
        if doc['company_address']:
            sheet.text(COMPANY_CENTER, Y_ADDRESS, doc['company_address'], 8.0,
                       color=ADDRESS, align='center', urdu=True)

        if doc['proprietor']:
            label = 'پروپرائٹر:'
            right = RIGHT - 0.75
            sheet.text(right, Y_PROPRIETOR, label, 7.6, color=INK,
                       align='right', urdu=True)
            cursor = right - _urdu_width(label, 7.6) - 0.9
            sheet.text(cursor, Y_PROPRIETOR, doc['proprietor'], 10.0,
                       color=INK, align='right', urdu=True)
        for index, phone in enumerate(doc['phones'][:2]):
            sheet.text(RIGHT - 0.764, Y_PHONE_1 + index * PHONE_STEP, phone,
                       6.6, color=INK, font=SANS, align='right')

        sheet.rect(LEFT, Y_RULE_1, CONTENT_W, RULE_1_H, fill=NAVY)
        sheet.hline(LEFT, RIGHT, Y_RULE_2, color=DOT, width=RULE_2_H,
                    dash=(2.9968, 2.9968))
        if doc['note']:
            note = _fit(doc['note'], 7.5, CONTENT_W, urdu=has_arabic(doc['note']))
            sheet.text(RIGHT, Y_NOTE, note, 7.5, color=INK, align='right',
                       urdu=True)
        _draw_meta_strip(sheet, doc)
        state['y'] = Y_META + META_H
    else:
        sheet.text(RIGHT - 0.8, 33.0, doc['company_name'], 10.0, color=NAVY,
                   align='right', urdu=True)
        if doc['bill_no']:
            sheet.text(LEFT, 33.0, doc['bill_no'], 8.6, color=INK,
                       font=SANS, align='left')
            sheet.text(LEFT + _latin_width(doc['bill_no'], SANS, 8.6) + 8,
                       33.0, doc['continuation_label'], 9.2, color=MUTED,
                       align='left', urdu=True)
        sheet.rect(LEFT, 42.0, CONTENT_W, 1.5, fill=NAVY)
        sheet.rect(LEFT, 45.8, CONTENT_W, 0.8, fill=NAVY)
        state['y'] = 50.0


def _draw_meta_strip(sheet, doc):
    sheet.rect(LEFT, Y_META, CONTENT_W, META_H, fill=BAR, stroke=BORDER,
               width=0.75)
    for x, _right in META_CELLS[:-1]:
        sheet.vline(x, Y_META, Y_META + META_H, color=BORDER, width=0.75)

    time_right = META_CELLS[0][1]
    date_right = META_CELLS[1][1]
    type_right = META_CELLS[2][1]
    bill_right = META_CELLS[3][1]

    _label_value(sheet, time_right, META_BASELINE, 'وقت', doc['time'],
                 value_size=8.0, gap=0.2)
    _label_value(sheet, date_right, META_BASELINE, 'تاریخ', doc['date'],
                 value_size=8.0, gap=0.2)
    if doc.get('type_label'):
        sheet.text(type_right, META_BASELINE, doc['type_label'], 7.4,
                   color=INK, font=SANS, align='right')
    _label_value(sheet, bill_right, META_BASELINE, 'بل نمبر', doc['bill_no'],
                 value_size=7.4, gap=0.2)


def _label_value(sheet, right_x, baseline, label, value, value_size=8.0,
                 gap=1.3, label_size=8.0, value_color=INK):
    cursor = right_x
    if label:
        label_text = label if label.endswith(':') else label + ':'
        sheet.text(cursor, baseline, label_text, label_size, color=value_color,
                   align='right', urdu=True)
        cursor -= _urdu_width(label_text, label_size) + gap
    if value:
        urdu = has_arabic(value)
        sheet.text(cursor, baseline, value, value_size if not urdu else 8.0,
                   color=INK, font=SANS, align='right', urdu=urdu)


def _panel_field(sheet, right_x, baseline, label, value, value_size,
                 label_color=MUTED, gap=1.0, max_width=None, urdu=None):
    """Draw ``label: value`` right-to-left; return the cursor after the value."""
    label_text = label if label.endswith(':') else label + ':'
    sheet.text(right_x, baseline, label_text, PANEL_LABEL_SIZE,
               color=label_color, align='right', urdu=True)
    cursor = right_x - _urdu_width(label_text, PANEL_LABEL_SIZE) - gap
    if value:
        urdu = has_arabic(value) if urdu is None else urdu
        available = max_width if max_width is not None else cursor - LEFT
        value = _fit(value, value_size, available, urdu=urdu)
        sheet.text(cursor, baseline, value, value_size, color=INK,
                   font=SANS, align='right', urdu=urdu)
        cursor -= (_urdu_width(value, value_size) if urdu
                   else _latin_width(value, SANS, value_size)) + gap
    return cursor


def _draw_panel(state, doc):
    sheet = state['sheet']
    sheet.rect(PANEL_RIGHT_X, Y_PANEL, PANEL_BOX_W, PANEL_H, fill=PANEL,
               stroke=BORDER, width=0.75)
    sheet.rect(LEFT, Y_PANEL, PANEL_BOX_W, PANEL_H, fill=PANEL,
               stroke=BORDER, width=0.75)

    right_inner = RIGHT - PANEL_INNER_PAD
    left_inner = LEFT + PANEL_BOX_W - PANEL_INNER_PAD

    # Right panel: bill-to + contact on the first row, code on the second.
    cursor = _panel_field(sheet, right_inner, PANEL_RIGHT_TOP,
                          doc.get('party_label') or 'بل برائے',
                          doc.get('party_name'), PANEL_PARTY_SIZE,
                          max_width=PANEL_BOX_W - 2 * PANEL_INNER_PAD - 60)
    contact = doc.get('party_phone') or '____'
    contact_urdu = has_arabic(contact) or contact == '____'
    _panel_field(sheet, cursor, PANEL_RIGHT_TOP, 'حوالہ', contact,
                 PANEL_LABEL_SIZE if contact_urdu else PANEL_LATIN_SIZE,
                 max_width=max(20.0, cursor - PANEL_RIGHT_X - PANEL_INNER_PAD),
                 urdu=contact_urdu)
    _panel_field(sheet, right_inner, PANEL_RIGHT_BOTTOM, 'کوڈ',
                 doc.get('party_code'), PANEL_LATIN_SIZE,
                 max_width=PANEL_BOX_W - 2 * PANEL_INNER_PAD - 20)

    # Left panel: delivery (or method) on the first row, account on the second.
    fields = doc.get('fields') or []
    delivery = next((f for f in fields if 'ڈیلیوری' in f[0] or 'ڈلیوری' in f[0]), None)
    account = next((f for f in fields if 'اکاؤنٹ' in f[0] or 'بینک' in f[0]), None)
    others = [f for f in fields if f not in (delivery, account)
              and f[0] != (doc.get('party_label') or 'بل برائے') and f[0] != 'کوڈ']
    top_field = delivery or (others[0] if others else None)
    bottom_field = account or (others[1] if len(others) > 1 else None)
    if top_field:
        size = PANEL_DELIVERY_SIZE if has_arabic(top_field[1]) else PANEL_LATIN_SIZE
        _panel_field(sheet, left_inner, PANEL_LEFT_TOP, top_field[0],
                     top_field[1], size,
                     max_width=PANEL_BOX_W - 2 * PANEL_INNER_PAD - 20)
    if bottom_field:
        size = PANEL_LATIN_SIZE if not has_arabic(bottom_field[1]) else 8.6
        _panel_field(sheet, left_inner, PANEL_LEFT_BOTTOM, bottom_field[0],
                     bottom_field[1], size,
                     max_width=PANEL_BOX_W - 2 * PANEL_INNER_PAD - 20)

    state['y'] = Y_PANEL + PANEL_H


def _draw_items(state, doc, sheets):
    items = doc['items']
    if not items:
        return
    pending = list(items)
    index = 0
    first = True
    while pending:
        sheet = state['sheet']
        title_y = Y_SECTION_TITLE if first else CONT_HEAD_TOP - 6.4
        capacity = ROWS_FIRST_PAGE if first else ROWS_CONT_PAGE
        chunk = pending[:capacity]
        pending = pending[capacity:]

        sheet.text(RIGHT - 2.242, title_y, doc['items_title'], 9.0,
                   color=NAVY, align='right', urdu=True)
        if first:
            sheet.text(LEFT - 2.25, Y_SECTION_NOTE, SECTION_NOTE, 7.5,
                       color=NOTE_COLOR, align='left', urdu=True)
        head_top = Y_ITEMS_HEAD if first else CONT_HEAD_TOP
        _draw_item_header(sheet, head_top)
        top = head_top + ITEMS_HEAD_H
        _draw_item_rows(sheet, top, chunk, index)
        index += len(chunk)
        state['y'] = top + len(chunk) * ROW_H

        if pending:
            first = False
            sheet = _new_sheet()
            sheets.append(sheet)
            state['sheet'] = sheet
            _draw_header(state, doc, first=False)


def _item_columns():
    """Physical column geometry, left to right, for the items table."""
    return [
        {'key': 'amount', 'x0': LEFT, 'x1': 114.8031, 'align': 'right',
         'x': 110.182, 'label': 'رقم (روپے)', 'label_x': 114.070},
        {'key': 'rate', 'x0': 114.8031, 'x1': 186.9732, 'align': 'center',
         'x': 150.888, 'label': 'ریٹ', 'label_x': 186.228},
        {'key': 'qty', 'x0': 186.9732, 'x1': 243.9496, 'align': 'center',
         'x': 215.461, 'label': 'مقدار', 'label_x': 243.198},
        {'key': 'name', 'x0': 243.9496, 'x1': 369.2976, 'align': 'right',
         'x': 364.676, 'label': 'تفصیل / آئٹم', 'label_x': 368.552},
        {'key': 'index', 'x0': 369.2976, 'x1': RIGHT, 'align': 'center',
         'x': 384.491, 'label': 'نمبر', 'label_x': 398.939},
    ]


def _draw_item_header(sheet, top):
    sheet.rect(LEFT, top, CONTENT_W, ITEMS_HEAD_H, fill=NAVY)
    for column in _item_columns():
        sheet.text(column['label_x'], top + 9.8508, column['label'], 8.0,
                   color=WHITE, align='right', urdu=True)


def _draw_item_rows(sheet, top, rows, start_index=0):
    if not rows:
        return
    height = len(rows) * ROW_H
    for offset in range(len(rows)):
        if (start_index + offset) % 2 == 1:
            sheet.rect(LEFT, top + offset * ROW_H, CONTENT_W, ROW_H, fill=BAR)
    for offset in range(len(rows) + 1):
        sheet.hline(LEFT, RIGHT, top + offset * ROW_H, color=GRID, width=0.75)
    for column in _item_columns()[1:]:
        sheet.vline(column['x0'], top, top + height, color=GRID, width=0.75)
    sheet.rect(LEFT, top, CONTENT_W, height, stroke=GRID, width=0.75)

    for offset, item in enumerate(rows):
        row_top = top + offset * ROW_H
        urdu_baseline = row_top + 9.887
        latin_baseline = row_top + 10.215
        for column in _item_columns():
            key = column['key']
            if key == 'index':
                sheet.text(column['x'], latin_baseline, str(item.get('index', '')),
                           7.4, color=INK, align='center')
            elif key == 'name':
                name = str(item.get('name') or '')
                urdu = has_arabic(name)
                size = 8.5 if urdu else 7.4
                name = _fit(name, size, column['x'] - column['x0'] - 4.0,
                            urdu=urdu)
                sheet.text(column['x'], urdu_baseline if urdu else latin_baseline,
                           name, size, color=INK, align='right', urdu=urdu)
            elif key in ('qty', 'rate'):
                sheet.text(column['x'], latin_baseline, item.get(key, ''), 7.4,
                           color=INK, align='center')
            else:
                sheet.text(column['x'], latin_baseline, item.get('amount', ''),
                           7.4, color=INK, font=SANS_BOLD, align='right')


def _summary_box_height(rows):
    return len(rows) * SUM_ROW_H + 0.75


def _draw_summary(state, doc, sheets):
    if not doc['summary']:
        state['summary_top'] = state['y']
        state['summary_h'] = 0.0
        return

    rows = doc['summary']
    box_h = _summary_box_height(rows)
    top = (state['y'] + SUMMARY_GAP) if doc['show_items'] else (state['y'] + 12.0)
    needed = box_h + TERMS_GAP + (62.0 if doc.get('terms') else 0.0)
    if top + needed > _content_bottom():
        sheet = _new_sheet()
        sheets.append(sheet)
        state['sheet'] = sheet
        _draw_header(state, doc, first=False)
        top = state['y'] + 12.0
    sheet = state['sheet']

    box_w = SUM_RIGHT - SUM_LEFT
    inner_top = top + 0.375
    total_index = next((i for i, r in enumerate(rows) if r.get('total')),
                       len(rows) - 1)
    # total bar
    sheet.rect(SUM_LEFT + 0.375, inner_top + total_index * SUM_ROW_H,
               box_w - 0.75, SUM_ROW_H, fill=NAVY)
    for index in range(1, len(rows)):
        sheet.hline(SUM_LEFT, SUM_RIGHT, inner_top + index * SUM_ROW_H,
                    color=BORDER, width=0.75)
    sheet.rect(SUM_LEFT, top, box_w, box_h, stroke=BORDER, width=0.75)
    sheet.vline(SUM_DIVIDER, top, inner_top + total_index * SUM_ROW_H - 0.375,
                color=BORDER, width=0.75)

    for index, row in enumerate(rows):
        is_total = bool(row.get('total')) or index == total_index
        label_color = WHITE if is_total else INK
        y = inner_top + index * SUM_ROW_H
        sheet.text(SUM_LABEL_X, y + 9.3265, row.get('label', ''), 8.0,
                   color=label_color, align='right', urdu=True)
        sheet.text(SUM_VALUE_X, y + 10.2375, row.get('value', ''), 7.4,
                   color=label_color, font=SANS, align='left')

    state['summary_top'] = top
    state['summary_h'] = box_h
    state['sig_y'] = top + total_index * SUM_ROW_H + 1.625
    state['y'] = top + box_h


def _draw_signature(state, doc):
    sheet = state['sheet']
    line_y = state.get('sig_y')
    if line_y is None:
        top = state.get('summary_top') or state['y']
        line_y = top + 44.978
    sheet.hline(SIG_LINE_X0, SIG_LINE_X1, line_y, color=NAVY, width=0.75)
    sheet.text(SIG_LABEL_X, line_y + SIG_LABEL_OFFSET,
               doc['signature_label'], 8.0, color=INK, align='center',
               urdu=True)


def _draw_terms(state, doc, sheets):
    terms = doc['terms']
    if not terms:
        return
    size = TERMS_SIZE
    step = TERMS_STEP
    right_text_x, right_num_x = TERMS_RIGHT_TEXT_X, TERMS_RIGHT_NUM_X
    left_text_x, left_num_x = TERMS_LEFT_TEXT_X, TERMS_LEFT_NUM_X
    right_width, left_width = TERMS_RIGHT_WIDTH, TERMS_LEFT_WIDTH
    bottom = _content_bottom() - 8.0

    entries = []
    for number, term in enumerate(terms, start=1):
        text = (term.get('text') or term.get('title') or '').strip()
        if text:
            entries.append((number, text))
    if not entries:
        return

    def lines_of(items, width):
        return sum(max(1, len(wrap_urdu(text, size, width, max_lines=3)))
                   for _n, text in items)

    pending = entries
    while pending:
        sheet = state['sheet']
        rule_y = state['y'] + TERMS_GAP
        heading_baseline = rule_y + 9.8684
        first_baseline = rule_y + 20.4924
        capacity = max(1, int((bottom - first_baseline) / step) + 1)

        half = (len(pending) + 1) // 2 if len(pending) > 2 else len(pending)
        right_items = pending[:half]
        left_items = pending[half:]
        while len(right_items) > 1 and lines_of(right_items, right_width) > capacity:
            left_items.insert(0, right_items.pop())
        kept, used = [], 0
        for entry in left_items:
            count = max(1, len(wrap_urdu(entry[1], size, left_width, max_lines=3)))
            if kept and used + count > capacity:
                break
            kept.append(entry)
            used += count
        remaining = left_items[len(kept):]
        left_items = kept

        sheet.hline(LEFT, RIGHT, rule_y, color=BORDER, width=0.75)
        sheet.text(RIGHT, heading_baseline, 'شرائط و ضوابط', 8.0, color=NAVY,
                   align='right', urdu=True, bold=True)

        last_baseline = first_baseline
        for items, text_x, num_x, width in (
                (right_items, right_text_x, right_num_x, right_width),
                (left_items, left_text_x, left_num_x, left_width)):
            y = first_baseline
            for number, text in items:
                for line_index, line in enumerate(
                        wrap_urdu(text, size, width, max_lines=3)):
                    sheet.text(text_x, y, line, size, color=INK, align='right',
                               urdu=True)
                    if line_index == 0:
                        num_color = TERMS_RED if number == 4 else NAVY
                        sheet.text(num_x, y, f'{number}.', 6.5, color=num_color,
                                   align='right', font=SANS_BOLD)
                    y += step
                    last_baseline = max(last_baseline, y - step)

        if last_baseline > first_baseline:
            sheet.vline(TERMS_ACCENT_X, first_baseline - 7.125,
                        last_baseline + 3.411, color=TERMS_ACCENT, width=0.75)
        state['y'] = max(rule_y, first_baseline + max(
            lines_of(right_items, right_width) if right_items else 0,
            lines_of(left_items, left_width) if left_items else 0) * step)
        pending = remaining
        if pending:
            sheet = _new_sheet()
            sheets.append(sheet)
            state['sheet'] = sheet
            _draw_header(state, doc, first=False)


# ---------------------------------------------------------------------------
# ReportLab backend
# ---------------------------------------------------------------------------

def _rl_colour(value):
    from reportlab.lib import colors
    value = (value or '#000000').strip()
    try:
        if value.startswith('#') and len(value) in (4, 7):
            hexval = value if len(value) == 7 else '#' + ''.join(
                c * 2 for c in value[1:])
            return colors.HexColor(hexval)
        return colors.HexColor(value)
    except Exception:
        return colors.black


def _draw_latin(canvas, x, baseline, text, font, size, color, align,
                spacing=0.0):
    width = _latin_width(text, font, size) + spacing * max(len(text) - 1, 0)
    if align == 'right':
        x -= width
    elif align == 'center':
        x -= width / 2.0
    canvas.saveState()
    canvas.setFillColor(_rl_colour(color))
    canvas.setFont(font, size)
    if spacing:
        text_obj = canvas.beginText(x, baseline)
        text_obj.setFont(font, size)
        text_obj.setCharSpace(spacing)
        text_obj.textOut(text)
        canvas.drawText(text_obj)
    else:
        canvas.drawString(x, baseline, text)
    canvas.restoreState()


def _draw_urdu(canvas, x, baseline, text, size, color, align, bold=False):
    """Draw a whole shaped Urdu run glyph by glyph, exactly as HarfBuzz orders it."""
    from app.services.urdu_text import UPEM, glyphs_width
    from app.services.bilingual import _PUA_BASE

    font_name = urdu_font_name()
    if not font_name:
        return
    runs = _urdu_runs(text)
    if not runs:
        return
    shaped = []
    total = 0.0
    for chunk, direction in runs:
        glyphs = _shape_dir(chunk, direction) or []
        width = glyphs_width(glyphs) * size / UPEM if glyphs else 0.0
        shaped.append((glyphs, width))
        total += width
    pen = x - total if align == 'right' else (
        x - total / 2.0 if align == 'center' else x)

    canvas.saveState()
    canvas.setFillColor(_rl_colour(color))
    canvas.setFont(font_name, size)
    if bold:
        canvas.setLineWidth(max(0.16, size * 0.024))
        canvas.setStrokeColor(_rl_colour(color))
        canvas._textRenderMode = 2
    scale = size / UPEM
    for glyphs, width in shaped:
        for gid, advance, dx, dy in glyphs:
            canvas.drawString(pen + dx * scale, baseline + dy * scale,
                              chr(_PUA_BASE + gid))
            pen += advance * scale
    canvas.restoreState()


def render_pdf(doc, title=None, author=None, copies=1):
    """Render *doc* to PDF bytes (A5, or two A5 copies on an A4 leaf)."""
    register_latin_fonts()
    urdu_font_name()
    from reportlab.pdfgen import canvas as rl_canvas

    pages = compose_document(doc, copies=copies)
    buf = io.BytesIO()
    pdf = rl_canvas.Canvas(buf, pagesize=(pages[0].w, pages[0].h))
    if title:
        pdf.setTitle(title)
    if author:
        pdf.setAuthor(author)

    for index, page in enumerate(pages):
        if index:
            pdf.showPage()
        pdf.setPageSize((page.w, page.h))
        for op in page.ops:
            if op['op'] == 'rect':
                _paint_rect(pdf, page, op)
            elif op['op'] in ('line', 'seg'):
                _paint_line(pdf, page, op)
        for op in page.ops:
            if op['op'] != 'text':
                continue
            baseline = page.h - op['y']
            if op['urdu']:
                _draw_urdu(pdf, op['x'], baseline, op['text'], op['size'],
                           op['color'], op['align'], bold=op['bold'])
            else:
                _draw_latin(pdf, op['x'], baseline, op['text'], op['font'],
                            op['size'], op['color'], op['align'],
                            spacing=op['spacing'])
    pdf.showPage()
    pdf.save()
    data = buf.getvalue()
    return data if data.startswith(b'%PDF-') else None


def _paint_rect(canvas, page, op):
    canvas.saveState()
    if op['fill']:
        canvas.setFillColor(_rl_colour(op['fill']))
    if op['stroke']:
        canvas.setStrokeColor(_rl_colour(op['stroke']))
        canvas.setLineWidth(op['width'])
        if op['dash']:
            canvas.setDash(list(op['dash']))
    y = page.h - op['y'] - op['h']
    if op['fill'] and op['stroke']:
        canvas.rect(op['x'], y, op['w'], op['h'], stroke=1, fill=1)
    elif op['fill']:
        canvas.rect(op['x'], y, op['w'], op['h'], stroke=0, fill=1)
    elif op['stroke']:
        canvas.rect(op['x'], y, op['w'], op['h'], stroke=1, fill=0)
    canvas.restoreState()


def _paint_line(canvas, page, op):
    canvas.saveState()
    canvas.setStrokeColor(_rl_colour(op['color']))
    canvas.setLineWidth(op.get('width') or 1.0)
    if op.get('dash'):
        canvas.setDash(list(op['dash']))
    canvas.line(op['x0'], page.h - op['y0'], op['x1'],
                page.h - op['y1'])
    canvas.restoreState()


# ---------------------------------------------------------------------------
# HTML backend (browser print / preview)
# ---------------------------------------------------------------------------

_HTML_HEAD = """<!DOCTYPE html>
<html lang="ur" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
@font-face {{ font-family: 'DejaVu Sans'; src: url("/static/fonts/DejaVuSans.ttf") format("truetype"); font-weight: 400; }}
@font-face {{ font-family: 'DejaVu Sans'; src: url("/static/fonts/DejaVuSans-Bold.ttf") format("truetype"); font-weight: 700; }}
@font-face {{ font-family: 'Jameel Noori'; src: url("/static/fonts/{urdu_file}") format("truetype"); font-weight: normal; }}
@font-face {{ font-family: 'Jameel Noori'; src: url("/static/fonts/{urdu_file}") format("truetype"); font-weight: bold; }}
@page {{ size: {pw}pt {ph}pt; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #fff; }}
body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.pg {{ position: relative; width: {pw}pt; height: {ph}pt; page-break-after: always;
       overflow: hidden; background: #fff; }}
.pg:last-child {{ page-break-after: auto; }}
@media screen {{
  body {{ background: #eceff3; padding: 12px 0; }}
  .pg {{ margin: 0 auto 14px; box-shadow: 0 3px 14px rgba(0,0,0,.25); }}
  .bar {{ position: fixed; inset: auto 0 0 0; background: #16212e; padding: 8px 12px;
         text-align: center; z-index: 9; }}
  .bar button, .bar a {{ font-family: 'DejaVu Sans', sans-serif; font-size: 13px; border: 0;
    border-radius: 6px; padding: 7px 16px; margin: 0 4px; cursor: pointer;
    text-decoration: none; display: inline-block; }}
  .bar .go {{ background: #ffc107; color: #16212e; font-weight: 700; }}
  .bar .back {{ background: #334155; color: #fff; }}
}}
@media print {{ .bar {{ display: none; }} }}
.s, .t {{ position: absolute; }}
.t {{ padding: 0; margin: 0; }}
</style>
</head>
<body>
"""


def render_html(doc, title='Urdu Bill', auto_print=False, copies=1):
    """Render *doc* as a print-ready HTML page (same pages as the PDF)."""
    pages = compose_document(doc, copies=copies)
    parts = [_HTML_HEAD.format(title=_escape_html(title), pw=_fmt(pages[0].w),
                               ph=_fmt(pages[0].h),
                               urdu_file=URDU_FONT_FILE)]
    for page in pages:
        parts.append(f'<div class="pg" style="width:{_fmt(page.w)}pt;'
                     f'height:{_fmt(page.h)}pt">')
        for op in page.ops:
            if op['op'] == 'rect':
                parts.append(_html_rect(op))
            elif op['op'] in ('line', 'seg'):
                parts.append(_html_line(op))
        for op in page.ops:
            if op['op'] == 'text':
                parts.append(_html_text(op, page))
        parts.append('</div>')
    parts.append(
        '<div class="bar no-print">'
        '<a class="back" href="javascript:history.back()">&larr; واپس</a>'
        '<button type="button" class="go" onclick="printUrduReceipt()">پرنٹ کریں</button>'
        '</div>'
        '<script>function printUrduReceipt(){'
        'var ready=(document.fonts&&document.fonts.ready)?document.fonts.ready:Promise.resolve();'
        'ready.then(function(){window.print();});}</script>')
    if auto_print:
        parts.append('<script>window.addEventListener("load",function(){'
                     'setTimeout(function(){window.print();},250);});</script>')
    parts.append('</body></html>')
    return ''.join(parts)


def _fmt(value):
    return ('%.4f' % float(value)).rstrip('0').rstrip('.')


def _html_rect(op):
    style = [f"left:{_fmt(op['x'])}pt", f"top:{_fmt(op['y'])}pt",
             f"width:{_fmt(max(op['w'], 0.6))}pt",
             f"height:{_fmt(max(op['h'], 0.6))}pt"]
    if op['fill']:
        style.append(f"background:{op['fill']}")
    if op['stroke']:
        dash = 'dashed' if op['dash'] else 'solid'
        style.append(f"border:{_fmt(op['width'])}pt {dash} {op['stroke']}")
    return f'<div class="s" style="{";".join(style)}"></div>'


def _html_line(op):
    if op.get('dash'):
        horizontal = abs(op['y1'] - op['y0']) < 0.01
        if horizontal:
            style = (f"left:{_fmt(min(op['x0'], op['x1']))}pt;"
                     f"top:{_fmt(op['y0'] - op['width'] / 2)}pt;"
                     f"width:{_fmt(abs(op['x1'] - op['x0']))}pt;height:0;"
                     f"border-top:{_fmt(op['width'])}pt dashed {op['color']};")
        else:
            style = (f"left:{_fmt(op['x0'] - op['width'] / 2)}pt;"
                     f"top:{_fmt(min(op['y0'], op['y1']))}pt;"
                     f"width:0;height:{_fmt(abs(op['y1'] - op['y0']))}pt;"
                     f"border-left:{_fmt(op['width'])}pt dashed {op['color']};")
        return f'<div class="s" style="{style}"></div>'
    if abs(op['y1'] - op['y0']) < 0.01:
        width = abs(op['x1'] - op['x0'])
        style = (f"left:{_fmt(min(op['x0'], op['x1']))}pt;"
                 f"top:{_fmt(op['y0'] - op['width'] / 2)}pt;"
                 f"width:{_fmt(width)}pt;height:{_fmt(max(op['width'], 0.5))}pt;"
                 f"background:{op['color']}")
    else:
        height = abs(op['y1'] - op['y0'])
        style = (f"left:{_fmt(op['x0'] - op['width'] / 2)}pt;"
                 f"top:{_fmt(min(op['y0'], op['y1']))}pt;"
                 f"width:{_fmt(max(op['width'], 0.5))}pt;height:{_fmt(height)}pt;"
                 f"background:{op['color']}")
    return f'<div class="s" style="{style}"></div>'


def _escape_html(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


def _html_urdu_markup(text):
    """Keep embedded figures/Latin codes left-to-right inside an RTL run.

    The PDF backend shapes those tokens as LTR runs; a browser would otherwise
    let the RTL paragraph bidi reorder a figure such as ``12×18``.  Wrapping the
    token in ``dir="ltr"`` makes the print page agree with the PDF without
    changing the logical text.
    """
    parts = []
    for token in _RUN_TOKEN.findall(text or ''):
        if re.fullmatch(_LTR_RUN, token):
            parts.append(f'<span dir="ltr">{_escape_html(token)}</span>')
        else:
            parts.append(_escape_html(token))
    return ''.join(parts)


def _html_text(op, page=None):
    size = op['size']
    font = op['font']
    ratio = _BASELINE_RATIO.get(font, 0.85)
    color = op['color']
    page_w = page.w if page is not None else PAGE_W
    if font == 'ur':
        family = f"{URDU_FAMILY}, 'Noto Nastaliq Urdu', serif"
        direction = 'rtl'
        weight = 'bold' if op['bold'] else 'normal'
    else:
        family = "'DejaVu Sans', Arial, sans-serif"
        direction = 'ltr'
        weight = '700' if font == SANS_BOLD else '400'
    anchor = []
    if op['align'] == 'right':
        anchor.append(f"right:{_fmt(page_w - op['x'])}pt")
        align = 'right'
    elif op['align'] == 'center':
        anchor.append(f"left:{_fmt(op['x'])}pt")
        align = 'center'
        anchor.append("transform:translateX(-50%)")
    else:
        anchor.append(f"left:{_fmt(op['x'])}pt")
        align = 'left'
    style = ';'.join([
        *anchor,
        f"top:{_fmt(op['y'] - ratio * size)}pt",
        f"font-family:{family}",
        f"font-size:{_fmt(size)}pt",
        f"font-weight:{weight}",
        f"color:{color}",
        'line-height:1',
        f"text-align:{align}",
        f"direction:{direction}",
        'white-space:nowrap',
        'padding:0',
    ])
    if op['spacing']:
        style += f";letter-spacing:{_fmt(op['spacing'])}pt"
    if font == 'ur' and op['bold']:
        style += f";-webkit-text-stroke:{_fmt(max(0.16, size * 0.024))}pt {color}"
    text = (_html_urdu_markup(op['text']) if font == 'ur'
            else _escape_html(op['text']))
    return f'<div class="t" style="{style}">{text}</div>'
