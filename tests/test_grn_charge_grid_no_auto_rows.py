"""The GRN charge grid is operator-driven: no charge row is ever pre-added.

Owner complaint (2026-11-02): a brand-new GRN showed four ready-made expense
lines — Vehicle Fare, Loading, Unloading, Other Expenses — each with a full
set of Recipient / Payment Status / Cost Treatment / Alloc. Basis dropdowns.
Nobody asked for those charges; the screen invented them.  A charge must exist
only because the operator pressed **Add charge**, or because it is already
saved on the GRN being edited.

Pinned here:

1. a new ``/grn`` renders **zero** charge rows, and the only row markup is the
   inert ``<template>`` the Add charge button clones (a template is never
   submitted and never counted);
2. the empty grid still posts ``charge_grid_present``, so the server can tell
   "no charges" from "this form has no charge grid";
3. saving with no charges stores no ``GRNCharge`` and no phantom obligation —
   the cost is the supplier material only (owner rules A1 / A2 unchanged);
4. saving the charges the operator actually added stores exactly those, in
   order, with no extra rows;
5. an edit screen shows exactly the saved charges — not four blanks, and not
   the saved ones plus padding;
6. removing the last charge on an edit really clears it.

The browser half (Add charge / remove / blank-row handling) is pinned by
``tests/frontend/test_grn_charges_dom.js``.
"""
from __future__ import annotations

import pytest

from models import db, GRN, GRNCharge, Supplier, Material
from app.services.grn_costing import grn_breakdown
from tests.conftest import make_csrf_client

LOGIN = {"username": "Admin", "password": "Admin@fbm12345"}


@pytest.fixture()
def app(app_factory):
    return app_factory(AUTO_RECONCILE_ENABLED="0", BACKUP_EMBEDDED_SCHEDULER="0")


@pytest.fixture()
def client(app):
    return make_csrf_client(app)


def login(client):
    assert client.post("/login", data=LOGIN, follow_redirects=True).status_code == 200


def seed(app):
    with app.app_context():
        sup = Supplier(name="Cement Works", is_active=True)
        mat = Material(code="MAT-GRID", name="Cement", total=0.0)
        db.session.add_all([sup, mat])
        db.session.commit()
        return sup.id


def charge_grid(html):
    """The rendered charge table, without the inert Add-charge blueprint."""
    start = html.index('id="grnChargesTable"')
    return html[start:html.index("</table>", start)]


def blueprint(html):
    start = html.index('<template id="grnChargeRowTemplate">')
    return html[start:html.index("</template>", start)]


def post_grn(client, supplier_id, *, charges=(), bill="GRID-1", edit_id=None, grid_present=True):
    """Post the wizard form.  ``charges`` are the rows the operator added."""
    data = {
        "action": "add",
        "supplier": "Cement Works",
        "supplier_id": str(supplier_id),
        "date": "2026-10-20",
        "time": "10:30",
        "manual_bill_no": bill,
        "mat_name[]": ["Cement"],
        "qty[]": ["100"],
        "price[]": ["1500"],
        "allocation_basis_default": "VALUE",
    }
    if grid_present:
        data["charge_grid_present"] = "1"
    if charges:
        data.update({
            "charge_id[]": [c.get("id", "") for c in charges],
            "charge_type[]": [c["type"] for c in charges],
            "charge_label[]": [c.get("label", "") for c in charges],
            "charge_amount[]": [str(c["amount"]) for c in charges],
            "charge_recipient_type[]": [c.get("recipient", "OTHER") for c in charges],
            "charge_recipient[]": [c.get("party", "") for c in charges],
            "charge_status[]": [c.get("status", "UNPAID") for c in charges],
            "charge_treatment[]": [c.get("treatment", "INVENTORY") for c in charges],
            "charge_basis[]": [c.get("basis", "VALUE") for c in charges],
        })
    url = f"/edit_grn/{edit_id}" if edit_id else "/grn"
    return client.post(url, data=data, follow_redirects=True)


