"""Structure-preserving layout for the ReportLab PDF fallback.

The original fallback turned rendered HTML into a flat list of paragraphs and
uniform-width tables.  That is fine for a plain report, but the app's receipts
and ledgers (``view_bill``, ``payment_receipt``, ``client_ledger_print``,
``supplier_ledger_print`` ...) are laid out with ``flex`` rows, header blocks,
summary boxes and a footer - and all of that was flattened, so the printed PDF
no longer looked like the page the user designed.

This module holds the pieces needed to keep that layout:

* ``Css``      - a small, dependency-free CSS cascade (specificity + order).
* ``Node``     - the DOM tree produced by :mod:`app.services.pdf_fallback`.
* ``layout``   - flows nodes into "blocks": paragraphs, tables and flex rows.

Nothing here recomputes a business figure; it only reproduces the geometry of
the markup it is given.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_COMMENT = re.compile(r'/\*.*?\*/', re.S)


def _iter_rule_blocks(text):
    """Yield ``(prelude, body)`` for every rule, nesting-aware."""
    depth = 0
    start = 0
    prelude_end = None
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                prelude_end = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and prelude_end is not None:
                yield text[start:prelude_end], text[prelude_end + 1:i]
                prelude_end = None
                start = i + 1
        elif ch == ';' and depth == 0:
            # ``@import``-style statement: skip it
            start = i + 1

_INHERITED = {
    'color', 'font-size', 'font-weight', 'font-style', 'font-family',
    'text-align', 'line-height', 'letter-spacing', 'text-transform',
}

_DEFAULT_FONT_SIZE = 8.2      # pt used by the old fallback for body text
_ROOT_FONT_SIZE = 8.2


def _split_decls(body: str) -> dict:
    """``{"prop": "value"}`` with ``!important`` flags stripped.

    Normalised here so every consumer (length parsing, colour parsing,
    cascade) sees a plain value; ``!important`` only changes which rule wins,
    and the cascade below already orders by specificity then source order.
    """
    out = {}
    for chunk in body.split(';'):
        if ':' not in chunk:
            continue
        key, _, value = chunk.partition(':')
        key = key.strip().lower()
        value = re.sub(r'\s*!\s*important\s*$', '', value.strip(),
                       flags=re.I).strip()
        if key and value:
            out[key] = value
    return out


def _parse_pt(value: str):
    """Parse a CSS length into points (``None`` when it cannot be parsed)."""
    if not value:
        return None
    value = value.strip().lower()
    em = re.fullmatch(r'(-?[\d.]+)\s*em', value)
    if em:
        return float(em.group(1)) * _ROOT_FONT_SIZE
    rem = re.fullmatch(r'(-?[\d.]+)\s*rem', value)
    if rem:
        return float(rem.group(1)) * _ROOT_FONT_SIZE
    pt = re.fullmatch(r'(-?[\d.]+)\s*pt', value)
    if pt:
        return float(pt.group(1))
    px = re.fullmatch(r'(-?[\d.]+)\s*px', value)
    if px:
        return float(px.group(1)) * 0.75
    mm = re.fullmatch(r'(-?[\d.]+)\s*mm', value)
    if mm:
        return float(mm.group(1)) * 72.0 / 25.4
    cm = re.fullmatch(r'(-?[\d.]+)\s*cm', value)
    if cm:
        return float(cm.group(1)) * 72.0 / 2.54
    pct = re.fullmatch(r'(-?[\d.]+)\s*%', value)
    if pct:
        return None      # percentage lengths are not used for type here
    try:
        return float(value) * 0.75      # bare number == px
    except (TypeError, ValueError):
        return None


def _selector_specificity(selector: str):
    """(ids, classes, elements) for one simple selector."""
    ids = len(re.findall(r'#[\w-]+', selector))
    classes = len(re.findall(r'\.[\w-]+', selector))
    classes += len(re.findall(r'\[[^\]]+\]', selector))
    classes += len(re.findall(r':(?!:)[\w-]+', selector))
    elements = len(re.findall(r'(?:^|[\s>+~])([a-zA-Z][\w-]*)', selector))
    return (ids, classes, elements)


class Rule:
    __slots__ = ('selector', 'decls', 'specificity', 'order')

    def __init__(self, selector, decls, order):
        self.selector = selector
        self.decls = decls
        self.order = order
        self.specificity = _selector_specificity(selector)


# Utility classes the templates rely on even though their definitions live in
# bootstrap.min.css, which is not embedded in the printed document.
_UTILITY_DECLS = {
    'text-end': {'text-align': 'right'},
    'text-right': {'text-align': 'right'},
    'text-start': {'text-align': 'left'},
    'text-left': {'text-align': 'left'},
    'text-center': {'text-align': 'center'},
    'text-nowrap': {'white-space': 'nowrap'},
    'fw-bold': {'font-weight': '700'},
    'fw-semibold': {'font-weight': '600'},
    'fw-bolder': {'font-weight': '800'},
    'fst-italic': {'font-style': 'italic'},
    'text-uppercase': {'text-transform': 'uppercase'},
    'text-muted': {'color': '#6b7280'},
}


def _utility_decls(node) -> dict:
    out = {}
    for name in node.classes:
        out.update(_UTILITY_DECLS.get(name) or {})
    return out


def _matches(node, selector: str) -> bool:
    """Match a (simple) selector against a node.

    Only the shapes actually used by the app's print templates are honoured:
    ``tag``, ``.class``, ``#id``, ``tag.class``, comma lists and descendant
    combinators (the right-most compound must match the node; ancestor
    compounds must appear anywhere above it).
    """
    selector = selector.strip()
    if not selector or selector.startswith('@'):
        return False
    if selector in ('*',):
        return True
    parts = re.split(r'\s+', selector)
    if not all(_matches_compound(node, p) for p in [parts[-1]]):
        return False
    ancestors = parts[:-1]
    if not ancestors:
        return True
    current = node.parent
    idx = len(ancestors) - 1
    while current is not None and idx >= 0:
        if _matches_compound(current, ancestors[idx]):
            idx -= 1
        current = current.parent
    return idx < 0


def _matches_compound(node, compound: str) -> bool:
    if not compound or compound == '*':
        return True
    compound = re.split(r'[>+~]', compound)[-1]     # child/sibling -> own part
    tag = re.match(r'^([a-zA-Z][\w-]*)', compound)
    if tag and node.tag != tag.group(1).lower():
        return False
    for name in re.findall(r'\.([\w-]+)', compound):
        if name not in node.classes:
            return False
    for name in re.findall(r'#([\w-]+)', compound):
        if node.attrs.get('id') != name:
            return False
    for name in re.findall(r'\[([\w-]+)(?:=[\'"]?([^\'"\]]*)[\'"]?)?\]', compound):
        key, want = name
        have = node.attrs.get(key.replace('-', '_'))
        if have is None:
            return False
        if want and have != want:
            return False
    return True


class Css:
    """Parsed stylesheets, queried per node."""

    def __init__(self):
        self.rules: list[Rule] = []

    def add_sheet(self, text: str) -> None:
        """Parse a stylesheet.

        ``@media`` blocks are unwrapped rather than dropped: the PDF *is* the
        printed artefact, so ``@media print`` (and the A5 sizing it carries)
        must win.  Bracing is counted by hand because a plain regex cannot
        follow the nesting.
        """
        text = _COMMENT.sub('', text or '')
        for selector_text, body in _iter_rule_blocks(text):
            selectors = selector_text.strip()
            if selectors.startswith('@'):
                # ``@media print`` and ``@media all`` apply; screen-only
                # blocks must not, or the PDF picks up on-screen sizing.
                inner = selectors.lower()
                if inner.startswith('@media') and 'screen' not in inner:
                    self.add_sheet(body)
                continue
            decls = _split_decls(body)
            if not decls:
                continue
            for selector in selectors.split(','):
                selector = selector.strip()
                if not selector or selector.startswith('@'):
                    continue
                self.rules.append(Rule(selector, decls, len(self.rules)))

    def declarations(self, node) -> dict:
        """Cascaded declarations for *node* (inline style wins)."""
        matched = []
        for rule in self.rules:
            if _matches(node, rule.selector):
                matched.append(rule)
        matched.sort(key=lambda r: (r.specificity, r.order))
        out = {}
        for rule in matched:
            out.update(rule.decls)
        out.update(_utility_decls(node))
        inline = _split_decls(node.attrs.get('style') or '')
        out.update(inline)
        return out


# ---------------------------------------------------------------------------
# DOM
# ---------------------------------------------------------------------------

class Node:
    __slots__ = ('tag', 'attrs', 'classes', 'children', 'parent', 'text')

    def __init__(self, tag='div', attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.classes = set((self.attrs.get('class') or '').split())
        self.children: list = []
        self.parent = parent
        self.text = ''

    # -- helpers --------------------------------------------------------
    def append(self, child):
        if isinstance(child, Node):
            child.parent = self
        self.children.append(child)
        return child

    def append_text(self, text: str):
        """Append a text run, merging with a trailing string when possible."""
        if self.children and isinstance(self.children[-1], str):
            self.children[-1] += text
        else:
            self.children.append(text)
        return text

    def iter(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.iter()

    def raw_text(self) -> str:
        """All descendant text, in document order."""
        out = []
        for child in self.children:
            if isinstance(child, Node):
                out.append(child.raw_text())
            else:
                out.append(child)
        return ' '.join(p for p in out if p)

    def __repr__(self):     # pragma: no cover - debugging aid
        return f'<{self.tag} {sorted(self.classes)}>'


def _collapse(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '')


# ---------------------------------------------------------------------------
# Style resolution
# ---------------------------------------------------------------------------

_TONES = {
    'muted': '#4b5563',
    'gray': '#4b5563',
    'secondary': '#4b5563',
    'black': '#000000',
}


def resolve(css: Css, node, inherited=None) -> dict:
    """Compute the effective style of *node* (inheritance + cascade)."""
    base = dict(inherited or {})
    decls = css.declarations(node)

    for prop in _INHERITED:
        if prop in decls:
            base[prop] = decls[prop]

    # ``font-size`` is inherited as a resolved number of points, never as the
    # raw CSS token, so the arithmetic below is always numeric.
    parent_size = base.get('font-size')
    if not isinstance(parent_size, (int, float)):
        parent_size = _parse_pt(str(parent_size or '')) or _DEFAULT_FONT_SIZE
        base['font-size'] = parent_size
    raw_size = (decls.get('font-size') or '').strip().lower()
    if raw_size.endswith('em') and not raw_size.endswith('rem'):
        try:
            base['font-size'] = parent_size * float(raw_size[:-2])
        except ValueError:
            pass
    else:
        size = _parse_pt(raw_size)
        if size:
            base['font-size'] = size
    if not isinstance(base.get('font-size'), (int, float)):
        base['font-size'] = _DEFAULT_FONT_SIZE

    weight = (base.get('font-weight') or 'normal').lower()
    base['bold'] = weight in ('bold', 'bolder', '600', '700', '800', '900')
    base['italic'] = (base.get('font-style') or '').lower() in ('italic', 'oblique')
    align = (base.get('text-align') or '').lower()
    base['align'] = align if align in ('left', 'right', 'center', 'justify') else base.get('align', 'left')
    case = (base.get('text-transform') or '').lower()
    base['upper'] = case == 'uppercase'

    colour = base.get('color') or '#000000'
    if colour.lower() in _TONES:
        colour = _TONES[colour.lower()]
    base['color'] = colour

    # --- box geometry (not inherited) --------------------------------
    padding = decls.get('padding')
    pad = _parse_pt(padding) if padding else None
    for side in ('left', 'right', 'top', 'bottom'):
        value = _parse_pt(decls.get(f'padding-{side}'))
        base[f'pad-{side}'] = value if value is not None else (pad or 0)

    margin = decls.get('margin')
    mar = _parse_pt(margin) if margin else None
    for side in ('left', 'right', 'top', 'bottom'):
        value = _parse_pt(decls.get(f'margin-{side}'))
        if value is None and mar is not None:
            value = mar
        base[f'margin-{side}'] = value or 0

    border = decls.get('border') or ''
    base['rule-below'] = bool(
        re.search(r'border-bottom', ' '.join(decls)) or
        ('border' in decls and re.search(r'\d', border or ''))
    )
    if 'border-bottom' in decls:
        base['rule-below'] = bool(re.search(r'[1-9]', decls['border-bottom']))
    base['box'] = bool(
        re.search(r'[1-9]', decls.get('border', '') or '') or
        any(k in decls for k in ('border-left', 'border-right'))
    )

    display = (decls.get('display') or '').lower()
    base['display'] = display
    base['flex'] = display in ('flex', 'inline-flex')
    base['nowrap'] = (decls.get('white-space') or '').lower() == 'nowrap'

    flex_dir = (decls.get('flex-direction') or '').lower()
    base['column'] = flex_dir.startswith('column')

    weight_justify = (decls.get('justify-content') or '').lower()
    if 'space-between' in weight_justify:
        base['justify'] = 'between'
    elif 'flex-end' in weight_justify or 'right' in weight_justify:
        base['justify'] = 'end'
    elif 'center' in weight_justify:
        base['justify'] = 'center'
    else:
        base['justify'] = base.get('justify') if not base['flex'] else 'start'

    background = (decls.get('background') or decls.get('background-color') or '').lower()
    base['shade'] = False
    if background and 'transparent' not in background:
        match = re.search(r'#([0-9a-f]{3,8})', background)
        if match:
            hexval = match.group(1)
            if len(hexval) == 3:
                hexval = ''.join(c * 2 for c in hexval)
            try:
                r, g, b = (int(hexval[i:i + 2], 16) for i in (0, 2, 4))
                base['shade'] = (r + g + b) / 3 < 246     # ignore near-white
                base['shade_color'] = f'#{hexval[:6]}'
            except ValueError:
                base['shade'] = False

    width = decls.get('width')
    base['width'] = _parse_pt(width) if width else None
    base['flex1'] = (decls.get('flex') or '').strip() in ('1', '1 1 auto', '1 1 0%')

    return base


# ---------------------------------------------------------------------------
# Layout blocks
# ---------------------------------------------------------------------------

class Line:
    """An inline run of text plus the runs nested inside it (``.ur`` spans)."""
    __slots__ = ('text', 'style', 'runs')

    def __init__(self, text, style):
        self.text = text
        self.style = style
        self.runs = []          # [(text, style)] appended after the main text

    def add_run(self, text, style):
        self.runs.append((text, style))


class TableBlock:
    __slots__ = ('rows', 'style', 'render_scale')

    def __init__(self, rows, style):
        self.rows = rows        # [[{'text','style','colspan','header'}...]]
        self.style = style
        self.render_scale = 0.0  # set when the table had to be squeezed


class RowBlock:
    """A flex row: side-by-side cells that must stay on one line."""
    __slots__ = ('cells', 'weights')

    def __init__(self, cells, weights=None):
        self.cells = cells          # [[block, ...]] one list per column
        self.weights = weights or [1.0] * len(cells)


_BLOCK_TAGS = {
    'html', 'body', 'div', 'p', 'section', 'article', 'header', 'footer',
    'main', 'nav', 'aside', 'figure', 'figcaption', 'form', 'fieldset',
    'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'tr',
    'td', 'th', 'blockquote', 'dl', 'dt', 'dd', 'hr', 'br', 'tbody',
    'thead', 'tfoot', 'center',
}


def _is_blockish(node) -> bool:
    return node.tag in _BLOCK_TAGS


def _inline_text(node, css, style) -> str:
    """All descendant text of *node* as one string (Urdu spans excluded)."""
    parts = []

    def walk(item, parent_style):
        if isinstance(item, str):
            parts.append(item)
            return
        if 'ur' in item.classes:
            return
        local = resolve(css, item, parent_style)
        if item.tag in ('br', 'hr'):
            parts.append(' ')
            return
        for child in item.children:
            walk(child, local)

    local = resolve(css, node, style)
    for child in node.children:
        walk(child, local)
    return _collapse(''.join(parts)).strip()


def _apply_case(text: str, style) -> str:
    return text.upper() if style.get('upper') else text


def layout(node, css, style=None, blocks=None):
    """Flow *node*'s children into ``blocks`` (list of layout blocks)."""
    if blocks is None:
        blocks = []
    style = style or resolve(css, node)

    if 'ur' in node.classes:
        return blocks

    display = style.get('display', '')
    if style.get('flex'):
        cells = _flex_cells(node, css, style)
        if len(cells) > 1:
            blocks.append(RowBlock(cells, _flex_weights(node, css, style,
                                                        len(cells))))
            return blocks
        # a single-cell flex container flows like a block
        for cell in cells:
            blocks.extend(cell)
        return blocks

    if node.tag == 'table':
        table = _build_table(node, css, style)
        if table is not None:
            blocks.append(table)
        return blocks

    if node.tag == 'hr':
        blocks.append(Line('', dict(style, rule_below=True)))
        return blocks

    # --- leaf-ish containers -----------------------------------------
    if _has_block_children(node):
        for child in node.children:
            if not isinstance(child, Node):
                continue
            layout(child, css, resolve(css, child, style), blocks)
        return blocks

    text = _inline_text(node, css, style)
    urdu = _urdu_runs(node, css, style)
    if not text and not urdu:
        return blocks
    line = Line(_apply_case(text, style), style)
    for run_text, run_style in urdu:
        line.add_run(run_text, run_style)
    blocks.append(line)
    return blocks


