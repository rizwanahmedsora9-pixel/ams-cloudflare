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
    'text-align', 'line-height', 'letter-spacing', 'text-transform', 'direction',
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
    # Structural pseudo-classes cannot be evaluated on this DOM.  ``:first-child``
    # used to compare literally and never matched, which silently dropped rules
    # such as ``.rcpt-table td.bill-no { white-space: nowrap }`` -- so bill
    # numbers wrapped.  Dropping the pseudo-class matches the element instead.
    compound = re.sub(r'::?[\w-]+(?:\([^)]*\))?', '', compound)
    if not compound:
        return True
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


def _box_values(value):
    """``(top, right, bottom, left)`` in points for a CSS box shorthand.

    ``padding: 14px 20px 10px`` (the receipt header) is expanded the CSS way;
    a single value applies to all four sides.  ``None`` means "not set".
    """
    if not value:
        return (0.0, 0.0, 0.0, 0.0)
    parts = [_parse_pt(p) for p in str(value).split() if p.strip()]
    parts = [p or 0.0 for p in parts]
    if not parts:
        return (0.0, 0.0, 0.0, 0.0)
    if len(parts) == 1:
        top = right = bottom = left = parts[0]
    elif len(parts) == 2:
        top, right = parts
        bottom, left = top, right
    elif len(parts) == 3:
        top, right, bottom = parts
        left = right
    else:
        top, right, bottom, left = parts[:4]
    return (top, right, bottom, left)


def _border_width(value):
    """Border thickness in points from ``2.5px solid #000`` (0 when absent)."""
    match = re.search(r'(\d+(?:\.\d+)?)\s*(px|pt|mm|cm)?', str(value or ''))
    if not match:
        return 0.0
    size = _parse_pt(match.group(1) + (match.group(2) or 'px'))
    return float(size or 0.0)


def _border_colour(value):
    match = re.search(r'#([0-9a-fA-F]{3,8})', str(value or ''))
    if not match:
        return '#000000'
    hexval = match.group(1)
    if len(hexval) == 3:
        hexval = ''.join(c * 2 for c in hexval)
    return '#' + hexval[:6]


def resolve(css: Css, node, inherited=None) -> dict:
    """Compute the effective style of *node* (inheritance + cascade)."""
    base = dict(inherited or {})
    decls = css.declarations(node)

    # ``padding`` / ``margin`` / borders are inherited through ``base`` above
    # only because ``base`` starts as a copy of the parent style.  They are
    # *not* inherited properties in CSS, so a header with a 3px bottom border
    # must not stamp that rule under every one of its descendants.
    for side in ('top', 'right', 'bottom', 'left'):
        base[f'pad-{side}'] = 0.0
        base[f'margin-{side}'] = 0.0
    base['rule-below'] = False
    base['box'] = False
    base['border-width'] = 0.0
    base['shade'] = False
    base['width'] = None
    base['flex1'] = False
    base['justify'] = None
    base['column'] = False

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

    direction = (decls.get('direction') or node.attrs.get('dir') or
                 base.get('direction') or 'ltr').strip().lower()
    base['direction'] = direction
    base['rtl'] = direction == 'rtl'

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
    # ``padding: 14px 20px 10px`` is a *list*; the first value is the vertical
    # padding and the second the horizontal one, so both are unpacked instead
    # of "unparseable -> 0".
    pad_top, pad_right, pad_bottom, pad_left = _box_values(decls.get('padding'))
    for side, value in (('top', pad_top), ('right', pad_right),
                        ('bottom', pad_bottom), ('left', pad_left)):
        explicit = _parse_pt(decls.get(f'padding-{side}'))
        base[f'pad-{side}'] = explicit if explicit is not None else value

    mar_top, mar_right, mar_bottom, mar_left = _box_values(decls.get('margin'))
    for side, value in (('top', mar_top), ('right', mar_right),
                        ('bottom', mar_bottom), ('left', mar_left)):
        explicit = _parse_pt(decls.get(f'margin-{side}'))
        if explicit is None:
            explicit = _parse_pt(decls.get('margin-block-start' if side == 'top'
                                           else 'margin-block-end'
                                           if side == 'bottom' else ''))
        base[f'margin-{side}'] = explicit if explicit is not None else value

    border = decls.get('border') or ''
    # A rule is only drawn under a line when the bottom border is really set;
    # the previous heuristic also fired on ``border: 2.5px solid`` (the
    # document title badge) and painted a stray line over the header.
    base['rule-below'] = bool(
        re.search(r'[1-9]', str(decls.get('border-bottom', '') or '')) or
        re.search(r'[1-9]', str(decls.get('border-block-end', '') or ''))
    )
    base['box'] = bool(
        re.search(r'[1-9]', str(decls.get('border', '') or '')) or
        any(re.search(r'[1-9]', str(decls.get(k) or ''))
            for k in ('border-left', 'border-right', 'border-top',
                      'border-bottom')))
    base['border-width'] = _border_width(decls.get('border') or
                                         decls.get('border-bottom') or '')
    base['border-color'] = _border_colour(decls.get('border') or
                                          decls.get('border-bottom') or '')
    base['shade_color'] = '#ffffff'

    display = (decls.get('display') or '').lower()
    base['display'] = display
    base['flex'] = display in ('flex', 'inline-flex')
    base['nowrap'] = (decls.get('white-space') or '').lower() == 'nowrap'

    flex_dir = (decls.get('flex-direction') or '').lower()
    base['column'] = flex_dir.startswith('column')

    weight_justify = (decls.get('justify-content') or '').lower()
    base['justify-self'] = {
        'flex-start': 'left', 'start': 'left', 'left': 'left',
        'flex-end': 'right', 'end': 'right', 'right': 'right',
        'center': 'center',
    }.get(weight_justify)
    if base['justify-self'] is None:
        # An RTL document starts at the right edge, exactly like the browser
        # layout the receipt template was designed against.
        base['justify-self'] = 'right' if base['rtl'] else 'left'
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
    """An inline run of text plus the runs nested inside it (``.ur`` spans).

    ``ordered`` is used by single-language Urdu bills: segments stay in visual
    document order instead of appending every Urdu span after the Latin text.
    """
    __slots__ = ('text', 'style', 'runs', 'ordered')

    def __init__(self, text, style):
        self.text = text
        self.style = style
        self.runs = []          # [(text, style)] appended after the main text
        self.ordered = None     # [(text, style, is_urdu)] for Urdu-only bills

    def add_run(self, text, style):
        self.runs.append((text, style))


