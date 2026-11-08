"""The Urdu bill: one fixed sheet, drawn the same on paper and in the PDF.

Every Urdu document the app produces - download or print - is this module's
output and nothing else.  Earlier Urdu bills reused the English receipt
template and merely swapped labels, so the Urdu sheet inherited an English
layout (black rules, a right-hand ``INVOICE`` badge, an English table header)
and looked like a translation of the English bill instead of its own document.

The sheet is the approved Urdu bill, measured off the reference PDF:

* A5 portrait, 419.53 x 595.28 pt, white paper, 19.8pt side margins.
* Header: QR block on the left, the company name centred in Nastaleeq with the
  address under it, the proprietor and the phone numbers hard right, closed by
  the thick navy rule and its thin companion.
* Meta strip: one bordered row of four cells - time / date / document type /
  bill number - split by hairlines.
* Info panel: a pale two-row panel.  The first row carries the four inline
  fields (bill to / delivery / code / account) read right to left; a dotted
  rule closes it and the shop note sits underneath.
* ``ٹرانزیکشن کی تفصیلات`` heading, then the navy item header and the ruled
  item rows (zebra tinted, amounts right aligned, quantities centred).
* Summary box on the right: sales / previous balance / paid, closed by the
  solid navy total bar, with the signature rule to its left.
* Terms & conditions in two numbered columns under a hairline.

Carbon copy
-----------
A carbon-copy receipt book prints the same bill twice.  The sheet is therefore
*paged*: :func:`layout_document` returns the A5 content pages and
:func:`compose_document` places them on the paper.  With ``copies=2`` (the
default) two identical A5 copies sit side by side on one A4 landscape leaf -
the original (``اصل``, for the customer) on the right, the carbon copy
(``نقل``, for the office) on the left - with a dashed cut line between them.
``copies=1`` prints a single A5 sheet.

Geometry is written once, in points, as a list of drawing primitives.  Both
backends consume that list:

* :func:`render_pdf` draws it on a ReportLab canvas (used for "Urdu PDF").
* :func:`render_html` lays the same primitives out absolutely in an HTML page
  (used for "Urdu Print"), so the browser preview, the printed sheet and the
  downloaded PDF are the same page.

Urdu runs are shaped with HarfBuzz and drawn glyph by glyph at the positions
HarfBuzz computed - Nastaleeq marks live outside their advance width, so a
naive ``drawString`` of a shaped string stacks them on the baseline.
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
GRID = '#AEBDCF'
DOT = '#B5C4D6'
WHITE = '#FFFFFF'

# Older names for two palette entries, kept because other modules read them.
HAIRLINE = BORDER
GRID_ROW = BAR

PAGE_W = 419.53          # A5 portrait, the size the sheet was approved on
PAGE_H = 595.28
A4_W = 841.89            # A4 landscape: two A5 copies side by side
A4_H = 595.28

LEFT = 19.8
RIGHT = 399.7
CONTENT_W = RIGHT - LEFT
PAGE_BOTTOM = 575.0      # nothing is printed below this line

# -- header ---------------------------------------------------------------
QR_X, QR_Y, QR_SIZE = 20.6, 15.0, 47.0
Y_COMPANY = 43.4
Y_ADDRESS = 62.8
Y_PROPRIETOR = 32.3
Y_PHONE_1 = 45.2
PHONE_STEP = 12.9
Y_RULE_1, RULE_1_H = 75.0, 2.9
Y_RULE_2, RULE_2_H = 79.2, 0.9
Y_META, META_H = 80.7, 16.2
META_BASELINE = 90.9
META_CELLS = ((111.2, 110.5), (217.3, 216.6), (278.0, 277.3), (RIGHT, 393.3))

# -- info panel -----------------------------------------------------------
Y_PANEL, PANEL_H = 99.7, 39.9
Y_PANEL_DOTS = 121.4
PANEL_BASELINE = 114.5
NOTE_BASELINE = 131.6
FIELD_WIDTH = CONTENT_W / 4.0

# -- items ----------------------------------------------------------------
Y_SECTION_TITLE = 152.3
Y_ITEMS_HEAD, ITEMS_HEAD_H = 158.7, 15.9
Y_ITEMS_ROWS = 174.6
ROW_H = 15.33
CONT_HEAD_TOP = 74.0     # continuation pages start their table here
ROWS_FIRST_PAGE = 15
ROWS_CONT_PAGE = 23
ITEMS_TITLE = 'ٹرانزیکشن کی تفصیلات'

# -- summary / signature / terms -----------------------------------------
SUMMARY_GAP = 6.9
SUM_LEFT, SUM_RIGHT, SUM_DIVIDER = 229.4, 397.4, 328.7
SUM_LABEL_X, SUM_VALUE_X = 391.0, 235.9
SIG_LINE_X0, SIG_LINE_X1 = 66.5, 208.3
SIG_OFFSET = 44.6
TERMS_GAP = 6.5

FONT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'static', 'fonts')
)

# Inter is the sheet's Latin face; the weights are the ones the approved
# document uses.  They are bundled (SIL Open Font License, see
# static/fonts/Inter-LICENSE.txt) because a shared host has no system fonts.
INTER_FILES = {
    'Inter': 'Inter-Regular.ttf',
    'Inter-Medium': 'Inter-Medium.ttf',
    'Inter-SemiBold': 'Inter-SemiBold.ttf',
    'Inter-Bold': 'Inter-Bold.ttf',
    'Inter-ExtraBold': 'Inter-ExtraBold.ttf',
}
URDU_FAMILY = "'Jameel Noori'"
URDU_FONT_FILE = 'JameelNooriNastaleeq.ttf'

# Baseline position inside a line box, per font, as a fraction of the type
# size.  The HTML backend needs it to put a baseline anchor exactly where the
# PDF backend draws it (``line-height: 1`` + these metrics).
# Where a browser puts the baseline inside a ``line-height: 1`` line box:
# ``(1 - (ascent + descent)) / 2 + ascent`` from the font's own metrics.  The
# HTML backend uses these to turn the PDF's baseline anchors into offsets, so
# "Urdu Print" and "Urdu PDF" sit on the very same line.
_BASELINE_RATIO = {
    'Inter': 0.864, 'Inter-Medium': 0.864, 'Inter-SemiBold': 0.864,
    'Inter-Bold': 0.864, 'Inter-ExtraBold': 0.864,
    'ur': 0.7627,          # Jameel Noori Nastaleeq: 1976 / 2048 upem
}

# Copy marks printed round each half of a carbon-copy leaf.
COPY_ORIGINAL = 'اصل'
COPY_CARBON = 'نقل'

_inter_registered = False


def _font_path(name):
    return os.path.join(FONT_DIR, INTER_FILES[name])


def register_latin_fonts():
    """Register the bundled Inter weights with ReportLab (idempotent)."""
    global _inter_registered
    if _inter_registered:
        return True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        for name, filename in INTER_FILES.items():
            path = os.path.join(FONT_DIR, filename)
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
        _inter_registered = True
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


def _urdu_size(base):
    """Urdu type size paired with a Latin size (Nastaleeq needs a little more)."""
    return round(float(base) * 1.075, 2)


# ---------------------------------------------------------------------------
# Text shaping helpers
# ---------------------------------------------------------------------------

_ARABIC = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFEFE]')


def _is_arabic_word(word):
    return bool(_ARABIC.search(word or ''))


def has_arabic(text):
    """True when *text* carries Arabic-script letters."""
    return bool(_ARABIC.search(text or ''))


def rtl_words(text):
    """Split *text* into ``[(word, is_urdu)]`` in visual (left to right) order.

    The sheet is written right to left, so the first word of an Urdu string is
    printed at the right edge: ``"07 نومبر 2026"`` puts ``07`` hard right and
    ``2026`` hard left, exactly like the approved bill.  Figures, codes and
    English words keep their own internal left-to-right order and are only
    moved as whole words, which is what a reader expects from
    ``FBMCL-00002`` or ``12,500``.
    """
    text = (text or '').strip()
    if not text:
        return []
    words = [w for w in re.split(r'\s+', text) if w]
    items = [(w, _is_arabic_word(w)) for w in words]
    return list(reversed(items))


def _shape(text):
    """``[(gid, advance, x_offset, y_offset)]`` for an Urdu run, or None."""
    try:
        from app.services.urdu_text import shape_glyphs
        return shape_glyphs(text)
    except Exception:
        return None


def _urdu_width(text, size):
    """Ink width in points of an Urdu run at *size*."""
    try:
        from app.services.urdu_text import measure_run
        width = measure_run(text, size)
        if width:
            return width
    except Exception:
        pass
    glyphs = _shape(text)
    if not glyphs:
        return 0.0
    from app.services.urdu_text import glyphs_width, UPEM
    return glyphs_width(glyphs) * size / UPEM


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
    measure = _urdu_width if urdu else (lambda t, s: _latin_width(t, 'Inter-SemiBold', s))
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

    # -- shapes ---------------------------------------------------------
    def rect(self, x, y, w, h, fill=None, stroke=None, width=1.0, dash=None,
             radius=0.0):
        self.ops.append({'op': 'rect', 'x': x, 'y': y, 'w': w, 'h': h,
                         'fill': fill, 'stroke': stroke, 'width': width,
                         'dash': dash, 'radius': radius})

    def outline(self, x, y, w, h, color=BORDER, width=0.9, dash=(3, 3),
                radius=0.0):
        """A hollow, dashed box - four hairlines, no fill at all."""
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

    # -- text -----------------------------------------------------------
    def text(self, x, baseline, value, size, color=INK, font='Inter',
             align='left', urdu=False, bold=False, spacing=0.0, nowrap=True):
        """Anchor a string.

        ``align='left'`` puts the string's left edge at *x*;
        ``align='right'`` puts its right edge at *x*;
        ``align='center'`` centres it on *x*.
        *urdu* runs are ordered right to left (see :func:`rtl_words`).
        """
        if value is None or str(value).strip() == '':
            return
        if urdu and not has_arabic(value):
            # A pure Latin value (an English note, a product name) keeps its
            # own left-to-right word order; only its anchor stays on the
            # sheet's right edge.
            urdu = False
        self.ops.append({
            'op': 'text', 'x': float(x), 'y': float(baseline),
            'text': str(value), 'size': float(size), 'color': color,
            'font': 'ur' if urdu else font, 'align': align,
            'urdu': bool(urdu), 'bold': bool(bold),
            'spacing': float(spacing or 0.0), 'nowrap': bool(nowrap),
        })

    def copy_to(self, page, dx=0.0, dy=0.0):
        """Draw this sheet's marks onto *page*, shifted by (dx, dy)."""
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
        # Ellipsis in Urdu text: a plain "…" is safe in both backends.
        while last and _urdu_width(last + '…', size) > width:
            last = last.rsplit(' ', 1)[0] if ' ' in last else last[:-1]
        lines[-1] = last + '…'
    return lines