def _flex_cells(node, css, style):
    """Split a flex container into one block list per visual column."""
    columns = []
    for child in node.children:
        if not isinstance(child, Node):
            continue
        child_style = resolve(css, child, style)
        cell_blocks = []
        if child_style.get('flex') and _has_block_children(child):
            cell_blocks = layout(child, css, child_style)
        else:
            cell_blocks = layout(child, css, child_style)
        if cell_blocks:
            columns.append(cell_blocks)
    # ``flex-direction: row`` in an RTL document reverses the visual order
    if 'rtl' in (node.attrs.get('dir') or '').lower():
        columns.reverse()
    return columns


def _flex_weights(node, css, style, count):
    """Relative widths for the flex items of *node*."""
    hints = []
    for child in node.children:
        if not isinstance(child, Node):
            continue
        child_style = resolve(css, child, style)
        width = child_style.get('width')
        hints.append(width if isinstance(width, (int, float)) and width > 0 else None)
    if count and all(h is not None for h in hints[:count]):
        return hints[:count]
    return [1.0] * count


def _has_block_children(node) -> bool:
    for child in node.children:
        if isinstance(child, Node) and _is_blockish(child):
            return True
    return False


def _urdu_runs(node, css, style):
    """``.ur`` descendants as (text, style) pairs, in document order."""
    out = []

    def walk(item):
        if isinstance(item, str):
            return
        if 'ur' in item.classes:
            text = _collapse(item.raw_text()).strip()
            if text:
                out.append((text, resolve(css, item, style)))
            return
        for child in item.children:
            walk(child)

    for child in node.children:
        walk(child)
    return out