# ---- 1. the screen invents nothing --------------------------------------

def test_new_grn_renders_no_charge_rows(client, app):
    login(client)
    seed(app)
    html = client.get("/grn").get_data(as_text=True)
    grid = charge_grid(html)
    assert grid.count('class="grn-charge-row"') == 0, "a new GRN must not pre-add charge rows"
    # None of the old four hard-coded starter rows may come back.
    body = grid[grid.index("<tbody"):]
    assert "<select" not in body and "<input" not in body, "the empty grid holds no fields at all"


def test_only_the_inert_template_holds_a_blank_row(client, app):
    login(client)
    seed(app)
    html = client.get("/grn").get_data(as_text=True)
    tpl = blueprint(html)
    assert tpl.count('class="grn-charge-row"') == 1, "Add charge needs exactly one blueprint row"
    assert 'name="charge_id[]" value=""' in tpl, "the blueprint must not carry a stored id"
    # The charge and recipient are the operator's choice, not a default.
    assert '<option value="" selected>Select charge' in tpl
    assert '<option value="" selected>Select recipient' in tpl
    # A <template> is never submitted, so it cannot become a phantom charge.
    assert html.count('name="charge_amount[]"') == 1, "only the blueprint may define an amount field"


def test_empty_grid_is_visible_and_announced(client, app):
    login(client)
    seed(app)
    html = client.get("/grn").get_data(as_text=True)
    assert 'id="grnChargesEmpty"' in html
    empty = html[html.index('id="grnChargesEmpty"'):]
    assert not empty[:80].strip().startswith("hidden"), "the notice shows when there are no charges"
    wrap = html[html.index('id="grnChargesWrap"'):]
    assert wrap[:80].count("hidden") == 1, "the empty table itself stays hidden"
    assert 'id="addGrnChargeBtn"' in html, "Add charge is the only way to create a row"
    assert 'name="charge_grid_present"' in html, "an empty grid must still be recognisable on save"


# ---- 2. saving what the operator did (and did not) add ------------------

def test_saving_with_no_charges_stores_none(client, app):
    login(client)
    supplier_id = seed(app)
    resp = post_grn(client, supplier_id, charges=[])
    assert b"GRN added successfully" in resp.data
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        assert GRNCharge.query.filter(GRNCharge.grn_id == grn.id).count() == 0
        bd = grn_breakdown(grn)
        assert bd["supplier_material_amount"] == pytest.approx(150000)
        assert bd["capitalised_charge_total"] == pytest.approx(0)
        assert bd["landed_cost_total"] == pytest.approx(150000)
        assert bd["average_actual_rate"] == pytest.approx(1500)
        # A1/A2: no money is paid and no obligation is invented.
        assert bd["total_remaining"] == pytest.approx(150000)
        assert len(bd["obligations"]) == 1


def test_only_the_charges_the_operator_added_are_stored(client, app):
    login(client)
    supplier_id = seed(app)
    resp = post_grn(client, supplier_id, charges=[
        {"type": "VEHICLE_FARE", "amount": 5000, "recipient": "TRANSPORTER",
         "party": "Rana Transport", "label": "Rana Transport"},
    ], bill="GRID-2")
    assert b"GRN added successfully" in resp.data
    with app.app_context():
        grn = GRN.query.filter(GRN.manual_bill_no.like("%GRID-2%")).first()
        saved = GRNCharge.query.filter(GRNCharge.grn_id == grn.id, GRNCharge.is_void == False).all()  # noqa: E712
        assert len(saved) == 1, "no Loading / Unloading / Other row may appear unasked"
        assert saved[0].charge_type == "VEHICLE_FARE"
        assert float(saved[0].amount) == pytest.approx(5000)
        bd = grn_breakdown(grn)
        assert bd["landed_cost_total"] == pytest.approx(155000)
        assert bd["supplier_material_amount"] == pytest.approx(150000), "A2: the charge never enters the supplier payable"
        assert bd["loading"] == pytest.approx(0)
        assert bd["unloading"] == pytest.approx(0)
        assert bd["other_charges"] == pytest.approx(0)