# ---------------------------------------------------------------------------
# QR code (vector modules, drawn by both backends)
# ---------------------------------------------------------------------------

def qr_matrix(text):
    """Booleans matrix for *text*, or ``None`` when no encoder is installed."""
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
    """The square QR block on the left of the header, with its caption."""
    matrix = qr_matrix(doc.get('qr_text'))
    if matrix:
        rows, cols = len(matrix), len(matrix[0])
        pad = 2.6
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
        sheet.text(QR_X, 70.6, caption, 5.5, color=INK, align='left',
                   urdu=has_arabic(caption), spacing=0.4)


# ---------------------------------------------------------------------------
# The document model
# ---------------------------------------------------------------------------

def _qty(value):
    """Quantities/amounts exactly as the bill stores them."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return str(value or '')
    if abs(number - round(number)) < 1e-9:
        return f'{int(round(number)):,}'
    return f'{number:,.2f}'.rstrip('0').rstrip('.')


def _phone(value):
    """``+92331-0000993`` -> ``+92 331 0000993`` (the sheet's phone style)."""
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
    """Phones from a settings string such as ``+92... | +92...``.

    Settings hold this line free-hand, so the separators may be ``|``, ``,``,
    ``;`` or plain spaces.  Each ``+92…`` group is one number; anything that
    is not a number is dropped.
    """
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
    """``07 نومبر 2026`` - the approved bill's date line."""
    if dt is None:
        return ''
    try:
        from app.services.bilingual import _URDU_MONTHS
        month = _URDU_MONTHS.get(dt.strftime('%b'), dt.strftime('%b'))
    except Exception:
        month = dt.strftime('%b')
    return f'{dt.strftime("%d")} {month} {dt.strftime("%Y")}'


def _urdu_time(dt):
    """``12:20 دوپہر`` - time first, then the Urdu half of the day."""
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
    """The four inline panel fields, read right to left.

    Order on the sheet: bill-to, delivery, code, account - exactly the run of
    fields the approved bill prints.
    """
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
                   fields=None, detail_rows=None, items=None, summary=None,
                   terms=None, type_label='', qr_text='', qr_caption='',
                   signature_label='مجاز دستخط', items_title=ITEMS_TITLE,
                   continuation_label='جاری', show_items=True,
                   footer_thanks='', footer_credit='', signature_left='',
                   signature_right=''):
    """Assemble the data the sheet needs.

    Every value is copied from the bill as stored - nothing is recomputed
    here, so the Urdu sheet can never disagree with the ledger about a figure.
    """
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


