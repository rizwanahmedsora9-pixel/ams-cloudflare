"""Editing a GRN must go through — sold stock or not.

Owner rule (``EDIT_POLICY.md``): a save is refused only when the data would be
wrong, never because a lot has already been sold.  The GRN edit route used to
refuse

* every item quantity/rate change, addition and removal once any part of the
  lot had been consumed by a cash/credit sale, and
* every landed-cost change (freight, loading, a corrected supplier rate) once
  delivered stock existed,

so in a working shop the pencil looked broken while the Client Ledger edited
freely.  These tests pin the new behaviour through the real HTTP route:

1. the edit page opens (it used to 500 for a GRN with no bill number),
2. quantity/rate/charge/price edits on a sold lot are saved,
3. the sale that consumed the lot is re-costed, so stock value and its frozen
   COGS still agree afterwards,
4. only impossible numbers are refused (a lot cannot hold less than it sold,
   a sold lot cannot be removed).
"""
from datetime import datetime

import pytest
from werkzeug.datastructures import MultiDict

from models import (
    DirectSale, DirectSaleItem, Entry, GRN, GRNCharge, GRNAllocation, GRNItem,
    Material, Supplier, SupplierPayment, db,
)

MATERIAL = "Cement 50kg"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _login(client, username="Admin", password="Admin@fbm12345"):
    response = client.post("/login", data={"username": username, "password": password})
    assert response.status_code in (302, 303)


def _seed_master():
    material = Material(code="MAT-GRN", name=MATERIAL, unit="Bag", unit_price=1200,
                        total=0, is_active=True)
    supplier = Supplier(name="Test Supplier", is_active=True)
    db.session.add_all([material, supplier])
    db.session.commit()
    return supplier.id


def _add_grn(client, *, qty=10, price=1200, charge=None, charge_include_supplier=False):
    """Post the real "add GRN" form and return the new GRN id."""
    data = {
        "action": "add",
        "supplier": "Test Supplier",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": "09:00",
        "mat_name[]": [MATERIAL],
        "qty[]": [str(qty)],
        "price[]": [str(price)],
        "charge_grid_present": "1",
        "charge_supplier_billing_present": "1",
        "note": "initial",
    }
    if charge is not None:
        data.update({
            "charge_type[]": ["FREIGHT"],
            "charge_label[]": [""],
            "charge_amount[]": [str(charge)],
            "charge_row_key[]": ["new-1"],
            "charge_recipient_type[]": ["SUPPLIER"],
            "charge_recipient[]": [""],
            "charge_treatment[]": ["INVENTORY"],
            "charge_basis[]": ["VALUE"],
            "charge_id[]": [""],
        })
        if charge_include_supplier:
            data["charge_include_in_supplier[]"] = ["new-1"]
    response = client.post("/grn", data=data, follow_redirects=False)
    assert response.status_code in (302, 303)


def _newest_grn_id(app):
    with app.app_context():
        grn = GRN.query.order_by(GRN.id.desc()).first()
        assert grn is not None, "the GRN was not saved"
        return grn.id


def _consume(app, grn_id, qty, sale_price=1200):
    """Post a cash sale that consumes *qty* from the GRN's first lot."""
    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        item = grn.items[0]
        supplier = Supplier.query.first()
        sale = DirectSale(
            client_name="Customer A",
            category="Cash",
            amount=float(qty) * float(sale_price),
            auto_bill_no="SB-SL-TEST",
            date_posted=datetime.now(),
            is_void=False,
        )
        db.session.add(sale)
        db.session.flush()
        sale_item = DirectSaleItem(
            sale_id=sale.id,
            product_name=item.mat_name,
            qty=float(qty),
            price_at_time=float(sale_price),
            grn_item_id=item.id,
            cost_rate_at_sale=float(item.landed_unit_cost or item.price_at_time or 0),
        )
        db.session.add(sale_item)
        db.session.flush()
        db.session.add(GRNAllocation(
            sale_id=sale.id,
            sale_item_id=sale_item.id,
            grn_item_id=item.id,
            qty=float(qty),
            cost_rate=float(item.landed_unit_cost or item.price_at_time or 0),
            is_void=False,
        ))
        item.is_locked = True
        db.session.commit()
        return item.id, sale_item.id


