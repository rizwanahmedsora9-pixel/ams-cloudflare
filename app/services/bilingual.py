"""Dual-language (English + Urdu) PDF support.

Every PDF the app saves is rendered in two languages inside the same
document: the original English text plus Urdu translations rendered in the
Jameel Noori Nastaleeq font (bundled at ``static/fonts/JameelNooriNastaleeq.ttf``).

Two rendering paths are covered:

* **WeasyPrint path** (``app.services.files_pdf._try_render_weasy_pdf``):
  :func:`apply_bilingual` injects a ``@font-face`` rule plus Urdu ``<span
  class="ur">`` elements next to known English labels.  Pango shapes the
  Arabic script automatically, so no pre-shaping is needed.

* **ReportLab paths** (the HTML fallback in ``app.services.pdf_fallback`` and
  the direct supplier-statement builder in ``app.services.supplier_ledger_pdf``):
  ReportLab cannot shape Arabic itself, so :func:`shape_urdu` runs the text
  through ``arabic_reshaper`` + ``python-bidi`` and :func:`register_urdu_font`
  registers the Jameel Noori TTF.
"""
from __future__ import annotations

import os
import re

# --------------------------------------------------------------------------
# Font location / registration
# --------------------------------------------------------------------------

FONT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'static', 'fonts')
)
JAMEEL_NOORI_TTF = os.path.join(FONT_DIR, 'JameelNooriNastaleeq.ttf')
URDU_FONT_FAMILY = 'Jameel Noori'
URDU_FONT_REPORTLAB = 'JameelNoori'   # registered TTF name for ReportLab

# The bundled Jameel Noori font keeps its Nastaleeq ligatures in OpenType GSUB
# tables and has almost no Arabic Presentation Forms in its cmap.  ReportLab
# does not apply GSUB, so for the ReportLab paths we shape the text with
# HarfBuzz ourselves and map the resulting glyph ids through a private-use
# cmap that we add to a cached copy of the font (see _shaped_font_path).
_PUA_BASE = 0xF0000

_urdu_font_registered = False
_hb_face = None
_hb_font = None


def urdu_font_available() -> bool:
    return os.path.exists(JAMEEL_NOORI_TTF)


def _font_cache_dir() -> str:
    cache = os.environ.get('AMS_FONT_CACHE_DIR')
    if not cache:
        import tempfile
        cache = os.path.join(tempfile.gettempdir(), 'ams_font_cache')
    os.makedirs(cache, exist_ok=True)
    return cache


def _shaped_font_path() -> str | None:
    """Cached copy of the Jameel font with a PUA cmap (glyph-id -> U+F0000+gid).

    Built once with fontTools and reused afterwards; returns ``None`` when the
    font or fontTools is unavailable.
    """
    if not urdu_font_available():
        return None
    dst = os.path.join(_font_cache_dir(), 'JameelNooriNastaleeq-shaped.ttf')
    try:
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            return dst
        from fontTools.ttLib import TTFont
        from fontTools.ttLib.tables._c_m_a_p import cmap_format_12
        tt = TTFont(JAMEEL_NOORI_TTF)
        order = tt.getGlyphOrder()
        newmap = dict(tt.getBestCmap())
        for gid, name in enumerate(order):
            if gid < 0xFFF0:
                newmap[_PUA_BASE + gid] = name
        fmt12 = cmap_format_12(12)
        fmt12.platformID = 3
        fmt12.platEncID = 10
        fmt12.language = 0
        fmt12.cmap = newmap
        tt['cmap'].tables.append(fmt12)
        tmp = dst + '.tmp'
        tt.save(tmp)
        os.replace(tmp, dst)
        return dst
    except Exception:
        return None


