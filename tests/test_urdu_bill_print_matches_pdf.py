"""Proof that the Urdu print page and the Urdu PDF are one and the same sheet.

Both backends paint the same ``Sheet`` operation list: the PDF through
ReportLab, the print page through absolutely-positioned ``pt`` divs.  These
tests walk that operation list and assert the HTML really carries every mark at
the same place — so "Urdu Print" cannot drift away from "Urdu PDF".
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


def _boxes(html):
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
            out.append((None, _pt(s['top']), _pt(R.PAGE_W - _pt(s['right'])),
                        _pt(R.PAGE_H)))
    return out


def _text_runs(html):
    out = []
    for css, text in TEXT.findall(html):
        s = _styles(css)
        top = _pt(s['top']) if 'top' in s else None
        if 'left' in s:
            x = _pt(s['left'])
        else:
            x = R.PAGE_W - _pt(s['right'])
        out.append((x, top, re.sub(r'<[^>]+>', '', text).strip(), s))
    return out


def test_every_shape_op_is_in_the_print_page():
    doc = base._document()
    sheets = R.layout_document(doc)
    html = bill_urdu.render_html(doc)
    boxes = _boxes(html)

    missing = []
    for op in sheets[0].ops:
        if op['op'] != 'rect':
            continue
        x0, y0, x1, y1 = op['x'], op['y'], op['x'] + op['w'], op['y'] + op['h']
        if not any(b[0] is not None and abs(b[0] - x0) < 1.2
                   and abs(b[1] - y0) < 1.2 for b in boxes):
            missing.append((round(x0, 1), round(y0, 1),
                            round(x1, 1), round(y1, 1)))
    assert not missing, f'shapes missing from the print page: {missing}'


def test_every_rule_is_in_the_print_page():
    doc = base._document()
    sheets = R.layout_document(doc)
    html = bill_urdu.render_html(doc)

    rules = []
    for css in SHAPE.findall(html):
        s = _styles(css)
        if 'left' in s and 'top' in s:
            rules.append((_pt(s['left']), _pt(s['top']),
                          _pt(s.get('width', '0'))))
    missing = []
    for op in sheets[0].ops:
        if op['op'] not in ('line', 'seg'):
            continue
        x, y = min(op['x0'], op['x1']), min(op['y0'], op['y1'])
        if not any(abs(a - x) < 1.2 and abs(b - y) < 1.4 for a, b, _w in rules):
            missing.append((op['op'], round(x, 1), round(y, 1)))
    assert not missing, f'rules missing from the print page: {missing}'


def test_every_text_run_is_in_the_print_page():
    doc = base._document()
    sheets = R.layout_document(doc)
    html = bill_urdu.render_html(doc)
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
    assert not missing, f'text runs missing from the print page: {missing}'


def test_print_page_uses_the_same_point_sizes_and_colours():
    doc = base._document()
    sheets = R.layout_document(doc)
    html = bill_urdu.render_html(doc)
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
    doc = base._document()
    html = bill_urdu.render_html(doc)
    body = html.split('<body>', 1)[1]
    first_text = body.find('<div class="t"')
    last_shape = body.rfind('<div class="s"')
    assert 0 < last_shape < first_text, 'shapes and text are interleaved'


def test_nothing_is_positioned_by_flow():
    """Every mark is absolutely placed, so the browser cannot reflow the bill."""
    doc = base._document()
    html = bill_urdu.render_html(doc)
    body = html.split('<body>', 1)[1]
    for div in re.findall(r'<div class="(?:s|t)"[^>]*>', body):
        css = _styles(div.split('style="', 1)[1].rstrip('">'))
        assert 'left' in css or 'right' in css, div
        assert 'top' in css, div


def test_print_page_has_no_flow_layout_furniture():
    """No table, no flex row, no Bootstrap: it is a printed sheet."""
    doc = base._document()
    html = bill_urdu.render_html(doc)
    for tag in ('<table', '<thead', '<tbody', '<tr', 'class="row"',
                'd-flex', 'container'):
        assert tag not in html, tag


def test_stamp_box_is_a_dashed_outline_not_a_shaded_box():
    doc = base._document()
    html = bill_urdu.render_html(doc)
    dashed = [css for css in SHAPE.findall(html) if 'dashed' in css]
    assert len(dashed) == 4, 'the stamp box is four dashed edges'
    for css in dashed:
        assert 'background' not in css, 'the stamp box must let the paper show'