def compose_document(doc, copies=2):
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

    # Two A5 copies side by side; centred on the slightly wider A4 leaf so
    # the paper margins stay equal.  The original sits on the right because
    # the sheet reads right to left.
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
    """Mark a copy in the blank strip under the terms."""
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
    """QR + company block + the double navy rule + the four-cell meta strip."""
    sheet = state['sheet']

    if first:
        _draw_qr(sheet, doc)

        # --- company block, centred on the sheet --------------------------
        # The name shares its row with the QR block and the proprietor, so a
        # long shop name is set a little smaller instead of running into
        # either of them.
        name = doc['company_name']
        name_size = 25.0
        if has_arabic(name):
            while name_size > 13.0 and _urdu_width(name, name_size) > 232.0:
                name_size -= 0.5
        sheet.text(200.3, Y_COMPANY, name, name_size, color=NAVY,
                   align='center', urdu=True)
        if doc['company_address']:
            sheet.text(200.3, Y_ADDRESS, doc['company_address'], 8.0,
                       color=ADDRESS, align='center', urdu=True, spacing=0.15)

        # --- proprietor and phones, hard right ----------------------------
        if doc['proprietor']:
            sheet.text(RIGHT - 0.8, Y_PROPRIETOR,
                       'پروپرائٹر: ' + doc['proprietor'], 7.6, color=INK,
                       align='right', urdu=True)
        for index, phone in enumerate(doc['phones'][:2]):
            sheet.text(RIGHT - 0.8, Y_PHONE_1 + index * PHONE_STEP, phone,
                       6.6, color=INK, font='Inter-SemiBold', align='right')

        # --- closing rules -------------------------------------------------
        sheet.rect(LEFT, Y_RULE_1, CONTENT_W, RULE_1_H, fill=NAVY)
        sheet.rect(LEFT, Y_RULE_2, CONTENT_W, RULE_2_H, fill=NAVY)

    else:
        # Continuation page: a slim running head, same rules.
        sheet.text(RIGHT - 0.8, 33.0, doc['company_name'], 10.0, color=NAVY,
                   align='right', urdu=True)
        if doc['bill_no']:
            sheet.text(LEFT, 33.0, doc['bill_no'], 8.6, color=INK,
                       font='Inter-SemiBold', align='left')
            sheet.text(LEFT + _latin_width(doc['bill_no'], 'Inter-SemiBold', 8.6) + 8,
                       33.0, doc['continuation_label'], 9.2, color=MUTED,
                       align='left', urdu=True)
        sheet.rect(LEFT, 42.0, CONTENT_W, 1.5, fill=NAVY)
        sheet.rect(LEFT, 45.8, CONTENT_W, 0.8, fill=NAVY)

    _draw_meta_strip(sheet, doc)
    state['y'] = Y_META + META_H


