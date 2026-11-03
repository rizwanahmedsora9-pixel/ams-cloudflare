"""GRN Costs tab — cost kinds, supplier filter, date range; no paid option.

Owner requirements pinned here:

1. The GRN screen has no paid/unpaid control on a charge: a charge row carries
   cost facts only, and a posted GRN never creates a payment.
2. The GRN Costs tab lists every individual cost line — stock / vehicle fare /
   loading / unloading / other — and can be filtered by cost kind, supplier and
   date range.
3. The numbers come from ``grn_costing.grn_breakdown``: stock cost is exactly
   qty x rate, and each charge is its own line with its own recipient.
"""
from __future__ import annotations

import re

import pytest

from models import (
    Account, GRN, GRNCharge, Material, Supplier, SupplierPayment, db,
)
from tests.conftest import make_csrf_client

LOGIN = {"username": "Admin", "password": "Admin@fbm12345"}


@pytest.fixture()
def costs_app(app_factory, tmp_path):
    app = app_factory(tmp_path / "grn_costs.db")
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        from app.services.schema import _ensure_default_admin
        _ensure_default_admin()
        db.session.commit()
    return app


def login(client):
    assert client.post("/login", data=LOGIN, follow_redirects=True).status_code == 200


def seed(app):
    with app.app_context():
        sup_a = Supplier(name="Alpha Cement", is_active=True)
        sup_b = Supplier(name="Beta Steel", is_active=True)
        db.session.add_all([
            sup_a, sup_b,
            Material(code="CEM", name="Cement", total=0.0),
            Material(code="STL", name="Steel", total=0.0),
            Account(name="CASH", type="Cash", account_type="company",
                    category="cash", balance=0.0, balance_minor=0, is_active=True),
        ])
        db.session.commit()
        return sup_a.id, sup_b.id


def post_grn(client, supplier_id, supplier_name, *, items, charges=(), bill, date):
    data = {
        "action": "add",
        "supplier": supplier_name,
        "supplier_id": str(supplier_id),
        "date": date,
        "time": "10:00",
        "manual_bill_no": bill,
        "mat_name[]": [name for name, _qty, _rate in items],
        "qty[]": [str(qty) for _n, qty, _r in items],
        "price[]": [str(rate) for _n, _q, rate in items],
        "allocation_basis_default": "VALUE",
        "charge_grid_present": "1",
        "charge_id[]": [""] * len(charges),
        "charge_type[]": [c[0] for c in charges],
        "charge_label[]": [c[1] for c in charges],
        "charge_amount[]": [str(c[2]) for c in charges],
        "charge_recipient_type[]": [c[3] for c in charges],
        "charge_recipient[]": [c[4] for c in charges],
        "charge_treatment[]": [c[5] if len(c) > 5 else "INVENTORY" for c in charges],
        "charge_basis[]": ["VALUE"] * len(charges),
        "charge_note[]": [""] * len(charges),
    }
    resp = client.post("/grn", data=data, follow_redirects=True)
    assert resp.status_code == 200
    assert b"GRN added successfully" in resp.data, resp.data[:1500]


def rows_table(html):
    start = html.index('id="grnCostsTable"')
    return html[start:html.index("</table>", start)]


def row_kinds(html):
    table = rows_table(html)
    return re.findall(r'data-cost-kind="([A-Z]+)"', table)


def amounts(html):
    table = rows_table(html)
    body = table[table.index("<tbody>"):table.index("</tbody>")]
    return [float(v.replace(",", "")) for v in re.findall(r'fw-bold">([\d,]+\.\d{2})</td>', body)]


# --------------------------------------------------------------------------- #
# 1. no paid control on a GRN
# --------------------------------------------------------------------------- #
def test_charge_grid_has_no_paid_or_unpaid_control(costs_app):
    client = make_csrf_client(costs_app)
    login(client)
    seed(costs_app)
    html = client.get("/grn").get_data(as_text=True)
    grid = html[html.index('id="grnChargesTable"'):html.index("</table>", html.index('id="grnChargesTable"'))]
    assert 'name="charge_status[]"' not in grid, "a charge must carry no paid/unpaid field"
    assert "Payment Status" not in grid
    assert "Paid (declaration only)" not in html
    # The tab strip and its explanation are present instead.
    assert "grn-main-tabs" in html and "<ul class=\"nav nav-tabs" in html, "the Records | Costs tab strip must exist"
    assert ">Costs\n" in html or ">Costs<" in html
    assert "PAY EXISTING GRN" in html


