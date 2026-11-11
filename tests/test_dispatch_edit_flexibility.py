"""End-to-end: editing/deleting a back-dated dispatch entry must go through.

Regression tests for the old hard stop

    "Permission Denied: Only Admins can edit back-dated records."

which refused every non-admin operator who tried to correct an entry posted
before today, redirecting them to the dashboard with no explanation.
"""
from datetime import date, timedelta

import pytest

from models import Entry, Material, db


def _login(client, username="Admin", password="Admin@fbm12345"):
    response = client.post("/login", data={"username": username, "password": password})
    assert response.status_code in (302, 303)


MATERIAL_NAME = "Cement 50kg"


def _make_material(name=MATERIAL_NAME):
    material = Material(code="MAT-TEST", name=name, unit="Bag", unit_price=1200,
                        total=100, is_active=True)
    db.session.add(material)
    db.session.commit()
    return name


def _make_entry(material_name, day):
    entry = Entry(
        date=day.strftime("%Y-%m-%d"),
        time="09:00:00",
        type="IN",
        material=material_name,
        client="Test Supplier",
        qty=10,
        note="opening stock",
    )
    db.session.add(entry)
    db.session.commit()
    return entry.id


@pytest.mark.parametrize("days_ago", [1, 14, 120])
def test_backdated_entry_edit_is_accepted_for_admin(app, client, days_ago):
    """An admin can always correct history — no date-based blocker."""
    day = date.today() - timedelta(days=days_ago)
    with app.app_context():
        material_name = _make_material()
        entry_id = _make_entry(material_name, day)

    _login(client)
    response = client.post(
        f"/edit_entry/{entry_id}",
        data={
            "date": (date.today() - timedelta(days=days_ago)).strftime("%Y-%m-%d"),
            "type": "IN",
            "material": material_name,
            "client": "Test Supplier",
            "qty": "12",
            "note": "corrected count",
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302, 303)

    with app.app_context():
        entry = db.session.get(Entry, entry_id)
        assert entry is not None, "the entry must not disappear on a failed edit"
        assert float(entry.qty) == 12
        assert entry.note == "corrected count"


def test_backdated_entry_delete_is_accepted_for_admin(app, client):
    day = date.today() - timedelta(days=30)
    with app.app_context():
        material_name = _make_material()
        entry_id = _make_entry(material_name, day)

    _login(client)
    response = client.post(f"/delete_entry/{entry_id}", follow_redirects=False)
    assert response.status_code in (200, 302, 303)

    with app.app_context():
        entry = db.session.get(Entry, entry_id)
        # Dispatch delete is a soft flag, not a row removal.
        assert entry is not None and bool(entry.is_void) is True


def test_todays_entry_still_edits_normally(app, client):
    with app.app_context():
        material_name = _make_material()
        entry_id = _make_entry(material_name, date.today())

    _login(client)
    response = client.post(
        f"/edit_entry/{entry_id}",
        data={
            "date": date.today().strftime("%Y-%m-%d"),
            "type": "IN",
            "material": material_name,
            "client": "Test Supplier",
            "qty": "11",
            "note": "same-day correction",
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302, 303)
    with app.app_context():
        assert float(db.session.get(Entry, entry_id).qty) == 11