def _draw_meta_strip(sheet, doc):
    """Time / date / type / bill number in one bordered strip."""
    sheet.rect(LEFT, Y_META, CONTENT_W, META_H, fill=BAR, stroke=BORDER,
               width=0.75)
    for x, _right in META_CELLS[:-1]:
        sheet.vline(x, Y_META, Y_META + META_H, color=BORDER, width=0.75)

    time_right = META_CELLS[0][1]
    date_right = META_CELLS[1][1]
    type_right = META_CELLS[2][1]
    bill_right = META_CELLS[3][1]

    _label_value(sheet, time_right, META_BASELINE, 'وقت', doc['time'],
                 value_size=8.0)
    _label_value(sheet, date_right, META_BASELINE, 'تاریخ', doc['date'],
                 value_size=8.0)
    if doc.get('type_label'):
        sheet.text(type_right, META_BASELINE, doc['type_label'], 7.4,
                   color=INK, font='Inter-SemiBold', align='right')
    _label_value(sheet, bill_right, META_BASELINE, 'بل نمبر', doc['bill_no'],
                 value_size=7.4)


def _label_value(sheet, right_x, baseline, label, value, value_size=8.0):
    """``label: value`` read right to left, anchored on *right_x*."""
    cursor = right_x
    if label:
        label_text = label if label.endswith(':') else label + ':'
        sheet.text(cursor, baseline, label_text, 8.0, color=INK,
                   align='right', urdu=True)
        cursor -= _urdu_width(label_text, 8.0) + 2.0
    if value:
        urdu = has_arabic(value)
        sheet.text(cursor, baseline, value, value_size if not urdu else 8.0,
                   color=INK, font='Inter-SemiBold', align='right', urdu=urdu)


