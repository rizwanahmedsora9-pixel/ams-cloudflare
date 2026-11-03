"""Delivery Rent — one summary row per delivery person, trips behind an arrow.

The screen used to print one table row per trip, so ten drivers doing ten
deliveries each produced a hundred rows a day.  These tests pin the replacement
behaviour:

* every delivery person is summarised once with rent / paid / remaining,
* the summary totals are exactly the sum of the trips underneath,
* the expand endpoint returns the same detail the page would have rendered,
* the driver's total agrees with the driver ledger (the number that decides how
  much cash may leave the business),
* filters, the per-day view and permissions keep working.
"""
from __future__ import annotations

from datetime import datetime

ADMIN = {"username": "Admin", "password": "Admin@fbm12345"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def login(client):
    response = client.post("/login", data=dict(ADMIN))
    assert response.status_code in (302, 303), response.get_data(as_text=True)[:300]


def seed(app, *, drivers=("ALI", "BILAL", "KAMRAN"), trips=4):
    """Create drivers, a cash account and ``trips`` sales per driver."""
    from models import Account, DeliveryPerson, DirectSale, SaleDeliveryPerson, db

    with app.app_context():
        account = Account(
            name="RENT CASH", type="CASH", account_type="company", category="cash",
            balance=100000.0, opening_balance=100000.0,
            opening_balance_date=datetime(2026, 1, 1), is_active=True,
        )
        db.session.add(account)
        people = []
        for name in drivers:
            person = DeliveryPerson(name=name, is_active=True)
            db.session.add(person)
            people.append(person)
        db.session.commit()

        created = {"sales": [], "allocations": []}
        for index, person in enumerate(people):
            for trip in range(trips):
                day = 5 + trip
                sale = DirectSale(
                    client_name=f"CLIENT {index}{trip}",
                    client_code=f"CL-{index}{trip}",
                    category="Credit Customer",
                    amount=1000.0 + trip,
                    date_posted=datetime(2026, 10, day, 10, 0),
                    manual_bill_no=f"BILL-{index}{trip}",
                    is_void=False,
                )
                db.session.add(sale)
                db.session.flush()
                allocation = SaleDeliveryPerson(
                    sale_id=sale.id,
                    delivery_person_id=person.id,
                    bags_delivered=10 + trip,
                    rent_amount=100.0 + (10 * trip),
                    created_at=datetime(2026, 10, day, 10, 0),
                )
                db.session.add(allocation)
                db.session.flush()
                created["sales"].append(sale.id)
                created["allocations"].append(allocation.id)
        db.session.commit()
        created["people"] = [p.id for p in people]
        created["account"] = account.id
        return created


def pay(app, *, person_id, amount, allocation_id=None, waive=0.0, day="2026-10-20"):
    """Record a settlement through the real service (account + ledger effects)."""
    from app.services.driver_payments import save_driver_payment
    from models import db

    with app.app_context():
        payment, created = save_driver_payment(
            delivery_person_id=person_id,
            allocation_id=allocation_id,
            amount_paid=amount,
            waive_off_amount=waive,
            method="Cash",
            payment_account_id=_cash_account_id(),
            date_posted=day,
            note="test settlement",
        )
        db.session.commit()
        assert created
        return payment.id


def _cash_account_id():
    from models import Account
    return Account.query.filter_by(name="RENT CASH").first().id


def group_payload(app, **filters):
    from app.services.delivery_rent_groups import build_delivery_rent_groups
    with app.app_context():
        return build_delivery_rent_groups(**filters)


def group_by_id(payload, person_id):
    return next(g for g in payload["groups"] if g["delivery_person_id"] == person_id)


# --------------------------------------------------------------------------- #
# grouping and totals
# --------------------------------------------------------------------------- #
def test_one_summary_row_per_delivery_person(app):
    created = seed(app)
    payload = group_payload(app)

    assert payload["group_by"] == "person"
    assert len(payload["groups"]) == 3
    # 3 drivers x 4 trips = 12 detail rows, but only three lines to read.
    assert payload["totals"]["entries"] == 12
    assert payload["totals"]["groups"] == 3

    for person_id in created["people"]:
        group = group_by_id(payload, person_id)
        assert group["entry_count"] == 4
        assert len(group["entries"]) == 4
        # 100 + 110 + 120 + 130
        assert group["rent"] == 460.0
        assert group["paid"] == 0.0
        assert group["due"] == 460.0
        assert group["status"] == "due"


def test_summary_is_the_sum_of_its_trips_and_of_the_period(app):
    created = seed(app)
    # Pay one trip in full, a second one partly, and waive a little off a third.
    first_three = created["allocations"][:3]
    pay(app, person_id=created["people"][0], amount=100.0, allocation_id=first_three[0])
    pay(app, person_id=created["people"][0], amount=40.0, allocation_id=first_three[1])
    pay(app, person_id=created["people"][0], amount=0.0, waive=15.0, allocation_id=first_three[2])

    payload = group_payload(app)
    group = group_by_id(payload, created["people"][0])

    assert group["rent"] == 460.0
    assert group["paid"] == 140.0
    assert group["waived"] == 15.0
    assert group["due"] == 305.0
    # The header must equal the sum of the detail rows to the paisa.
    assert round(sum(e["rent"] for e in group["entries"]), 2) == group["rent"]
    assert round(sum(e["paid"] for e in group["entries"]), 2) == group["paid"]
    assert round(sum(e["due"] for e in group["entries"]), 2) == group["due"]

    # Entries carry their own payments so a trip shows how it was settled.
    paid_entry = next(e for e in group["entries"] if e["kind"] == "rent" and e["paid"] > 0)
    assert paid_entry["payments"], "settled trip should list its payment"
    assert paid_entry["due"] == round(paid_entry["rent"] - paid_entry["paid"] - paid_entry["waived"], 2)

    # Period totals are the sum of the group totals.
    assert payload["totals"]["rent"] == 460.0 * 3
    assert payload["totals"]["paid"] == 140.0 + 0.0
    assert payload["totals"]["due"] == payload["totals"]["rent"] - payload["totals"]["paid"] - payload["totals"]["waived"]


def test_summary_agrees_with_the_driver_ledger(app):
    """The screen must never claim a different payable than the ledger."""
    from app.services.financial_ledgers import build_delivery_person_financial_ledger
    from models import DeliveryPerson

    created = seed(app)
    pay(app, person_id=created["people"][0], amount=100.0, allocation_id=created["allocations"][0])
    pay(app, person_id=created["people"][1], amount=0.0, waive=25.0, allocation_id=created["allocations"][4], day="2026-10-05")

    payload = group_payload(app)
    with app.app_context():
        for person_id in created["people"]:
            person = DeliveryPerson.query.get(person_id)
            ledger = build_delivery_person_financial_ledger(person)
            group = group_by_id(payload, person_id)
            assert round(group["due"], 2) == round(ledger["closing_balance"], 2), person.name


# --------------------------------------------------------------------------- #
# legacy rows and non-double-counting
# --------------------------------------------------------------------------- #
def test_legacy_rent_rows_are_counted_once(app):
    created = seed(app, drivers=("ALI",), trips=1)

    from models import DeliveryRent, DeliveryPerson, DirectSale, SaleDeliveryPerson, db
    with app.app_context():
        person = DeliveryPerson.query.first()
        # A legacy row for a sale that already has an allocation: ignore it.
        sale_with_alloc = db.session.get(DirectSale, created["sales"][0])
        db.session.add(DeliveryRent(
            sale_id=sale_with_alloc.id, delivery_person_name=person.name,
            bill_no="BILL-00", amount=999.0, date_posted=datetime(2026, 10, 5, 10, 0),
        ))
        # A legacy row with no allocation at all: it must still show.
        legacy_sale = DirectSale(
            client_name="OLD CLIENT", client_code="CL-OLD", category="Credit Customer",
            amount=500.0, date_posted=datetime(2026, 10, 30, 9, 0),
            manual_bill_no="OLD-1", is_void=False,
        )
        db.session.add(legacy_sale)
        db.session.flush()
        db.session.add(DeliveryRent(
            sale_id=legacy_sale.id, delivery_person_name=person.name,
            bill_no="OLD-1", amount=80.0, date_posted=datetime(2026, 10, 30, 9, 0),
        ))
        db.session.commit()

    payload = group_payload(app)
    group = group_by_id(payload, created["people"][0])
    assert group["rent"] == 100.0 + 80.0
    assert group["entry_count"] == 2
    assert any(e["kind"] == "legacy_rent" for e in group["entries"])


def test_void_sales_are_excluded(app):
    created = seed(app, drivers=("ALI",), trips=2)
    from models import DirectSale, db
    with app.app_context():
        sale = db.session.get(DirectSale, created["sales"][0])
        sale.is_void = True
        db.session.commit()

    payload = group_payload(app)
    assert payload["totals"]["rent"] == 110.0  # only the second trip remains


# --------------------------------------------------------------------------- #
# filters and views
# --------------------------------------------------------------------------- #
def test_date_and_driver_filters(app):
    created = seed(app)

    payload = group_payload(app, date_from="2026-10-06", date_to="2026-10-06")
    assert payload["totals"]["entries"] == 3           # one trip per driver that day
    assert payload["totals"]["rent"] == 330.0         # 3 x 110

    payload = group_payload(app, driver="BILAL")
    assert len(payload["groups"]) == 1
    assert payload["groups"][0]["name"] == "BILAL"


def test_search_matches_bill_and_keeps_the_group_total(app):
    created = seed(app)
    payload = group_payload(app, q="BILL-12")
    assert len(payload["groups"]) == 1
    group = payload["groups"][0]
    assert group["delivery_person_id"] == created["people"][1]
    assert len(group["entries"]) == 1
    assert group["entries"][0]["bill_ref"].endswith("BILL-12")
    # Narrowed detail must not rewrite the debt shown on the header.
    assert group["rent"] == 460.0


def test_per_day_view_groups_by_date(app):
    created = seed(app)
    payload = group_payload(app, group_by="day")
    assert payload["group_by"] == "day"
    assert len(payload["groups"]) == 4          # four trip days
    assert payload["totals"]["entries"] == 12
    for group in payload["groups"]:
        assert group["kind"] == "day"
        assert group["entry_count"] == 3        # one trip per driver
        assert {e["person_name"] for e in group["entries"]} == {"ALI", "BILAL", "KAMRAN"}


def test_sort_by_due_puts_the_biggest_debt_first(app):
    created = seed(app)
    pay(app, person_id=created["people"][0], amount=460.0, allocation_id=None)  # settles ALI oldest-first
    payload = group_payload(app)
    assert payload["groups"][-1]["delivery_person_id"] == created["people"][0]
    assert payload["groups"][-1]["due"] == 0.0
    assert payload["groups"][-1]["status"] == "settled"


# --------------------------------------------------------------------------- #
# HTTP: page, expand endpoint, payments
# --------------------------------------------------------------------------- #
def test_page_renders_summary_rows_without_detail_when_idle(app, client):
    created = seed(app)
    login(client)
    response = client.get("/delivery_rents")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert "Delivery Person Rent" in body
    assert 'class="rent-group-row"' in body
    assert body.count('class="rent-group-row"') == 3
    for key in ("ALI", "BILAL", "KAMRAN"):
        assert key in body
    # Detail is rendered inline for a small period and sits hidden until the
    # arrow is used.
    assert 'id="rentDetail_1"' in body
    assert 'data-loaded="1"' in body
    assert "BILL-00" in body


def test_expand_endpoint_returns_the_same_detail(app, client):
    created = seed(app)
    login(client)
    person_id = created["people"][0]

    response = client.get(f"/delivery_rents/group/person:{person_id}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["group"]["delivery_person_id"] == person_id
    assert data["group"]["rent"] == 460.0
    assert data["group"]["due"] == 460.0
    assert "BILL-00" in data["html"]
    assert "rent-entry-row" in data["html"]
    # Four trips -> four detail rows.
    assert data["html"].count("rent-entry-row") == 4


def test_expand_endpoint_404s_for_an_unknown_group(app, client):
    seed(app)
    login(client)
    assert client.get("/delivery_rents/group/person:999999").status_code == 404


def test_pay_a_delivery_person_from_the_summary_row(app, client):
    created = seed(app)
    login(client)
    person_id = created["people"][0]
    account_id = created["account"]

    response = client.post(
        f"/delivery_rents/pay_driver/{person_id}",
        data={
            "paid_amount": "200",
            "waive_off_amount": "0",
            "method": "Cash",
            "payment_account_id": str(account_id),
            "date": "2026-10-20",
            "note": "paid from summary row",
            "idempotency_key": "summary-pay-1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Payment recorded for ALI" in body or "already recorded" in body

    payload = group_payload(app)
    group = group_by_id(payload, person_id)
    assert group["paid"] == 200.0
    assert group["due"] == 260.0
    # It was spread over the oldest trips first, so those rows show it.
    settled = [e for e in group["entries"] if e["paid"] > 0]
    assert settled
    assert round(sum(e["paid"] for e in settled), 2) == 200.0


def test_pay_one_trip_from_inside_the_expanded_detail(app, client):
    created = seed(app)
    login(client)
    allocation_id = created["allocations"][0]

    response = client.post(
        f"/delivery_rents/pay/{allocation_id}",
        data={
            "paid_amount": "100",
            "waive_off_amount": "0",
            "method": "Cash",
            "payment_account_id": str(created["account"]),
            "date": "2026-10-20",
            "idempotency_key": "trip-pay-1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    payload = group_payload(app)
    entry = next(
        e for e in group_by_id(payload, created["people"][0])["entries"]
        if e["id"] == allocation_id
    )
    assert entry["paid"] == 100.0
    assert entry["due"] == 0.0


def test_delete_a_trip_from_the_expanded_detail(app, client):
    created = seed(app)
    login(client)
    allocation_id = created["allocations"][0]
    response = client.post(f"/delivery_rents/void/{allocation_id}", follow_redirects=True)
    assert response.status_code == 200

    payload = group_payload(app)
    group = group_by_id(payload, created["people"][0])
    assert group["entry_count"] == 3
    assert group["rent"] == 360.0


def test_detail_is_lazy_loaded_for_a_busy_period(app, client):
    """A quarter with hundreds of trips must not render every row up front."""
    created = seed(app, drivers=("ALI", "BILAL", "KAMRAN", "DAWOOD", "EHSAN"),
                   trips=10)
    # 50 trips: force the lazy path by lowering the inline limit for this app.
    app.config["DELIVERY_RENT_INLINE_DETAIL_LIMIT"] = 10
    login(client)
    body = client.get("/delivery_rents").get_data(as_text=True)
    assert body.count('class="rent-group-row"') == 5
    assert 'data-loaded="0"' in body        # detail arrives on expand
    assert "BILL-00" not in body

    expanded = client.get(f"/delivery_rents/group/person:{created['people'][0]}")
    assert expanded.status_code == 200
    assert "BILL-00" in expanded.get_json()["html"]


def test_page_respects_the_view_permission(app, client, app_factory):
    seed(app)
    from models import User, db
    with app.app_context():
        user = User(
            username="norents", role="user", status="active",
            can_view_delivery_rent=False, can_manage_sales=False,
            password_hash="x",
        )
        db.session.add(user)
        db.session.commit()

    # An unauthorised POST/logout-free check: the route gate itself.
    login(client)
    # Admin can see it; a standard user without the permission cannot.
    assert client.get("/delivery_rents").status_code == 200
    with app.app_context():
        from app.services.constants import ENDPOINT_PERMISSION_MAP
        assert ENDPOINT_PERMISSION_MAP["delivery_rent_group"] == "can_view_delivery_rent"
        assert ENDPOINT_PERMISSION_MAP["pay_delivery_person_rent"] == "can_manage_sales"


def test_posts_return_to_the_filtered_page_and_never_to_the_json_view(app, client):
    """A delete/pay made from an expanded row must come back to the screen."""
    created = seed(app)
    login(client)
    allocation_id = created["allocations"][0]
    view = "/delivery_rents?group_by=person&sort=due&driver=ALI"

    response = client.post(
        f"/delivery_rents/void/{allocation_id}",
        data={"next": view},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["Location"].endswith(view)

    # The detail fragment itself points back at the page, not the JSON route.
    data = client.get(f"/delivery_rents/group/person:{created['people'][0]}?sort=due").get_json()
    assert 'name="next" value="/delivery_rents?sort=due"' in data["html"]

    # A redirect target from another site is ignored, never followed.
    response = client.post(
        f"/delivery_rents/void/{created['allocations'][1]}",
        data={"next": "https://evil.example/steal"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "evil.example" not in response.headers["Location"]