class TableBlock:
    __slots__ = ('rows', 'style', 'render_scale', 'rtl')

    def __init__(self, rows, style, rtl=False):
        self.rows = rows        # [[{'text','style','colspan','header'}...]]
        self.style = style
        self.rtl = bool(rtl)     # mirrored column order (Urdu documents)
        self.render_scale = 0.0  # set when the table had to be squeezed


class RowBlock:
    """A flex row: side-by-side cells that must stay on one line."""
    __slots__ = ('cells', 'weights', 'rtl')

    def __init__(self, cells, weights=None, rtl=False):
        self.cells = cells          # [[block, ...]] one list per column
        self.weights = weights or [1.0] * len(cells)
        self.rtl = bool(rtl)


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


def layout(node, css, style=None, blocks=None, urdu_primary=False):
    """Flow *node*'s children into ``blocks`` (list of layout blocks).

    ``urdu_primary`` is set for single-language Urdu bills.  In that mode the
    ``.ur`` spans are the document text (not optional translations appended
    after an English line), so they are kept in inline order and measured.
    """
    if blocks is None:
        blocks = []
    style = style or resolve(css, node)

    if 'ur' in node.classes and not urdu_primary:
        return blocks

    display = style.get('display', '')
    if style.get('flex'):
        cells = _flex_cells(node, css, style)
        if len(cells) > 1:
            weights = _flex_weights(node, css, style, len(cells))
            blocks.append(RowBlock(cells, weights, rtl=bool(style.get('rtl'))))
            return blocks
        # a single-cell flex container flows like a block
        for cell in cells:
            blocks.extend(cell)
        return blocks

    if node.tag == 'table':
        table = _build_table(node, css, style, urdu_primary=urdu_primary)
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
            layout(child, css, resolve(css, child, style), blocks,
                   urdu_primary=urdu_primary)
        return blocks

    if urdu_primary:
        segments = _ordered_segments(node, css, style)
        text = _collapse(''.join(t for t, _s, _u in segments)).strip()
        if not text:
            return blocks
        line = Line(_apply_case(text, style), style)
        line.ordered = segments
        blocks.append(line)
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
        cell_blocks = layout(child, css, child_style,
                             urdu_primary=style.get('rtl', False))
        if cell_blocks:
            columns.append(cell_blocks)
    # NOTE: ``flex-direction: row`` in an RTL document starts at the right
    # edge; :func:`_render_row` reverses the columns once, from ``RowBlock.rtl``.
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


