"""English / Urdu PDF support.

Non-bill exports use the legacy dual-language layer: the original English text
plus Urdu translations rendered in the Jameel Noori Nastaleeq font (bundled at
``static/fonts/JameelNooriNastaleeq.ttf``).  Bills and receipts instead use the
single-language helpers at the bottom of this module so each document is either
fully English or fully Urdu, never a mixed bilingual receipt.

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

import html as html_lib
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
_no_hb = False           # set once uharfbuzz is known to be missing
_font_em = 2048.0        # units-per-em of the bundled face
_font_line_ratio = 1.40  # (ascent + |descent|) / upem, for Paragraph leading

# Nastaleeq has far more width per character than a Latin face.  A label set
# next to its English original at the same nominal size therefore measures
# roughly ``URDU_WIDTH_FACTOR`` times wider, so the ReportLab paths render it
# proportionally smaller.  Measured empirically against Jameel Noori.
URDU_WIDTH_FACTOR = 2.6


def urdu_font_available() -> bool:
    return os.path.exists(JAMEEL_NOORI_TTF)


def _font_metrics() -> None:
    """Load the real ascent/descent from the bundled font (best effort).

    ReportLab's TTFont reports ascent/descent as *fractions* of the em for
    fonts whose OS/2 table claims more than one em of line height, which made
    every Nastaleeq paragraph ``leading`` crush the glyphs onto each other.
    The values are read straight from ``hhea`` inside the shaped-font cache
    builder instead, so the shapes below are correct on every install.
    """
    global _font_em, _font_line_ratio
    try:
        from fontTools.ttLib import TTFont
        tt = TTFont(JAMEEL_NOORI_TTF, lazy=True)
        em = float(tt['head'].unitsPerEm) or 2048.0
        hhea = tt['hhea']
        _font_em = em
        _font_line_ratio = (hhea.ascent - hhea.descent) / em
        tt.close()
    except Exception:
        pass


def urdu_line_factor(font_size: float) -> float:
    """``leading`` for a Nastaleeq run at *font_size* with no clipped marks."""
    _font_metrics()
    return max(font_size * _font_line_ratio, font_size * 1.25)


# Nastaleeq sits low on the baseline and its x-height is small, so a
# translation set at exactly the Latin point size reads as an illegible
# squiggle.  Slightly larger keeps it legible without dominating the line.
URDU_SIZE_FACTOR = 1.08


def urdu_size_for_html(font_size: float) -> float:
    """ReportLab ``<font size>`` value used for an Urdu run.

    ``<font size="N">`` in ReportLab takes an absolute point size, so the
    Latin size is scaled by :data:`URDU_SIZE_FACTOR` and clamped to a floor
    that is still readable in a printed A5 document.
    """
    size = max(float(font_size or 0) * URDU_SIZE_FACTOR, 5.4)
    return round(size, 2)


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
    global _hb_face, _hb_font, _no_hb
    if _hb_font is not None:
        return _hb_font
    if _no_hb or not urdu_font_available():
        return None
    try:
        import uharfbuzz as hb
        with open(JAMEEL_NOORI_TTF, 'rb') as fh:
            data = fh.read()
        _hb_face = hb.Face(data)
        _hb_font = hb.Font(_hb_face)
        return _hb_font
    except Exception:
        _no_hb = True
        return None


def _hb_shape(text: str):
    """HarfBuzz shape of *text*, or ``None`` when uharfbuzz is unavailable."""
    font = _hb()
    if font is None:
        return None
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
        return None


# --- fontTools fallback shaping -------------------------------------------
# Some hosts cannot install uharfbuzz (no wheel for the interpreter/ARM
# build).  The old code then handed arabic_reshaper's Presentation-Forms
# output to ReportLab, but the bundled Jameel Noori face has *no* glyphs for
# those codepoints - the Urdu silently vanished from the PDF.  The path below
# applies the font's own GSUB rules with fontTools instead and maps the result
# through the same private-use cmap the HarfBuzz path uses, so both engines
# produce identical glyph ids.

_FALLBACK_FONT = None


def _gsub_lookups_for_lang(tt, script_tag='arab', lang_tag='URD '):
    """Lookup indices to apply for Urdu, in the order the font declares them."""
    gsub = tt['GSUB'].table
    scripts = {r.ScriptTag: r.Script for r in gsub.ScriptList.ScriptRecord}
    script = scripts.get(script_tag)
    if script is None:
        return []
    langsys = None
    for rec in (getattr(script, 'LangSysRecord', None) or []):
        if rec.LangSysTag == lang_tag:
            langsys = rec.LangSys
            break
    if langsys is None:
        langsys = script.DefaultLangSys
    if langsys is None:
        return []
    features = {i: fr for i, fr in enumerate(gsub.FeatureList.FeatureRecord)}
    # OpenType applies the Arabic shaping features in this fixed order - the
    # feature *list* order inside the font is arbitrary (this face stores
    # fina before init), so it must not be relied on.
    wanted = ('ccmp', 'isol', 'fina', 'fin2', 'fin3', 'medi', 'med2',
              'init', 'rlig', 'rclt', 'calt')
    used, indices = set(), []
    active = {features[fi].FeatureTag: features[fi].Feature
              for fi in (langsys.FeatureIndex or [])
              if fi in features}
    for tag in wanted:
        feature = active.get(tag)
        if feature is None:
            continue
        for idx in (feature.LookupListIndex or []):
            if idx not in used:
                used.add(idx)
                indices.append(idx)
    return indices


def _fallback_font():
    """Lazily loaded shaping tables: (TTFont, glyph order map, features)."""
    global _FALLBACK_FONT
    if _FALLBACK_FONT is not None:
        return _FALLBACK_FONT or None
    if not urdu_font_available():
        _FALLBACK_FONT = False
        return None
    try:
        from fontTools.ttLib import TTFont
        tt = TTFont(JAMEEL_NOORI_TTF)
        gid = {name: i for i, name in enumerate(tt.getGlyphOrder())}
        gsub = tt['GSUB'].table
        by_tag = {}
        for record in gsub.FeatureList.FeatureRecord:
            by_tag.setdefault(record.FeatureTag, []).extend(
                record.Feature.LookupListIndex or [])
        shapes = {}
        for tag in ('isol', 'init', 'medi', 'fina', 'ccmp'):
            mapping = {}
            for idx in by_tag.get(tag, []):
                for raw in (gsub.LookupList.Lookup[idx].SubTable or []):
                    sub = _unwrap(raw)
                    if getattr(sub, 'mapping', None):
                        mapping.update(sub.mapping)
            shapes[tag] = mapping
        order = [i for i in by_tag.get('rlig', []) + by_tag.get('calt', [])]
        _FALLBACK_FONT = (tt, gid, shapes, order)
        return _FALLBACK_FONT
    except Exception:
        _FALLBACK_FONT = False
        return None


def _unwrap(sub):
    """Resolve an Extension (lookup type 7) subtable to its real self."""
    if type(sub).__name__ == 'ExtensionSubst':
        return sub.ExtSubTable
    return sub


def _cov_has(cov, glyph):
    glyphs = getattr(cov, 'glyphs', None) if cov is not None else None
    return bool(glyphs) and glyph in glyphs


def _match_ligature(sub, glyphs, i):
    """(ligature glyph name, consumed length) for the longest match at *i*."""
    options = (getattr(sub, 'ligatures', None) or {}).get(glyphs[i])
    if not options:
        return None
    best = None
    for lig in options:
        comps = list(getattr(lig, 'Component', None) or [])
        span = len(comps) + 1
        if i + span > len(glyphs):
            continue
        if span > 1 and glyphs[i + 1:i + span] != comps:
            continue
        if best is None or span > best[1]:
            best = (lig.LigGlyph, span)
    return best


def _chain_matches(sub, glyphs, i):
    """True when the chaining-context rule at *i* applies."""
    back_covs = getattr(sub, 'BacktrackCoverage', None) or []
    back_counts = getattr(sub, 'Backtrack', None) or []
    pos = 0
    for k, cov in enumerate(back_covs):
        count = back_counts[k] if k < len(back_counts) else 1
        for _ in range(max(1, count)):
            pos += 1
            if i - pos < 0 or not _cov_has(cov, glyphs[i - pos]):
                return False
    in_covs = getattr(sub, 'InputCoverage', None) or []
    if not in_covs or not _cov_has(in_covs[0], glyphs[i]):
        return False
    in_counts = getattr(sub, 'Input', None) or []
    pos = 0
    for k, cov in enumerate(in_covs[1:]):
        count = in_counts[k + 1] if k + 1 < len(in_counts) else 1
        for _ in range(max(1, count)):
            pos += 1
            if i + pos >= len(glyphs) or not _cov_has(cov, glyphs[i + pos]):
                return False
    look_covs = getattr(sub, 'LookAheadCoverage', None) or []
    look_counts = getattr(sub, 'LookAhead', None) or []
    pos = len(in_covs)
    offset = 0
    for k, cov in enumerate(look_covs):
        count = look_counts[k] if k < len(look_counts) else 1
        for _ in range(max(1, count)):
            offset += 1
            if i + pos + offset - 1 >= len(glyphs):
                return False
            if not _cov_has(cov, glyphs[i + pos + offset - 1]):
                return False
    return True


def _run_lookup(tt, lookup_index, glyphs, position):
    """Apply one nested lookup at *position*; returns the new glyph list."""
    lookups = tt['GSUB'].table.LookupList.Lookup
    if lookup_index >= len(lookups) or position >= len(glyphs):
        return glyphs
    for raw in (lookups[lookup_index].SubTable or []):
        sub = _unwrap(raw)
        kind = type(sub).__name__
        if kind == 'SingleSubst':
            mapping = getattr(sub, 'mapping', None) or {}
            if glyphs[position] in mapping:
                glyphs[position] = mapping[glyphs[position]]
            return glyphs
        if kind == 'LigatureSubst':
            match = _match_ligature(sub, glyphs, position)
            if match:
                lig, span = match
                glyphs[position:position + span] = [lig]
                return glyphs
        if kind == 'MultipleSubst':
            seq = (getattr(sub, 'mapping', None) or {}).get(glyphs[position])
            if seq:
                glyphs[position:position + 1] = list(seq)
                return glyphs
    return glyphs


def _apply_subtable_at(tt, subtables, glyphs, i):
    """Try each subtable at position *i*; True when one applied."""
    for sub in subtables:
        kind = type(sub).__name__
        if kind == 'SingleSubst':
            mapping = getattr(sub, 'mapping', None) or {}
            if glyphs[i] in mapping:
                glyphs[i] = mapping[glyphs[i]]
                return True
        elif kind == 'LigatureSubst':
            match = _match_ligature(sub, glyphs, i)
            if match:
                lig, span = match
                glyphs[i:i + span] = [lig]
                return True
        elif kind == 'MultipleSubst':
            seq = (getattr(sub, 'mapping', None) or {}).get(glyphs[i])
            if seq:
                glyphs[i:i + 1] = list(seq)
                return True
        elif kind == 'ChainContextSubst':
            if not _chain_matches(sub, glyphs, i):
                continue
            for rec in (sub.SubstLookupRecord or []):
                if rec.SequenceIndex == 0:
                    _run_lookup(tt, rec.LookupListIndex, glyphs, i)
            return True
    return False


def _apply_gsub(tt, glyphs, lookup_indices):
    """Apply GSUB lookups over a glyph-name list.

    A single lookup can hold subtables of different types (this face mixes
    SingleSubst and ChainContextSubst), so dispatch happens per subtable.
    """
    lookups = tt['GSUB'].table.LookupList.Lookup
    for idx in lookup_indices:
        if idx >= len(lookups):
            continue
        subtables = [_unwrap(raw) for raw in (lookups[idx].SubTable or [])]
        i = 0
        while i < len(glyphs):
            _apply_subtable_at(tt, subtables, glyphs, i)
            i += 1
    return glyphs


# --- Arabic joining analysis ---------------------------------------------

def _is_transparent(ch):
    """Combining marks / join controls that must not break a joining run."""
    import unicodedata
    return unicodedata.category(ch) == 'Mn' or ch in '\u200c\u200d'


def _joining_forms(chars, cmap, shapes):
    """Per-character OpenType form (isol/init/medi/fina) for an Arabic run.

    Joining behaviour is read from the font itself: a character can connect to
    the *left* only when it has an initial or medial form, and to the *right*
    only when it has a final or medial form.  Deriving it that way keeps
    right-joining letters (ا د ر و ...) correct without a hard-coded list.
    """
    def glyph(ch):
        return cmap.get(ord(ch))

    def links_next(ch):
        g = glyph(ch)
        return g is not None and (g in shapes['init'] or g in shapes['medi'])

    def links_prev(ch):
        g = glyph(ch)
        return g is not None and (g in shapes['fina'] or g in shapes['medi'])

    forms, n = [], len(chars)
    for i, ch in enumerate(chars):
        if _is_transparent(ch):
            forms.append('ccmp')
            continue
        if glyph(ch) is None:
            forms.append(None)
            continue
        left = i - 1
        while left >= 0 and _is_transparent(chars[left]):
            left -= 1
        joined_left = (left >= 0 and links_next(chars[left])
                       and links_prev(ch))
        right = i + 1
        while right < n and _is_transparent(chars[right]):
            right += 1
        joined_right = (right < n and links_prev(chars[right])
                        and links_next(ch))
        if joined_left and joined_right:
            forms.append('medi')
        elif joined_left:
            forms.append('fina')
        elif joined_right:
            forms.append('init')
        else:
            forms.append('isol')
    return forms


def _shape_with_fonttools(text: str):
    """Fallback shaper: returns PUA glyph ids in visual order, or ``None``.

    Mirrors what a shaping engine does, using only fontTools:

    1. ``ccmp`` - character composition (spaces, marks, ZWJ handling)
    2. ``isol`` / ``init`` / ``medi`` / ``fina`` - cursive joining forms,
       chosen by the joining analysis in :func:`_joining_forms`
    3. ``rlig`` + ``calt`` - required and contextual ligatures
    4. reverse the logical run, because ReportLab draws left-to-right

    HarfBuzz produces more refined ligature choices (it can look further ahead
    than this simplified walker), so it stays the preferred engine; this path
    guarantees Urdu is still *legible* where the uharfbuzz wheel is missing.
    """
    loaded = _fallback_font()
    if not loaded:
        return None
    tt, gid, shapes, order = loaded
    try:
        cmap = tt.getBestCmap()
        chars = list(text)
        glyphs = []
        for ch, form in zip(chars, _joining_forms(chars, cmap, shapes)):
            name = cmap.get(ord(ch))
            if name is None or form is None:
                continue
            name = shapes['ccmp'].get(name, name)
            if form != 'ccmp':
                name = shapes[form].get(name, name)
            glyphs.append(name)
        if not glyphs:
            return None
        glyphs = _apply_gsub(tt, glyphs, order)
        out = []
        for name in reversed(glyphs):
            g = gid.get(name)
            if g is not None:
                out.append(chr(_PUA_BASE + g))
        return ''.join(out) or None
    except Exception:
        return None


def _arabic_reshaper_shape(text: str):
    """Last resort: Presentation-Forms text (needs a font that has them)."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return None