def test_two_added_charges_keep_their_order_and_values(client, app):
    login(client)
    supplier_id = seed(app)
    post_grn(client, supplier_id, charges=[
        {"type": "LOADING", "amount": 1000, "recipient": "LABOUR", "party": "Loading Team"},
        {"type": "OTHER", "amount": 500, "recipient": "OTHER", "party": "Misc Party"},
    ], bill="GRID-3")
    with app.app_context():
        grn = GRN.query.filter(GRN.manual_bill_no.like("%GRID-3%")).first()
        saved = GRNCharge.query.filter(
            GRNCharge.grn_id == grn.id, GRNCharge.is_void == False  # noqa: E712
        ).order_by(GRNCharge.id.asc()).all()
        assert [c.charge_type for c in saved] == ["LOADING", "OTHER"]
        assert [float(c.amount) for c in saved] == [1000, 500]
        assert grn_breakdown(grn)["landed_cost_total"] == pytest.approx(151500)


# ---- 3. editing shows the saved charges, nothing else -------------------

def test_edit_screen_shows_exactly_the_saved_charges(client, app):
    login(client)
    supplier_id = seed(app)
    post_grn(client, supplier_id, charges=[
        {"type": "VEHICLE_FARE", "amount": 5000, "recipient": "TRANSPORTER", "party": "Rana Transport"},
    ], bill="GRID-4")
    with app.app_context():
        grn_id = GRN.query.filter(GRN.manual_bill_no.like("%GRID-4%")).first().id
    html = client.get(f"/edit_grn/{grn_id}").get_data(as_text=True)
    grid = charge_grid(html)
    assert grid.count('class="grn-charge-row"') == 1, "one saved charge = one row, no padding"
    assert 'value="VEHICLE_FARE" selected' in grid
    assert 'value="5000.0"' in grid or 'value="5000"' in grid


def test_edit_screen_of_a_chargeless_grn_is_also_empty(client, app):
    login(client)
    supplier_id = seed(app)
    post_grn(client, supplier_id, charges=[], bill="GRID-5")
    with app.app_context():
        grn_id = GRN.query.filter(GRN.manual_bill_no.like("%GRID-5%")).first().id
    html = client.get(f"/edit_grn/{grn_id}").get_data(as_text=True)
    assert charge_grid(html).count('class="grn-charge-row"') == 0, \
        "a GRN saved without charges must not grow four blank rows on edit"


def test_removing_the_last_charge_on_edit_clears_it(client, app):
    """An empty grid posts no charge_* field at all — only the sentinel.

    Without ``charge_grid_present`` the edit route skipped the sync entirely
    and the removed charge silently stayed on the GRN.
    """
    login(client)
    supplier_id = seed(app)
    post_grn(client, supplier_id, charges=[
        {"type": "VEHICLE_FARE", "amount": 5000, "recipient": "TRANSPORTER", "party": "Rana Transport"},
    ], bill="GRID-6")
    with app.app_context():
        grn_id = GRN.query.filter(GRN.manual_bill_no.like("%GRID-6%")).first().id
    resp = post_grn(client, supplier_id, charges=[], bill="GRID-6", edit_id=grn_id)
    assert b"GRN updated successfully" in resp.data
    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        active = GRNCharge.query.filter(
            GRNCharge.grn_id == grn_id, GRNCharge.is_void == False  # noqa: E712
        ).count()
        assert active == 0, "removing the last row must clear the charge"
        assert grn_breakdown(grn)["landed_cost_total"] == pytest.approx(150000)