def register_urdu_font() -> str | None:
    """Register the (shaped-cache) Jameel Noori TTF with ReportLab.

    Returns the registered font name, or ``None`` when the font file or
    ReportLab is unavailable so callers can gracefully fall back.
    """
    global _urdu_font_registered
    if _urdu_font_registered:
        return URDU_FONT_REPORTLAB
    if not urdu_font_available():
        return None
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        shaped = _shaped_font_path()
        pdfmetrics.registerFont(TTFont(URDU_FONT_REPORTLAB, shaped or JAMEEL_NOORI_TTF))
        _urdu_font_registered = True
        return URDU_FONT_REPORTLAB
    except Exception:
        return None


def _hb():
    """Lazily built HarfBuzz face/font for the bundled Jameel font."""
    global _hb_face, _hb_font
    if _hb_font is not None:
        return _hb_font
    if not urdu_font_available():
        return None
    try:
        import uharfbuzz as hb
        with open(JAMEEL_NOORI_TTF, 'rb') as fh:
            data = fh.read()
        _hb_face = hb.Face(data)
        _hb_font = hb.Font(_hb_face)
        return _hb_font
    except Exception:
        return None


def shape_urdu(text: str) -> str:
    """Shape Arabic-script text for ReportLab.

    HarfBuzz applies the font's own GSUB rules and returns glyph ids in
    visual order (RTL buffers come out left-to-right); each glyph id is
    mapped to a private-use codepoint (U+F0000+gid) that the cached shaped
    font resolves through its added cmap.  Falls back to
    arabic_reshaper/python-bidi, then to the raw text.
    """
    if not text:
        return text
    font = _hb()
    if font is not None:
        try:
            import uharfbuzz as hb
            buf = hb.Buffer()
            buf.add_str(text)
            buf.direction = 'rtl'
            buf.script = 'Arab'
            buf.language = 'ur'
            hb.shape(font, buf, {})
            return ''.join(chr(_PUA_BASE + info.codepoint) for info in buf.glyph_infos)
        except Exception:
            pass
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


# --------------------------------------------------------------------------
# English -> Urdu label dictionary
# --------------------------------------------------------------------------
# Ordered longest-first at use time so multi-word labels win over their
# single-word prefixes (e.g. "Total Paid" before "Total" before "Paid").
# Urdu values that contain non-Arabic filler are dropped by the sanity filter
# at the bottom of this section, so a bad entry can never leak into a PDF.

# Codepoint-built Urdu words for terms that must never render as Latin filler.
_ADA_SHUDA = '\u0627\u062f\u0627 \u0634\u062f\u06c1'          # Ada shuda (paid)
_DEBIT = '\u062f\u06cc\u0628\u0679'                          # debit (dibutt)
_CREDIT = '\u06a9\u0631\u06cc\u0688\u0679'                    # credit (credit)
_DELIVERED = '\u0688\u0644\u06cc\u0648\u0631\u06cc\u062f'      # delivered (delivered)
_STOCK = '\u0627\u0633\u0679\u0627\u06a9'                    # stock
_LOSS = '\u0646\u0642\u0635\u0627\u0646'                      # loss
_TRANSFER = '\u0645\u0646\u062a\u0642\u0644\u06cc'             # transfer
_TRANSFERS = '\u0645\u0646\u062a\u0642\u0644\u06cc\u0627\u06ba'  # transfers
_DOWNLOAD = '\u0688\u0648\u0627\u0646\u0644\u0648\u062f'       # download
_KIYA_GAYA = '\u06a9\u06cc\u0627 \u06af\u06cc\u0627'          # kiya gaya (done)
_VEHICLE_FARE = '\u06af\u0627\u0691\u06cc \u06a9\u0627 \u06a9\u0631\u0627\u06cc\u06c1'  # vehicle fare (gari kaMono krayah)
_UNLOADING = '\u0627\u062a\u0627\u0631\u0646\u0627'             # unloading
_LOADING = '\u0644\u0648\u0688 \u06a9\u0631\u0646\u0627'       # loading
_CHARGES = '\u0686\u0627\u0631\u062c\u0632'                    # charges
_CHARGE = '\u0686\u0627\u0631\u062c'                          # charge
_EXPENSE = '\u062e\u0631\u0686\u06c1'                         # expense
_GROSS = '\u062e\u0627\u0645'                                 # gross
_ESTIMATED = '\u0627\u0646\u062f\u0627\u0632\u06c1'           # estimated
_WAIVE = '\u0645\u0639\u0627\u0641'                          # waive-off
_PURCHASE = '\u062e\u0631\u06cc\u062f\u0627\u0631\u06cc'       # purchase
_COST = '\u0644\u0627\u06af\u062a'                            # cost
_DIRECT = '\u0628\u0631\u0627\u06c1 \u0631\u0627\u0633\u062a'   # direct
_SALES = '\u0641\u0631\u0648\u062e\u062a'                     # sales
_SPENT = '\u062e\u0631\u0686'                                 # spent
_RECORDS = '\u0631\u06cc\u06a9\u0627\u0631\u0688\u0632'        # records
_SETTLED = '\u062a\u0633\u0648\u06cc\u06c1'                   # settled

