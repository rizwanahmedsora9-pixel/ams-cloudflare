"""Per-expense supplier billing: explicit choices, legacy fallback, form keys."""
from __future__ import annotations

from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

from app.services.grn_costing import (
    charge_billed_to_supplier, grn_breakdown, sync_charges_from_form,
)
from models import GRN, GRNCharge, Supplier, db


def _grn_with_charges(app):
    with app.app_context():
        supplier = Supplier(name="Choice Supplier", is_active=True)
        grn = GRN(supplier="Choice Supplier", costing_mode="LANDED",
                  include_charges_in_supplier=True)
        db.session.add_all([supplier, grn])
        db.session.flush()
        grn.supplier_id = supplier.id
        a = GRNCharge(grn_id=grn.id, charge_type="VEHICLE_FARE", amount=5000,
                      amount_minor=500000, include_in_supplier=None)
        b = GRNCharge(grn_id=grn.id, charge_type="LOADING", amount=1000,
                      amount_minor=100000, include_in_supplier=False)
        db.session.add_all([a, b])
        db.session.commit()
        # The release database acquired this column via ALTER TABLE, where
        # old rows really are NULL.  Simulate that state rather than a new ORM
        # insert (new rows correctly receive the explicit False default).
        db.session.execute(db.text("UPDATE grn_charge SET include_in_supplier = NULL WHERE id = :id"), {"id": a.id})
        db.session.commit()
        db.session.expire_all()
        return grn.id, a.id, b.id


def test_null_legacy_row_falls_back_but_explicit_unchecked_never_does(app):
    gid, aid, bid = _grn_with_charges(app)
    with app.app_context():
        grn = db.session.get(GRN, gid)
        a, b = db.session.get(GRNCharge, aid), db.session.get(GRNCharge, bid)
        assert charge_billed_to_supplier(a, grn) is True
        assert charge_billed_to_supplier(b, grn) is False
        assert grn_breakdown(grn)["supplier_billed_charges"] == 5000


def test_0005_copies_legacy_choice_once_and_keeps_later_explicit_choice(app):
    gid, aid, bid = _grn_with_charges(app)
    sql = (Path(__file__).resolve().parents[1] / "app" / "migrations" /
           "0005_grn_per_expense_supplier_billing.sql").read_text()
    with app.app_context():
        db.session.execute(db.text(sql))
        db.session.commit()
        assert db.session.get(GRNCharge, aid).include_in_supplier is True
        assert db.session.get(GRNCharge, bid).include_in_supplier is False
        db.session.get(GRNCharge, aid).include_in_supplier = False
        db.session.execute(db.text(sql))
        db.session.commit()
        assert db.session.get(GRNCharge, aid).include_in_supplier is False


def _form(selected=()):
    return MultiDict([
        ("charge_supplier_billing_present", "1"),
        ("charge_id[]", ""), ("charge_id[]", ""),
        ("charge_row_key[]", "new-a"), ("charge_row_key[]", "new-b"),
        ("charge_type[]", "VEHICLE_FARE"), ("charge_type[]", "LOADING"),
        ("charge_label[]", "Vehicle"), ("charge_label[]", "Loading"),
        ("charge_amount[]", "5000"), ("charge_amount[]", "1000"),
        ("charge_recipient_type[]", "TRANSPORTER"), ("charge_recipient_type[]", "LABOUR"),
        ("charge_recipient[]", "Transport"), ("charge_recipient[]", "Labour"),
        ("charge_treatment[]", "INVENTORY"), ("charge_treatment[]", "EXPENSE"),
        ("charge_basis[]", "VALUE"), ("charge_basis[]", "VALUE"),
        * [("charge_include_in_supplier[]", key) for key in selected],
    ])


def test_form_keys_select_only_named_rows_even_when_other_boxes_are_unchecked(app):
    with app.app_context():
        grn = GRN(supplier="Choice Supplier", costing_mode="LANDED")
        db.session.add(grn)
        db.session.flush()
        sync_charges_from_form(grn, _form(["new-b"]))
        db.session.commit()
        rows = GRNCharge.query.filter_by(grn_id=grn.id).order_by(GRNCharge.id).all()
        assert [c.include_in_supplier for c in rows] == [False, True]
        bd = grn_breakdown(grn)
        assert bd["supplier_billed_charges"] == 1000
        assert bd["capitalised_charge_total"] == 5000
        assert bd["expense_charge_total"] == 1000


def test_duplicate_or_unknown_billing_keys_are_refused(app):
    with app.app_context():
        grn = GRN(supplier="Choice Supplier", costing_mode="LANDED")
        db.session.add(grn)
        db.session.flush()
        duplicate = _form(["new-a"])
        duplicate.setlist("charge_row_key[]", ["new-a", "new-a"])
        with pytest.raises(ValueError, match="unique row key"):
            sync_charges_from_form(grn, duplicate)
        with pytest.raises(ValueError, match="does not match"):
            sync_charges_from_form(grn, _form(["missing-row"]))