def test_removing_the_paid_field_does_not_change_received_costs(costs_app):
    client = make_csrf_client(costs_app)
    login(client)
    sup_a, _sup_b = seed(costs_app)
    post_grn(client, sup_a, "Alpha Cement", bill="NP-1", date="2026-10-01",
             items=[("Cement", 10, 1500)],
             charges=[("LOADING", "Loading team", 400, "LABOUR", "Loading Team")])
    with costs_app.app_context():
        grn = GRN.query.filter(GRN.manual_bill_no.like("%NP-1")).one()
        charge = GRNCharge.query.filter_by(grn_id=grn.id).one()
        assert float(charge.amount or 0) == pytest.approx(400.0)
        assert charge.declared_status == "UNPAID"  # default kept, nothing invented
        assert float(grn.landed_cost_total or 0) == pytest.approx(15400.0)
        assert SupplierPayment.query.filter_by(grn_id=grn.id).count() == 0, "a GRN never pays"


# --------------------------------------------------------------------------- #
# 2. the GRN Costs tab
# --------------------------------------------------------------------------- #
def test_costs_tab_lists_every_cost_kind(costs_app):
    client = make_csrf_client(costs_app)
    login(client)
    sup_a, _sup_b = seed(costs_app)
    post_grn(client, sup_a, "Alpha Cement", bill="COST-1", date="2026-10-05",
             items=[("Cement", 100, 1500), ("Steel", 10, 20000)],
             charges=[
                 ("VEHICLE_FARE", "Rana Transport", 5000, "TRANSPORTER", "Rana Transport"),
                 ("LOADING", "Loading team", 1000, "LABOUR", "Loading Team"),
                 ("UNLOADING", "Unloading team", 700, "LABOUR", "Unload Team"),
                 ("OTHER", "Misc", 300, "OTHER", "Misc Party"),
             ])

    html = client.get("/grn?tab=costs").get_data(as_text=True)
    assert 'id="grnCostsTab"' in html
    # The Costs tab replaces the records table/toolbar instead of stacking on it.
    assert 'class="table table-hover grn-table"' not in html
    assert 'id="grnCostsFilter"' in html
    kinds = row_kinds(html)
    # Two stock lines + four charges.
    assert kinds.count("STOCK") == 2
    assert kinds.count("VEHICLE") == 1
    assert kinds.count("LOADING") == 1
    assert kinds.count("UNLOADING") == 1
    assert kinds.count("OTHER") == 1

    # Stock cost is exactly qty x rate; charges are their own lines.
    assert sorted(amounts(html)) == sorted([150000.0, 200000.0, 5000.0, 1000.0, 700.0, 300.0])

    # The tab never shows a paid control.
    assert "charge_status[]" not in html
    assert "Not Applicable" not in html


def test_costs_tab_filters_by_kind(costs_app):
    client = make_csrf_client(costs_app)
    login(client)
    sup_a, _sup_b = seed(costs_app)
    post_grn(client, sup_a, "Alpha Cement", bill="KIND-1", date="2026-10-06",
             items=[("Cement", 100, 1500)],
             charges=[
                 ("VEHICLE_FARE", "Rana Transport", 5000, "TRANSPORTER", "Rana Transport"),
                 ("TRANSPORT", "Second trip", 2000, "TRANSPORTER", "Rana Transport"),
                 ("LOADING", "Loading team", 1000, "LABOUR", "Loading Team"),
                 ("UNLOADING", "Unload team", 700, "LABOUR", "Unload Team"),
                 ("OTHER", "Misc", 300, "OTHER", "Misc Party"),
             ])

    vehicle = client.get("/grn?tab=costs&cost_kind=VEHICLE").get_data(as_text=True)
    assert set(row_kinds(vehicle)) == {"VEHICLE"}
    assert sum(amounts(vehicle)) == pytest.approx(7000.0)  # fare + transport

    loading = client.get("/grn?tab=costs&cost_kind=LOADING").get_data(as_text=True)
    assert set(row_kinds(loading)) == {"LOADING"}
    assert sum(amounts(loading)) == pytest.approx(1000.0)

    unloading = client.get("/grn?tab=costs&cost_kind=UNLOADING").get_data(as_text=True)
    assert set(row_kinds(unloading)) == {"UNLOADING"}
    assert sum(amounts(unloading)) == pytest.approx(700.0)

    stock = client.get("/grn?tab=costs&cost_kind=STOCK").get_data(as_text=True)
    assert set(row_kinds(stock)) == {"STOCK"}
    assert sum(amounts(stock)) == pytest.approx(150000.0)

    other = client.get("/grn?tab=costs&cost_kind=OTHER").get_data(as_text=True)
    assert set(row_kinds(other)) == {"OTHER"}
    assert sum(amounts(other)) == pytest.approx(300.0)

    every = client.get("/grn?tab=costs&cost_kind=ALL").get_data(as_text=True)
    assert sum(amounts(every)) == pytest.approx(150000.0 + 7000.0 + 1000.0 + 700.0 + 300.0)