def shape_urdu(text: str) -> str:
    """Shape Arabic-script text so ReportLab draws correct Nastaleeq glyphs.

    Order of preference:

    1. **HarfBuzz** (``uharfbuzz``) — full OpenType shaping by the font's own
       GSUB rules; each glyph id becomes the private-use codepoint
       ``U+F0000+gid`` that the shaped-font cmap resolves.
    2. **fontTools GSUB walker** — the same rules applied in pure Python, for
       hosts where the ``uharfbuzz`` wheel does not exist.  Without this the
       previous code fell to arabic_reshaper, whose Presentation-Forms output
       this Nastaleeq face has *no glyphs for*, so the Urdu disappeared.
    3. **arabic_reshaper + python-bidi** — retained only for alphabets whose
       face genuinely carries Presentation-Forms glyphs.
    4. Raw text, if nothing else is available.
    """
    if not text:
        return text
    shaped = _hb_shape(text)
    if shaped is not None:
        return shaped
    shaped = _shape_with_fonttools(text)
    if shaped is not None:
        return shaped
    shaped = _arabic_reshaper_shape(text)
    if shaped is not None:
        return shaped
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
_BAGS = '\u0628\u0648\u0631\u06cc\u0627\u06ba'                       # bags
_KG = '\u06a9\u06cc \u062c\u06cc'                            # kg
_LABOUR = '\u0645\u0632\u062f\u0648\u0631\u06cc'                        # labour

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
    # --- receipt / statement furniture ---------------------------------
    # These labels were previously left untranslated, so a "bilingual" PDF
    # still showed English-only headings such as "Current Bill Total:".
    'Sign Here': 'یہاں دستخط کریں',
    'Stamp Here': 'یہاں مہر لگائیں',
    'Bags': _BAGS,
    'Bag': _BAGS,
    'Kg': _KG,
    'KG': _KG,
    'Labor': _LABOUR,
    'Labour': _LABOUR,
    'Account No.': 'اکاؤنٹ نمبر',
    'Account Statement For': 'اکاؤنٹ اسٹیٹمنٹ برائے',
    'Actual Purchase Cost & Payments': 'اصل ' + _PURCHASE + ' ' + _COST + ' اور ادائیگیاں',
    'Additional Charges Paid / Remaining': 'اضافی ' + _CHARGES + ' ' + _ADA_SHUDA + ' / بقایا',
    'Advance with us': 'ہمارے پاس پیشگی',
    'Audit row': 'آڈٹ سطر',
    'Average Actual Cost / Unit': 'اوسط اصل ' + _COST + ' فی یونٹ',
    'Bill Pending:': 'بقایا بل:',
    'Bill value': 'بل کی رقم',
    'Cleared': 'کلیئر',
    'Clearance Statement': 'کلیئرنس اسٹیٹمنٹ',
    'Client Full History': 'گاہک کی ' + '\u0645\u06a9\u0645\u0644 ' + '\u06c1\u0633\u0679\u0631\u06cc',
    'Client Ledger': 'گاہک لیجر',
    'Complete Receipts Section': 'مکمل رسیدوں کا حصہ',
    'Code': 'کوڈ',
    'Current Bill Total:': 'موجودہ بل کا کل:',
    'Delivery Persons': 'ڈلیوری پرسنز',
    'Discount': 'رعایت',
    'EXTERNAL LINK': 'بیرونی لنک',
    'Financial Ledger': 'مالی لیجر',
    'GOODS RECEIVED': 'موصول شدہ مال',
    'Generated': 'بنایا گیا',
    'Generated By': 'بنانے والا',
    'MATERIAL RETURN': 'میٹیریل واپسی',
    'MB': 'مینول بل',
    'No active pending/paid bill rows found.': 'کوئی فعال زیر التوا یا ' + _ADA_SHUDA + ' بل نہیں ملا۔',
    'No financial transaction records found.': 'کوئی مالی ٹرانزیکشن ' + _RECORDS + ' نہیں ملا۔',
    'No financial transactions found.': 'کوئی مالی ٹرانزیکشن نہیں ملا۔',
    'Outstanding': 'بقایا',
    'Outstanding Balance': 'بقایا رقم',
    'Recent financial activity': 'حالیہ مالی سرگرمی',
    'No material transaction records found.': 'کوئی میٹیریل ٹرانزیکشن ' + _RECORDS + ' نہیں ملا۔',
    'No printable receipts found for this client.': 'اس گاہک کے لیے کوئی قابلِ پرنٹ رسید نہیں ملی۔',
    'No transactions found.': 'کوئی ٹرانزیکشن نہیں ملا۔',
    'No unpaid bills.': 'کوئی غیر ' + _ADA_SHUDA + ' بل نہیں۔',
    'Note:': 'نوٹ:',
    'Opening Balance': 'ابتدائی بقایا',
    'Original': 'اصل',
    'Outstanding': 'بقایا',
    'Paid Amount:': 'ادا شدہ رقم:',
    'Payment Obligations & History': 'ادائیگی کی ذمہ داریاں اور تاریخ',
    'Please pay': 'براہِ کرم ادائیگی کریں',
    'Please settle the outstanding amount to clear this account.':
        'اس اکاؤنٹ کو کلیئر کرنے کے لیے براہِ کرم بقایا رقم ادا کریں۔',
    'Prev. Stock': 'پچھلا ' + _STOCK,
    'Previous Balance Pending:': 'پچھلا بقایا:',
    'Previous Balance:': 'پچھلا بقایا:',
    'Receipt:': 'رسید:',
    'Recent financial activity': 'حالیہ مالی کارروائی',
    'Supplier Invoice #': 'سپلائر ' + '\u0627\u0646\u0648\u0627\u0626\u0633' + ' نمبر',
    'Supplier Ledger': 'سپلائر لیجر',
    'Total (Previous + Current):': 'کل (پچھلا + موجودہ):',
    'Total Due (Carry Forward):': 'کل واجب الادا (آگے منتقل):',
    'Total Outstanding Balance:': 'کل بقایا رقم:',
    'UPLOADED PHOTO': 'اپ لوڈ شدہ تصویر',
    'Unpaid bills': 'غیر ' + _ADA_SHUDA + ' بل',
    'View Full Size': 'پوری تصویر دیکھیں',
    'via': 'بذریعہ',

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
_BAD_CHARS = re.compile(
    r'[^\u0600-\u06FF\uFB50-\uFEFF0-9 \u060C\u061B\u061F/()#.,+\-:;%]')


