"""The master export/import must preserve each expense's supplier-billing choice."""
from __future__ import annotations

from io import BytesIO

import pandas as pd

from models import GRN, GRNCharge, Supplier, db


def test_master_export_import_round_trips_mixed_supplier_choices(app):
    from blueprints.import_export.export_build import _build_master_export_bytes
    from blueprints.import_export.sheets_master_supply import _process_grn_charges

    with app.app_context():
        supplier = Supplier(name="Billing Supplier", is_active=True)
        grn = GRN(supplier="Billing Supplier", manual_bill_no="BILL-EXPORT", costing_mode="LANDED")
        db.session.add_all([supplier, grn])
        db.session.flush()
        grn.supplier_id = supplier.id
        db.session.add_all([
            GRNCharge(grn_id=grn.id, charge_type="VEHICLE_FARE", label="Vehicle",
                      amount=5000, amount_minor=500000, include_in_supplier=True),
            GRNCharge(grn_id=grn.id, charge_type="LOADING", label="Loading",
                      amount=1000, amount_minor=100000, include_in_supplier=False),
        ])
        db.session.commit()
        exported = _build_master_export_bytes()

    book = pd.read_excel(BytesIO(exported), sheet_name="GRNCharges")
    assert book["Include In Supplier"].tolist() == [True, False]

    # Import into a fresh database: only the selected row may bill the supplier.
    with app.app_context():
        db.session.query(GRNCharge).delete()
        db.session.query(GRN).delete()
        db.session.query(Supplier).delete()
        db.session.commit()
        supplier = Supplier(name="Billing Supplier", is_active=True)
        grn = GRN(supplier="Billing Supplier", manual_bill_no="BILL-EXPORT", costing_mode="LANDED")
        db.session.add_all([supplier, grn])
        db.session.commit()
        frame = book.copy()
        frame.columns = [c.lower().strip().replace(" ", "_") for c in frame.columns]
        report = {"imported": 0, "skipped": 0, "errors": 0}
        _process_grn_charges(frame.fillna(""), "update", report)
        db.session.commit()
        assert report["imported"] == 2
        rows = GRNCharge.query.order_by(GRNCharge.id).all()
        assert [c.include_in_supplier for c in rows] == [True, False]
        from app.services.grn_costing import grn_breakdown
        assert grn_breakdown(grn)["supplier_billed_charges"] == 5000
