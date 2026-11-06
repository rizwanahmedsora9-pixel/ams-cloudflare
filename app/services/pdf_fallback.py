"""Pure-Python HTML -> PDF fallback for exports.

The primary exporter is WeasyPrint, which reproduces the on-screen HTML/CSS
with high fidelity.  WeasyPrint, however, links against system libraries
(pango/cairo/gdk-pixbuf) that are frequently unavailable on shared hosts such
as PythonAnywhere, and on those hosts every download used to silently degrade
to an ``.html`` attachment - the user asked for a PDF and received a web page.

This module removes that failure mode.  It renders a genuine PDF with
ReportLab (already a declared dependency, pure Python, no system libraries) by
walking the same rendered HTML and laying out its text and tables.

Accuracy contract:
* Every number is copied **verbatim** from the rendered HTML.  Nothing here
  recomputes, re-rounds or reformats a value, so a PDF produced by this path
  always shows the same figures as the screen and as the WeasyPrint path.
* Tables are emitted as real PDF tables so ledger columns (debit / credit /
  running balance) stay aligned and complete.
* If even this path fails, the caller decides the response; this module never
  pretends success.
"""
from __future__ import annotations

import io
import logging
import os
import re
from html import unescape
from html.parser import HTMLParser

from app.services.pdf_layout import (
    Css, Node, Line, RowBlock, TableBlock, _apply_case, _build_table,
    _escape, _has_block_children, _inline_text, _is_blockish, build_story,
    layout, resolve,
)

log = logging.getLogger(__name__)

# Same geometry the WeasyPrint path forces: 14.8cm x 21cm with 1cm margins.
PAGE_WIDTH_CM = 14.8
PAGE_HEIGHT_CM = 21.0
MARGIN_CM = 1.0

# Block-level tags that terminate the current inline run.
_BLOCK_TAGS = {
    'p', 'div', 'section', 'article', 'header', 'footer', 'li', 'ul', 'ol',
    'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre',
    'tr', 'table', 'thead', 'tbody', 'tfoot', 'dl', 'dt', 'dd', 'figcaption',
}
_HEADING_TAGS = {'h1': 13, 'h2': 12, 'h3': 11, 'h4': 10.5, 'h5': 10, 'h6': 9.5}
_SKIP_CONTENT_TAGS = {'script', 'style', 'noscript', 'svg', 'canvas', 'head'}
_INLINE_SEP_TAGS = {'br', 'hr'}

# Application chrome that must never reach an exported document.  These mirror
# the selectors the app already hides under ``@media print`` in layout.html, so
# the ReportLab path and the WeasyPrint print-media path agree.
_SKIP_CLASS_TOKENS = {
    'sidebar', 'sidebar-overlay', 'mobile-header', 'modal', 'modal-backdrop',
    'loading-overlay', 'd-print-none', 'no-print', 'toast-container',
    'offcanvas',
}
_SKIP_ID_TOKENS = {
    'sidebar', 'sidebarOverlay', 'loadingOverlay',
}

# Elements with no end tag.  They must not deepen the skip nesting counter, or
# the counter could never return to zero and the rest of the document would be
# discarded.
_VOID_TAGS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
    'meta', 'param', 'source', 'track', 'wbr',
}


def _is_chrome(attrs):
    """True when this element and its subtree should be excluded from the PDF."""
    for key, value in attrs:
        if key == 'class':
            tokens = set((value or '').split())
            if tokens & _SKIP_CLASS_TOKENS:
                return True
        elif key == 'id' and value in _SKIP_ID_TOKENS:
            return True
    return False

_WS = re.compile(r'\s+')


# Registered Jameel Noori TTF name for Urdu runs (set by render_html_to_pdf).
_URDU_FONT = None


def _shape_urdu_run(data):
    """Shape an Urdu text run and wrap it in a Jameel Noori <font> tag."""
    if not _URDU_FONT or not data.strip():
        return data
    try:
        from xml.sax.saxutils import escape
        from app.services.bilingual import shape_urdu
        # Render the Urdu run slightly smaller than the body text so the added
        # translation does not push English content onto a new line.
        return f'<font face="{_URDU_FONT}" size="6">{escape(shape_urdu(data))}</font>'
    except Exception:
        return data