def _is_clean_urdu(value: str) -> bool:
    if not any('\u0600' <= ch <= '\u06ff' for ch in value):
        return False
    probe = value
    for tok in _ALLOWED_LATIN:
        probe = probe.replace(tok, '')
    return _BAD_CHARS.search(probe) is None


LABELS = {en: ur for en, ur in LABELS.items() if _is_clean_urdu(ur)}

# Templates render "Code:" / "Bill Pending:" with the colon in the markup while
# the dictionary stores the bare label.  Dropping the colon from the keys means
# the longest-match alternation can never pick a colon variant that hits no
# entry, so the specific translation wins.  The values lose the same colon:
# the punctuation already comes from the template, so keeping it here printed
# "Current Bill Total: موجودہ بل کا کل::".
LABELS = {(en.rstrip(':').strip() or en): ur.rstrip(':').strip() or ur
          for en, ur in LABELS.items()}
# Templates are scanned as *rendered* HTML, where "&" appears as "&amp;".  The
# dictionary is keyed on the plain character, so unescape any entity left in a
# label name (``Actual Purchase Cost &amp; Payments``) before matching.
LABELS = {(html_lib.unescape(en)): ur for en, ur in LABELS.items()}
LABELS = dict(sorted(LABELS.items(), key=lambda kv: len(kv[0]), reverse=True))

