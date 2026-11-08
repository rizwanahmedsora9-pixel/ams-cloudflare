"""Proof that the Urdu print page and the Urdu PDF are one and the same sheet.

Both backends paint the same ``Sheet`` operation list: the PDF through
ReportLab, the print page through absolutely-positioned ``pt`` divs.  These
tests walk that operation list and assert the HTML really carries every mark at
the same place — so "Urdu Print" cannot drift away from "Urdu PDF" — and that
the carbon-copy leaf carries the bill twice, once per copy.
"""
from __future__ import annotations

import re

from app.services import bill_urdu
from app.services import urdu_receipt as R

import test_urdu_bill_sheet as base   # noqa: E402  (tests/ is on pythonpath)

SHAPE = re.compile(r'<div class="s" style="([^"]+)"></div>')
TEXT = re.compile(r'<div class="t" style="([^"]+)">(.*?)</div>', re.S)


def _styles(css):
    out = {}
    for part in css.split(';'):
        if ':' in part:
            key, _, value = part.partition(':')
            out[key.strip()] = value.strip()
    return out


def _pt(value):
    return float(str(value).replace('pt', '').replace('px', ''))


def _boxes(html, page_w=R.PAGE_W):
    out = []
    for css in SHAPE.findall(html):
        s = _styles(css)
        if 'left' in s and 'top' in s:
            x, y = _pt(s['left']), _pt(s['top'])
            out.append((x, y, x + _pt(s.get('width', '0')),
                        y + _pt(s.get('height', '0'))))
        elif 'right' in s and 'top' in s:
            # a right-anchored run: its own width is not fixed, so record the
            # anchor and let the caller check the baseline only
            out.append((None, _pt(s['top']), page_w - _pt(s['right']),
                        R.PAGE_H))
    return out


def _text_runs(html, page_w=R.PAGE_W):
    out = []
    for css, text in TEXT.findall(html):
        s = _styles(css)
        top = _pt(s['top']) if 'top' in s else None
        if 'left' in s:
            x = _pt(s['left'])
        else:
            x = page_w - _pt(s['right'])
        out.append((x, top, re.sub(r'<[^>]+>', '', text).strip(), s))
    return out


def test_every_shape_op_is_in_the_print_page():
    doc = base._document()
    sheets = R.layout_document(doc)
    html = bill_urdu.render_html(doc, copies=1)
    boxes = _boxes(html)

    missing = []
    for op in sheets[0].ops:
        if op['op'] != 'rect':
            continue
        x0, y0 = op['x'], op['y']
        if not any(b[0] is not None and abs(b[0] - x0) < 1.2
                   and abs(b[1] - y0) < 1.2 for b in boxes):
            missing.append((round(x0, 1), round(y0, 1)))
    assert not missing, f'shapes missing from the print page: {missing[:6]}'


def test_every_rule_is_in_the_print_page():
    doc = base._document()
    sheets = R.layout_document(doc)
    html = bill_urdu.render_html(doc, copies=1)

    rules = []
    for css in SHAPE.findall(html):
        s = _styles(css)
        if 'left' in s and 'top' in s:
            rules.append((_pt(s['left']), _pt(s['top'])))
    missing = []
    for op in sheets[0].ops:
        if op['op'] not in ('line', 'seg'):
            continue
        x, y = min(op['x0'], op['x1']), min(op['y0'], op['y1'])
        if not any(abs(a - x) < 1.2 and abs(b - y) < 1.4 for a, b in rules):
            missing.append((op['op'], round(x, 1), round(y, 1)))
    assert not missing, f'rules missing from the print page: {missing[:6]}'


def test_every_text_run_is_in_the_print_page():
    doc = base._document()
    sheets = R.layout_document(doc)
    html = bill_urdu.render_html(doc, copies=1)
    runs = _text_runs(html)

    missing = []
    for op in sheets[0].ops:
        if op['op'] != 'text':
            continue
        hit = None
        for x, top, text, css in runs:
            if text != op['text']:
                continue
            if abs(x - op['x']) > 1.0:
                continue
            # the div's top is the baseline minus the font's own ratio
            want_top = op['y'] - R._BASELINE_RATIO.get(op['font'], 0.85) * op['size']
            if abs(top - want_top) > 0.35:
                continue
            hit = css
            break
        if hit is None:
            missing.append((round(op['x'], 1), round(op['y'], 1), op['text']))
    assert not missing, f'text runs missing from the print page: {missing[:6]}'