def _draw_panel(state, doc):
    """The pale panel: four inline fields, a dotted rule, then the shop note."""
    sheet = state['sheet']
    sheet.rect(LEFT, Y_PANEL, CONTENT_W, PANEL_H, fill=PANEL, stroke=BORDER,
               width=0.75)
    sheet.hline(LEFT + 6.5, RIGHT - 6.4, Y_PANEL_DOTS, color=DOT, width=0.9,
                dash=(1.1, 1.9))

    fields = doc['fields'][:4]
    for index, (label, value) in enumerate(fields):
        cell_right = RIGHT - index * FIELD_WIDTH - 8.5
        cell_left = cell_right - FIELD_WIDTH + 6.0
        label_text = label if label.endswith(':') else label + ':'
        sheet.text(cell_right, PANEL_BASELINE, label_text, 8.0, color=MUTED,
                   align='right', urdu=True)
        label_w = _urdu_width(label_text, 8.0)
        value_size = 8.0 if has_arabic(value) else 6.4
        available = cell_right - label_w - cell_left - 2.0
        value_text = _fit(value, value_size, available,
                          urdu=has_arabic(value))
        sheet.text(cell_right - label_w - 3.0, PANEL_BASELINE, value_text,
                   value_size, color=INK, font='Inter-SemiBold',
                   align='right', urdu=has_arabic(value_text))

    if doc['note']:
        note = wrap_urdu(doc['note'], 7.5, RIGHT - 6.4 - (LEFT + 12.0),
                         max_lines=1)
        if note:
            sheet.text(RIGHT - 6.4, NOTE_BASELINE, note[0], 7.5, color=INK,
                       align='right', urdu=True)

    state['y'] = Y_PANEL + PANEL_H


