"""Positioned Urdu text for the ReportLab PDF path.

Why this module exists
----------------------
ReportLab cannot shape Arabic script.  The app already works around that by
shaping Urdu with HarfBuzz/fontTools and mapping the shaped glyph ids through
a private-use cmap (:func:`app.services.bilingual.shape_urdu`), but a shaped
*string* is still drawn by ReportLab one glyph after another at the font's own
advance widths and **on the baseline**.  HarfBuzz, however, positions every
glyph with ``(x_advance, x_offset, y_offset)``:

* Nastaleeq stacks marks with ``y_offset`` (the ``ٹ`` of ``زمرہ`` sits a full
  em above the baseline, the ``۔`` of ``شکریہ`` too), and
* it slides glyphs horizontally with ``x_offset`` (kashida, medial forms).

Dropping those offsets is exactly what produced the "distorted" Urdu bills:
marks collapsed onto the baseline and letters overlapped each other.

This module keeps the full HarfBuzz output and renders each glyph at
``(pen_x + x_offset, baseline + y_offset)``, so the PDF matches what a browser
shows.  It also provides ``UrduParagraph`` - a ReportLab flowable that wraps
mixed Latin/Urdu runs, honours RTL order and alignment, and draws the Urdu
runs with the positioned glyphs above.
"""
from __future__ import annotations

import re

from reportlab.platypus import Flowable as _Flowable

from app.services import bilingual as B

# HarfBuzz positions are in font units; the bundled face is 2048/em.
UPEM = float(getattr(B, '_font_em', 2048.0) or 2048.0)
PUA_BASE = B._PUA_BASE

_TAG_RE = re.compile(r'<[^>]+>')


# ---------------------------------------------------------------------------
# HarfBuzz access
# ---------------------------------------------------------------------------

def harfbuzz_available() -> bool:
    return B._hb() is not None


def _hb_font():
    font = B._hb()
    if font is None:
        return None
    try:
        font.scale = (int(UPEM), int(UPEM))
    except Exception:
        pass
    return font


def shape_glyphs(text: str):
    """Shape *text* and return ``[(gid, x_advance, x_offset, y_offset)]``.

    Falls back to the fontTools shaper in :mod:`app.services.bilingual` (glyph
    advances only, no offsets) when ``uharfbuzz`` is missing, and to ``None``
    when the bundled font is unavailable.
    """
    text = text or ''
    if not text:
        return []
    font = _hb_font()
    if font is not None:
        try:
            import uharfbuzz as hb
            buf = hb.Buffer()
            buf.add_str(text)
            buf.direction = 'rtl'
            buf.script = 'Arab'
            buf.language = 'ur'
            hb.shape(font, buf, {})
            return [
                (info.codepoint, pos.x_advance, pos.x_offset, pos.y_offset)
                for info, pos in zip(buf.glyph_infos, buf.glyph_positions)
            ]
        except Exception:
            pass
    # fontTools fallback: glyph ids in visual order, no fine positioning.
    shaped = B._shape_with_fonttools(text)
    if not shaped:
        return None
    out = []
    for ch in shaped:
        gid = ord(ch) - PUA_BASE
        out.append((gid, _gid_advance(gid), 0, 0))
    return out


def _gid_advance(gid: int) -> int:
    """Advance width of *gid* in font units (used by the fallback shaper)."""
    loaded = B._fallback_font()
    if not loaded:
        return 0
    tt, _gid_map, _shapes, _order = loaded
    try:
        width = tt['hmtx'][tt.getGlyphOrder()[gid]][0]
        return int(width)
    except Exception:
        return 0


def pua_text(glyphs) -> str:
    """The PUA string for a shaped glyph list (one char per glyph)."""
    return ''.join(chr(PUA_BASE + g[0]) for g in glyphs)


def measure_run(text: str, size: float) -> float:
    """Width in points of a shaped Urdu run at *size*."""
    glyphs = shape_glyphs(text)
    if not glyphs:
        return 0.0
    return sum(g[1] for g in glyphs) * size / UPEM


def latin_width(text: str, font: str, size: float) -> float:
    from reportlab.pdfbase import pdfmetrics
    try:
        return pdfmetrics.stringWidth(text or '', font, size)
    except Exception:
        return len(text or '') * size * 0.5


# ---------------------------------------------------------------------------
# Flowable: mixed Latin/Urdu paragraph with positioned Urdu glyphs
# ---------------------------------------------------------------------------