# Alternation order must put the longest label first, otherwise "Total" would
# win over "Total Due" and "Amount" over "Paid Amount:".
_LABEL_ITEMS = sorted(LABELS.items(), key=lambda kv: len(kv[0]), reverse=True)
_LABEL_NAMES = [en for en, _ in _LABEL_ITEMS]

_MARKER = '<!--ams-bilingual-v1-->'

_TAG_RE = re.compile(r'(<[^>]+>)')


# One alternation of all labels (longest first) so a single-pass substitution
# never re-matches text inside an Urdu span we just inserted.  A label only
# counts as a *label* when it is the whole text segment or is followed by a
# colon - free text such as notes, party or material names is never touched.
_LABEL_PATTERN = re.compile(
    r'(?<![A-Za-z0-9])('
    # longest first, so "Total Due" is preferred over "Total" and "Paid
    # Amount:" over "Amount".  ``re`` alternation is first-match-wins.
    # ``&`` is written as ``&amp;`` inside rendered HTML, so allow either form
    # for any ampersand inside a label.
    + '|'.join(re.escape(en).replace(r'\&', '(?:&|&amp;)')
               for en in sorted(_LABEL_NAMES, key=len, reverse=True))
    # A label ends at a tag/entity/end of text, or is followed by a colon.
    # A colon is an unambiguous label terminator in these templates
    # ("Outstanding: Rs 350,000.00"), so text may follow it; without the colon
    # only a number/dash may follow ("Amount 12"), which keeps free text such
    # as "Booking: OPC CEMENT" from being mistaken for a label.  The colon
    # branch is listed FIRST so "<strong>Client:</strong>" still matches.
    + r')(?![A-Za-z0-9])(?=\s*(?::\s*(?:\S|$)|\s*(?:$|&|<|[0-9-])))'
)