def test_costs_tab_filters_by_supplier_and_date_range(costs_app):
    client = make_csrf_client(costs_app)
    login(client)
    sup_a, sup_b = seed(costs_app)
    post_grn(client, sup_a, "Alpha Cement", bill="A-1", date="2026-09-01",
             items=[("Cement", 10, 1500)],
             charges=[("LOADING", "Load A", 100, "LABOUR", "Load A")])
    post_grn(client, sup_b, "Beta Steel", bill="B-1", date="2026-10-15",
             items=[("Steel", 2, 20000)],
             charges=[("VEHICLE_FARE", "Fare B", 900, "TRANSPORTER", "Fare B")])

    by_supplier = client.get("/grn?tab=costs&cost_supplier=Beta+Steel").get_data(as_text=True)
    assert "Alpha Cement" not in rows_table(by_supplier)
    assert set(amounts(by_supplier)) == {40000.0, 900.0}

    by_range = client.get(
        "/grn?tab=costs&cost_start=2026-09-01&cost_end=2026-09-30").get_data(as_text=True)
    assert "Beta Steel" not in rows_table(by_range)
    assert set(amounts(by_range)) == {15000.0, 100.0}

    both = client.get(
        "/grn?tab=costs&cost_supplier=Alpha+Cement&cost_start=2026-10-01&cost_kind=ALL"
    ).get_data(as_text=True)
    assert "No all costs found" in both or 'data-cost-kind' not in rows_table(both)


def test_costs_tab_totals_match_the_filtered_rows(costs_app):
    client = make_csrf_client(costs_app)
    login(client)
    sup_a, _sup_b = seed(costs_app)
    post_grn(client, sup_a, "Alpha Cement", bill="TOT-1", date="2026-10-20",
             items=[("Cement", 100, 1500)],
             charges=[("VEHICLE_FARE", "Fare", 5000, "TRANSPORTER", "Fare"),
                      ("LOADING", "Load", 1000, "LABOUR", "Load")])

    html = client.get("/grn?tab=costs").get_data(as_text=True)
    # KPI strip: stock, vehicle, loading, unloading, other, grand total.
    assert "Rs 150,000.00" in html
    assert "Rs 5,000.00" in html
    assert "Rs 1,000.00" in html
    assert "Rs 156,000.00" in html

    filtered = client.get("/grn?tab=costs&cost_kind=VEHICLE").get_data(as_text=True)
    assert "filtered total" in filtered.lower()
    assert "Rs 5,000.00" in filtered


# --------------------------------------------------------------------------- #
# 3. the projection itself
# --------------------------------------------------------------------------- #
def test_projection_groups_and_totals(costs_app):
    client = make_csrf_client(costs_app)
    login(client)
    sup_a, _sup_b = seed(costs_app)
    post_grn(client, sup_a, "Alpha Cement", bill="PROJ-1", date="2026-10-21",
             items=[("Cement", 10, 1500)],
             charges=[("VEHICLE_FARE", "Fare", 200, "TRANSPORTER", "Fare"),
                      ("LOADING", "Load", 50, "LABOUR", "Load")])
    with costs_app.app_context():
        from app.services.grn_costs import build_grn_costs, normalize_kind

        full = build_grn_costs()
        assert full["totals"]["STOCK"] == pytest.approx(15000.0)
        assert full["totals"]["VEHICLE"] == pytest.approx(200.0)
        assert full["totals"]["LOADING"] == pytest.approx(50.0)
        assert full["totals"]["UNLOADING"] == pytest.approx(0.0)
        assert full["grand_total"] == pytest.approx(15250.0)
        assert full["row_count"] == 3

        only_vehicle = build_grn_costs(kind="vehicle")
        assert only_vehicle["kind"] == "VEHICLE"
        assert [r["kind"] for r in only_vehicle["rows"]] == ["VEHICLE"]
        assert only_vehicle["filtered_total"] == pytest.approx(200.0)
        # Narrowing the list never hides the whole picture.
        assert only_vehicle["grand_total"] == pytest.approx(15250.0)

        # An unreadable kind/date falls back instead of exploding.
        assert normalize_kind("nonsense") == "ALL"
        assert build_grn_costs(kind="nonsense", start="not-a-date", end="")["row_count"] == 3