def _draw_items(state, doc, sheets):
    """Section heading, navy header row and the ruled item rows."""
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

        sheet.text(RIGHT, title_y, doc['items_title'], 9.0, color=NAVY,
                   align='right', urdu=True)
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
        {'key': 'amount', 'x0': LEFT, 'x1': 114.8, 'align': 'right',
         'x': 110.2, 'label': 'رقم (روپے)', 'label_x': 114.1},
        {'key': 'rate', 'x0': 114.8, 'x1': 187.0, 'align': 'center',
         'x': 150.9, 'label': 'ریٹ', 'label_x': 186.2},
        {'key': 'qty', 'x0': 187.0, 'x1': 243.9, 'align': 'center',
         'x': 215.45, 'label': 'مقدار', 'label_x': 243.2},
        {'key': 'name', 'x0': 243.9, 'x1': 369.3, 'align': 'right',
         'x': 364.7, 'label': 'تفصیل / آئٹم', 'label_x': 368.6},
        {'key': 'index', 'x0': 369.3, 'x1': RIGHT, 'align': 'center',
         'x': 384.5, 'label': 'نمبر', 'label_x': 398.9},
    ]


def _draw_item_header(sheet, top):
    sheet.rect(LEFT, top, CONTENT_W, ITEMS_HEAD_H, fill=NAVY)
    for column in _item_columns()[1:]:
        sheet.vline(column['x0'], top, top + ITEMS_HEAD_H, color=WHITE,
                    width=0.75)
    for column in _item_columns():
        sheet.text(column['label_x'], top + 9.9, column['label'], 8.0,
                   color=WHITE, align='right', urdu=True)


def _draw_item_rows(sheet, top, rows, start_index=0):
    if not rows:
        return
    height = len(rows) * ROW_H
    # zebra tint on every second row, exactly as the approved sheet prints it
    for offset in range(len(rows)):
        if (start_index + offset) % 2 == 1:
            sheet.rect(LEFT, top + offset * ROW_H, CONTENT_W, ROW_H, fill=BAR)
    # the ruled grid
    for offset in range(len(rows) + 1):
        sheet.hline(LEFT, RIGHT, top + offset * ROW_H, color=GRID, width=0.75)
    for column in _item_columns()[1:]:
        sheet.vline(column['x0'], top, top + height, color=GRID, width=0.75)
    sheet.rect(LEFT, top, CONTENT_W, height, stroke=GRID, width=0.75)

    for offset, item in enumerate(rows):
        baseline = top + offset * ROW_H + 10.0
        for column in _item_columns():
            key = column['key']
            if key == 'index':
                sheet.text(column['x'], baseline, str(item.get('index', '')),
                           7.4, color=INK, align='center')
            elif key == 'name':
                name = str(item.get('name') or '')
                urdu = has_arabic(name)
                size = 8.5 if urdu else 7.4
                # a long material name is ellipsised inside its own column
                # instead of running over the quantity beside it
                name = _fit(name, size, column['x'] - column['x0'] - 4.0,
                            urdu=urdu)
                sheet.text(column['x'], baseline, name, size,
                           color=INK, align='right', urdu=urdu)
            elif key in ('qty', 'rate'):
                sheet.text(column['x'], baseline, item.get(key, ''), 7.4,
                           color=INK, align='center')
            else:
                sheet.text(column['x'], baseline, item.get('amount', ''), 7.4,
                           color=INK, font='Inter-Bold', align='right')


def _draw_summary(state, doc, sheets):
    """The summary box on the right half, closed by the navy total bar."""
    if not doc['summary']:
        state['summary_top'] = state['y']
        state['summary_h'] = 0.0
        return

    rows = doc['summary']
    heights = [15.2] + [14.5] * (len(rows) - 1)
    box_h = sum(heights)

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
    y = top
    for index, row in enumerate(rows):
        row_h = heights[index]
        is_total = bool(row.get('total'))
        if is_total:
            sheet.rect(SUM_LEFT, y, box_w, row_h, fill=NAVY)
        if index:
            sheet.hline(SUM_LEFT, SUM_RIGHT, y, color=BORDER, width=0.75)
        label_color = WHITE if is_total else INK
        sheet.text(SUM_LABEL_X, y + 8.2, row.get('label', ''), 8.0,
                   color=label_color, align='right', urdu=True)
        sheet.text(SUM_VALUE_X, y + 9.1, row.get('value', ''), 7.4,
                   color=label_color, font='Inter-Bold', align='left')
        y += row_h

    sheet.rect(SUM_LEFT, top, box_w, box_h, stroke=BORDER, width=0.75)
    sheet.vline(SUM_DIVIDER, top, top + box_h - heights[-1], color=BORDER,
                width=0.75)

    state['summary_top'] = top
    state['summary_h'] = box_h
    state['y'] = top + box_h