def _clean(text):
    return _WS.sub(' ', unescape(text or '')).strip()


class _HtmlToFlowables(HTMLParser):
    """Builds a DOM tree while recording the embedded stylesheets."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('html')
        self._stack = [self.root]
        self._skip_depth = 0
        self._sheets = []

    # -- parser events ---------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        ad = {k.replace('-', '_') if k == 'class' else k: v for k, v in attrs}
        ad['class'] = dict(attrs).get('class', '')
        if tag == 'style':
            # ``<style>`` may live in ``<head>``, which is otherwise skipped.
            # It used to be swallowed by ``_skip_depth`` so a template that
            # styles itself in ``<head>`` rendered completely unstyled.
            node = Node('style', ad, self._stack[-1])
            self._stack[-1].append(node)
            self._stack.append(node)
            self._skip_depth += 1
            return
        if self._skip_depth:
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if tag in _SKIP_CONTENT_TAGS:
            self._skip_depth = 1
            return
        if _is_chrome(attrs):
            self._skip_depth = 1
            return
        node = Node(tag, ad, self._stack[-1])
        self._stack[-1].append(node)
        if tag in ('style', 'script', 'noscript', 'head'):
            self._skip_depth = 1
            self._stack.append(node)
            return
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth -= 1
            if self._stack and self._stack[-1].tag in _SKIP_CONTENT_TAGS | {'head'}:
                if self._skip_depth == 0:
                    self._stack.pop()
            return
        if len(self._stack) <= 1:
            return
        # pop to the matching open element
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if self._skip_depth:
            node = self._stack[-1]
            if node.tag == 'style':
                self._sheets.append(data)
            return
        # Text is kept in document order alongside the element children, so
        # ``<strong>Client:</strong> NAME`` stays "Client: NAME" instead of
        # collapsing into the parent's own text buffer.
        if data:
            self._stack[-1].append_text(data)

    def close(self):
        super().close()


def _parse_document(html):
    parser = _HtmlToFlowables()
    try:
        parser.feed(html or '')
        parser.close()
    except Exception:
        log.exception('HTML parsing for the PDF fallback was interrupted')
    css = Css()
    for sheet in parser._sheets:
        css.add_sheet(sheet)
    return parser.root, css


def _parse_html(html):
    """Legacy view of the parse: ``[('text', str, style) | ('table', rows)]``.

    Kept for the existing tests and any external callers; the renderer itself
    uses :func:`_parse_document` and keeps the full layout.
    """
    root, css = _parse_document(html)
    blocks = []
    _walk_legacy(root, css, resolve(css, root), blocks)
    return blocks


def _walk_legacy(node, css, style, out):
    if 'ur' in node.classes:
        return
    if node.tag == 'table':
        table = _build_table(node, css, style)
        if table is not None:
            out.append(('table', [[(c['text'], c['colspan'], c['header'])
                                   for c in row] for row in table.rows]))
        return
    block_children = [c for c in node.children
                      if isinstance(c, Node) and _is_blockish(c)]
    if block_children:
        for child in block_children:
            _walk_legacy(child, css, resolve(css, child, style), out)
        return
    text = _inline_text(node, css, style)
    if text:
        out.append(('text', _apply_case(text, style), 'body'))


def _build_story(blocks, body_font, bold_font, small_size):
    """Legacy block renderer (kept for API compatibility)."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    normal = ParagraphStyle('pdfBody', fontName=body_font, fontSize=small_size,
                            leading=small_size * 1.4, spaceAfter=3,
                            wordWrap='LTR')
    story = []
    for block in blocks:
        if block[0] == 'text':
            story.append(Paragraph(_escape(block[1]), normal))
        else:
            rows = block[1]
            width = max((sum(c[1] for c in r) for r in rows), default=1) or 1
            data = []
            for r in rows:
                out = []
                for text, colspan, _header in r:
                    out.append(Paragraph(_escape(text), normal))
                    out.extend([''] * (colspan - 1))
                while len(out) < width:
                    out.append('')
                data.append(out[:width])
            if not data:
                continue
            tbl = Table(data, colWidths=[(PAGE_WIDTH_CM - 2 * MARGIN_CM) * 28.35 / width] * width)
            tbl.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#9aa0a6')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            story.append(tbl)
    return story