def _ordered_segments(node, css, style):
    """Inline segments in document order, marking Urdu spans for shaping."""
    out = []
    if 'ur' in node.classes:
        text = _collapse(node.raw_text()).strip()
        return [(text, resolve(css, node, style), True)] if text else []

    def walk(item, parent_style):
        if isinstance(item, str):
            if item:
                out.append((item, parent_style, False))
            return
        local = resolve(css, item, parent_style)
        if 'ur' in item.classes:
            text = _collapse(item.raw_text()).strip()
            if text:
                out.append((text, local, True))
            return
        if item.tag in ('br', 'hr'):
            out.append((' ', local, False))
            return
        for child in item.children:
            walk(child, local)

    local = resolve(css, node, style)
    for child in node.children:
        walk(child, local)
    return out


def _build_table(node, css, style, urdu_primary=False):
    rows = []
    for row_node in _descend(node, ('thead', 'tbody', 'tfoot', 'tr')):
        if row_node.tag != 'tr':
            continue
        cells = []
        for cell_node in row_node.children:
            if not isinstance(cell_node, Node) or cell_node.tag not in ('td', 'th'):
                continue
            cell_style = resolve(css, cell_node, style)
            if urdu_primary or cell_style.get('rtl'):
                segments = _ordered_segments(cell_node, css, cell_style)
                text = _collapse(''.join(t for t, _s, _u in segments)).strip()
                urdu = []
            else:
                segments = None
                text = _inline_text(cell_node, css, cell_style)
                urdu = _urdu_runs(cell_node, css, cell_style)
            cells.append({
                'text': _apply_case(text, cell_style),
                'urdu': urdu,
                'ordered': segments,
                'style': cell_style,
                'header': cell_node.tag == 'th',
                'colspan': _int(cell_node.attrs.get('colspan'), 1),
            })
        if cells:
            rows.append(cells)
    if not rows:
        return None
    # ``direction: rtl`` mirrors the columns; :func:`_render_table` flips the
    # cells (keeping ``colspan`` groups intact) so the first markup column is
    # printed on the right edge.
    return TableBlock(rows, style, rtl=bool(style.get('rtl')))


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


def _style_sheet(style, body_font, bold_font):
    """ParagraphStyle for a resolved CSS style (Latin text)."""
    from reportlab.lib.styles import ParagraphStyle

    size = float(style.get('font-size') or _DEFAULT_FONT_SIZE)
    font = bold_font if style.get('bold') else body_font
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


def _urdu_size(style) -> float:
    """Point size used for an Urdu run inside a cell/paragraph."""
    from app.services.bilingual import urdu_size_for_html
    return urdu_size_for_html(float(style.get('font-size') or _DEFAULT_FONT_SIZE))


def _paragraph(segments, style, body_font, bold_font, available=None):
    """Build the right flowable for *segments* (``[(text, style, is_urdu)]``).

    Latin-only content keeps the classic ReportLab ``Paragraph`` (cheap,
    fully featured).  Anything that contains shaped Urdu goes through
    :class:`app.services.urdu_text.UrduParagraph`, which draws each glyph at
    the position HarfBuzz gave it - without that, Nastaleeq marks collapse
    onto the baseline and the words read as gibberish.
    """
    from app.services import urdu_text as U
    from reportlab.platypus import Paragraph

    base_size = float(style.get('font-size') or _DEFAULT_FONT_SIZE)
    colour = style.get('color') or '#000000'
    bold = bool(style.get('bold'))
    font = bold_font if bold else body_font
    align = style.get('align') if style.get('align') in _ALIGN else 'left'

    if align == 'left' and style.get('rtl'):
        # RTL text starts at the right edge unless the template pins an
        # explicit alignment (``.text-end`` on totals stays right).
        align = style.get('justify-self') or 'right'

    has_urdu = any(is_urdu for _t, _s, is_urdu in segments)
    if not has_urdu:
        markup = ''.join(_escape(text) for text, _s, _u in segments if text)
        pstyle = _style_sheet(style, body_font, bold_font)
        return Paragraph(markup or '&nbsp;', pstyle)

    spans = []
    for text, seg_style, is_urdu in segments:
        if not text:
            continue
        size = (_urdu_size(seg_style) if is_urdu
                else float(seg_style.get('font-size') or base_size))
        seg_colour = seg_style.get('color') or colour
        seg_bold = bool(seg_style.get('bold'))
        spans.append(U.Span(
            text,
            urdu=is_urdu,
            font=(bold_font if seg_bold else body_font),
            size=size,
            color=seg_colour,
            bold=seg_bold,
            nowrap=bool(seg_style.get('nowrap')),
        ))
    leading = None
    if any(s.urdu for s in spans):
        from app.services.bilingual import urdu_line_factor
        leading = urdu_line_factor(max(s.size for s in spans))
    return U.UrduParagraph(
        spans,
        leading=leading,
        align=align,
        color=colour,
        style=style,
    )