LABELS = {
    # document titles
    'SUPPLIER LEDGER': 'سپلائر لیجر',
    'CLIENT LEDGER': 'گاہک لیجر',
    'FINANCIAL LEDGER': 'مالی لیجر',
    'RECEIPT': 'رسید',
    'INVOICE': 'انوائس',
    'BOOKING': 'بکنگ',
    'LEDGER': 'لیجر',
    'Client Clearance / Outstanding Statement': 'گاہک کلیئرنس / بقایا اسٹیٹمنٹ',
    'Full Client History PDF': 'گاہک کی ' + '\u0645\u06a9\u0645\u0644 ' + '\u06c1\u0633\u0679\u0631\u06cc',
    # parties
    'Client Name': 'گاہک کا نام',
    'Client Code': 'گاہک کوڈ',
    'Client': 'گاہک',
    'Customer': 'گاہک',
    'Supplier Account': 'سپلائر اکاؤنٹ',
    'Supplier Ledger Bill': 'سپلائر لیجر بل',
    'Supplier Material Amount': 'سپلائر میٹیریل رقم',
    'Supplier Paid / Remaining': 'سپلائر ' + _ADA_SHUDA + ' / بقایا',
    'Supplier': 'سپلائر',
    'Associated Party': 'متعلقہ فریق',
    'Received From': 'وصول کنندہ سے',
    'Recipient / Charge': 'وصول کنندہ / ' + _CHARGE,
    'Delivery Person': 'ڈلیوری پرسن',
    'Bill To': 'بل برائے',
    # references / dates
    'Bill No': 'بل نمبر',
    'Bill #': 'بل نمبر',
    'Bill/Nimbus': 'بل / نمبس',
    'Bill': 'بل',
    'Bill value': 'بل کی رقم',
    'Date/Time': 'تاریخ / وقت',
    'Date': 'تاریخ',
    'Time': 'وقت',
    'Reference': 'حوالہ',
    'Statement No.': 'اسٹیٹمنٹ نمبر',
    'GENERATED': 'بنایا گیا',
    'PERIOD': 'مدت',
    'STATEMENT NO.': 'اسٹیٹمنٹ نمبر',
    'Period in': 'مدت سے',
    'Period out': 'مدت تک',
    'Start of period': 'مدت کا آغاز',
    # money columns
    'Amount Received': 'وصول شدہ رقم',
    'Total Cash Actually Paid': 'کل نقد ' + _ADA_SHUDA,
    'Total Actual Purchase Cost': 'کل اصل ' + _PURCHASE + ' ' + _COST,
    'Total Bill': 'کل بل',
    'Total Due': 'کل واجب الادا',
    'Total Paid': 'کل ' + _ADA_SHUDA,
    'Total Pending': 'کل زیر التوا',
    'Total Received': 'کل وصولی',
    'Total credit': 'کل ' + _CREDIT,
    'Total debit': 'کل ' + _DEBIT,
    'Amount': 'رقم',
    'Paid Now': 'ابھی ' + _ADA_SHUDA,
    'Paid': _ADA_SHUDA,
    'Pending / Paid Bills': 'زیر التوا / ' + _ADA_SHUDA + ' بل',
    'Pending Bills': 'زیر التوا بل',
    'Unpaid bills': 'غیر ' + _ADA_SHUDA + ' بل',
    'Pending': 'زیر التوا',
    'Remaining Balance': 'بقایا رقم',
    'Remaining': 'بقایا',
    'Due': 'واجب الادا',
    'Net Pending': 'خالص زیر التوا',
    'Previous Balance': 'پچھلا بقایا',
    'Current Balance': 'موجودہ بقایا',
    'Closing Balance': 'اختتامی بقایا',
    'Closing balance': 'اختتامی بقایا',
    'Closing': 'اختتام',
    'Balance Summary': 'بقایا کا خلاصہ',
    'Balance': 'بقایا',
    'Debit': _DEBIT,
    'Credit': _CREDIT,
    'DEBIT': _DEBIT,
    'CREDIT': _CREDIT,
    'BALANCE': 'بقایا',
    'Total': 'کل',
    'Totals (transfers are not income or expense)': 'کل (' + _TRANSFERS + ' آمدنی یااخراجات نہیں)',
    'Totals for period (closing balance)': 'مدت کے کل (اختتامی بقایا)',
    'Total Bookings': 'کل بکنگز',
    'Total Direct Sales': 'کل ' + _DIRECT + ' ' + _SALES,
    'Total Received (IN)': 'کل وصولی (ان)',
    'Total Sent (OUT)': 'کل بھیجے (آؤٹ)',
    'Total Spent': 'کل ' + _SPENT,
    'Total Waive-Off': 'کل ' + _WAIVE,
    'GRN Costs Billed to Supplier': 'سپلائر کو GRN ' + _COST + ' کے بل',
    # items
    'Description / Material': 'تفصیل / میٹیریل',
    'Description': 'تفصیل',
    'PARTICULARS': 'تفصیلات',
    'Material Ledger': 'میٹیریل لیجر',
    'Material Transaction Ledger': 'میٹیریل ٹرانزیکشن لیجر',
    'Material Delivery Summary': 'میٹیریل ڈیلیوری کا خلاصہ',
    'Materials Booked': 'میٹیریلز بک ' + _KIYA_GAYA,
    'Materials Delivered': _DELIVERED + ' میٹیریلز',
    'Material Brand': 'میٹیریل برانڈ',
    'Material': 'میٹیریل',
    'Item': 'آئٹم',
    'Items': 'آئٹمز',
    'Qty Added': 'مقدار شامل ' + _KIYA_GAYA,
    'Qty Delivered': 'مقدار ' + _DELIVERED,
    'Delivered qty': _DELIVERED + ' مقدار',
    'Dispatched': 'بھیجا گیا',
    'Delivered': _DELIVERED,
    'Remaining qty': 'بقایا مقدار',
    'Remaining Stock': 'بقایا ' + _STOCK,
    'Remaining stock value': 'بقایا ' + _STOCK + ' کی قیمت',
    'Remaining value': 'بقایا قیمت',
    'Qty': 'مقدار',
    'QTY': 'مقدار',
    'Rate': 'ریٹ',
    'RATE': 'ریٹ',
    'Booked rate': 'بک ' + _KIYA_GAYA + ' ریٹ',
    'AMOUNT': 'رقم',
    'ACCOUNT': 'اکاؤنٹ',
    'DATE': 'تاریخ',
    'REFERENCE': 'حوالہ',
    'Price': 'قیمت',
    # payment details
    'Payment Type': 'ادائیگی کی قسم',
    'Payment Details': 'ادائیگی کی تفصیلات',
    'Payment Received': 'وصول شدہ ادائیگی',
    'Method': 'طریقہ',
    'Bank / details': 'بینک / تفصیلات',
    'Bank Amount': 'بینک رقم',
    'Bank account': 'بینک اکاؤنٹ',
    'Bank': 'بینک',
    'Account Name': 'اکاؤنٹ کا نام',
    'Account': 'اکاؤنٹ',
    'Cash Amount (in hand)': 'نقد رقم (ہاتھ میں)',
    'Cash account': 'نقد اکاؤنٹ',
    'Physical Cash': 'طبیعی نقد',
    'Card': 'کارڈ',
    'Vehicle Fare': _VEHICLE_FARE,
    'Unloading': _UNLOADING,
    'Loading': _LOADING,
    'Other Charges': 'دیگر ' + _CHARGES,
    'Gain': 'منافع',
    'Expense / loss': _EXPENSE + ' / ' + _LOSS,
    'Revenue': 'آمدنی',
    'Profit / loss': 'منافع / ' + _LOSS,
    'Profit': 'منافع',
    'Gross profit': _GROSS + ' ' + 'منافع',
    'Estimated profit': _ESTIMATED + ' ' + 'منافع',
    'Margin': 'مارجن',
    'Net margin': 'خالص مارجن',
    # misc fields
    'Status': 'حالت',
    'Reason / Note': 'وجہ / نوٹ',
    'Reason': 'وجہ',
    'Void Reason': 'باطل ' + _KIYA_GAYA,
    'Notes': 'نوٹس',
    'Note': 'نوٹ',
    'Action': 'عمل',
    'Actions': 'اعمال',
    'Type / ref': 'قسم / حوالہ',
    'Type': 'قسم',
    'Category': 'زمرہ',
    'Name': 'نام',
    'Address': 'پتہ',
    'Phone': 'فون',
    'ID': 'شناختی نمبر',
    'Transaction Ledger': 'ٹرانزیکشن لیجر',
    'Financial Transaction Ledger': 'مالی ٹرانزیکشن لیجر',
    'Transaction Details': 'ٹرانزیکشن کی تفصیلات',
    'DETAILED TRANSACTION LOG': 'تفصیلی ٹرانزیکشن لاگ',
    'TRANSACTIONS': 'ٹرانزیکشنز',
    'Client Summary': 'گاہک کا خلاصہ',
    'Balance brought forward': 'آگے لایا گیا بقایا',
    'Payable to supplier': 'سپلائر کو قابل ادائیگی',
    'Advance paid to supplier': 'سپلائر کو پیشگی ' + _ADA_SHUDA,
    'Settled': _SETTLED,
    'Company Stamp': 'کمپنی مہر',
    'Receiver / Authorized Sign': 'وصول کنندہ / مجاز دستخط',
    'Authorized Sign': 'مجاز دستخط',
    'Attachments': 'منسلکات',
    'No records': 'کوئی ' + _RECORDS + ' نہیں',
    'Active': 'فعال',
    'Voided': 'باطل ' + _KIYA_GAYA,
    'Added': 'شامل ' + _KIYA_GAYA,
    'Consumed': 'استعمال ' + _KIYA_GAYA,
    'Received only': 'صرف ' + 'وصولی',
    'Spent only': 'صرف ' + _SPENT + ' ' + _KIYA_GAYA,
    'Transfer': _TRANSFER,
    'Transfers': _TRANSFERS,
    'Next Day Opening': 'اگلے دن کا افتتاح',
    'Download PDF': 'PDF ' + _DOWNLOAD,
    'Go Back': 'واپس جائیں',
    'Print': 'پرنٹ',
    'Save': 'محفوظ ' + _KIYA_GAYA,
    'Close': 'بند ' + _KIYA_GAYA,
}