def _build_table(node, css, style):
    rows = []
    for row_node in _descend(node, ('thead', 'tbody', 'tfoot', 'tr')):
        if row_node.tag != 'tr':
            continue
        cells = []
        for cell_node in row_node.children:
            if not isinstance(cell_node, Node) or cell_node.tag not in ('td', 'th'):
                continue
            cell_style = resolve(css, cell_node, style)
            text = _apply_case(_inline_text(cell_node, css, cell_style), cell_style)
            urdu = _urdu_runs(cell_node, css, cell_style)
            cells.append({
                'text': text,
                'urdu': urdu,
                'style': cell_style,
                'header': cell_node.tag == 'th',
                'colspan': _int(cell_node.attrs.get('colspan'), 1),
            })
        if cells:
            rows.append(cells)
    if not rows:
        return None
    return TableBlock(rows, style)


def _descend(node, tags):
    """Yield ``tr`` nodes in document order (table sections are transparent)."""
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if child.tag == 'tr':
            yield child
        elif child.tag in tags:
            yield from _descend(child, tags)


def _int(value, default=1):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# ReportLab rendering
# ---------------------------------------------------------------------------

_ALIGN = {'left': 0, 'center': 1, 'right': 2, 'justify': 4}


def _rl_colour(value: str):
    from reportlab.lib import colors
    try:
        if value.startswith('#') and len(value) in (4, 7):
            return colors.HexColor(value if len(value) == 7 else
                                   '#' + ''.join(c * 2 for c in value[1:]))
        return colors.HexColor('#000000')
    except Exception:
        return colors.HexColor('#000000')