def _translate_text_segment(segment: str, replace: bool = False) -> str:
    """Replace known English labels inside a plain-text HTML segment.

    ``replace=False`` (the legacy behaviour) appends the Urdu translation in a
    ``<span class="ur">`` *after* the English label.  ``replace=True`` swaps the
    English label for the Urdu one, which is what a single-language Urdu
    document needs.
    """
    if not segment or 'class="ur"' in segment:
        return segment
    if not _LABEL_ITEMS:
        return segment

    def _sub(match):
        en = match.group(1)
        plain = html_lib.unescape(en)          # "&amp;" -> "&"
        ur = LABELS.get(plain)
        if ur is None:
            # "Code:" / "Bill Pending:" are the same label as "Code" once the
            # trailing colon (rendered by the template) is stripped.
            ur = LABELS.get(plain.rstrip(':').strip())
        if ur is None:
            return en
        # Template already prints the colon ("Current Bill Total:"), and the
        # Urdu label carries its own — keep one, not two.
        if en.rstrip().endswith(':') and ur.endswith(':'):
            ur = ur[:-1].rstrip()
        if replace:
            # Keep whatever punctuation the template rendered after the label
            # (usually a colon) so "Total Due:" stays "ٹوٹل ڈیو:".
            tail = en[len(en.rstrip()):]
            return ('<span class="ur" lang="ur" dir="rtl">' + ur + '</span>'
                    + tail)
        return en + '<span class="ur" lang="ur" dir="rtl">' + ur + '</span>'

    return _LABEL_PATTERN.sub(_sub, segment)


