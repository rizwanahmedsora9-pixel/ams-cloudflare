"""Delivery Person Ledger — expandable daily summary rows.

Verifies that:
* chronological movements are grouped by calendar date into one expandable row
  per day with exact Decimal totals (debit, credit, net, closing_balance),
* opening balance and start-date carry-forward rows remain standalone groups so
  they never distort operational daily totals,
* multi-slice FIFO driver settlements collapse cleanly into the payment date's
  total credit while keeping every underlying bill slice and edit/reverse
  control inside the expandable detail row,
* pagination paginates whole day groups so a busy day is never split across
  two pages,
* the rendered /delivery_person_ledger/<id> page starts collapsed by default
  (aria-expanded="false", detail row hidden) while supplier/client ledgers
  keep their standard layout.
"""
from __future__ import annotations

from datetime import datetime
import re

import pytest

ADMIN = {"username": "Admin", "password": "Admin@fbm12345"}


def _login(client):
    resp = client.post("/login", data=dict(ADMIN))
    assert resp.status_code in (302, 303)


def _seed_driver_ledger(app):
    from models import Account, DeliveryPerson, DirectSale, SaleDeliveryPerson, db
    from app.services.driver_payments import settle_driver_fifo

    with app.app_context():
        cash = Account(
            name="LEDGER CASH",
            type="CASH",
            account_type="company",
            category="cash",
            balance=200000.0,
            opening_balance=200000.0,
            opening_balance_date=datetime(2026, 1, 1),
            is_active=True,
        )
        person = DeliveryPerson(
            name="HAFIZ SHOAIB",
            phone="0300-1112233",
            opening_balance=500.0,
            opening_balance_date=datetime(2026, 10, 1, 9, 0),
            is_active=True,
        )
        db.session.add_all([cash, person])
        db.session.commit()

        # Day 1 (2026-10-05): 3 trips -> 1000 + 1500 + 800 = 3300
        day1_rents = [(10, 1000.0, 25), (14, 1500.0, 40), (17, 800.0, 20)]
        for idx, (hour, rent, bags) in enumerate(day1_rents, start=1):
            sale = DirectSale(
                client_name=f"CLIENT D1-{idx}",
                client_code=f"CL-D1-{idx}",
                category="Credit Customer",
                amount=5000.0,
                date_posted=datetime(2026, 10, 5, hour, 0),
                manual_bill_no=f"MB-10{idx}",
                is_void=False,
            )
            db.session.add(sale)
            db.session.flush()
            db.session.add(SaleDeliveryPerson(
                sale_id=sale.id,
                delivery_person_id=person.id,
                bags_delivered=bags,
                rent_amount=rent,
                created_at=datetime(2026, 10, 5, hour, 0),
            ))

        # Day 2 (2026-10-06): 2 trips (600 + 900 = 1500) + 1 FIFO lump-sum
        # settlement of 2800 paid + 200 waived (splits across multiple trips!)
        day2_rents = [(9, 600.0, 15), (11, 900.0, 30)]
        for idx, (hour, rent, bags) in enumerate(day2_rents, start=1):
            sale = DirectSale(
                client_name=f"CLIENT D2-{idx}",
                client_code=f"CL-D2-{idx}",
                category="Credit Customer",
                amount=4000.0,
                date_posted=datetime(2026, 10, 6, hour, 0),
                manual_bill_no=f"MB-20{idx}",
                is_void=False,
            )
            db.session.add(sale)
            db.session.flush()
            db.session.add(SaleDeliveryPerson(
                sale_id=sale.id,
                delivery_person_id=person.id,
                bags_delivered=bags,
                rent_amount=rent,
                created_at=datetime(2026, 10, 6, hour, 0),
            ))
        db.session.commit()

        payment_rows = settle_driver_fifo(
            delivery_person_id=person.id,
            amount_paid=2800.0,
            waive_off_amount=200.0,
            method="Cash",
            payment_account_id=cash.id,
            reference="VCH-77",
            date_posted="2026-10-06",
            note="Lump-sum driver settlement",
        )
        db.session.commit()
        return {
            "person_id": person.id,
            "account_id": cash.id,
            "payment_ids": [p.id for p in payment_rows],
        }


def test_daily_groups_totals_and_running_balance_chain(app):
    from app.services.financial_ledgers import build_delivery_person_financial_ledger
    from models import DeliveryPerson

    seeded = _seed_driver_ledger(app)
    with app.app_context():
        person = DeliveryPerson.query.get(seeded["person_id"])
        ledger = build_delivery_person_financial_ledger(person)

        groups = ledger["day_groups"]
        # 1 opening group + 2 operational day groups (2026-10-05 and 2026-10-06)
        assert [g["kind"] for g in groups] == ["opening", "day", "day"]
        assert [g["date"] for g in groups] == ["2026-10-01", "2026-10-05", "2026-10-06"]

        # Opening: 500 debit -> balance 500
        g_open, g_day1, g_day2 = groups
        assert g_open["total_debit"] == pytest.approx(500.0)
        assert g_open["total_credit"] == pytest.approx(0.0)
        assert g_open["closing_balance"] == pytest.approx(500.0)

        # Day 1: 3 trips = 3300 debit -> balance 3800
        assert g_day1["entry_count"] == 3
        assert g_day1["total_debit"] == pytest.approx(3300.0)
        assert g_day1["total_credit"] == pytest.approx(0.0)
        assert g_day1["closing_balance"] == pytest.approx(3800.0)
        assert "3 Delivery Rent" in g_day1["summary_text"]

        # Day 2: 2 trips (1500 debit) + multi-slice FIFO settlement (2800 paid + 200 waive = 3000 credit)
        # Running balance: 3800 + 1500 - 3000 = 2300
        assert len(seeded["payment_ids"]) >= 3  # FIFO split across multiple trips
        assert g_day2["total_debit"] == pytest.approx(1500.0)
        assert g_day2["total_credit"] == pytest.approx(3000.0)
        assert g_day2["net"] == pytest.approx(-1500.0)
        assert g_day2["closing_balance"] == pytest.approx(2300.0)
        assert g_day2["closing_balance"] == pytest.approx(ledger["closing_balance"])

        # Invariant: sum of group entries and totals equals underlying ledger rows
        assert sum(g["entry_count"] for g in groups) == len(ledger["filtered_rows"])
        assert sum(g["total_debit"] for g in groups) == pytest.approx(ledger["total_debit"])
        assert sum(g["total_credit"] for g in groups) == pytest.approx(ledger["total_credit"])