def _escape(text: str) -> str:
    return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _style_sheet(style, body_font, bold_font, urdu_font):
    """ParagraphStyle for a resolved CSS style."""
    from reportlab.lib.styles import ParagraphStyle

    size = float(style.get('font-size') or _DEFAULT_FONT_SIZE)
    bold = style.get('bold')
    font = bold_font if bold else body_font
    if style.get('italic'):
        font = body_font
    leading = float(style.get('line-height-pt') or 0) or size * 1.28
    return ParagraphStyle(
        f'pdf_{id(style)}',
        fontName=font,
        fontSize=size,
        leading=leading,
        alignment=_ALIGN.get(style.get('align'), 0),
        textColor=_rl_colour(style.get('color')),
        spaceBefore=0,
        spaceAfter=float(style.get('margin-bottom') or 0),
        leftIndent=0,
        rightIndent=0,
        wordWrap='LTR',
    )


def _inline_markup(line: Line, bold_font: str, urdu_font: str | None,
                   urdu_factor: float) -> str:
    """ReportLab inline markup for one line, with the Urdu runs appended."""
    body = _escape(line.text)
    for text, run_style in line.runs:
        if not urdu_font or not text:
            continue
        body += ' ' + _urdu_markup(text, run_style, urdu_font, urdu_factor)
    return body