def inject_urdu_labels(html: str, replace: bool = False) -> str:
    """Insert Urdu ``<span class="ur">`` translations for English labels.

    ``replace=False`` appends the translation beside the English label
    (the legacy mixed English+Urdu sheet).  ``replace=True`` substitutes it,
    producing a single-language Urdu document.

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
                result.append(_translate_text_segment(part, replace=replace))
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

    NOTE: this mixed English+Urdu layer is retained for non-bill documents
    (ledgers, statements, reports).  Bills and receipts use :func:`apply_urdu`
    / plain English instead, so each bill is a single-language document.
    """
    if not html:
        return html
    if _MARKER in html:
        return html
    return bilingual_css() + inject_urdu_labels(html)


# --------------------------------------------------------------------------
# Single-language Urdu mode (bills / receipts)
# --------------------------------------------------------------------------
# Bills are offered as two separate documents: English only, or Urdu only.
# ``apply_urdu`` therefore does NOT append translations beside English labels.
# The bill templates emit Urdu labels through the ``bill_label`` / ``bill_date``
# Jinja filters when ``bill_lang == 'ur'``; this helper only adds the Nastaleeq
# font face and switches the receipt wrapper to RTL.  User-entered names, notes,
# bill numbers and material names are never machine-translated.

_URDU_MARKER = '<!--ams-urdu-v1-->'
_HAS_URDU = re.compile(r'[\u0600-\u06FF\uFB50-\uFEFF]')

# Transaction-type badges resolved by ``billing._resolve_transaction_type``.
_URDU_TX = {
    'general_transaction': 'عمومی ٹرانزیکشن',
    'grn_purchase': 'جی آر این / خریداری',
    'payment_only': 'صرف ادائیگی',
    'direct_sale_cash': 'براہ راست فروخت (نقد)',
    'direct_sale_credit': 'براہ راست فروخت (ادھار)',
    'direct_sale_mixed': 'براہ راست فروخت (بک شدہ + بقایا)',
    'direct_sale_booked': 'براہ راست فروخت (بک شدہ ڈیلیوری)',
    'direct_sale_open_khata': 'براہ راست فروخت (کھلا کھاتہ)',
    'direct_sale': 'براہ راست فروخت',
    'invoice': 'انوائس',
    'cancellation': 'منسوخی',
    'delivery': 'ڈیلیوری',
    'booking': 'بکنگ',
    'pending_adjustment': 'زیر التوا / ایڈجسٹمنٹ',
}
_URDU_NOTE_PHRASES = {
    'Stock receiving purchase bill': 'اسٹاک وصولی خریداری بل',
    'General invoice record': 'عمومی انوائس ریکارڈ',
    'Booking cancellation / reversal': 'بکنگ منسوخی / واپسی',
    'Material delivery transaction': 'میٹیریل ڈیلیوری ٹرانزیکشن',
    'Booked / reserved material bill': 'بک شدہ / محفوظ میٹیریل بل',
}
_URDU_METHOD = {
    'Cash': 'نقد', 'Bank': 'بینک', 'Card': 'کارڈ',
    'Cheque': 'چیک', 'Check': 'چیک', 'Online': 'آن لائن',
    'Receipt': 'رسید', 'Payment': 'ادائیگی',
}
_URDU_CATEGORY = {
    'Cash': 'نقد', 'Credit Customer': 'ادھار گاہک',
    'Booked + Due': 'بک شدہ + بقایا', 'Booking Delivery': 'بکنگ ڈیلیوری',
    'Open Khata': 'کھلا کھاتہ', 'Mixed Transaction': 'مخلوط ٹرانزیکشن',
}

# Bill-specific fixed text that is not part of the shared ledger label dict.
_BILL_LABELS = {
    'N/A': 'غیر موجود',
    'Open URL': 'یو آر ایل کھولیں',
    'Thank you for your business!': 'آپ کے کاروبار کا شکریہ۔',
    'Software by AMS SYSTEM FOR EASE': 'سافٹ ویئر: اے ایم ایس سسٹم فار ایز',
    'Payment Received': 'وصول شدہ ادائیگی',
    'via': 'بذریعہ',
    'GRN expense': 'جی آر این خرچہ',
    'Unattributed landed cost': 'غیر منسوب لینڈڈ لاگت',
    'Supplier bill': 'سپلائر بل',
    'Stock / material amount': 'اسٹاک / میٹیریل رقم',
    'GRN expenses billed to supplier': 'سپلائر کو بل کیے گئے GRN اخراجات',
    'Supplier advance': 'سپلائر ایڈوانس',
    'Legacy GRN payment': 'پرانی GRN ادائیگی',
    'GRN charge': 'GRN خرچہ',
    'Transportation': 'نقل و حمل',
    'Other Expenses': 'دیگر اخراجات',
    'Vehicle / Transporter': 'گاڑی / ٹرانسپورٹر',
    'Loading / Labour': 'لوڈنگ / لیبر',
    'Other Party': 'دیگر پارٹی',
    'Unassigned (legacy charge)': 'غیر تفویض شدہ (پرانا خرچہ)',
}
_BILL_LABELS.update(_URDU_METHOD)

