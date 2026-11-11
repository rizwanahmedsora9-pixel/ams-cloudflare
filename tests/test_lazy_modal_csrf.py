"""CSRF regressions for forms fetched after the page has loaded."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import db
from models import Client, User


_LAZY_MODAL_TEMPLATES = (
    "_client_modals.html",
    "_booking_edit_modal.html",
    "_direct_sale_edit_modal.html",
    "_pending_bill_modals.html",
)


@pytest.mark.parametrize("template_name", _LAZY_MODAL_TEMPLATES)
def test_lazy_modal_forms_use_the_csrf_guard_field(template_name):
    """Every on-demand form must serialize the parameter checked by hooks.py."""
    template = Path(__file__).resolve().parents[1] / "templates" / template_name
    source = template.read_text(encoding="utf-8")

    assert 'name="_csrf_token"' in source
    assert 'name="csrf_token"' not in source


def test_client_can_be_created_then_edited_with_name_and_opening_balance(app):
    """A lazy-loaded client edit form carries a token accepted by the real gate."""
    app.config["AMS_CSRF_ALWAYS"] = True
    browser = app.test_client()

    with app.app_context():
        admin_id = User.query.filter_by(username="Admin").one().id

    with browser.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    # A normal client page initializes the session token. The add form is in
    # that page, so the layout's browser-side injector would send this field.
    page = browser.get("/clients")
    assert page.status_code == 200
    with browser.session_transaction() as session:
        page_token = session["_csrf_token"]

    created = browser.post(
        "/add_client",
        data={
            "_csrf_token": page_token,
            "name": "Before Edit",
            "code": "CSRF-CLIENT-1",
            "category": "General",
            "opening_balance": "0",
            "opening_balance_date": "2026-11-01",
        },
        follow_redirects=False,
    )
    assert created.status_code in (302, 303)

    with app.app_context():
        client_row = Client.query.filter_by(code="CSRF-CLIENT-1").one()
        client_id = client_row.id
        assert client_row.opening_balance == 0

    # The edit modal is a separately fetched HTML fragment; its form cannot
    # rely on the page-load JavaScript that injects tokens into existing forms.
    fragment = browser.get(f"/clients/{client_id}/modals")
    assert fragment.status_code == 200
    html = fragment.get_data(as_text=True)
    csrf_fields = re.findall(
        r'<input\b[^>]*\bname="([^\"]*csrf_token)"[^>]*\bvalue="([^\"]*)"',
        html,
    )
    assert len(csrf_fields) == 2  # edit and transfer forms
    assert all(name == "_csrf_token" for name, _value in csrf_fields)
    assert all(value == page_token for _name, value in csrf_fields)

    form_token_name, form_token = csrf_fields[0]
    updated = browser.post(
        f"/edit_client/{client_id}",
        data={
            form_token_name: form_token,
            "name": "After Edit",
            "name_ur": "",
            "code": "CSRF-CLIENT-1",
            "category": "General",
            "opening_balance": "1250.75",
            "opening_balance_date": "2026-11-10",
            "phone": "",
            "address": "",
            "location_url": "",
        },
        follow_redirects=False,
    )

    assert updated.status_code in (302, 303)
    with app.app_context():
        client_row = db.session.get(Client, client_id)
        assert client_row.name == "After Edit"
        assert client_row.opening_balance == pytest.approx(1250.75)
        assert client_row.opening_balance_date.strftime("%Y-%m-%d") == "2026-11-10"