def _urdu_markup(text, run_style, urdu_font, urdu_factor=1.0) -> str:
    """Shaped Urdu in Jameel Noori at a readable size."""
    from app.services.bilingual import shape_urdu, urdu_size_for_html
    shaped = _escape(shape_urdu(text))
    base = float(run_style.get('font-size') or 7.4) * urdu_factor
    size = urdu_size_for_html(base)
    return (f'<font face="{urdu_font}" size="{size}" '
            f'color="#4b5563">{shaped}</font>')


def build_story(blocks, body_font, bold_font, urdu_font, usable_width):
    """Turn layout blocks into ReportLab flowables."""
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    story = []
    for block in blocks:
        try:
            _append_block(block, story, body_font, bold_font, urdu_font,
                          usable_width)
        except Exception:      # never lose the document over one bad block
            import logging
            logging.getLogger(__name__).exception(
                'Skipped a PDF block that could not be laid out')
    return story


def _append_block(block, story, body_font, bold_font, urdu_font, usable_width):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    if isinstance(block, Line):
        if not block.text and not block.runs:
            story.append(Spacer(1, 2))
            return story
        pstyle = _style_sheet(block.style, body_font, bold_font, urdu_font)
        markup = _inline_markup(block, bold_font, urdu_font, 1.0)
        story.append(Paragraph(markup, pstyle))
        if block.style.get('rule-below'):
            story.append(_rule(usable_width, block.style, colors))
    elif isinstance(block, TableBlock):
        story.append(_render_table(block, body_font, bold_font, urdu_font,
                                   usable_width, colors, Paragraph, Table,
                                   TableStyle))
        story.append(Spacer(1, 3))
    elif isinstance(block, RowBlock):
        story.append(_render_row(block, body_font, bold_font, urdu_font,
                                 usable_width, colors, Paragraph, Table,
                                 TableStyle))
        story.append(Spacer(1, 3))
    return story


