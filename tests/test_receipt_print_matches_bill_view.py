"""The printed bill has to be the bill view, printed.

``view_bill.html`` / ``payment_receipt.html`` are one sheet used three ways:
the page the user reads, the browser's print preview (``action=print``) and the
PDF (WeasyPrint, or the ReportLab fallback which applies ``@media print`` from
the same markup).  These tests pin the print stylesheet that keeps all three on
one sheet:

* the sheet is the 600px screen design scaled by a single factor into the A5
  text block - not each class re-sized by hand in pt;
* the letterhead and the signature block flow with the document instead of
  being ``position: fixed`` above a guessed ``margin-top: 50mm`` (that offset
  only applies to page 1, so on a longer bill the fixed header printed on top
  of page 2's rows and the fixed footer on top of its last rows);
* the design's own font weights survive - the old ``font-weight: 700`` on
  every node made the printed bill visibly heavier than the bill on screen.

The CSS is parsed here with a small local helper so the test needs nothing but
the templates; ``app.services.pdf_layout.Css`` unwraps ``@media print`` the
same way when the ReportLab fallback renders the PDF.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates'
PRINT_SHEET = TEMPLATES / 'partials' / '_receipt_print_css.html'
RECEIPTS = ('view_bill.html', 'payment_receipt.html')

# The screen design and the paper it is printed on.
DESIGN_WIDTH_PX = 600
DESIGN_FONT_PX = 13
DESIGN_FONT_PT = DESIGN_FONT_PX * 0.75          # 13px == 9.75pt

A5_WIDTH_MM = 148.0
PX_PER_MM = 96 / 25.4


def _print_block() -> str:
    """The ``@media print { ... }`` body of the shared sheet, comments gone."""
    text = PRINT_SHEET.read_text(encoding='utf-8')
    text = re.sub(r'\{#.*?#\}', '', text, flags=re.S)          # Jinja comment
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)          # CSS comments
    start = text.index('@media print')
    body_start = text.index('{', start)
    depth = 0
    for i in range(body_start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[body_start + 1:i]
    raise AssertionError('unbalanced @media print block')


def _decls(selector: str) -> dict:
    """Declarations of *selector* inside the print block (last rule wins)."""
    body = _print_block()
    out: dict = {}
    for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', body):
        selectors = [s.strip() for s in match.group(1).split(',')]
        if selector not in selectors:
            continue
        for chunk in match.group(2).split(';'):
            if ':' not in chunk:
                continue
            key, _, value = chunk.partition(':')
            out[key.strip().lower()] = re.sub(
                r'\s*!\s*important\s*$', '', value.strip(), flags=re.I)
    return out


def _pt(value: str) -> float:
    return float(value.replace('pt', '').strip())


def _mm(value: str) -> float:
    return float(value.replace('mm', '').strip())


def _pt_per_px() -> float:
    """Design px -> printed pt, as the sheet itself declares it (8.5 / 13)."""
    return _pt(_decls('.rcpt-wrapper')['font-size']) / DESIGN_FONT_PX


def _scale() -> float:
    """The unitless factor the screen design is shrunk by on paper."""
    return _pt(_decls('.rcpt-wrapper')['font-size']) / DESIGN_FONT_PT


# ---------------------------------------------------------------------------
# the print stylesheet is the one the browser and the PDF fallback see
# ---------------------------------------------------------------------------

def test_both_receipt_templates_render_the_shared_print_sheet():
    include = "{% include 'partials/_receipt_print_css.html' %}"
    for name in RECEIPTS:
        html = (TEMPLATES / name).read_text(encoding='utf-8')
        assert include in html, f'{name} does not print the shared receipt sheet'
        # The @page rule must stay *inline*: page_margins_cm() reads it out of
        # the rendered markup to give the ReportLab PDF the same page.
        assert '@media print' not in html, (
            f'{name} still carries a @media print block of its own next to the '
            'shared sheet'
        )


def test_print_sheet_declares_a_real_a5_page():
    rule = re.search(r'@page\s*\{([^}]*)\}', _print_block())
    assert rule, 'the shared print sheet declares no @page rule'
    decls = {}
    for chunk in rule.group(1).split(';'):
        key, _, value = chunk.partition(':')
        if key.strip():
            decls[key.strip()] = value.strip()
    assert decls.get('size') == 'A5 portrait'
    assert _mm(decls['margin'].split()[0]) > 0, (
        'a zero page margin printed the sheet edge to edge, so the yard '
        'printer clipped the rules'
    )


# ---------------------------------------------------------------------------
# one scale factor: the A5 sheet is the screen design
# ---------------------------------------------------------------------------

def test_the_sheet_is_one_scale_of_the_screen_design():
    scale = _pt_per_px()

    # A design value in the screen CSS and the pt the printed sheet declares:
    # every one has to be the same scaled value, or the printed bill drifts
    # away from the view.
    design = {
        '.rcpt-co-name': 22, '.rcpt-co-sub': 11, '.rcpt-doc-type': 16,
        '.rcpt-doc-no': 14, '.rcpt-doc-date': 10, '.rcpt-party-name': 15,
        '.rcpt-party-label': 9, '.rcpt-section-title': 9, '.rcpt-table': 11.5,
        '.rcpt-table th': 10, '.rcpt-terms': 11, '.rcpt-credits': 9.5,
    }
    for selector, px in design.items():
        printed = _pt(_decls(selector)['font-size'])
        want = px * scale
        assert abs(printed - want) <= 0.15, (
            f'{selector}: printed {printed}pt, the screen design scales to '
            f'{want:.2f}pt'
        )

    # Spacing is scaled by the same factor, not restated in hand-picked mm.
    header_padding = [_pt(v) for v in _decls('.rcpt-header')['padding'].split()]
    assert abs(header_padding[1] - 20 * scale) <= 0.15      # 20px side padding
    assert abs(header_padding[0] - 14 * scale) <= 0.15      # 14px top padding


def test_sheet_width_matches_the_a5_text_block():
    margin = re.search(r'@page\s*\{[^}]*margin\s*:\s*([^;}]+)',
                       _print_block()).group(1)
    side_mm = _mm(margin.split()[0])

    text_width_mm = A5_WIDTH_MM - 2 * side_mm
    design_width_mm = DESIGN_WIDTH_PX / PX_PER_MM * _scale()

    # Within 2%: the width the design is scaled to is the width the sheet has.
    assert abs(text_width_mm - design_width_mm) / design_width_mm < 0.02, (
        f'A5 text block {text_width_mm:.1f}mm vs scaled design '
        f'{design_width_mm:.1f}mm'
    )


# ---------------------------------------------------------------------------
# the two things that made the print look different / broken
# ---------------------------------------------------------------------------

def test_letterhead_and_signatures_flow_with_the_rows():
    body = _print_block()
    for block in ('.rcpt-header', '.rcpt-footer'):
        assert 'position' not in _decls(block), (
            f'{block} is pinned; a fixed header/footer printed on top of the '
            'rows on every page after the first'
        )
    assert not re.search(r'margin-(top|bottom)\s*:\s*\d+mm', body), (
        'the body still reserves a guessed page offset above the rows'
    )
    # A long bill must break cleanly between rows instead.
    for selector in ('.rcpt-table tr', '.rcpt-parties', '.rcpt-detail-box',
                     '.rcpt-sig-row'):
        decls = _decls(selector)
        assert 'break-inside' in decls or 'page-break-inside' in decls, (
            f'{selector} may be split across pages'
        )


def test_print_keeps_the_designs_font_weights():
    body = _print_block()
    for selector, decls_text in re.findall(r'([^{}]+)\{([^{}]*)\}', body):
        if 'font-weight' not in decls_text:
            continue
        selectors = [s.strip() for s in selector.split(',')]
        assert '*' not in selectors, (
            'a blanket font-weight on every node makes the print heavier than '
            f'the bill view: {selector.strip()}'
        )
    assert 'font-weight' not in _decls('.rcpt-co-sub'), (
        'the company address line keeps the 600 weight it has in the bill view'
    )
