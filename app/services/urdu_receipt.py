"""The Urdu bill: one fixed sheet, drawn the same on paper and in the PDF.

Every Urdu document the app produces - download or print - is this module's
output and nothing else.  Earlier Urdu bills reused the English receipt
template and merely swapped labels, so the Urdu sheet inherited an English
layout (black rules, a right-hand ``INVOICE`` badge, an English table header)
and looked like a translation of the English bill instead of its own document.

The approved Urdu sheet is a fixed design:

* A5 portrait, 419.53 x 595.28 pt, white paper, 28pt side margins.
* Header: three meta rows on the left (``بل نمبر`` / ``تاریخ`` / ``وقت``) over
  hairline rules, the company block on the right (name, address, proprietor,
  phones separated by a vertical hairline), closed by a double navy rule.
* Info panel: a light note strip on top, then two columns split by a hairline -
  transaction details on the left, the paying party on the right.
* ``آئٹمز`` section: navy header row, airy rows, amounts right aligned.
* Summary box on the left half: sales / previous balance / paid, with the
  outstanding total in a navy bar.
* Dashed stamp box and signature rule, then the thank-you footer.

Geometry is written once, in points, as a list of drawing primitives.  Two
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

NAVY = '#1F3A5E'
INK = '#16212E'
MUTED = '#5D6874'
HAIRLINE = '#E1E4E8'
BORDER = '#C7CFD5'
# The item table's grid is the deep ink; its row separators are the pale
# hairline.  Two different inks, exactly as the sheet prints them.
GRID = '#0D1F40'
GRID_ROW = '#E1E4E8'
RULE = '#C7CFD5'
PANEL = '#F4F5F7'
PANEL_HEAD = '#EEF1F6'
WHITE = '#FFFFFF'

PAGE_W = 419.53          # A5 portrait, the size the sheet was approved on
PAGE_H = 595.28
LEFT = 28.0
RIGHT = 391.0
CONTENT_W = RIGHT - LEFT

# Vertical anchors of the fixed blocks (measured off the approved sheet).
Y_META_1 = 32.2
META_STEP = 16.5
Y_RULE_1 = 84.0
Y_RULE_2 = 87.8
Y_PANEL = 97.9
Y_NOTE_H = 18.6
Y_PANEL_BOTTOM = 177.0
Y_ITEMS_TITLE = 191.0
Y_ITEMS_HEAD = 199.1
Y_SUMMARY = 394.2
ROW_H = 23.4
ROWS_PER_PAGE = 10
Y_SIG_BOX = 483.7
Y_SIG_BOX_H = 33.1
Y_FOOT_RULE = 540.4

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
_NUMERIC = re.compile(r'^[\s0-9+.,:/()%#\-\u2013]+$')


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


# ---------------------------------------------------------------------------
# Primitive canvas
# ---------------------------------------------------------------------------

class Sheet:
    """One physical page: an ordered list of drawing primitives."""

    def __init__(self):
        self.ops = []

    # -- shapes ---------------------------------------------------------
    def rect(self, x, y, w, h, fill=None, stroke=None, width=1.0, dash=None,
             radius=0.0):
        self.ops.append({'op': 'rect', 'x': x, 'y': y, 'w': w, 'h': h,
                         'fill': fill, 'stroke': stroke, 'width': width,
                         'dash': dash, 'radius': radius})

    def outline(self, x, y, w, h, color=HAIRLINE, width=0.9, dash=(3, 3),
                radius=0.0):
        """A hollow, dashed box — four hairlines, no fill at all.

        The reference's stamp box is exactly this: a dashed outline with the
        paper showing through, not a box with a pale background.
        """
        for y0, y1 in ((y, y), (y + h, y + h)):
            self.ops.append({'op': 'seg', 'x0': x, 'y0': y0, 'x1': x + w,
                             'y1': y1, 'color': color, 'width': width,
                             'dash': dash})
        for x0, x1 in ((x, x), (x + w, x + w)):
            self.ops.append({'op': 'seg', 'x0': x0, 'y0': y, 'x1': x1,
                             'y1': y + h, 'color': color, 'width': width,
                             'dash': dash})

    def hline(self, x0, x1, y, color=HAIRLINE, width=0.8):
        self.ops.append({'op': 'line', 'x0': x0, 'y0': y, 'x1': x1,
                         'y1': y, 'color': color, 'width': width})

    def vline(self, x, y0, y1, color=HAIRLINE, width=0.8):
        self.ops.append({'op': 'line', 'x0': x, 'y0': y0, 'x1': x,
                         'y1': y1, 'color': color, 'width': width})

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

    def block(self, x, top, w, value, size, color=INK, align='right',
              urdu=True, bold=False, leading=None, max_lines=2):
        """Draw a paragraph that may wrap (notes, terms), right to left.

        Returns the height used.  Manual wrapping keeps both backends on the
        same line breaks - the browser never has to reflow by itself.
        """
        leading = leading or size * (1.75 if urdu else 1.30)
        lines = wrap_urdu(value, size, w, max_lines=max_lines)
        used = 0.0
        first_urdu = True
        for line in lines:
            baseline = top + used + (size * (0.86 if urdu else 0.80))
            self.text(x, baseline, line, size, color=color, align=align,
                      urdu=urdu, bold=bold)
            used += leading
            first_urdu = False
        return used or leading


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
# The document model
# ---------------------------------------------------------------------------

def _u(value):
    """Urdu text with Urdu punctuation tidied ('' when empty)."""
    return ('' if value is None else str(value)).strip()


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


def build_document(*, bill_no='', date_posted=None, company_name='',
                   company_address='', company_phone='', proprietor='',
                   note='', party_name='', party_code='', party_label='بل برائے',
                   detail_rows=None, items=None, summary=None,
                   terms=None, footer_thanks='آپ کے کاروبار کا شکریہ',
                   footer_credit='سافٹ ویئر: اے ایم ایس سسٹم فار ایز',
                   signature_left='کمپنی مہر',
                   signature_right='وصول کنندہ / مجاز دستخط',
                   show_items=True, items_title='آئٹمز',
                   continuation_label='جاری'):
    """Assemble the data the sheet needs.

    Every value is copied from the bill as stored - nothing is recomputed
    here, so the Urdu sheet can never disagree with the ledger about a figure.
    """
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
        'detail_rows': [r for r in (detail_rows or []) if r and r[1]],
        'items': list(items or []),
        'summary': list(summary or []),
        'terms': list(terms or []),
        'footer_thanks': footer_thanks,
        'footer_credit': footer_credit,
        'signature_left': signature_left,
        'signature_right': signature_right,
        'show_items': bool(show_items and items),
        'items_title': items_title,
        'continuation_label': continuation_label,
    }


# ---------------------------------------------------------------------------
# Layout: data -> pages of primitives
# ---------------------------------------------------------------------------

def layout_document(doc):
    """Return ``[Sheet, ...]`` - the exact page(s) both backends draw."""
    sheets = []
    sheet = _new_sheet()
    sheets.append(sheet)

    state = {'sheet': sheet, 'y': 0.0}
    _draw_header(state, doc, first=True)
    _draw_panel(state, doc)
    if doc['show_items']:
        _draw_items(state, doc, sheets)
    _draw_summary(state, doc, sheets)
    if doc.get('terms'):
        _draw_terms(state, doc, sheets)
    _draw_signatures(state, doc, sheets)
    _draw_footer(state, doc, sheets)
    return sheets


def _new_sheet():
    sheet = Sheet()
    sheet.rect(0, 0, PAGE_W, PAGE_H, fill=WHITE)
    return sheet


def _ensure_space(state, sheets, needed, doc):
    """Start a continuation page when *needed* points do not fit."""
    bottom = PAGE_H - 30.0
    if state['y'] + needed <= bottom:
        return False
    sheet = _new_sheet()
    sheets.append(sheet)
    state['sheet'] = sheet
    _draw_header(state, doc, first=False)
    return True


def _draw_header(state, doc, first=True):
    """Meta rows + company block + the double navy rule."""
    sheet = state['sheet']

    if first:
        # --- left: bill number / date / time over hairline rules ----------
        rows = [
            ('بل نمبر', doc['bill_no'], 'Inter-Bold', 9.4),
            ('تاریخ', doc['date'], 'Inter-SemiBold', 8.6),
            ('وقت', doc['time'], 'Inter-SemiBold', 8.6),
        ]
        y = Y_META_1
        for index, (label, value, font, size) in enumerate(rows):
            sheet.text(158.5, y, label, _urdu_size(8.6), color=MUTED,
                       align='right', urdu=True)
            if value:
                sheet.text(28.3, y, value, size, color=INK, font=font,
                           align='left', urdu=_is_arabic_word(value))
            if index < len(rows) - 1:
                sheet.hline(LEFT, 158.5, y + 6.3, color=HAIRLINE, width=0.8)
            y += META_STEP

        # --- right: company block ----------------------------------------
        sheet.text(390.8, 33.0, doc['company_name'], 14.0, color=NAVY,
                   font='Inter-Bold', align='right')
        sheet.text(390.2, 47.2, doc['company_address'], 7.8, color=MUTED,
                   font='Inter-Medium', align='right', spacing=0.55)
        if doc['proprietor']:
            sheet.text(391.0, 61.0, 'پروپرائٹر: ' + doc['proprietor'],
                       _urdu_size(9.2), color=MUTED, align='right', urdu=True)
        phones = doc['phones'][:2]
        if phones:
            cursor = 391.0
            sheet.text(cursor, 73.0, 'فون', _urdu_size(8.8), color=MUTED,
                       align='right', urdu=True)
            cursor -= _urdu_width('فون', _urdu_size(8.8)) + 5.0
            for index, phone in enumerate(phones):
                sheet.text(cursor, 73.0, phone, 8.4, color=INK,
                           font='Inter-SemiBold', align='right')
                cursor -= _latin_width(phone, 'Inter-SemiBold', 8.4)
                if index < len(phones) - 1:
                    sheet.vline(cursor - 5.0, 66.2, 75.2, color=BORDER,
                                width=0.7)
                    cursor -= 11.0

        # --- closing double rule -----------------------------------------
        # closing double rule: a 1.5pt bar, then a 0.8pt one beneath it
        sheet.rect(LEFT, Y_RULE_1, CONTENT_W, 1.5, fill=NAVY)
        sheet.rect(LEFT, Y_RULE_2 - 0.4, CONTENT_W, 0.8, fill=NAVY)

    else:
        # Continuation page: a slim running head, same rules.
        sheet.text(390.8, 33.0, doc['company_name'], 10.0, color=NAVY,
                   font='Inter-Bold', align='right')
        if doc['bill_no']:
            sheet.text(LEFT, 33.0, doc['bill_no'], 8.6, color=INK,
                       font='Inter-SemiBold', align='left')
            sheet.text(LEFT + _latin_width(doc['bill_no'], 'Inter-SemiBold', 8.6) + 8,
                       33.0, doc['continuation_label'], _urdu_size(8.6),
                       color=MUTED, align='left', urdu=True)
        sheet.rect(LEFT, 42.0, CONTENT_W, 1.5, fill=NAVY)
        sheet.rect(LEFT, 45.8, CONTENT_W, 0.8, fill=NAVY)

    state['y'] = Y_RULE_2 + 0.8 if first else 46.6


def _draw_panel(state, doc):
    """Note strip + two columns (transaction details / paying party)."""
    sheet = state['sheet']
    top = Y_PANEL if state['y'] < Y_PANEL else state['y'] + 10.0
    note_h = Y_NOTE_H if doc['note'] else 0.0
    # The sheet's panel body is 59.1pt under an 18.6pt note strip.  A receipt
    # carries more detail rows (method / type / bank / account), so the body
    # grows by one 13pt line per extra row and nothing is ever clipped.
    body_h = max(60.5, 60.5 + 13.0 * (len(doc['detail_rows']) - 3))
    height = note_h + body_h
    bottom = top + height

    sheet.rect(LEFT + 0.4, top, CONTENT_W - 0.4, height, fill=PANEL,
               stroke=BORDER, width=1.0)

    if doc['note']:
        sheet.rect(LEFT + 1.15, top + 0.75, CONTENT_W - 1.55, note_h - 0.75,
                   fill=PANEL_HEAD)
        sheet.hline(LEFT + 1.15, RIGHT - 0.75, top + note_h, color=BORDER,
                    width=0.8)
        note_lines = wrap_urdu(doc['note'], 9.02, CONTENT_W - 26.0, max_lines=1)
        if note_lines:
            sheet.text(RIGHT - 8.0, top + 13.0, note_lines[0], 9.02,
                       color=MUTED, align='right', urdu=True)

    body_top = top + note_h
    divider = 224.5
    sheet.vline(divider, body_top, bottom - 0.4, color=BORDER, width=0.8)

    # -- left column: transaction details --------------------------------
    left_x = divider - 10.5
    y = body_top + 13.5
    if doc['detail_rows']:
        sheet.text(left_x, y, 'ٹرانزیکشن کی تفصیلات', 10.56,
                   color=INK, align='right', urdu=True, bold=True)
        y += 13.7
        for label, value in doc['detail_rows']:
            label_text = label if label.endswith(':') else label + ':'
            sheet.text(left_x, y, label_text, _urdu_size(9.2), color=MUTED,
                       align='right', urdu=True)
            label_w = _urdu_width(label_text, _urdu_size(9.2))
            # A Latin value (``Cash``, ``Drawer Cash``) starts where the label
            # ends, so the colon sits between the two the way the sheet reads.
            sheet.text(left_x - label_w - 3.5, y, value, 9.4, color=INK,
                       font='Inter-SemiBold', align='right',
                       urdu=has_arabic(value))
            y += 13.0
    else:
        sheet.text(left_x, y, 'ٹرانزیکشن کی تفصیلات', 10.56,
                   color=INK, align='right', urdu=True, bold=True)

    # -- right column: the paying party ----------------------------------
    right_x = RIGHT - 9.5
    sheet.text(right_x, body_top + 14.6, doc['party_label'], 9.9,
               color=MUTED, align='right', urdu=True)
    if doc['party_name']:
        sheet.text(right_x, body_top + 35.0, doc['party_name'], 14.3,
                   color=INK, align='right', urdu=True, bold=True)
    if doc['party_code']:
        code_y = body_top + 53.5
        sheet.text(right_x, code_y, 'کوڈ', _urdu_size(9.2), color=MUTED,
                   align='right', urdu=True)
        code_w = _urdu_width('کوڈ', _urdu_size(9.2))
        sheet.text(right_x - code_w - 4.5, code_y, doc['party_code'], 8.6,
                   color=INK, font='Inter-SemiBold', align='right')

    state['y'] = bottom


def _draw_items(state, doc, sheets):
    """``آئٹمز`` title, navy header row and the item rows."""
    items = doc['items']
    if not items:
        # A payment or a plain receipt has no material lines, so the whole
        # table is skipped rather than printed as an empty grid that leaves a
        # large blank in the middle of the page.
        return
    columns = _item_columns()

    sheet = state['sheet']
    # On a clean bill the section keeps the sheet's own anchors; a long bill
    # (or one whose panel grew) simply continues into a new page.
    title_y = max(Y_ITEMS_TITLE, state['y'] + 14.0)
    if state['y'] + 40.0 + ROW_H * 2 > PAGE_H - 30:
        _ensure_space(state, sheets, 40.0 + ROW_H * 2, doc)
        sheet = state['sheet']
        title_y = state['y'] + 16.0
    _draw_items_title(sheet, doc, title_y)

    state['y'] = title_y + 8.1
    pending = list(items)
    while pending:
        chunk = pending[:ROWS_PER_PAGE]
        pending = pending[ROWS_PER_PAGE:]
        if state['y'] + 19.5 + len(chunk) * ROW_H > PAGE_H - 32:
            _ensure_space(state, sheets, 60.0, doc)
            sheet = state['sheet']
            title_y = state['y'] + 16.0
            _draw_items_title(sheet, doc, title_y)
            state['y'] = title_y + 8.1
            sheet = state['sheet']
        top = state['y']
        _draw_item_header(sheet, columns, top)
        _draw_item_rows(sheet, columns, top + 19.5, chunk)
        state['y'] = top + 19.5 + len(chunk) * ROW_H + 4.9

    sheet = state['sheet']
    # the closing rule is a 0.8pt bar, exactly like every other rule
    sheet.rect(LEFT, state['y'] - 0.5, CONTENT_W, 0.8, fill=NAVY)


def _draw_items_title(sheet, doc, title_y):
    sheet.text(RIGHT - 9.0, title_y + 2.0, doc['items_title'], 10.56,
               color=INK, align='right', urdu=True, bold=True)
    sheet.rect(RIGHT - 3.0, title_y - 7.3, 3.0, 11.2, fill=NAVY)


def _item_columns():
    """Physical column geometry, left to right, for the items table."""
    return [
        {'key': 'amount', 'x0': LEFT, 'x1': 107.2, 'pad': 5.7,
         'label': 'رقم (روپے)'},
        {'key': 'rate', 'x0': 107.2, 'x1': 169.4, 'pad': 5.6, 'label': 'ریٹ'},
        {'key': 'qty', 'x0': 169.4, 'x1': 218.1, 'pad': 15.4,
         'label': 'مقدار'},
        {'key': 'name', 'x0': 218.1, 'x1': 365.1, 'pad': 8.2,
         'label': 'تفصیل / میٹیریل'},
        {'key': 'index', 'x0': 365.1, 'x1': RIGHT, 'pad': 9.3,
         'label': 'نمبر'},
    ]


def _draw_item_header(sheet, columns, top):
    sheet.rect(LEFT, top, CONTENT_W, 19.5, fill=NAVY)
    for column in columns:
        if column['x0'] > LEFT:
            # white hairlines between the navy header cells
            sheet.vline(column['x0'], top, top + 19.5, color=WHITE, width=0.8)
        sheet.text(column['x1'] - column['pad'], top + 16.5,
                   column['label'], 9.9, color=WHITE, align='right', urdu=True,
                   bold=True)


def _draw_item_rows(sheet, columns, top, rows):
    for index, item in enumerate(rows):
        y = top + index * ROW_H
        if index:
            # the pale hairline sits 0.9pt above the row's own box
            sheet.rect(LEFT, y - 0.9, CONTENT_W, 0.8, fill=GRID_ROW)
        baseline = y + 14.2
        for column in columns:
            right = column['x1'] - column['pad']
            if column['key'] == 'index':
                sheet.text(right, y + 14.2, str(item.get('index', '')), 8.4,
                           color=MUTED, align='right')
            elif column['key'] == 'name':
                name = item.get('name', '')
                sheet.text(right, baseline, name, 10.56, color=INK,
                           align='right', urdu=_is_arabic_word(name),
                           bold=True)
            elif column['key'] == 'qty':
                sheet.text(right, baseline, item.get('qty', ''), 8.8,
                           color=INK, align='right')
            elif column['key'] == 'rate':
                sheet.text(right, baseline, item.get('rate', ''), 8.8,
                           color=INK, align='right')
            else:
                sheet.text(right, baseline, item.get('amount', ''), 8.8,
                           color=INK, font='Inter-Bold', align='right')
    bottom = top + len(rows) * ROW_H
    if rows:
        # the last row's own separator closes the table
        sheet.rect(LEFT, bottom - 0.9, CONTENT_W, 0.8, fill=GRID_ROW)
    sheet.rect(LEFT, top, CONTENT_W, bottom - top, stroke=GRID, width=0.9)
    for column in columns[1:]:
        sheet.vline(column['x0'], top, bottom, color=GRID, width=0.9)


def _draw_summary(state, doc, sheets):
    """The summary box on the left half, closed by the navy total bar.

    The reference draws this as stacked bands: a navy top edge, pale hairlines
    between plain rows, a solid navy bar for the total, then the box outline.
    The vertical divider stops at the total bar and continues in white, so the
    bar reads as one unbroken block from the left edge to the right.
    """
    if not doc['summary']:
        return
    rows = doc['summary']
    heights = [20.2 if row.get('total') else 17.5 for row in rows]
    box_h = sum(heights)

    # With no item table above it (a payment or a plain receipt) the totals
    # follow the panel directly, instead of hanging off the bottom anchor and
    # leaving a hole in the middle of the sheet.
    top = max(Y_SUMMARY, state['y']) if doc['items'] else state['y'] + 24.0
    if top + box_h > PAGE_H - 118:
        _ensure_space(state, sheets, box_h + 22.0, doc)
        top = state['y'] + 16.0
    sheet = state['sheet']

    box_right = 220.8
    box_w = box_right - LEFT
    divider = 121.6
    total_h = heights[-1] if rows[-1].get('total') else 0.0

    # top edge of the box
    sheet.rect(LEFT, top, box_w, 0.9, fill=NAVY)

    y = top
    for index, row in enumerate(rows):
        row_h = heights[index]
        is_total = bool(row.get('total'))
        if is_total:
            sheet.rect(LEFT, y, box_w, row_h, fill=NAVY)
        if index:
            # every row is closed by a navy hairline (the total bar's own lid
            # is drawn again below so it reads as one solid block)
            sheet.rect(LEFT, y, box_w, 0.9, fill=NAVY)
        band = y + (14.3 if is_total else 12.4)
        sheet.text(214.5, band, row.get('label', ''),
                   11.0 if is_total else 10.12,
                   color=WHITE if is_total else INK,
                   align='right', urdu=True, bold=is_total)
        sheet.text(101.6, band, row.get('value', ''),
                   11.0 if is_total else 9.2,
                   color=WHITE if is_total else INK, font='Inter-Bold',
                   align='right')
        y += row_h

    bottom = top + box_h
    # navy lid on the total bar, then its closing edge
    if total_h:
        sheet.rect(LEFT, bottom - total_h, box_w, 0.9, fill=NAVY)
    sheet.rect(LEFT, bottom - 0.9, box_w, 0.9, fill=NAVY)

    sheet.rect(LEFT, top, box_w, box_h, stroke=NAVY, width=0.9)
    sheet.vline(divider, top, bottom - total_h, color=NAVY, width=0.9)
    if total_h:
        # the divider becomes a white gap alongside the total bar
        sheet.rect(divider, bottom - total_h, 0.9, total_h, fill=WHITE)
    state['y'] = bottom


def _draw_terms(state, doc, sheets):
    """Terms & conditions, when the user asked for them on the Urdu bill."""
    terms = doc['terms']
    if not terms:
        return
    sheet = state['sheet']
    size = 8.6
    line_h = size * 1.62
    width = RIGHT - LEFT - 12.0

    blocks = [(term.get('title', ''),
               wrap_urdu(term.get('text', ''), size, width, max_lines=4))
              for term in terms]
    height = 20.0 + sum(13.0 + len(lines) * line_h + 4.0
                        for _t, lines in blocks)
    if state['y'] + height + 118.0 > PAGE_H:
        _ensure_space(state, sheets, 30.0, doc)
        sheet = state['sheet']

    top = state['y'] + 12.0
    sheet.text(RIGHT, top + 7.0, 'شرائط و ضوابط', _urdu_size(9.2), color=INK,
               align='right', urdu=True, bold=True)
    sheet.hline(LEFT, RIGHT, top + 12.0, color=NAVY, width=0.8)
    y = top + 12.0
    for title, lines in blocks:
        y += 12.0
        if title:
            sheet.text(RIGHT, y, title, _urdu_size(8.6), color=INK,
                       align='right', urdu=True, bold=True)
            y += 12.5
        for line in lines:
            sheet.text(RIGHT, y, line, size, color=MUTED, align='right',
                       urdu=True)
            y += line_h
        y += 4.0
    state['y'] = y


def _draw_signatures(state, doc, sheets):
    sheet = state['sheet']
    top = max(Y_SIG_BOX, state['y'])
    if top + Y_SIG_BOX_H + 14.0 > PAGE_H - 40:
        _ensure_space(state, sheets, 80.0, doc)
        sheet = state['sheet']
        top = state['y'] + 20.0

    # dashed stamp box on the left, its label centred beneath it
    box_w, box_h = 115.7, Y_SIG_BOX_H
    sheet.outline(LEFT - 0.8, top, box_w, box_h, color=BORDER, width=0.9,
                  dash=(3, 3))
    sheet.text(LEFT - 0.8 + box_w / 2, top + box_h + 11.2,
               doc['signature_left'], _urdu_size(9.2), color=MUTED,
               align='center', urdu=True)

    # signature rule on the right, its label just below
    sheet.hline(232.8, RIGHT, top + box_h - 1.2, color=INK, width=0.9)
    sheet.text(RIGHT, top + box_h + 10.6, doc['signature_right'],
               _urdu_size(9.2), color=MUTED, align='right', urdu=True)
    state['y'] = top + box_h + 13.0


def _draw_footer(state, doc, sheets):
    sheet = state['sheet']
    if state['y'] + 50.0 > PAGE_H - 4:
        _ensure_space(state, sheets, 50.0, doc)
        sheet = state['sheet']
    y = max(Y_FOOT_RULE, state['y'] + 6.0)
    sheet.hline(LEFT, RIGHT, y, color=BORDER, width=0.8)
    sheet.text(PAGE_W / 2, y + 15.7, doc['footer_thanks'], _urdu_size(10.2),
               color=NAVY, align='center', urdu=True, bold=True)
    sheet.text(PAGE_W / 2, y + 32.0, doc['footer_credit'], 8.58, color=MUTED,
               align='center', urdu=True)
    state['y'] = y + 34.0



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


def _draw_latin(canvas, x, baseline, text, font, size, color, align, spacing=0.0):
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
            width = _latin_width(word, 'Inter-SemiBold', size)
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
            canvas.setFont('Inter-SemiBold', size)
            canvas.drawString(pen, baseline, word)
            canvas.setFont(font_name, size)
        pen += width + space
    canvas.restoreState()


def render_pdf(doc, title=None, author=None):
    """Render *doc* to PDF bytes (A5, one or more pages)."""
    register_latin_fonts()
    urdu_font_name()
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    pdf = rl_canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    if title:
        pdf.setTitle(title)
    if author:
        pdf.setAuthor(author)

    for index, sheet in enumerate(layout_document(doc)):
        if index:
            pdf.showPage()
        for op in sheet.ops:
            if op['op'] == 'rect':
                _paint_rect(pdf, op)
            elif op['op'] in ('line', 'seg'):
                _paint_line(pdf, op)
        # Text is painted after the shapes of the same page so a filled bar or
        # a header background can never cover a label drawn before it.
        for op in sheet.ops:
            if op['op'] != 'text':
                continue
            baseline = PAGE_H - op['y']
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


def _paint_rect(canvas, op):
    canvas.saveState()
    if op['fill']:
        canvas.setFillColor(_rl_colour(op['fill']))
    if op['stroke']:
        canvas.setStrokeColor(_rl_colour(op['stroke']))
        canvas.setLineWidth(op['width'])
        if op['dash']:
            canvas.setDash(list(op['dash']))
    y = PAGE_H - op['y'] - op['h']
    if op['fill'] and op['stroke']:
        canvas.rect(op['x'], y, op['w'], op['h'], stroke=1, fill=1)
    elif op['fill']:
        canvas.rect(op['x'], y, op['w'], op['h'], stroke=0, fill=1)
    elif op['stroke']:
        canvas.rect(op['x'], y, op['w'], op['h'], stroke=1, fill=0)
    canvas.restoreState()


def _paint_line(canvas, op):
    canvas.saveState()
    canvas.setStrokeColor(_rl_colour(op['color']))
    canvas.setLineWidth(op.get('width') or 1.0)
    if op.get('dash'):
        canvas.setDash(list(op['dash']))
    canvas.line(op['x0'], PAGE_H - op['y0'], op['x1'], PAGE_H - op['y1'])
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
         text-align: center; }}
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


def render_html(doc, title='Urdu Bill', auto_print=False):
    """Render *doc* as a print-ready HTML page (same page as the PDF)."""
    parts = [_HTML_HEAD.format(title=title, pw=_fmt(PAGE_W), ph=_fmt(PAGE_H),
                               urdu_file=URDU_FONT_FILE)]
    for sheet in layout_document(doc):
        parts.append('<div class="pg">')
        for op in sheet.ops:
            if op['op'] == 'rect':
                parts.append(_html_rect(op))
            elif op['op'] in ('line', 'seg'):
                parts.append(_html_line(op))
        for op in sheet.ops:
            if op['op'] == 'text':
                parts.append(_html_text(op))
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
                 f"width:{_fmt(width)}pt;height:{_fmt(op['width'])}pt;"
                 f"background:{op['color']}")
    else:
        height = abs(op['y1'] - op['y0'])
        style = (f"left:{_fmt(op['x0'] - op['width'] / 2)}pt;"
                 f"top:{_fmt(min(op['y0'], op['y1']))}pt;"
                 f"width:{_fmt(op['width'])}pt;height:{_fmt(height)}pt;"
                 f"background:{op['color']}")
    return f'<div class="s" style="{style}"></div>'


def _html_text(op):
    size = op['size']
    font = op['font']
    ratio = _BASELINE_RATIO.get(font, 0.85)
    top = op['y'] - ratio * size
    color = op['color']
    if font == 'ur':
        family = f"{URDU_FAMILY}, 'Noto Nastaliq Urdu', serif"
        direction = 'rtl'
        weight = 'bold' if op['bold'] else 'normal'
    else:
        family = f"Inter, Arial, sans-serif"
        direction = 'ltr'
        weight = {'Inter-Medium': '500', 'Inter-SemiBold': '600',
                  'Inter-Bold': '700', 'Inter-ExtraBold': '800'}.get(font, '400')
    anchor = []
    if op['align'] == 'right':
        anchor.append(f"right:{_fmt(PAGE_W - op['x'])}pt")
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
