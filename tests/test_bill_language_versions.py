"""Bills and receipts must be offered as two clean, single-language documents.

The previous bilingual layer appended Urdu beside English inside the same
receipt.  These tests pin the new contract:

* ``/view_bill`` shows separate English/Urdu PDF + Print buttons.
* ``/download_invoice`` defaults to English and accepts ``lang=ur`` aliases.
* The English document contains no Urdu layer/font.
* The Urdu document translates fixed bill furniture and names, preserves other data,
  and still embeds the bundled Jameel Noori font.
* Non-bill exports are plain English; ``?lang=ur`` gives a separate Urdu copy.
"""
from __future__ import annotations

from datetime import datetime
import io
import re

import pytest
from pypdf import PdfReader

from app import db
from app.services import bilingual as B
from app.services.files_pdf import (
    _bilingual_print_html,
    _try_render_weasy_pdf,
    resolve_export_lang,
)
from models.cash import Account
from models.catalog import Material
from models.parties import Client
from models.sales import DirectSale, Payment
from models.stock import Entry


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _receipt_block(html: str) -> str:
    match = re.search(
        r'<div class="rcpt-wrapper.*?</div><!-- /rcpt-wrapper -->',
        html,
        re.S,
    )
    assert match, "receipt print area was not rendered"
    # Comments are template furniture, not visible bill text.
    return re.sub(r'<!--.*?-->', '', match.group(0), flags=re.S)