def _rule(width, style, colors):
    from reportlab.platypus import Table, TableStyle
    thickness = 1.0 if style.get('bold') else 0.6
    table = Table([['']], colWidths=[width], rowHeights=[0.1], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), thickness, colors.HexColor('#000000')),
    ]))
    return table


def _render_table(block, body_font, bold_font, urdu_font, usable_width,
                  colors, Paragraph, Table, TableStyle):
    from app.services.bilingual import shape_urdu, urdu_size_for_html

    ncols = max(sum(c['colspan'] for c in row) for row in block.rows)
    col_widths = _column_widths(block, ncols, usable_width, body_font,
                                bold_font)
    data, styles = [], []
    for r, row in enumerate(block.rows):
        out = []
        col_index = 0
        for cell in row:
            style = cell['style']
            markup = _escape(cell['text'])
            run_markup = ''
            for text, _run_style in cell['urdu']:
                if not urdu_font or not text:
                    continue
                size = urdu_size_for_html(float(style.get('font-size')
                                                or _DEFAULT_FONT_SIZE))
                run_markup += (f'<font face="{urdu_font}" size="{size}">'
                               f'{_escape(shape_urdu(text))}</font>')
            if run_markup:
                available = (col_widths[col_index]
                             if col_index < len(col_widths) else usable_width)
                markup += _urdu_separator(cell, style, run_markup,
                                          available - 2, body_font, bold_font)
            if not markup:
                markup = '&nbsp;'
            pstyle = _style_sheet(style, body_font, bold_font, urdu_font)
            if block.render_scale and block.render_scale < 1.0:
                pstyle.fontSize *= block.render_scale
            pstyle.leading = max(pstyle.fontSize * 1.24, pstyle.leading)
            out.append(Paragraph(markup, pstyle))
            if cell['header']:
                styles.append(('BACKGROUND', (len(out) - 1, r),
                               (len(out) - 1, r), colors.HexColor('#eceff1')))
            if style.get('align') == 'right':
                styles.append(('ALIGN', (len(out) - 1, r),
                               (len(out) - 1, r), 'RIGHT'))
            out.extend([''] * (cell['colspan'] - 1))
            col_index += cell['colspan']
        while len(out) < ncols:
            out.append('')
        data.append(out)
    if not data:
        return Table([['']], colWidths=[usable_width], hAlign='LEFT')

    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#8b8f96')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2.5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2.5),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ] + styles))
    return table