# --- sanity filter ---------------------------------------------------------
# Keep only entries whose Urdu value is purely Arabic-script (plus digits,
# punctuation and a small whitelist of Latin document tokens).  This makes it
# impossible for a stray non-Urdu token to leak into a generated PDF.
_ALLOWED_LATIN = ('GRN', 'PDF', 'FIFO', 'AMS', 'ID', 'IN', 'OUT')
_BAD_CHARS = re.compile(r'[^\u0600-\u06FF\uFB50-\uFEFF0-9 \u060C\u061B\u061F/()#.,+\-]')


def _is_clean_urdu(value: str) -> bool:
    if not any('\u0600' <= ch <= '\u06ff' for ch in value):
        return False
    probe = value
    for tok in _ALLOWED_LATIN:
        probe = probe.replace(tok, '')
    return _BAD_CHARS.search(probe) is None


LABELS = {en: ur for en, ur in LABELS.items() if _is_clean_urdu(ur)}

_LABEL_ITEMS = sorted(LABELS.items(), key=lambda kv: len(kv[0]), reverse=True)

_MARKER = '<!--ams-bilingual-v1-->'

_TAG_RE = re.compile(r'(<[^>]+>)')


# One alternation of all labels (longest first) so a single-pass substitution
# never re-matches text inside an Urdu span we just inserted.  A label only
# counts as a *label* when it is the whole text segment or is followed by a
# colon - free text such as notes, party or material names is never touched.
_LABEL_PATTERN = re.compile(
    r'(?<![A-Za-z0-9])('
    + '|'.join(re.escape(en) for en, _ in _LABEL_ITEMS)
    + r')(?![A-Za-z0-9])(?=\s*:?\s*$|\s*:)'
)