def _segments_for_line(line: Line):
    """``[(text, style, is_urdu)]`` for a
    :class:`Line` built by :func:`layout`."""
    if line.ordered is not None:
        return [(text, style, bool(is_urdu))
                for text, style, is_urdu in line.ordered if text]
    segments = [(line.text, line.style, False)]
    for text, run_style in line.runs:
        segments.append((text, run_style, True))
    return [s for s in segments if s[0]]


def _segments_for_cell(cell):
    if cell.get('ordered') is not None:
        return [(text, style, bool(is_urdu))
                for text, style, is_urdu in cell['ordered'] if text]
    segments = [(cell['text'], cell['style'], False)]
    for text, run_style in cell.get('urdu', []):
        segments.append((text, run_style, True))
    return [s for s in segments if s[0]]


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
            # A single bad flowable must not silently erase a section of the
            # document: keep its text as a plain line instead.
            try:
                story.extend(_fallback_flowables(block, body_font))
            except Exception:
                pass
    return story


def _fallback_flowables(block, body_font):
    """Best-effort plain-text rendering of a block that failed to lay out."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    texts = []
    if isinstance(block, Line):
        texts = [block.text] + [text for text, _s in block.runs]
        if block.ordered:
            texts = [''.join(t for t, _s, _u in block.ordered)]
    elif isinstance(block, (TableBlock,)):
        for row in block.rows:
            texts.append('   '.join(c.get('text') or '' for c in row))
    elif isinstance(block, RowBlock):
        return []
    style = ParagraphStyle('pdfFallback', fontName=body_font, fontSize=7.5,
                           leading=10)
    return [Paragraph(_escape(t), style) for t in texts if (t or '').strip()]


def _append_block(block, story, body_font, bold_font, urdu_font, usable_width):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    if isinstance(block, Line):
        segments = _segments_for_line(block)
        if not segments:
            story.append(Spacer(1, 2))
            return story
        story.append(_paragraph(segments, block.style, body_font, bold_font,
                                usable_width))
        if block.style.get('rule-below'):
            # Honour the box's bottom padding: Nastaleeq descenders hang well
            # below the baseline, and without the gap the rule cuts through
            # the last word of the heading.
            from reportlab.platypus import Spacer
            pad = float(block.style.get('pad-bottom') or 0)
            urdu_line = any(is_urdu for _t, _s, is_urdu in segments)
            story.append(Spacer(1, max(pad, 2.0 if urdu_line else 0.5)))
            story.append(_rule(usable_width, block.style, colors))
        return story
    if isinstance(block, TableBlock):
        story.append(_render_table(block, body_font, bold_font, urdu_font,
                                   usable_width, colors, Paragraph, Table,
                                   TableStyle))
        story.append(Spacer(1, 3))
        return story
    if isinstance(block, RowBlock):
        story.append(_render_row(block, body_font, bold_font, urdu_font,
                                 usable_width, colors, Paragraph, Table,
                                 TableStyle))
        story.append(Spacer(1, 3))
        return story
    return story


def _rule(width, style, colors):
    from reportlab.platypus import Table, TableStyle
    thickness = float(style.get('border-width') or 0) or (
        1.0 if style.get('bold') else 0.6)
    colour = style.get('border-color') or '#000000'
    table = Table([['']], colWidths=[max(width, 1)], rowHeights=[0.1],
                  hAlign='LEFT')
    table.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), min(thickness, 3.0),
         _rl_colour(colour)),
    ]))
    return table


def _render_table(block, body_font, bold_font, urdu_font, usable_width,
                  colors, Paragraph, Table, TableStyle):
    ncols = max(sum(c['colspan'] for c in row) for row in block.rows)
    col_widths = _column_widths(block, ncols, usable_width, body_font,
                                bold_font, urdu_font)
    rows = block.rows
    if block.rtl:
        # An RTL table mirrors its columns: the first cell of the markup lands
        # in the right-most column.  ``colspan`` cells keep their span, and
        # every ``ALIGN`` column index is mirrored at the end.
        rows = [_mirror_row(row, ncols) for row in rows]
    data, styles = [], []
    for r, row in enumerate(rows):
        out = []
        col_index = 0
        for cell in row:
            if cell is None:            # covered by a mirrored colspan
                out.append('')
                col_index += 1
                continue
            style = cell['style']
            segments = _segments_for_cell(cell)
            span = max(1, int(cell.get('colspan', 1)))
            span_widths = col_widths[col_index:col_index + span]
            available = sum(span_widths) if span_widths else usable_width
            if block.render_scale and block.render_scale < 1.0:
                # Dense table: shrink the type *before* the paragraph is built.
                # Scaling afterwards leaves ReportLab's cached fragments and
                # line breaks at the old size, so a figure that now fits still
                # wrapped mid-number.
                style = _scaled_style(style, block.render_scale)
            flowable = _paragraph(segments, style, body_font, bold_font,
                                  available - 2)
            out.append(flowable)
            for _ in range(span - 1):
                out.append('')
            if span > 1:
                # Real merge so ReportLab hands the full width to the
                # flowable; without the SPAN the label wraps inside the first
                # column and spills out of the table.
                # Rows are already mirrored, so ``col_index`` is the
                # physical (left-to-right) start of this cell.
                styles.append(('SPAN', (col_index, r),
                               (col_index + span - 1, r)))
            if cell['header']:
                styles.append(('BACKGROUND', (col_index, r),
                               (col_index + span - 1, r),
                               colors.HexColor('#eceff1')))
            if isinstance(flowable, Paragraph) and (
                    getattr(flowable.style, 'wordWrap', '') == 'RTL' or
                    block.rtl):
                # A Latin-only cell inside an RTL table can still be a label
                # (e.g. a colspan summary row): align it with the Urdu cells
                # instead of stranding it on the wrong edge.
                flowable.style.alignment = _ALIGN['right']
            cell_align = flowable.style.alignment if isinstance(flowable, Paragraph) \
                else _ALIGN.get(getattr(flowable, 'align', 'left'), 0)
            # ``col_index`` is already a physical column of the mirrored row;
            # deriving it from the cell count is wrong once a row carries a
            # span (the count stops matching the column index).
            column = col_index
            if style.get('align') == 'right' or (
                    style.get('rtl') and cell_align == 0
                    and style.get('justify-self') == 'right'):
                styles.append(('ALIGN', (column, r), (column, r), 'RIGHT'))
            elif cell_align == _ALIGN['center']:
                styles.append(('ALIGN', (column, r), (column, r), 'CENTER'))
            col_index += span
        while len(out) < ncols:
            out.append('')
        data.append(out)
    if not data:
        return Table([['']], colWidths=[usable_width], hAlign='LEFT')
    # ``colspan`` placeholders make the row lists *shorter* than the cell
    # count (a 2-cell ``colspan=3`` row is one placeholder plus one value).
    # ReportLab then treats the row as having variable width and sizes the
    # table from the cells, appending columns -- the extra blank strip on the
    # right of the bill.  Pad every row to exactly ``ncols`` first.
    for out in data:
        while len(out) < ncols:
            out.append('')
        del out[ncols:]

    # Pin the geometry.  ReportLab treats a column holding a flowable whose
    # width cannot be derived from string metrics as "variable width" and then
    # re-sizes *every* column from the cells' ``minWidth()`` -- which is how a
    # BILL # column ended up narrower than ``MB NO.7001`` and wrapped it, and
    # how the table grew past the printable area.
    col_widths = [float(w) for w in list(col_widths[:ncols])]
    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign='LEFT')
    table._argW = list(col_widths)
    table._ncols = ncols
    table._colWidths = list(col_widths)
    table._colpositions = [0.0]
    total = 0.0
    for width in col_widths:
        total += width
        table._colpositions.append(total)
    table._width = total
    table._width_calculated_once = 1
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#8b8f96')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2.5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2.5),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ] + styles))
    return table


def _mirror_row(row, ncols):
    """Cells of *row* in mirrored order, with ``None`` for span placeholders."""
    out = []
    for cell in reversed(row):
        out.append(cell)
        out.extend([None] * (cell.get('colspan', 1) - 1))
    if len(out) != ncols:
        out = out[:ncols] + [None] * max(0, ncols - len(out))
    return out


def _scaled_style(style, factor):
    """Copy of *style* with its type sizes multiplied by *factor*."""
    scaled = dict(style)
    for key in ('font-size', 'line-height-pt'):
        value = scaled.get(key)
        if value:
            scaled[key] = float(value) * factor
    return scaled


def _strip_markup(markup: str) -> str:
    return re.sub(r'<[^>]+>', '', markup or '')


def _column_widths(block, ncols, usable_width, body_font, bold_font=None,
                   urdu_font=None):
    """Column widths from the longest unbreakable token in each column.

    Text that cannot wrap (dates, bill numbers, amounts) sets a hard minimum;
    the remaining space is shared in proportion to how much each column wants
    to say, so a wide description column still gets the room it needs.
    """
    from reportlab.pdfbase import pdfmetrics
    from app.services import urdu_text as U

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
            segments = _segments_for_cell(cell)
            latin = ''.join(t for t, _s, u in segments if not u)
            urdu = ' '.join(t for t, _s, u in segments if u)
            whole = U.latin_width(latin, face, size)
            if urdu:
                usize = _urdu_size(style)
                uwidth = U.measure_run(urdu, usize)
                whole += uwidth + (2.0 if latin.strip() else 0.0)
                longest = max(U.latin_width(max(latin.split(), key=len,
                                                default=''), face, size),
                              uwidth)
            else:
                longest = max((U.latin_width(t, face, size)
                               for t in (latin.split() or [''])), default=0.0)
            if style.get('nowrap'):
                minimums[index] = max(minimums[index], whole)
                wants[index] = max(wants[index], whole)
            else:
                minimums[index] = max(minimums[index], longest)
                wants[index] = max(wants[index],
                                   min(whole, usable_width * 0.34))
            index += cell['colspan']

    # Cell padding is constant: it must stay out of the shrink calculation, or
    # the scaled type still does not fit the scaled column and figures wrap
    # mid-number ("600,000.0" / "0").
    pad = 5.5
    padding = pad * ncols
    room = max(usable_width - padding, 1.0)
    total_min = sum(minimums) or 1.0
    if total_min > room:
        # The table needs more room than the sheet has (very dense ledgers on
        # A5).  Shrink the type and flag the block so the renderer scales the
        # flowables to match instead of letting figures wrap.
        block.render_scale = room / total_min
        return [m * block.render_scale + pad for m in minimums]

    spare = room - total_min
    extra_wanted = [max(0.0, w - m) for w, m in zip(wants, minimums)]
    total_extra = sum(extra_wanted)
    if total_extra <= 0:
        return [m + spare * (m / total_min) + pad for m in minimums]
    return [m + spare * (e / total_extra) + pad
            for m, e in zip(minimums, extra_wanted)]


def _segments_width(segments, face, size, urdu_font):
    from app.services import urdu_text as U
    total = 0.0
    for text, style, is_urdu in segments:
        if not text:
            continue
        if is_urdu:
            total += U.measure_run(text, _urdu_size(style or {}))
        else:
            total += U.latin_width(text, face, size)
    return total


def _render_row(block, body_font, bold_font, urdu_font, usable_width,
                colors, Paragraph, Table, TableStyle):
    """Render a flex row as a borderless table of side-by-side stories."""
    weights = block.weights or [1.0] * len(block.cells)
    total = sum(weights) or 1.0
    widths = [usable_width * (w / total) for w in weights]
    cells = []
    columns = block.cells
    if block.rtl:
        # ``flex-direction: row`` inside an RTL document lays the first item
        # out at the right edge; the PDF table runs left-to-right.
        columns = list(reversed(columns))
        widths = list(reversed(widths))
    for column, width in zip(columns, widths):
        inner = build_story(column, body_font, bold_font, urdu_font,
                            max(width - 4, 4))
        if inner:
            nest = Table([[item] for item in inner],
                         colWidths=[max(width - 4, 4)], hAlign='LEFT')
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