def _draw_signature(state, doc):
    """The signature rule and its label, to the left of the summary box."""
    sheet = state['sheet']
    top = state.get('summary_top') or state['y']
    height = state.get('summary_h') or 0.0
    offset = min(SIG_OFFSET, max(10.0, height - 14.0)) if height else 0.0
    line_y = top + offset
    sheet.hline(SIG_LINE_X0, SIG_LINE_X1, line_y, color=NAVY, width=0.9)
    sheet.text((SIG_LINE_X0 + SIG_LINE_X1) / 2, line_y + 7.9,
               doc['signature_label'], 8.0, color=INK, align='center',
               urdu=True)


def _draw_terms(state, doc, sheets):
    """Terms & conditions, numbered, in two right-to-left columns.

    The right column carries the first half of the clauses and the left
    column the rest - the reading order of the sheet.  A clause that wraps
    keeps its number once, on the first line, and a clause that will not fit
    the remaining height continues on the next page rather than being clipped.
    """
    terms = doc['terms']
    if not terms:
        return
    # The sheet sets the clauses a shade under body size so a whole clause
    # holds one line in the right column, exactly like the approved bill.
    size = 6.6
    step = 11.7
    right_text_x, right_num_x = 392.7, 399.7
    left_text_x, left_num_x = 197.1, 204.1
    right_width, left_width = 188.0, 122.0
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
        heading_baseline = rule_y + 8.3
        first_baseline = rule_y + 19.1
        capacity = max(1, int((bottom - first_baseline) / step) + 1)

        half = (len(pending) + 1) // 2 if len(pending) > 2 else len(pending)
        right_items = pending[:half]
        left_items = pending[half:]
        # Never let the right column run past the page: overflow moves left.
        while len(right_items) > 1 and lines_of(right_items,
                                                right_width) > capacity:
            left_items.insert(0, right_items.pop())
        # Fill the left column only as far as the page allows.
        kept, used = [], 0
        for entry in left_items:
            count = max(1, len(wrap_urdu(entry[1], size, left_width,
                                         max_lines=3)))
            if kept and used + count > capacity:
                break
            kept.append(entry)
            used += count
        remaining = left_items[len(kept):]
        left_items = kept

        sheet.hline(LEFT, RIGHT, rule_y, color=BORDER, width=0.8)
        sheet.text(RIGHT, heading_baseline, 'شرائط و ضوابط', 8.0, color=NAVY,
                   align='right', urdu=True, bold=True)

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
                        sheet.text(num_x, y, f'{number}.', 6.5, color=INK,
                                   align='right')
                    y += step

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
    width = _latin_width(text, font, size)
    if align == 'right':
        x -= width
    elif align == 'center':
        x -= width / 2.0
    canvas.saveState()
    canvas.setFillColor(_rl_colour(color))
    canvas.setFont(font, size)
    if spacing:
        # ReportLab exposes character spacing through the text object only.
        text_obj = canvas.beginText(x, baseline)
        text_obj.setFont(font, size)
        text_obj.setCharSpace(spacing)
        text_obj.textOut(text)
        canvas.drawText(text_obj)
        canvas.restoreState()
        return
    canvas.drawString(x, baseline, text)
    canvas.restoreState()