def _urdu_separator(cell, style, run_markup, available, body_font,
                    bold_font=None):
    """Space before the Urdu run, or ``<br/>`` when it will not fit inline.

    Splitting a currency figure across two lines ("600,000" / ".00") is far
    worse than dropping the translation onto its own line, so the separator is
    chosen from the measured width of both runs against the column width.
    """
    from reportlab.pdfbase import pdfmetrics
    if not available or available <= 0:
        return ' ' + run_markup
    face = bold_font if (bold_font and style.get('bold')) else body_font
    size = float(style.get('font-size') or _DEFAULT_FONT_SIZE)
    try:
        need = (pdfmetrics.stringWidth(cell['text'] or '', face, size) + 3.0 +
                pdfmetrics.stringWidth(_strip_markup(run_markup), face,
                                       size * 1.08))
    except Exception:
        return ' ' + run_markup
    return ('<br/>' if need > available else ' ') + run_markup


def _strip_markup(markup: str) -> str:
    return re.sub(r'<[^>]+>', '', markup or '')


def _column_widths(block, ncols, usable_width, body_font, bold_font=None):
    """Column widths from the longest unbreakable token in each column.

    Text that cannot wrap (dates, bill numbers, amounts) sets a hard minimum;
    the remaining space is shared in proportion to how much each column wants
    to say, so a wide description column still gets the room it needs.
    """
    from reportlab.pdfbase import pdfmetrics

    wants = [1.0] * ncols
    minimums = [1.0] * ncols
    for row in block.rows:
        index = 0
        for cell in row:
            if index >= ncols:
                break
            style = cell['style']
            size = float(style.get('font-size') or _DEFAULT_FONT_SIZE)
            face = bold_font if (bold_font and style.get('bold')) else body_font
            text = cell['text'] or ''
            tokens = text.split() or ['']
            longest = max((pdfmetrics.stringWidth(t, face, size)
                           for t in tokens), default=0.0)
            whole = pdfmetrics.stringWidth(text, face, size)
            pad = 7.0
            if style.get('nowrap'):
                minimums[index] = max(minimums[index], whole + pad)
                wants[index] = max(wants[index], whole + pad)
            else:
                minimums[index] = max(minimums[index], longest + pad)
                wants[index] = max(wants[index],
                                   min(whole + pad, usable_width * 0.34))
            index += cell['colspan']

    total_min = sum(minimums) or 1.0
    if total_min > usable_width:
        # The table needs more room than the sheet has (very dense ledgers on
        # A5).  Fit the columns to the page proportionally and flag the block
        # so the renderer shrinks the type instead of letting figures wrap.
        block.render_scale = usable_width / total_min
        return [m * block.render_scale for m in minimums]

    spare = usable_width - total_min
    extra_wanted = [max(0.0, w - m) for w, m in zip(wants, minimums)]
    total_extra = sum(extra_wanted)
    if total_extra <= 0:
        return [m + spare * (m / total_min) for m in minimums]
    return [m + spare * (e / total_extra)
            for m, e in zip(minimums, extra_wanted)]


def _render_row(block, body_font, bold_font, urdu_font, usable_width,
                colors, Paragraph, Table, TableStyle):
    """Render a flex row as a borderless table of side-by-side stories."""
    weights = block.weights or [1.0] * len(block.cells)
    total = sum(weights) or 1.0
    widths = [usable_width * (w / total) for w in weights]
    cells = []
    for column, width in zip(block.cells, widths):
        inner = build_story(column, body_font, bold_font, urdu_font,
                            width - 4)
        if inner:
            nest = Table([[item] for item in inner],
                         colWidths=[width - 4], hAlign='LEFT')
            nest.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            cells.append(nest)
        else:
            cells.append('')
    if not cells:
        return Table([['']], colWidths=[usable_width], hAlign='LEFT')
    outer = Table([cells], colWidths=widths, hAlign='LEFT')
    outer.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return outer