class Span:
    """One inline run: either Latin text drawn by ReportLab, or Urdu text."""

    __slots__ = ('text', 'urdu', 'font', 'size', 'color', 'bold', 'rise',
                 'nowrap')

    def __init__(self, text, urdu, font, size, color='#000000', bold=False,
                 rise=0.0, nowrap=False):
        self.text = text
        self.urdu = urdu
        self.font = font
        self.size = float(size)
        self.color = color
        self.bold = bool(bold)
        self.rise = float(rise)
        # ``nowrap`` (CSS ``white-space: nowrap``) keeps the run on one line:
        # a bill number must never be split into ``MB`` / ``NO.7001``.
        self.nowrap = bool(nowrap)

    def __repr__(self):     # pragma: no cover - debugging aid
        return f'Span({self.text!r}, urdu={self.urdu})'


def _rl_color(value):
    from reportlab.lib import colors
    value = (value or '#000000').strip()
    try:
        if value.startswith('#') and len(value) in (4, 7):
            hexval = value if len(value) == 7 else '#' + ''.join(
                c * 2 for c in value[1:])
            return colors.HexColor(hexval)
        if value.lower() in ('black',):
            return colors.black
        return colors.HexColor(value)
    except Exception:
        return colors.black


class UrduParagraph(_Flowable):
    """Positioning-aware centred/left/right paragraph for mixed scripts.

    A real ``reportlab.platypus.Flowable`` so it behaves like any other story
    element (splitting, spacing, table cells) while drawing Urdu glyphs at the
    positions HarfBuzz computed.
    """

    def __init__(self, spans, leading=None, align='left', color='#000000',
                 space_before=0.0, space_after=0.0, style=None, bidi_rtl=None):
        _Flowable.__init__(self)
        self.spans = [s for s in spans if s is not None and s.text]
        sizes = [s.size for s in self.spans] or [8.0]
        self.size = max(sizes)
        urdu = any(s.urdu for s in self.spans)
        self.leading = float(leading or 0) or (
            B.urdu_line_factor(self.size) if urdu else self.size * 1.28)
        if urdu:
            # Nastaleeq needs room for the deep descenders and high marks.
            self.leading = max(self.leading, B.urdu_line_factor(self.size))
        self.align = align if align in ('left', 'right', 'center', 'justify') \
            else 'left'
        # ``bidi_rtl`` is the paragraph's base direction: an Urdu document
        # lays out right to left even where a line has no Urdu word.
        self.bidi_rtl = bool(bidi_rtl) if bidi_rtl is not None else any(
            s.urdu for s in self.spans)
        self.color = color
        self.space_before = float(space_before or 0)
        self.space_after = float(space_after or 0)
        self.style = style
        self._lines = []        # [[(span, text, width)] ...]
        self._height = self.leading
        self._width = 0.0
        self._words = self._split_words()

    # -- measuring -------------------------------------------------------
    def _split_words(self):
        """Flatten spans into word tokens with measured widths."""
        words = []
        for span in self.spans:
            pieces = re.split(r'([ \t\n\r\u00a0]+)', span.text)
            for piece in pieces:
                if not piece:
                    continue
                if piece.isspace():
                    # ``is_breaking_space`` distinguishes a real word gap from
                    # ZWSP/padding whitespace, which must not be re-inserted
                    # between runs (that is what turned ``موجودہ بل کا کل:``
                    # into ``موجودہ بل  کا کل:``).
                    word = Word(span, ' ', space=True)
                    word.is_breaking_space = ' ' in piece.replace('\u00a0', ' ')
                    words.append(word)
                    continue
                for idx, chunk in enumerate(piece.split('\u200b')):
                    if idx:
                        words.append(Word(span, '', space=True))
                    if chunk:
                        words.append(Word(span, chunk, space=False))
        return words

    def _min_word_width(self) -> float:
        """Widest single token on this paragraph (its unbreakable minimum)."""
        best = 0.0
        for word in self._words:
            if word.space:
                continue
            word.measure()
            best = max(best, word.width)
        return best

    def wrap(self, availWidth, availHeight=None):
        """Split the runs into lines and order each line for its direction.

        Wrapping itself always walks the *logical* order; the physical order is
        decided per line afterwards (:meth:`_reorder`), exactly like the bidi
        algorithm a browser applies:

        * a right-to-left line (an Urdu label, or an Urdu document) starts at
          the right edge and its Urdu/Latin runs are laid out right to left;
        * a left-to-right line keeps its run order, but an Urdu run inside it
          is still drawn right to left, so its words are reversed and the run
          is anchored at its right edge.
        """
        width = max(float(availWidth or 0), 1.0)
        lines, current, used = [], [], 0.0
        for word in self._words:
            word.measure()
            if word.space:
                if current:
                    current.append(word)
                    used += word.width
                continue
            if current and word.span.nowrap and current[-1].span is word.span:
                # Part of an unbreakable run that already started on this
                # line: keep the whole run together.
                current.append(word)
                used += word.width
                continue
            if current and used + word.width > width:
                while current and current[-1].space:
                    used -= current[-1].width
                    current.pop()
                lines.append(current)
                current, used = [], 0.0
            current.append(word)
            used += word.width
        if current:
            while current and current[-1].space:
                current.pop()
            lines.append(current)
        if not lines:
            lines = [[]]
        self._lines = [self._reorder(line) for line in lines]
        self._width = width
        self._height = max(self.leading * len(lines), self.leading)
        return width, self._height

    def _line_is_rtl(self, line) -> bool:
        if self.align == 'right' and self.bidi_rtl:
            return True
        for word in line:
            if not word.space and word.span.urdu:
                return True
        return False

    def _reorder(self, line):
        """Physical (left-to-right) order of one line, as :class:`LineRun`s.

        Each inline run keeps its words *and* its own spaces, so
        ``"06 نومبر 2026"`` stays one drawing operation with its gaps intact;
        the runs themselves are ordered right to left in an RTL line, and an
        Urdu run reverses its tokens (a space reverses with them, which is
        exactly the bidi behaviour).
        """
        tokens = [w for w in line if w.text]
        if not tokens:
            return []
        base_rtl = self._line_is_rtl(tokens)

        groups = []
        for word in tokens:
            key = id(word.span)
            if groups and groups[-1][0] == key:
                groups[-1][1].append(word)
            else:
                groups.append([key, [word], word.span.urdu])

        # Build the runs in *logical* order first.  A run's own words are
        # already in visual order (an Urdu run reverses its tokens), so the
        # only thing left is deciding which side the neighbouring runs sit on.
        logical = []
        for _key, group, urdu in groups:
            words = list(group)
            start_gap = bool(words and words[0].space
                             and words[0].is_breaking_space)
            end_gap = bool(words and words[-1].space
                           and words[-1].is_breaking_space)
            if urdu:
                words.reverse()
            while words and words[0].space:
                words.pop(0)
            while words and words[-1].space:
                words.pop()
            if not words:
                continue
            run = LineRun(words[0].span, words)
            run.measure()
            run.start_gap = start_gap
            run.end_gap = end_gap
            logical.append(run)
        if not logical:
            return []

        physical = list(reversed(logical)) if base_rtl else list(logical)
        for index in range(1, len(physical)):
            left, right = physical[index - 1], physical[index]
            if base_rtl:
                earlier, later = right, left       # RTL: right-hand run first
            else:
                earlier, later = left, right
            # Whitespace on *either* side of the logical boundary is the only
            # thing separating ``مینول بل:`` from ``MB NO.9101``; without it the
            # label and the bill number collide.  The gap is appended to the
            # left-hand run so it is drawn where the two meet.
            if not (earlier.end_gap or later.start_gap):
                continue
            gap = later.words[0].space_width()
            if gap <= 0:
                continue
            separator = Word(left.words[-1].span, ' ', space=True)
            separator.is_breaking_space = True
            separator.width = gap
            left.words.append(separator)
            left.width += gap
        return physical

    # -- drawing ---------------------------------------------------------
    def draw(self):
        canvas = self.canv
        y = self._height - self.leading + (
            self.leading - self.size) * 0.30
        for line in self._lines:
            line_width = sum(run.width for run in line)
            if self.align == 'right':
                x = self._width - line_width
            elif self.align == 'center':
                x = (self._width - line_width) / 2.0
            else:
                x = 0.0
            for run in line:
                self._draw_run(canvas, run, x, y)
                x += run.width
            y -= self.leading
        try:
            canvas.setTextRenderMode(0)
        except Exception:
            pass

    def _draw_run(self, canvas, run, x, y):
        """Draw one run; Latin text goes out as one aligned string."""
        span = run.span
        size = span.size
        if span.urdu:
            self._draw_urdu(canvas, run, x, y)
            return
        text = run.text()
        if not text.strip():
            return
        canvas.saveState()
        canvas.setFillColor(_rl_color(span.color))
        self._apply_weight(canvas, span)
        canvas.setFont(span.font, size)
        # Always ``drawString`` at the run's computed start: the aligned
        # helpers split a string into one drawing operation per word, which
        # fragments the PDF's text layer ("MB NO" / ".9101") for copy/paste.
        canvas.drawString(x, y + span.rise, text)
        canvas.restoreState()

    def _draw_urdu(self, canvas, run, x, y):
        """Draw a shaped Urdu run glyph by glyph at its HarfBuzz position."""
        span = run.span
        size = span.size
        scale = size / UPEM
        canvas.saveState()
        canvas.setFillColor(_rl_color(span.color))
        self._apply_weight(canvas, span)
        canvas.setFont(B.URDU_FONT_REPORTLAB, size)
        pen = x
        drawn = []          # (x, y, text) — emitted right to left at the end
        for word in run.words:
            if word.space:
                # A space has no glyph of its own here (the bundled face maps
                # it to a 5-unit advance).  Advance the pen by a real word gap
                # and keep a literal space in the text layer so the words of
                # the PDF do not run together.
                gap = _space_advance() * scale
                drawn.append((pen, y + span.rise, ' '))
                pen += gap
                continue
            glyphs = word.glyphs or []
            chunk, chunk_x = '', None
            for gid, advance, dx, dy in glyphs:
                if dx == 0 and dy == 0 and advance > 0:
                    if chunk_x is None:
                        chunk_x = pen
                    chunk += chr(PUA_BASE + gid)
                else:
                    if chunk:
                        drawn.append((chunk_x, y + span.rise, chunk))
                        chunk, chunk_x = '', None
                    # Offsets are the Nastaleeq marks; a zero advance means the
                    # mark owns no horizontal room and would be overpainted by
                    # the next glyph if it stayed inside a chunk.
                    drawn.append((pen + dx * scale,
                                  y + span.rise + dy * scale,
                                  chr(PUA_BASE + gid)))
                pen += advance * scale
            if chunk:
                drawn.append((chunk_x, y + span.rise, chunk))
        # Urdu reads right to left: emitting the chunks from the rightmost one
        # keeps the PDF text layer in logical order.
        for glyph_x, glyph_y, text in reversed(drawn):
            canvas.drawString(glyph_x, glyph_y, text)
        canvas.restoreState()

    @staticmethod
    def _apply_weight(canvas, span):
        """Faux-bold Urdu: the bundled face ships a single weight."""
        if not span.bold:
            return
        try:
            canvas.setLineWidth(max(0.18, span.size * 0.026))
            canvas.setTextRenderMode(2)
        except Exception:
            pass

    # -- Paragraph-compatible API ---------------------------------------
    def getSpaceBefore(self):
        return self.space_before

    def getSpaceAfter(self):
        return self.space_after

    def minWidth(self):
        """Narrowest the paragraph can be without breaking a word.

        ReportLab uses this to size table columns; returning 0 let it squeeze
        the description column until ``MB NO.7001`` wrapped into two lines.
        """
        return self._min_word_width()

    def split(self, availWidth, availHeight):
        """Break a long paragraph between lines instead of overflowing.

        ReportLab asks for a split whenever the flowable does not fit the rest
        of the page; returning ``[self]`` (the old behaviour) made it retry the
        same object until it raised ``LayoutError`` and the whole document was
        lost.
        """
        if not self._lines:
            self.wrap(availWidth)
        if self._height <= availHeight:
            return [self]
        fit = int(float(availHeight) // max(self.leading, 0.1))
        if fit < 1:
            return []
        head = self._clone(self._lines[:fit])
        tail_lines = self._lines[fit:]
        tail = self._clone(tail_lines) if tail_lines else None
        return [head, tail] if tail else [head]

    def _clone(self, lines):
        clone = UrduParagraph(list(self.spans), leading=self.leading,
                              align=self.align, color=self.color,
                              space_before=0, space_after=0, style=self.style,
                              bidi_rtl=self.bidi_rtl)
        clone._lines = [list(line) for line in lines]
        clone._width = self._width
        clone._height = max(self.leading * len(lines), self.leading)
        return clone

    def __repr__(self):     # pragma: no cover - debugging aid
        return f'<UrduParagraph spans={len(self.spans)}>'


class LineRun:
    """A stretch of one line drawn as a single drawing operation.

    Keeping whole runs (``"MB NO.9101"``, a full Urdu label) in one
    ``drawString``/``drawAlignedString`` call keeps the PDF's text layer in
    reading order, so copy/paste and text extraction still return real words
    id="line-run" instead of one fragment per word.
    """

    __slots__ = ('span', 'words', 'width', 'start_gap', 'end_gap')

    def __init__(self, span, words):
        self.span = span
        self.words = list(words)
        self.width = 0.0
        self.start_gap = False    # logical space before this run
        self.end_gap = False      # logical space after this run

    def text(self):
        return ''.join(w.text for w in self.words)

    def measure(self):
        self.width = sum(w.width for w in self.words)
        return self.width


def _space_advance() -> int:
    """Advance width of one space in font units (the bundled font: 512)."""
    try:
        from reportlab.pdfbase import pdfmetrics
        return int(round(pdfmetrics.stringWidth(' ', B.URDU_FONT_REPORTLAB, 1.0)
                         * UPEM))
    except Exception:
        return int(UPEM * 0.25)


def _text_width(text: str, size: float) -> float:
    from reportlab.pdfbase import pdfmetrics
    try:
        return pdfmetrics.stringWidth(text, B.URDU_FONT_REPORTLAB, size)
    except Exception:
        return len(text) * size * 0.5


class Word:
    __slots__ = ('span', 'text', 'space', 'width', 'glyphs',
                 'is_breaking_space')

    def __init__(self, span, text, space=False):
        self.span = span
        self.text = text
        self.space = space
        self.width = 0.0
        self.glyphs = None
        self.is_breaking_space = bool(space)

    def space_width(self):
        """Width of one word separator for this word's run."""
        span = self.span
        if span.urdu:
            return _space_advance() * span.size / UPEM
        return latin_width(' ', span.font, span.size)

    def measure(self):
        """Cache this word's shaped glyphs and its width in points."""
        span = self.span
        if span.urdu:
            self.glyphs = [] if self.space else (shape_glyphs(self.text) or [])
            if self.glyphs:
                self.width = (sum(g[1] for g in self.glyphs)
                              * span.size / UPEM)
            else:
                self.width = latin_width(self.text, span.font, span.size)
        else:
            self.width = latin_width(self.text, span.font, span.size)
        return self.width


# ---------------------------------------------------------------------------
# Helpers used by the layout engine
# ---------------------------------------------------------------------------

_URDU_RANGE = re.compile(r'[\u0600-\u06FF\uFB50-\uFEFF]')


def has_urdu(text: str) -> bool:
    """True when *text* carries real Arabic-script characters."""
    return bool(_URDU_RANGE.search(text or ''))


def has_shaped_glyphs(text: str) -> bool:
    """True when *text* still holds private-use glyph ids from ``shape_urdu``."""
    return any(ord(ch) >= PUA_BASE for ch in (text or ''))


def markup_to_spans(markup: str, base_font: str, base_size: float,
                    base_color: str = '#000000', base_bold: bool = False):
    """Convert ReportLab inline markup into :class:`Span` objects.

    Understands the subset the app emits: ``<font face size color>``,
    ``<b>``/``<strong>``, ``<br/>`` (becomes a space), and bare PUA glyph
    runs (which are treated as shaped Urdu).
    """
    spans = []
    font, size, color, bold = base_font, base_size, base_color, base_bold
    stack = []
    pos = 0
    text_parts = []

    def flush():
        if not text_parts:
            return
        text = ''.join(text_parts)
        text_parts.clear()
        if not text:
            return
        urdu = has_shaped_glyphs(text)
        spans.append(Span(text, urdu, font, size, color, bold))

    for match in re.finditer(r'<(/?)(\w+)([^>]*)>', markup or ''):
        chunk = markup[pos:match.start()]
        if chunk:
            text_parts.append(chunk)
        pos = match.end()
        closing, tag, attrs = match.group(1), match.group(2).lower(), match.group(3)
        if closing:
            if stack:
                font, size, color, bold = stack.pop()
            continue
        flush()
        stack.append((font, size, color, bold))
        for key, value in re.findall(r'(\w+)\s*=\s*"([^"]*)"', attrs or ''):
            key = key.lower()
            if key in ('face', 'fontname'):
                font = value
            elif key in ('size', 'fontsize'):
                try:
                    size = float(value)
                except ValueError:
                    pass
            elif key in ('color', 'textcolor'):
                color = value
        if tag in ('b', 'strong'):
            bold = True
        elif tag in ('super', 'sup'):
            # Rises are handled by the shaper; a nested super is treated as a
            # normal run so no glyph is dropped.
            pass
        elif tag == 'br':
            text_parts.append(' ')
    tail = (markup or '')[pos:]
    if tail:
        text_parts.append(_TAG_RE.sub('', tail))
    flush()
    return spans


def is_urdu_markup(markup: str) -> bool:
    return has_shaped_glyphs(markup) or has_urdu(markup)