def test_print_page_uses_the_same_point_sizes_and_colours():
    doc = base._document()
    sheets = R.layout_document(doc)
    html = bill_urdu.render_html(doc, copies=1)
    styles = [_styles(css[0]) for css in TEXT.findall(html)]
    sizes = {s.get('font-size') for s in styles if s.get('font-size')}
    colours = {s.get('color', '').upper() for s in styles if s.get('color')}

    for op in sheets[0].ops:
        if op['op'] != 'text':
            continue
        assert f"{R._fmt(op['size'])}pt" in sizes, op
        assert op['color'].upper() in colours, op


def test_print_page_paints_shapes_before_text():
    """A navy bar must never cover its label, in either backend."""
    html = bill_urdu.render_html(base._document())
    body = html.split('<body>', 1)[1]
    first_text = body.find('<div class="t"')
    last_shape = body.rfind('<div class="s"')
    assert 0 < last_shape < first_text, 'shapes and text are interleaved'


def test_nothing_is_positioned_by_flow():
    """Every mark is absolutely placed, so the browser cannot reflow the bill."""
    html = bill_urdu.render_html(base._document())
    body = html.split('<body>', 1)[1]
    for div in re.findall(r'<div class="(?:s|t)"[^>]*>', body):
        css = _styles(div.split('style="', 1)[1].rstrip('">'))
        assert 'left' in css or 'right' in css, div
        assert 'top' in css, div


def test_print_page_has_no_flow_layout_furniture():
    """No table, no flex row, no Bootstrap: it is a printed sheet."""
    html = bill_urdu.render_html(base._document())
    for tag in ('<table', '<thead', '<tbody', '<tr', 'class="row"',
                'd-flex', 'container'):
        assert tag not in html, tag


def test_the_print_page_is_the_a4_landscape_carbon_copy():
    html = bill_urdu.render_html(base._document())
    assert f'width:{R._fmt(R.A4_W)}pt' in html
    assert f'height:{R._fmt(R.A4_H)}pt' in html
    assert f'size: {R._fmt(R.A4_W)}pt {R._fmt(R.A4_H)}pt' in html


def test_both_print_copies_carry_every_text_run():
    """The A4 leaf holds the same bill twice, at the two A5 offsets."""
    doc = base._document()
    content = R.layout_document(doc)[0]
    html = bill_urdu.render_html(doc, copies=2)
    runs = _text_runs(html, page_w=R.A4_W)
    offset = (R.A4_W - 2 * R.PAGE_W) / 2.0

    missing = []
    for op in content.ops:
        if op['op'] != 'text':
            continue
        for dx in (offset, offset + R.PAGE_W):
            want_top = op['y'] - R._BASELINE_RATIO.get(op['font'], 0.85) * op['size']
            if not any(text == op['text'] and abs(x - (op['x'] + dx)) < 1.0
                       and abs(top - want_top) < 0.35
                       for x, top, text, _css in runs):
                missing.append((round(op['x'] + dx, 1), round(op['y'], 1)))
    assert not missing, f'copy runs missing from the print page: {missing[:6]}'


def test_only_the_panel_rule_and_the_cut_line_are_dashed():
    html = bill_urdu.render_html(base._document(), copies=2)
    dashed = [_styles(css) for css in SHAPE.findall(html) if 'dashed' in css]
    # the dotted rule under the panel fields, once on each copy, then the cut
    assert len(dashed) == 3
    vertical = [css for css in dashed if css.get('width') == '0']
    assert len(vertical) == 1, 'one cut line down the middle of the leaf'
    assert abs(_pt(vertical[0]['left']) - (R.A4_W / 2)) < 1.0
    for css in dashed:
        assert 'background' not in css, 'a dashed mark must let the paper show'