def _edit_payload(**overrides):
    data = {
        "item_grid_present": "1",
        "supplier": "Test Supplier",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": "09:00",
        "mat_name[]": [MATERIAL],
        "qty[]": ["10"],
        "price[]": ["1200"],
        "grn_item_id[]": [""],
        "note": "edited",
        "charge_grid_present": "1",
        "charge_supplier_billing_present": "1",
    }
    data.update(overrides)
    return data


def _flash_text(response):
    return " ".join(response.get_data(as_text=True).split())


# --------------------------------------------------------------------------- #
# the edit page itself
# --------------------------------------------------------------------------- #
def test_edit_page_opens_for_a_grn_without_any_bill_number(app, client):
    """A GRN with no manual/auto bill number used to 500 the whole page.

    ``url_for('view_bill', bill_no='')`` cannot be built (the route takes a
    ``path`` parameter), so the listing and the edit page crashed instead of
    letting the operator fix the legacy row.
    """
    with app.app_context():
        supplier = Supplier(name="Legacy Supplier", is_active=True)
        db.session.add(supplier)
        db.session.commit()
        grn = GRN(supplier="Legacy Supplier", supplier_id=supplier.id,
                  manual_bill_no=None, auto_bill_no=None,
                  date_posted=datetime.now(), costing_mode="LANDED", created_by="Admin")
        db.session.add(grn)
        db.session.flush()
        db.session.add(GRNItem(grn_id=grn.id, mat_name=MATERIAL, qty=5, price_at_time=1200))
        db.session.commit()
        grn_id = grn.id

    _login(client)
    assert client.get("/grn").status_code == 200
    assert client.get(f"/edit_grn/{grn_id}").status_code == 200