def _draw_urdu(canvas, x, baseline, text, size, color, align, bold=False):
    """Draw a right-to-left run word by word, glyph by glyph."""
    from app.services.urdu_text import UPEM, glyphs_width
    from app.services.bilingual import _PUA_BASE

    font_name = urdu_font_name()
    if not font_name:
        return
    words = rtl_words(text)
    if not words:
        return
    space = size * 0.235
    shaped = []
    total = 0.0
    for word, is_urdu in words:
        if is_urdu:
            glyphs = _shape(word) or []
            width = glyphs_width(glyphs) * size / UPEM if glyphs else 0.0
        else:
            glyphs = None
            width = _latin_width(word, 'Inter-SemiBold', size * 0.92)
        shaped.append((word, is_urdu, glyphs, width))
        total += width
    total += space * max(0, len(shaped) - 1)

    pen = x - total if align == 'right' else (
        x - total / 2.0 if align == 'center' else x)

    canvas.saveState()
    canvas.setFillColor(_rl_colour(color))
    canvas.setFont(font_name, size)
    if bold:
        # Faux bold: the bundled Nastaleeq face ships a single weight, so text
        # is drawn fill+stroke (the same trick the browser applies).
        canvas.setLineWidth(max(0.16, size * 0.024))
        canvas.setStrokeColor(_rl_colour(color))
        canvas._textRenderMode = 2
    for word, is_urdu, glyphs, width in shaped:
        if is_urdu and glyphs:
            scale = size / UPEM
            cursor = pen
            for gid, advance, dx, dy in glyphs:
                canvas.drawString(cursor + dx * scale, baseline + dy * scale,
                                  chr(_PUA_BASE + gid))
                cursor += advance * scale
        elif word:
            canvas.setFont('Inter-SemiBold', size * 0.92)
            canvas.drawString(pen, baseline, word)
            canvas.setFont(font_name, size)
        pen += width + space
    canvas.restoreState()


def render_pdf(doc, title=None, author=None, copies=2):
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
        # Text is painted after the shapes of the same page so a filled bar or
        # a header background can never cover a label drawn before it.
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
    canvas.line(op['x0'], page.h - op['y0'], op['x1'], page.h - op['y1'])
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
@font-face {{ font-family: 'Inter'; src: url("/static/fonts/Inter-Regular.ttf") format("truetype"); font-weight: 400; }}
@font-face {{ font-family: 'Inter'; src: url("/static/fonts/Inter-Medium.ttf") format("truetype"); font-weight: 500; }}
@font-face {{ font-family: 'Inter'; src: url("/static/fonts/Inter-SemiBold.ttf") format("truetype"); font-weight: 600; }}
@font-face {{ font-family: 'Inter'; src: url("/static/fonts/Inter-Bold.ttf") format("truetype"); font-weight: 700; }}
@font-face {{ font-family: 'Inter'; src: url("/static/fonts/Inter-ExtraBold.ttf") format("truetype"); font-weight: 800; }}
@font-face {{ font-family: 'Jameel Noori'; src: url("/static/fonts/{urdu_file}") format("truetype"); font-weight: normal; }}
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
  .bar button, .bar a {{ font-family: Inter, sans-serif; font-size: 13px; border: 0;
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


def render_html(doc, title='Urdu Bill', auto_print=False, copies=2):
    """Render *doc* as a print-ready HTML page (same pages as the PDF)."""
    pages = compose_document(doc, copies=copies)
    parts = [_HTML_HEAD.format(title=title, pw=_fmt(pages[0].w),
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
        '<button type="button" class="go" onclick="window.print()">پرنٹ کریں</button>'
        '</div>')
    if auto_print:
        parts.append('<script>window.addEventListener("load",function(){'
                     'setTimeout(function(){window.print();},250);});</script>')
    parts.append('</body></html>')
    return ''.join(parts)


def _fmt(value):
    return ('%.2f' % float(value)).rstrip('0').rstrip('.')


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
        # a dashed hairline: a hollow div with one dashed edge
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
        family = "Inter, Arial, sans-serif"
        direction = 'ltr'
        weight = {'Inter-Medium': '500', 'Inter-SemiBold': '600',
                  'Inter-Bold': '700', 'Inter-ExtraBold': '800'}.get(font, '400')
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
    text = (op['text'].replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))
    return f'<div class="t" style="{style}">{text}</div>'