_URDU_MONTHS = {
    'Jan': 'جنوری', 'Feb': 'فروری', 'Mar': 'مارچ', 'Apr': 'اپریل',
    'May': 'مئی', 'Jun': 'جون', 'Jul': 'جولائی', 'Aug': 'اگست',
    'Sep': 'ستمبر', 'Oct': 'اکتوبر', 'Nov': 'نومبر', 'Dec': 'دسمبر',
}


def urdu_tx_label(code: str, fallback: str = '') -> str:
    """Urdu badge text for a transaction-type *code* (falls back to *fallback*)."""
    return _URDU_TX.get((code or '').strip(), fallback)


def urdu_tx_note(note: str) -> str:
    """Urdu version of the short transaction note shown on a bill.

    Known fixed phrases and the ``Method:`` / ``Sale Category:`` prefixes are
    translated; free-text reasons typed by the user are left untouched.
    """
    note = (note or '').strip()
    if not note:
        return note
    if note in _URDU_NOTE_PHRASES:
        return _URDU_NOTE_PHRASES[note]
    if note.startswith('Method:'):
        val = note[len('Method:'):].strip()
        return 'طریقہ: ' + _URDU_METHOD.get(val, val)
    if note.startswith('Sale Category:'):
        val = note[len('Sale Category:'):].strip()
        return 'فروخت کا زمرہ: ' + _URDU_CATEGORY.get(val, val)
    return note


def _urdu_span(text: str):
    """Return an RTL Urdu span as safe Jinja markup."""
    from markupsafe import Markup, escape
    return Markup('<span class="ur" lang="ur" dir="rtl">{}</span>').format(escape(str(text)))


def bill_label(text, lang: str = 'en'):
    """Translate a fixed bill label/value when *lang* is Urdu.

    English mode returns the original string untouched.  Urdu mode replaces the
    label with a single RTL span; it never appends Urdu beside English.  Unknown
    user-entered text is preserved verbatim (proper nouns, notes, references).
    """
    if text is None:
        return ''
    text = str(text)
    if (lang or 'en').strip().lower() not in ('ur', 'urdu', 'urd') or not text:
        return text
    key = text.strip()
    trailing = ':' if key.endswith(':') else ''
    base = key[:-1].strip() if trailing else key
    ur = _BILL_LABELS.get(base)
    if ur is None:
        ur = LABELS.get(base)
    if ur is None:
        lowered = base.lower()
        for en, value in LABELS.items():
            if en.lower() == lowered:
                ur = value
                break
    if ur is not None:
        return _urdu_span(ur + trailing)
    if _HAS_URDU.search(text):
        return _urdu_span(text)
    return text


def _ltr_bdi(text: str):
    """Return an isolated left-to-right run for figures in an Urdu document."""
    from markupsafe import Markup, escape
    return Markup('<bdi dir="ltr">{}</bdi>').format(escape(str(text)))


def bill_date(value, lang: str = 'en'):
    """Format a bill timestamp.

    Urdu bills use the simple reading order requested for receipts:
    ``صبح/شام → time → date → Urdu month → year``.  Each figure group is an
    LTR isolate, so both the browser and the ReportLab fallback keep ``05:03``
    and ``06`` in that order while the surrounding Urdu line remains RTL.
    """
    if value is None:
        return ''
    if not hasattr(value, 'strftime'):
        return str(value)
    if (lang or 'en').strip().lower() not in ('ur', 'urdu', 'urd'):
        return value.strftime('%d %b %Y  %I:%M %p')

    from markupsafe import Markup

    # Keep the spaces inside their neighbouring runs.  The fallback renderer
    # reverses inline runs for an RTL line; standalone whitespace would be
    # discarded there and make the date pieces touch each other.
    period = 'صبح' if getattr(value, 'hour', 0) < 12 else 'شام'
    month = _URDU_MONTHS.get(value.strftime('%b'), value.strftime('%b'))
    return Markup('{}{}{}{}{}').format(
        _urdu_span(period + ' '),
        _ltr_bdi(value.strftime('%I:%M ')),
        _ltr_bdi(value.strftime('%d ')),
        _urdu_span(month + ' '),
        _ltr_bdi(value.strftime('%Y')),
    )