# --------------------------------------------------------------------------- #
# edits on a lot that has already been sold
# --------------------------------------------------------------------------- #
def test_quantity_change_on_a_sold_lot_is_saved(app, client):
    with app.app_context():
        _seed_master()
    _login(client)
    _add_grn(client, qty=10)
    grn_id = _newest_grn_id(app)
    item_id, _ = _consume(app, grn_id, qty=4)

    response = client.post(
        f"/edit_grn/{grn_id}",
        data=_edit_payload(**{
            "grn_item_id[]": [str(item_id)],
            "qty[]": ["12"],
        }),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "locked lots" not in _flash_text(response).lower()

    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        assert [float(i.qty) for i in grn.items] == [12.0]
        assert grn.items[0].id == item_id, "the lot must keep its identity for the sale that used it"
        assert grn.note == "edited"
        in_qty = sum(float(e.qty or 0) for e in Entry.query.filter_by(type="IN").all())
        assert in_qty == 12.0
        assert float(Material.query.filter_by(name=MATERIAL).first().total) == 12.0


def test_price_change_on_a_sold_lot_recosts_the_sale(app, client):
    """The frozen COGS follows the corrected supplier rate instead of blocking."""
    with app.app_context():
        _seed_master()
    _login(client)
    _add_grn(client, qty=10, price=1200)
    grn_id = _newest_grn_id(app)
    item_id, sale_item_id = _consume(app, grn_id, qty=4)

    response = client.post(
        f"/edit_grn/{grn_id}",
        data=_edit_payload(**{
            "grn_item_id[]": [str(item_id)],
            "price[]": ["1500"],
        }),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "frozen sale cogs" not in _flash_text(response).lower()

    with app.app_context():
        item = db.session.get(GRNItem, item_id)
        assert float(item.price_at_time) == 1500.0
        alloc = GRNAllocation.query.filter_by(grn_item_id=item_id).one()
        assert abs(float(alloc.cost_rate) - 1500.0) < 1e-6
        sale_item = db.session.get(DirectSaleItem, sale_item_id)
        assert abs(float(sale_item.cost_rate_at_sale) - 1500.0) < 1e-6


def test_landed_charge_change_on_a_sold_lot_is_saved_and_recosted(app, client):
    with app.app_context():
        _seed_master()
    _login(client)
    _add_grn(client, qty=10, price=1200, charge=500)
    grn_id = _newest_grn_id(app)
    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        item_id = grn.items[0].id
        charge_id = grn.charges[0].id
    _consume(app, grn_id, qty=4)

    response = client.post(
        f"/edit_grn/{grn_id}",
        data=_edit_payload(**{
            "grn_item_id[]": [str(item_id)],
            "charge_id[]": [str(charge_id)],
            "charge_type[]": ["FREIGHT"],
            "charge_label[]": [""],
            "charge_amount[]": ["700"],
            "charge_row_key[]": [f"saved-{charge_id}"],
            "charge_recipient_type[]": ["SUPPLIER"],
            "charge_recipient[]": [""],
            "charge_treatment[]": ["INVENTORY"],
            "charge_basis[]": ["VALUE"],
        }),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "frozen sale cogs" not in _flash_text(response).lower()

    with app.app_context():
        charge = db.session.get(GRNCharge, charge_id)
        assert abs(float(charge.amount) - 700.0) < 1e-6
        item = db.session.get(GRNItem, item_id)
        expected_unit = (10 * 1200.0 + 700.0) / 10.0
        assert abs(float(item.landed_unit_cost) - expected_unit) < 1e-4
        alloc = GRNAllocation.query.filter_by(grn_item_id=item_id).one()
        assert abs(float(alloc.cost_rate) - expected_unit) < 1e-4


# --------------------------------------------------------------------------- #
# the refusals that stay: the data would be wrong
# --------------------------------------------------------------------------- #
def test_reducing_a_lot_below_what_was_sold_is_refused(app, client):
    with app.app_context():
        _seed_master()
    _login(client)
    _add_grn(client, qty=10)
    grn_id = _newest_grn_id(app)
    item_id, _ = _consume(app, grn_id, qty=4)

    response = client.post(
        f"/edit_grn/{grn_id}",
        data=_edit_payload(**{
            "grn_item_id[]": [str(item_id)],
            "qty[]": ["2"],
            "note": "should not save",
        }),
        follow_redirects=True,
    )
    text = _flash_text(response)
    assert response.status_code == 200
    assert "already been sold from this lot" in text
    assert "enter 4.00 or more" in text.lower()

    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        assert [float(i.qty) for i in grn.items] == [10.0]
        assert grn.note == "initial", "nothing may be saved when the edit is refused"


def test_removing_a_sold_lot_is_refused(app, client):
    with app.app_context():
        _seed_master()
    _login(client)
    _add_grn(client, qty=10)
    grn_id = _newest_grn_id(app)
    _consume(app, grn_id, qty=4)

    # The wizard posts the whole grid; every row removed means no mat_name[].
    response = client.post(
        f"/edit_grn/{grn_id}",
        data={
                "item_grid_present": "1",
            "supplier": "Test Supplier",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": "09:00",
            "note": "remove attempt",
        },
        follow_redirects=True,
    )
    text = _flash_text(response)
    assert response.status_code == 200
    assert "cannot be removed" in text

    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        assert len([i for i in grn.items if not i.is_void]) == 1
        assert grn.note == "initial"


# --------------------------------------------------------------------------- #
# ordinary edits keep working
# --------------------------------------------------------------------------- #
def test_unsold_lines_can_be_replaced_and_added(app, client):
    with app.app_context():
        _seed_master()
        db.session.add(Material(code="MAT-GRN-2", name="Sand", unit="Cft",
                                unit_price=100, total=0, is_active=True))
        db.session.commit()
    _login(client)
    _add_grn(client, qty=10)

    with app.app_context():
        grn_id = GRN.query.order_by(GRN.id.desc()).first().id
        old_item_id = GRN.query.get(grn_id).items[0].id

    response = client.post(
        f"/edit_grn/{grn_id}",
        data=_edit_payload(**{
            "grn_item_id[]": ["", ""],
            "mat_name[]": [MATERIAL, "Sand"],
            "qty[]": ["8", "5"],
            "price[]": ["1200", "100"],
        }),
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        lines = {i.mat_name: float(i.qty) for i in grn.items}
        assert lines == {MATERIAL: 8.0, "Sand": 5.0}
        assert old_item_id not in [i.id for i in grn.items]
        entries = {(e.material, float(e.qty)) for e in Entry.query.filter_by(type="IN").all()}
        assert entries == {(MATERIAL, 8.0), ("Sand", 5.0)}


def test_header_only_post_leaves_the_lines_untouched(app, client):
    with app.app_context():
        _seed_master()
    _login(client)
    _add_grn(client, qty=10)
    grn_id = _newest_grn_id(app)

    response = client.post(
        f"/edit_grn/{grn_id}",
        data={
                "supplier": "Test Supplier",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": "09:00",
            "note": "header only",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        grn = db.session.get(GRN, grn_id)
        assert grn.note == "header only"
        assert [float(i.qty) for i in grn.items] == [10.0]


# --------------------------------------------------------------------------- #
# an expense that Accounts already paid
# --------------------------------------------------------------------------- #
def test_paid_charge_can_be_increased_but_not_lowered_below_paid(app, client):
    from app.services.grn_costing import sync_charges_from_form

    with app.app_context():
        _seed_master()
        grn = GRN(supplier="Test Supplier", auto_bill_no="SB-GRN-PAID",
                  date_posted=datetime.now(), costing_mode="LANDED", created_by="Admin")
        db.session.add(grn)
        db.session.flush()
        db.session.add(GRNItem(grn_id=grn.id, mat_name=MATERIAL, qty=10, price_at_time=1200))
        charge = GRNCharge(grn_id=grn.id, charge_type="FREIGHT", amount_minor=50000,
                           amount=500.0, cost_treatment="INVENTORY",
                           allocation_basis="VALUE", is_void=False)
        db.session.add(charge)
        db.session.flush()
        supplier = Supplier.query.first()
        db.session.add(SupplierPayment(
            supplier_id=supplier.id, grn_id=grn.id, grn_charge_id=charge.id,
            amount=200.0, amount_minor=20000, is_void=False,
            date_posted=datetime.now(), created_by="Admin",
        ))
        db.session.commit()
        grn_id, charge_id = grn.id, charge.id

        def payload(amount):
            return MultiDict([
                ("charge_grid_present", "1"),
                ("charge_supplier_billing_present", "1"),
                ("charge_id[]", str(charge_id)),
                ("charge_type[]", "FREIGHT"),
                ("charge_label[]", ""),
                ("charge_amount[]", str(amount)),
                ("charge_row_key[]", f"saved-{charge_id}"),
                ("charge_recipient_type[]", "SUPPLIER"),
                ("charge_recipient[]", ""),
                ("charge_treatment[]", "INVENTORY"),
                ("charge_basis[]", "VALUE"),
            ])

        # Lower than the Rs 200 already paid: impossible, refused with a reason.
        with pytest.raises(ValueError) as blocked:
            sync_charges_from_form(db.session.get(GRN, grn_id), payload(100), actor="Admin")
        db.session.rollback()
        assert "cannot be set below" in str(blocked.value)

        # Increasing it is a normal correction and must go through.
        sync_charges_from_form(db.session.get(GRN, grn_id), payload(650), actor="Admin")
        db.session.commit()
        assert abs(float(db.session.get(GRNCharge, charge_id).amount) - 650.0) < 1e-6