def login(client):
    resp = client.post(
        "/login",
        data={"username": "Admin", "password": "Admin@fbm12345"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


@pytest.fixture()
def bill_data(app, client):
    login(client)

    client.post("/add_material", data={
        "material_name": "LANG TEST CEMENT",
        "material_unit": "Bags",
    }, follow_redirects=True)
    client.post("/add_client", data={
        "name": "LANG TEST CLIENT",
        "code": "LTC-001",
        "category": "General",
        "opening_balance": "0",
    }, follow_redirects=True)
    client.post("/accounts/accounts/add", data={
        "name": "LANG CASH ACCOUNT",
        "class_category": "Assets",
        "class_subcategory": "Cash",
        "class_account_type": "Main Cash",
        "account_status": "active",
        "opening_amount": "0",
        "opening_position": "debit",
        "opening_effective_date": "2026-01-01",
    }, follow_redirects=True)

    with app.app_context():
        mat = Material.query.filter_by(name="LANG TEST CEMENT").first()
        cli = Client.query.filter_by(code="LTC-001").first()
        acc = Account.query.filter(Account.name.like("%LANG CASH%")).first()
        assert mat and cli and acc
        db.session.add(Entry(
            date="2026-01-01", time="09:00:00", type="IN",
            material=mat.name, qty=1000,
            bill_no="MB NO.9001", client_category="Stock In",
        ))
        from app.services.void_rebuild import _rebuild_material_totals
        _rebuild_material_totals()
        db.session.commit()
        ids = {"mat": mat.id, "client": cli.id, "account": acc.id,
               "client_code": cli.code, "client_name": cli.name,
               "material_name": mat.name}

    note = "Cash delivery after Jun SPECIAL 9988"
    resp = client.post("/add_direct_sale", data={
        "client_code": ids["client_code"],
        "client_name": ids["client_name"],
        "category": "Credit Customer",
        "manual_bill_no": "MB NO.9101",
        "driver_name": "TEST DRIVER",
        "product_name[]": ids["material_name"],
        "material_id[]": str(ids["mat"]),
        "qty[]": "20",
        "unit_rate[]": "1500",
        "paid_amount": "0",
        "note": note,
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        sale = DirectSale.query.filter_by(manual_bill_no="MB NO.9101").first()
        assert sale is not None
        ids["sale_id"] = sale.id

    resp = client.post("/add_payment", data={
        "client_code": ids["client_code"],
        "amount": "25000",
        "payment_type": "Receipt",
        "method": "Cash",
        "payment_account_id": str(ids["account"]),
        "manual_bill_no": "MB NO.9102",
        "note": note,
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        payment = Payment.query.filter_by(manual_bill_no="MB NO.9102").first()
        assert payment is not None
        ids["payment_id"] = payment.id

    ids["note"] = note
    return ids


def test_bill_label_filter_replaces_instead_of_mixing():
    assert B.bill_label("Bill To", "en") == "Bill To"
    urdu = str(B.bill_label("Bill To", "ur"))
    assert 'class="ur"' in urdu
    assert B.LABELS["Bill To"] in urdu
    assert "Bill To" not in urdu
    # Unknown user-entered text is never machine-translated.
    assert B.bill_label("Cash delivery after Jun", "ur") == "Cash delivery after Jun"
    assert B.bill_label("MB-123", "ur") == "MB-123"


def test_apply_urdu_is_rtl_font_only_and_idempotent():
    html = '<div class="rcpt-wrapper"><p>MB-123</p><p>Cash delivery after Jun</p></div>'
    out = B.apply_urdu(html)
    assert B.apply_urdu(out) == out
    assert 'dir="rtl"' in out
    assert "JameelNooriNastaleeq.ttf" in out
    assert "MB-123" in out
    assert "Cash delivery after Jun" in out
    assert "<!--ams-bilingual-v1-->" not in out


def test_urdu_bill_date_reads_time_period_day_month_year_right_to_left():
    """Urdu receipt dates read time, صبح/شام, date, month, then year.

    The sequence is the English one - ``05:03 PM 06 Nov 2026`` - only written
    right to left, so the *first* thing an Urdu reader meets at the right edge
    is the time.
    """
    evening = str(B.bill_date(datetime(2026, 11, 6, 17, 3), "ur"))
    morning = str(B.bill_date(datetime(2026, 1, 2, 5, 3), "urdu"))

    # Dropping markup shows the exact order users read on the receipt.  Each
    # number is an LTR isolate so the PDF fallback cannot swap time and day.
    assert re.sub(r"<[^>]+>", "", evening) == "05:03 شام 06 نومبر 2026"
    assert re.sub(r"<[^>]+>", "", morning) == "05:03 صبح 02 جنوری 2026"
    assert evening.count('<bdi dir="ltr">') == 3
    assert "AM" not in morning and "PM" not in evening

    # The time is the first run of the line, which is what puts it against the
    # right edge once the line is written right to left.
    assert evening.index("05:03") < evening.index("شام") < evening.index("06")

    # English bills retain their established date format.
    assert B.bill_date(datetime(2026, 11, 6, 17, 3), "en") == "06 Nov 2026  05:03 PM"


def test_urdu_css_writes_the_date_line_right_to_left():
    """The date line must not be pinned left-to-right, or screen and PDF differ.

    Bill numbers, phone numbers and amounts are figures and stay LTR; the date
    is an Urdu sentence and has to be *written* RTL while its own numbers stay
    readable LTR inside their isolates.
    """
    css = B._urdu_css()
    date_rule = re.search(
        r'\.rcpt-wrapper\[dir="rtl"\] \.rcpt-doc-date\s*{[^}]*}', css)
    assert date_rule, "the Urdu stylesheet has no rule for .rcpt-doc-date"
    assert "direction: rtl" in date_rule.group(0), date_rule.group(0)

    # The pinned-LTR block must no longer list the date.
    ltr_rules = re.findall(
        r'([^{}]*?)\{\s*direction: ltr;[^}]*\}', css)
    for selectors in ltr_rules:
        assert ".rcpt-doc-date" not in selectors, (
            "the date line cannot be pinned to direction: ltr: "
            + " ".join(selectors.split())
        )


def test_view_bill_has_separate_language_buttons(client, bill_data):
    resp = client.get(
        f"/view_bill/MB NO.9101?src=direct_sale&src_id={bill_data['sale_id']}"
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "English PDF" in html
    assert "Urdu PDF" in html
    assert "English Print" in html
    assert "Urdu Print" in html
    assert "lang=en" in html
    assert "lang=ur" in html
    assert "action=print" in html


def test_invoice_pdf_language_versions(client, bill_data):
    url = f"/download_invoice/MB NO.9101?src=direct_sale&src_id={bill_data['sale_id']}"

    english = client.get(url)
    assert english.status_code == 200
    assert english.data.startswith(b"%PDF-")
    assert "-EN.pdf" in english.headers["Content-Disposition"]
    assert b"Jameel-Noori" not in english.data
    en_text = _pdf_text(english.data)
    assert "MB NO.9101" in en_text
    assert bill_data["note"] in en_text

    urdu = client.get(url + "&lang=ur")
    assert urdu.status_code == 200
    assert urdu.data.startswith(b"%PDF-")
    assert "-UR.pdf" in urdu.headers["Content-Disposition"]
    assert b"Jameel-Noori" in urdu.data
    ur_text = _pdf_text(urdu.data)
    # Identifiers, amounts and free-text notes survive unchanged.
    assert "MB NO.9101" in ur_text
    assert bill_data["note"] in ur_text
    assert "30,000" in ur_text or "30000" in ur_text
    # Fixed English furniture is replaced, not appended beside Urdu.
    ur_upper = ur_text.upper()
    assert "BILL TO" not in ur_upper
    assert "TRANSACTION DETAILS" not in ur_upper
    assert "TOTAL OUTSTANDING BALANCE" not in ur_upper


def test_invoice_print_language_versions(client, bill_data):
    url = f"/download_invoice/MB NO.9101?src=direct_sale&src_id={bill_data['sale_id']}&action=print"

    english = client.get(url)
    assert english.status_code == 200
    en_html = english.get_data(as_text=True)
    assert "-EN.html" in english.headers["Content-Disposition"]
    assert "<!--ams-urdu-v1-->" not in en_html
    assert 'class="ur"' not in _receipt_block(en_html)
    assert "Bill To" in _receipt_block(en_html)

    urdu = client.get(url + "&lang=urdu")
    assert urdu.status_code == 200
    ur_html = urdu.get_data(as_text=True)
    assert "-UR.html" in urdu.headers["Content-Disposition"]
    assert "<!--ams-urdu-v1-->" in ur_html
    block = _receipt_block(ur_html)
    assert 'dir="rtl"' in block
    assert B.LABELS["Bill To"] in block
    assert B.LABELS["Transaction Details"] in block
    assert "Bill To" not in block
    assert "Transaction Details" not in block
    assert bill_data["note"] in block
    assert "MB NO.9101" in block


def test_payment_receipt_language_versions(client, bill_data):
    view = client.get(
        f"/view_bill/MB NO.9102?src=payment&src_id={bill_data['payment_id']}"
    )
    assert view.status_code == 200
    view_html = view.get_data(as_text=True)
    assert "English PDF" in view_html
    assert "Urdu PDF" in view_html
    assert "English Print" in view_html
    assert "Urdu Print" in view_html

    url = f"/download_invoice/MB NO.9102?src=payment&src_id={bill_data['payment_id']}"
    english = client.get(url)
    assert english.status_code == 200
    assert english.data.startswith(b"%PDF-")
    assert b"Jameel-Noori" not in english.data
    assert "RECEIVED FROM" in _pdf_text(english.data).upper()

    urdu = client.get(url + "&lang=urd")
    assert urdu.status_code == 200
    assert urdu.data.startswith(b"%PDF-")
    assert b"Jameel-Noori" in urdu.data
    ur_text = _pdf_text(urdu.data)
    ur_upper = ur_text.upper()
    assert "RECEIVED FROM" not in ur_upper
    assert "BALANCE SUMMARY" not in ur_upper
    assert "MB NO.9102" in ur_text
    assert bill_data["note"] in ur_text

    print_ur = client.get(url + "&action=print&lang=ur")
    assert print_ur.status_code == 200
    block = _receipt_block(print_ur.get_data(as_text=True))
    assert B.LABELS["Received From"] in block
    assert B.LABELS["Balance Summary"] in block
    assert "Received From" not in block
    assert "Balance Summary" not in block


def test_default_and_unknown_lang_are_english(client, bill_data):
    url = f"/download_invoice/MB NO.9101?src=direct_sale&src_id={bill_data['sale_id']}&action=print"
    default = client.get(url)
    unknown = client.get(url + "&lang=fr")
    assert default.status_code == unknown.status_code == 200
    for resp in (default, unknown):
        html = resp.get_data(as_text=True)
        assert "-EN.html" in resp.headers["Content-Disposition"]
        assert "<!--ams-urdu-v1-->" not in html
        assert 'class="ur"' not in _receipt_block(html)


def test_non_bill_exports_are_english_until_urdu_is_asked_for(app):
    """Ledgers/statements ship plain English; Urdu is a separate document.

    These exports used to append a Nastaleeq translation beside every English
    label.  The pure-Python PDF fallback (the only engine on hosts without
    pango/cairo) drew both scripts on one baseline inside one paragraph, so
    every header and summary line came out as overlapping mush.  A document is
    now one language or the other.
    """
    html = "<div><h2>CLIENT LEDGER</h2><p>Bill No: BK-1</p></div>"
    with app.test_request_context():
        pdf = _try_render_weasy_pdf(html, "ledger.pdf")
        printed = _bilingual_print_html(html)
    assert pdf is not None
    assert pdf.get_data().startswith(b"%PDF-")
    # English: no Urdu font, no Urdu label beside the English one.
    assert b"Jameel-Noori" not in pdf.get_data()
    assert "<!--ams-bilingual-v1-->" not in printed
    assert B.LABELS["Bill No"] not in printed
    assert "Bill No" in printed

    with app.test_request_context():
        ur_pdf = _try_render_weasy_pdf(html, "ledger.pdf", lang='ur',
                                       urdu_labels=True)
        ur_printed = _bilingual_print_html(html, lang='ur', urdu_labels=True)
    assert ur_pdf is not None
    assert ur_pdf.get_data().startswith(b"%PDF-")
    # Urdu: the font is embedded, the label is *replaced*, never appended.
    assert b"Jameel-Noori" in ur_pdf.get_data()
    assert B.LABELS["Bill No"] in ur_printed
    assert "Bill No:" not in ur_printed
    assert 'dir="rtl"' in ur_printed


def test_export_language_comes_from_the_query_string(app):
    with app.test_request_context('/x'):
        assert resolve_export_lang() == 'en'
    with app.test_request_context('/x?lang=ur'):
        assert resolve_export_lang() == 'ur'
    with app.test_request_context('/x?lang=urdu'):
        assert resolve_export_lang() == 'ur'
    with app.test_request_context('/x?lang=fr'):
        assert resolve_export_lang() == 'en'


def test_urdu_bill_and_receipt_names_use_saved_spellings(client, app, bill_data):
    from models.parties import DeliveryPerson
    with app.app_context():
        person = Client.query.get(bill_data['client'])
        material = Material.query.get(bill_data['mat'])
        person.name_ur = 'فیصل'
        material.name_ur = 'ڈی جی سیمنٹ'
        driver = DeliveryPerson.query.filter_by(name='TEST DRIVER').first()
        if driver is None:
            driver = DeliveryPerson(name='TEST DRIVER')
            db.session.add(driver)
        driver.name_ur = 'حامد'
        db.session.commit()

    sale_url = f"/download_invoice/MB NO.9101?src=direct_sale&src_id={bill_data['sale_id']}&action=print"
    ur = _receipt_block(client.get(sale_url + '&lang=ur').get_data(as_text=True))
    assert 'فیصل' in ur
    assert 'حامد' in ur
    assert 'ڈی جی سیمنٹ' in ur
    en = _receipt_block(client.get(sale_url).get_data(as_text=True))
    assert bill_data['client_name'] in en
    assert bill_data['material_name'] in en
    assert 'فیصل' not in en

    payment_url = f"/download_invoice/MB NO.9102?src=payment&src_id={bill_data['payment_id']}&action=print&lang=ur"
    assert 'فیصل' in _receipt_block(client.get(payment_url).get_data(as_text=True))