def _urdu_css() -> str:
    """``@font-face`` + RTL rules for a single-language Urdu receipt."""
    file_url = 'file://' + JAMEEL_NOORI_TTF.replace(os.sep, '/')
    return (
        '<style id="ams-urdu-css">'
        '@font-face {'
        f'  font-family: "{URDU_FONT_FAMILY}";'
        '  src: url("/static/fonts/JameelNooriNastaleeq.ttf") format("truetype"),'
        f'       url("{file_url}") format("truetype");'
        '  font-weight: normal; font-style: normal;'
        '}'
        '.rcpt-wrapper[dir="rtl"] { direction: rtl; text-align: right; }'
        '.rcpt-wrapper[dir="rtl"] .ur {'
        f'  font-family: "{URDU_FONT_FAMILY}", "Noto Nastaliq Urdu", serif;'
        '  direction: rtl; unicode-bidi: embed;'
        '  font-size: 1.08em; line-height: 1.9;'
        '  letter-spacing: normal; text-transform: none;'
        '}'
        '.rcpt-wrapper[dir="rtl"] .rcpt-detail-val,'
        '.rcpt-wrapper[dir="rtl"] .rcpt-doc-no,'
        '.rcpt-wrapper[dir="rtl"] .rcpt-doc-date,'
        '.rcpt-wrapper[dir="rtl"] .rcpt-party-sub,'
        '.rcpt-wrapper[dir="rtl"] .rcpt-co-phone,'
        '.rcpt-wrapper[dir="rtl"] .rcpt-amount-val,'
        '.rcpt-wrapper[dir="rtl"] td.text-end {'
        '  direction: ltr; unicode-bidi: embed;'
        '}'
        # A row that pairs an Urdu label with a figure (``کل بقایا`` / ``25,000``)
        # puts the label on the right and the figure on the left: the same
        # order the left-to-right document shows.  ``row-reverse`` in an RTL
        # wrapper makes that explicit, so the figures never sit left of their
        # own label and the amounts stay in their column.
        '.rcpt-wrapper[dir="rtl"] .rcpt-detail-row,'
        '.rcpt-wrapper[dir="rtl"] .rcpt-summary-row,'
        '.rcpt-wrapper[dir="rtl"] .rcpt-total-row {'
        '  flex-direction: row-reverse;'
        '}'
        # A phone number is a run of digits and '+', '-', '|' - all neutral in
        # bidi - so inside right-to-left text the two numbers of
        # ``+92331-... | +92340-...`` swap and the '+' jumps to the end.  The
        # isolate keeps the number itself left to right wherever it appears.
        '.rcpt-wrapper[dir="rtl"] [dir="ltr"],'
        '.rcpt-wrapper[dir="rtl"] .rcpt-ltr {'
        '  direction: ltr; unicode-bidi: isolate;'
        '}'
        '</style>'
    )


def _set_receipt_rtl(html: str) -> str:
    """Add ``dir="rtl" lang="ur"`` to the document wrapper when missing.

    Bills and receipts wrap their content in ``.rcpt-wrapper``; ledgers do too.
    Templates that use a different wrapper fall back to ``<body>`` so the whole
    Urdu document still reads right-to-left.
    """
    pattern = re.compile(r'(<div\b[^>]*class="[^"]*\brcpt-wrapper\b[^"]*")', re.I)
    match = pattern.search(html)
    if match and not re.search(r'\bdir\s*=', match.group(1), re.I):
        return pattern.sub(lambda m: m.group(1) + ' dir="rtl" lang="ur"',
                           html, count=1)
    if match:
        return html
    body = re.search(r'<body\b[^>]*>', html, re.I)
    if body and not re.search(r'\bdir\s*=', body.group(0), re.I):
        return (html[:body.end() - 1] + ' dir="rtl" lang="ur"'
                + html[body.end() - 1:])
    return html


def apply_urdu(html: str) -> str:
    """Return *html* ready for a single-language Urdu bill PDF/print.

    The bill template has already selected Urdu labels via ``bill_lang``.  This
    injects the bundled Jameel Noori font and RTL layout only.  It is idempotent
    and does not translate or reorder user-entered Latin data.
    """
    if not html:
        return html
    if _URDU_MARKER in html or _MARKER in html:
        return html
    return _urdu_css() + _URDU_MARKER + _set_receipt_rtl(html)


# --------------------------------------------------------------------------
# Single-language Urdu for *non-bill* documents (ledgers, statements, reports)
# --------------------------------------------------------------------------
# Bills get their Urdu labels from the template itself (``bill_lang``), so
# :func:`apply_urdu` only has to add the font and the RTL direction.  Ledgers
# and statements are plain English templates with no Urdu branch, so for those
# the labels are swapped here instead: :func:`apply_urdu_labels` runs the same
# dictionary in *replace* mode and then applies the RTL sheet.
#
# This is what makes it possible to offer two clean downloads — English or Urdu —
# instead of one mixed sheet.  The mixed layer (:func:`apply_bilingual`) is no
# longer used for exports: appending Nastaleeq beside every Latin label made
# the pure-Python PDF fallback unreadable, because the two scripts were drawn
# on the same baseline inside the same paragraph.

def urdu_only_css() -> str:
    """``@font-face`` + ``.ur`` rules for a *label-replaced* Urdu document.

    Same as :func:`bilingual_css` but without the ``" / "`` separator, which
    only makes sense when the Urdu sits next to its English original.
    """
    file_url = 'file://' + JAMEEL_NOORI_TTF.replace(os.sep, '/')
    return (
        '<style id="ams-urdu-css">'
        '@font-face {'
        f'  font-family: "{URDU_FONT_FAMILY}";'
        '  src: url("/static/fonts/JameelNooriNastaleeq.ttf") format("truetype"),'
        f'       url("{file_url}") format("truetype");'
        '  font-weight: normal; font-style: normal;'
        '}'
        '.ur {'
        f'  font-family: "{URDU_FONT_FAMILY}", "Noto Nastaliq Urdu", serif;'
        '  direction: rtl; unicode-bidi: embed;'
        '}'
        '</style>'
    )


def apply_urdu_labels(html: str) -> str:
    """Return *html* as a single-language Urdu document.

    English labels are *replaced* by their Urdu translation (never appended),
    the Jameel Noori font is attached and the document is switched to RTL.
    Numbers, dates, bill numbers, party names and notes are left untouched —
    only known labels are translated.  Idempotent.
    """
    if not html:
        return html
    if _URDU_MARKER in html:
        return html
    body = inject_urdu_labels(html, replace=True)
    return urdu_only_css() + _urdu_css() + _URDU_MARKER + _set_receipt_rtl(body)