def render_html_to_pdf(html, download_name='document.pdf', title='AMS Report'):
    """Render *html* into a real PDF.  Returns bytes, or ``None`` on failure.

    Raises nothing: callers fall back to their own behaviour when this returns
    ``None``, but the intent is that this path succeeds wherever ReportLab is
    importable, so a PDF is always delivered.
    """
    try:
        from reportlab.lib.units import cm
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
    except Exception:
        log.warning('ReportLab unavailable; cannot build fallback PDF.')
        return None

    try:
        # Register the bundled Jameel Noori font so Urdu runs (span.ur) render
        # shaped and in the right typeface instead of as tofu boxes.
        global _URDU_FONT
        try:
            from app.services.bilingual import register_urdu_font
            _URDU_FONT = register_urdu_font()
        except Exception:
            _URDU_FONT = None

        # Prefer Helvetica (always present in ReportLab); DejaVu is optional.
        body_font, bold_font = 'Helvetica', 'Helvetica-Bold'
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            candidates = [
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            ]
            if all(os.path.exists(p) for p in candidates):
                pdfmetrics.registerFont(TTFont('DejaVu', candidates[0]))
                pdfmetrics.registerFont(TTFont('DejaVu-Bold', candidates[1]))
                body_font, bold_font = 'DejaVu', 'DejaVu-Bold'
        except Exception:
            pass

        usable_width = (PAGE_WIDTH_CM - 2 * MARGIN_CM) * cm

        # Layout the real DOM instead of a flattened text stream, so flex
        # headers, summary boxes, receipt footers and table geometry survive.
        try:
            root, css = _parse_document(html)
            urdu_primary = '<!--ams-urdu-v1-->' in (html or '')
            blocks = layout(root, css, urdu_primary=urdu_primary)
            story = build_story(blocks, body_font, bold_font, _URDU_FONT,
                                usable_width)
        except Exception:
            log.exception('Structured PDF layout failed; using flat text.')
            story = _build_story(_parse_html(html), body_font, bold_font, 7.4)

        buf = io.BytesIO()
        pagesize = (PAGE_WIDTH_CM * cm, PAGE_HEIGHT_CM * cm)
        doc = BaseDocTemplate(
            buf, pagesize=pagesize, title=title,
            leftMargin=MARGIN_CM * cm, rightMargin=MARGIN_CM * cm,
            topMargin=MARGIN_CM * cm, bottomMargin=MARGIN_CM * cm,
        )
        frame = Frame(
            MARGIN_CM * cm, MARGIN_CM * cm,
            (PAGE_WIDTH_CM - 2 * MARGIN_CM) * cm,
            (PAGE_HEIGHT_CM - 2 * MARGIN_CM) * cm,
            id='main',
        )

        def _decorate(canv, _doc):
            canv.saveState()
            canv.setFont(body_font, 6.5)
            canv.setFillColorRGB(0.35, 0.35, 0.35)
            canv.drawString(MARGIN_CM * cm, 0.55 * cm, title)
            canv.drawRightString(
                (PAGE_WIDTH_CM - MARGIN_CM) * cm, 0.55 * cm,
                f'Page {_doc.page}',
            )
            canv.restoreState()

        doc.addPageTemplates([PageTemplate(id='main', frames=[frame], onPage=_decorate)])
        doc.build(story)
        data = buf.getvalue()
        if not data.startswith(b'%PDF-'):
            log.error('ReportLab produced a non-PDF payload; refusing to serve it.')
            return None
        return data
    except Exception:
        log.exception('ReportLab fallback PDF generation failed.')
        return None