def test_adding_a_charge_to_a_chargeless_grn_on_edit(client, app):
    login(client)
    supplier_id = seed(app)
    post_grn(client, supplier_id, charges=[], bill="GRID-7")
    with app.app_context():
        grn_id = GRN.query.filter(GRN.manual_bill_no.like("%GRID-7%")).first().id
    post_grn(client, supplier_id, charges=[
        {"type": "UNLOADING", "amount": 800, "recipient": "LABOUR", "party": "Yard Team"},
    ], bill="GRID-7", edit_id=grn_id)
    with app.app_context():
        saved = GRNCharge.query.filter(
            GRNCharge.grn_id == grn_id, GRNCharge.is_void == False  # noqa: E712
        ).all()
        assert [c.charge_type for c in saved] == ["UNLOADING"]
        assert grn_breakdown(db.session.get(GRN, grn_id))["landed_cost_total"] == pytest.approx(150800)


# ---- 4. legacy GRNs keep their own stored classification -----------------

def test_legacy_charge_keeps_its_untracked_classification(client, app):
    """A migrated legacy charge must survive an edit unchanged.

    Migration 0003 backfills old flat columns as ``UNTRACKED_LEGACY`` /
    ``UNSPECIFIED`` mirror obligations.  Those codes are not in the wizard's
    normal dropdowns: without a preserved option the browser posted the first
    option instead and silently reclassified history as a material cost.
    """
    from datetime import datetime

    login(client)
    with app.app_context():
        sup = Supplier(name="Legacy Sup", is_active=True)
        db.session.add(sup)
        db.session.flush()
        grn = GRN(supplier=sup.name, supplier_id=sup.id, manual_bill_no="LEG-GRID",
                  costing_mode="LEGACY", freight_cost=2000.0,
                  date_posted=datetime(2026, 9, 1, 10, 0))
        db.session.add(grn)
        db.session.flush()
        db.session.add(GRNCharge(
            grn_id=grn.id, charge_type="VEHICLE_FARE", amount=2000.0, amount_minor=200000,
            recipient_type="UNSPECIFIED", cost_treatment="UNTRACKED_LEGACY",
            is_legacy_mirror=True, legacy_column="freight_cost", declared_status="UNPAID",
        ))
        db.session.commit()
        grn_id, supplier_id = grn.id, sup.id

    html = client.get(f"/edit_grn/{grn_id}").get_data(as_text=True)
    grid = charge_grid(html)
    assert grid.count('class="grn-charge-row"') == 1, "the stored legacy charge is shown, no blanks added"
    assert "Unassigned (legacy charge)" in grid
    assert "Legacy (untracked)" in grid
    assert 'value="UNTRACKED_LEGACY" selected' in grid
    assert 'value="UNSPECIFIED" selected' in grid

    with app.app_context():
        charge_id = GRNCharge.query.filter(GRNCharge.grn_id == grn_id).first().id
    resp = client.post(f"/edit_grn/{grn_id}", data={
        "supplier": "Legacy Sup", "supplier_id": str(supplier_id),
        "date": "2026-09-01", "time": "10:00", "manual_bill_no": "LEG-GRID",
        "mat_name[]": [""], "qty[]": [""], "price[]": [""],
        "charge_grid_present": "1",
        "charge_id[]": [str(charge_id)],
        "charge_type[]": ["VEHICLE_FARE"], "charge_label[]": [""],
        "charge_amount[]": ["2000"], "charge_recipient_type[]": ["UNSPECIFIED"],
        "charge_recipient[]": [""], "charge_status[]": ["UNPAID"],
        "charge_treatment[]": ["UNTRACKED_LEGACY"], "charge_basis[]": ["VALUE"],
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        charge = GRNCharge.query.filter(
            GRNCharge.grn_id == grn_id, GRNCharge.is_void == False  # noqa: E712
        ).first()
        assert charge is not None, "the legacy charge must not be dropped"
        assert charge.cost_treatment == "UNTRACKED_LEGACY"
        assert charge.recipient_type == "UNSPECIFIED"
        assert float(charge.amount) == pytest.approx(2000)
