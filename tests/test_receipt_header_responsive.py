"""Receipt header must stay inside the page on narrow screens.

Both bill screens (``view_bill.html`` and ``payment_receipt.html``) render a
receipt header as a flex row: company block on the left, document block
(``INVOICE`` / ``RECEIPT`` box, transaction-type badge, bill number, date) on
the right.  The document block used to carry ``white-space: nowrap`` inside a
non-wrapping flex row, so on phone widths the INVOICE box and the transaction
type ran off the right edge of the screen.

The contract pinned here (presence, not pixels):

* the header row may wrap, so the document block drops below the company
  block instead of overflowing;
* the document block and its badge may shrink to the page width;
* bill number / date keep ``nowrap`` so figures are never split;
* the compaction rules are scoped to ``screen`` — the printed / WeasyPrint A5
  sheet keeps its own fixed sizes.
"""
from __future__ import annotations

import os
import re

import pytest

TEMPLATES = [
    os.path.join(os.path.dirname(__file__), "..", "templates", "view_bill.html"),
    os.path.join(os.path.dirname(__file__), "..", "templates", "payment_receipt.html"),
]


@pytest.fixture(params=TEMPLATES, ids=lambda p: os.path.basename(p))
def receipt_css(request):
    with open(request.param, encoding="utf-8") as fh:
        return fh.read()


def test_header_row_can_wrap(receipt_css):
    header = re.search(r"\.rcpt-header\s*{[^}]*}", receipt_css)
    assert header, "receipt header rule missing"
    assert "flex-wrap" in header.group(0), "header row must be allowed to wrap"


def test_document_block_may_shrink_instead_of_running_off_screen(receipt_css):
    right = re.search(r"\.rcpt-header-right\s*{[^}]*}", receipt_css)
    assert right, "receipt header-right rule missing"
    block = right.group(0)
    assert "white-space" not in block, (
        "the document block must not be frozen with nowrap; "
        "only its figures (doc no / date) stay nowrap"
    )
    assert "max-width" in block, "the document block must be capped to the page"

    badge = re.search(r"\.rcpt-tx-badge\s*{[^}]*}", receipt_css)
    assert badge and "max-width" in badge.group(0)

    doc_type = re.search(r"\.rcpt-doc-type\s*{[^}]*}", receipt_css)
    assert doc_type and "max-width" in doc_type.group(0)


def test_figures_keep_their_single_line(receipt_css):
    for selector in (".rcpt-doc-no", ".rcpt-doc-date"):
        rule = re.search(re.escape(selector) + r"[^{}]*{[^}]*}", receipt_css)
        assert rule, f"{selector} rule missing"
        assert "white-space" in rule.group(0) and "nowrap" in rule.group(0), (
            f"{selector} must keep nowrap so the bill number / date stay on one line"
        )


def test_small_screen_rules_are_screen_scoped(receipt_css):
    """``@media screen and (max-width: …)`` keeps WeasyPrint A5 output untouched."""
    assert re.search(
        r"@media\s+screen\s+and\s+\(max-width:\s*575\.98px\)", receipt_css
    ), "small-screen block missing or not scoped to screen media"
    # A bare max-width media query would also match WeasyPrint's 148mm page.
    assert not re.search(r"@media\s+\(max-width", receipt_css)