def _translate_text_segment(segment: str) -> str:
    """Replace known English labels inside a plain-text HTML segment."""
    if not segment or 'class="ur"' in segment:
        return segment
    if not _LABEL_ITEMS:
        return segment

    def _sub(match):
        en = match.group(1)
        ur = LABELS[en]
        return en + '<span class="ur" lang="ur" dir="rtl">' + ur + '</span>'

    return _LABEL_PATTERN.sub(_sub, segment)


def inject_urdu_labels(html: str) -> str:
    """Insert Urdu ``<span class="ur">`` translations next to English labels.

    Only text nodes are touched — tag markup, ``<style>``/``<script>``
    contents and existing Urdu spans are left alone, and the operation is
    idempotent (a marker comment prevents double injection).
    """
    if not html:
        return html
    if _MARKER in html:
        return html
    parts = _TAG_RE.split(html)
    in_skip_content = False   # inside <style>/<script>
    result = []
    for part in parts:
        if part.startswith('<') and part.endswith('>'):
            tag = part[1:-1].strip().lower()
            if tag.startswith('style') or tag.startswith('script'):
                if not tag.endswith('/'):
                    in_skip_content = True
            elif tag.startswith('/style') or tag.startswith('/script'):
                in_skip_content = False
            result.append(part)
        else:
            if in_skip_content:
                result.append(part)
            else:
                result.append(_translate_text_segment(part))
    return _MARKER + ''.join(result)