def test_start_date_carry_forward_stays_separate_from_day_totals(app):
    from app.services.financial_ledgers import build_delivery_person_financial_ledger
    from models import DeliveryPerson

    seeded = _seed_driver_ledger(app)
    with app.app_context():
        person = DeliveryPerson.query.get(seeded["person_id"])
        ledger = build_delivery_person_financial_ledger(person, start_date="2026-10-06")

        groups = ledger["day_groups"]
        assert [g["kind"] for g in groups] == ["carry_forward", "day"]
        carry, day2 = groups
        assert carry["closing_balance"] == pytest.approx(3800.0)
        assert carry["total_debit"] == pytest.approx(0.0)
        assert carry["total_credit"] == pytest.approx(0.0)

        # Day 2 operational totals are strictly Day 2's own movements
        assert day2["date"] == "2026-10-06"
        assert day2["total_debit"] == pytest.approx(1500.0)
        assert day2["total_credit"] == pytest.approx(3000.0)
        assert day2["closing_balance"] == pytest.approx(2300.0)


def test_busy_day_never_splits_across_pages(app, client):
    """Pagination slices day groups, never raw rows inside a single day."""
    from models import DeliveryPerson, DirectSale, SaleDeliveryPerson, db

    _login(client)
    with app.app_context():
        person = DeliveryPerson(name="BUSY DRIVER", is_active=True)
        db.session.add(person)
        db.session.commit()
        # 30 trips on ONE single day (exceeds default per_page=25 if raw rows were paginated)
        for idx in range(30):
            sale = DirectSale(
                client_name=f"BULK CLIENT {idx}",
                client_code=f"BC-{idx}",
                category="Credit Customer",
                amount=1000.0,
                date_posted=datetime(2026, 10, 12, 8 + (idx % 10), idx % 60),
                manual_bill_no=f"BULK-{idx}",
                is_void=False,
            )
            db.session.add(sale)
            db.session.flush()
            db.session.add(SaleDeliveryPerson(
                sale_id=sale.id,
                delivery_person_id=person.id,
                bags_delivered=10,
                rent_amount=100.0,
                created_at=datetime(2026, 10, 12, 8 + (idx % 10), idx % 60),
            ))
        db.session.commit()
        person_id = person.id

    resp = client.get(f"/delivery_person_ledger/{person_id}?per_page=10")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # All 30 trips belong to 2026-10-12 -> 1 day group, Page 1 of 1, full Rs. 3,000.00 total
    assert "1 day" in html
    assert "30 movements" in html
    assert "Page 1 of 1" in html
    assert "Rs. 3,000.00" in html
    for idx in range(30):
        assert f"BULK-{idx}" in html


def test_rendered_driver_ledger_starts_collapsed_with_expandable_details(app, client):
    from models import Supplier, db

    seeded = _seed_driver_ledger(app)
    _login(client)

    resp = client.get(f"/delivery_person_ledger/{seeded['person_id']}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Driver expandable table and JS present
    assert 'id="driverLedgerTable"' in html
    assert 'id="driverLedgerToggleAll"' in html
    assert 'driver_ledger.js' in html

    # Summary rows start collapsed (aria-expanded="false") and detail rows start hidden
    summary_matches = re.findall(r'<tr class="driver-day-row"[^>]*>', html)
    detail_matches = re.findall(r'<tr class="driver-day-detail-row"[^>]*>', html)
    assert len(summary_matches) == 3
    assert len(detail_matches) == 3
    for tag in summary_matches:
        assert 'aria-expanded="false"' in tag
    for tag in detail_matches:
        assert "hidden" in tag

    # Collapsed totals and underlying detail bills/edit modals are both present in DOM
    assert "Rs. 3,300.00" in html
    assert "Rs. 1,500.00" in html
    assert "Rs. 3,000.00" in html
    assert "MB-101" in html
    assert "MB-202" in html
    for pid in seeded["payment_ids"]:
        assert f'id="editDriverPayment{pid}"' in html

    # API endpoint exposes both rows and day_groups
    api_resp = client.get(f"/api/delivery_person_ledger/{seeded['person_id']}")
    assert api_resp.status_code == 200
    payload = api_resp.get_json()
    assert payload["ok"] is True
    assert len(payload["day_groups"]) == 3
    assert payload["closing_balance"] == pytest.approx(2300.0)

    # Supplier ledger keeps its standard flat itemised layout
    with app.app_context():
        sup = Supplier(name="TEST SUPPLIER LEDGER")
        db.session.add(sup)
        db.session.commit()
        sup_id = sup.id
    sup_resp = client.get(f"/supplier_ledger/{sup_id}")
    assert sup_resp.status_code == 200
    sup_html = sup_resp.get_data(as_text=True)
    assert 'id="driverLedgerTable"' not in sup_html