# --------------------------------------------------------------------------
# CSS for the WeasyPrint path (and for browser print previews)
# --------------------------------------------------------------------------

def bilingual_css() -> str:
    """``@font-face`` + ``.ur`` rules for the bundled Jameel Noori font."""
    file_url = 'file://' + JAMEEL_NOORI_TTF.replace(os.sep, '/')
    return (
        '<style id="ams-bilingual-css">'
        '@font-face {'
        f'  font-family: "{URDU_FONT_FAMILY}";'
        '  src: url("/static/fonts/JameelNooriNastaleeq.ttf") format("truetype"),'
        f'       url("{file_url}") format("truetype");'
        '  font-weight: normal; font-style: normal;'
        '}'
        '.ur {'
        f'  font-family: "{URDU_FONT_FAMILY}", "Noto Nastaliq Urdu", serif;'
        '  direction: rtl; unicode-bidi: embed;'
        '  font-size: 0.92em; padding-inline-start: 2px;'
        '}'
        '.ur::before { content: " / "; direction: ltr; unicode-bidi: embed; '
        '  font-family: inherit; color: #6b7280; }'
        '</style>'
    )


def apply_bilingual(html: str) -> str:
    """Return *html* ready for dual-language PDF rendering.

    Injects the Jameel Noori ``@font-face`` CSS and Urdu label spans.  Safe to
    call on any rendered template; idempotent.
    """
    if not html:
        return html
    if _MARKER in html:
        return html
    return bilingual_css() + inject_urdu_labels(html)
