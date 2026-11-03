"""Delivery-rent grouping — one payable row per delivery person.

The Delivery Rent screen used to render a flat list: one table row per
``SaleDeliveryPerson`` allocation.  That is fine for two or three drivers, but
ten drivers doing ten trips a day produce a hundred rows and nobody can see who
is owed what without adding them up by hand.

This module answers the accounting question directly — *per driver: how much was
earned, how much has been paid, how much is still owed* — and keeps every rent
allocation underneath it as the expandable detail.

The numbers are built from the same sources the driver ledger uses, so the two
views can never disagree:

``SaleDeliveryPerson.rent_amount``                 driver earned this (debit)
``DeliveryPersonPayment.amount_paid``              money actually paid (credit)
``DeliveryPersonPayment.waive_off_amount``         written-off amount (credit)

Legacy ``DeliveryRent`` rows (written before allocations existed, or imported
from the old system) are still historical data.  They are included only when the
same sale has no live allocation, exactly like
``financial_ledgers._delivery_person_rows``, so a sale is never counted twice.

Everything is computed in ``Decimal`` and rounded once to paisa, so a group's
totals are the sum of its entries to the last cent.  ``build_delivery_rent_groups``
is a pure read: it never mutates a row.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import url_for
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from models import (
    DeliveryPerson,
    DeliveryPersonPayment,
    DeliveryRent,
    DirectSale,
    SaleDeliveryPerson,
    db,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
# One paisa: an entry is settled when it owes less than a hundredth of a unit.
EPS = CENT

# A day group can never contain more entries than allocations exist, but a
# person group in a long period can.  These caps keep one JSON response (and one
# page of DOM) bounded; the ledger link stays available for the full story.
MAX_GROUPS = 400
MAX_ENTRIES_PER_GROUP = 1500


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _money(value) -> Decimal:
    """Coerce a legacy float/string/None to an exact two-decimal Decimal."""
    if value is None or value == "":
        return ZERO
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return ZERO


def _num(value) -> float:
    """Render an exact Decimal as a float rounded once to paisa."""
    return float(_money(value))


def _norm(value) -> str:
    """Case/whitespace-insensitive name key — matches the ledger's own rule."""
    return " ".join(str(value or "").strip().casefold().split())


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_day(value) -> str:
    """Normalise a ``YYYY-MM-DD`` query argument; ignore anything else."""
    day = _as_date(value)
    return day.isoformat() if day else ""


def _bill_ref(sale, sale_id=None) -> str:
    """The bill reference exactly as the ledgers show it."""
    if sale is not None:
        for value in (sale.manual_bill_no, sale.auto_bill_no):
            if (value or "").strip():
                return value.strip()
        invoice = getattr(sale, "invoice", None)
        if invoice is not None and (invoice.invoice_no or "").strip():
            return invoice.invoice_no.strip()
        return f"DS-{sale.id}"
    return f"DS-{sale_id}" if sale_id else ""


def _display_date(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value or "").strip()
    return raw[:10]


def _endpoint_url(endpoint: str, **values) -> str:
    """Build a URL without letting a missing endpoint break a whole page."""
    try:
        return url_for(endpoint, **values)
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# row builders
# --------------------------------------------------------------------------- #
def _payment_payload(payment) -> dict:
    return {
        "kind": "payment",
        "id": payment.id,
        "date": _display_date(payment.date_posted),
        "date_display": _display_date(payment.date_posted),
        "amount_paid": _num(_money(payment.amount_paid)),
        "waive_off_amount": _num(_money(payment.waive_off_amount)),
        "method": (payment.method or "").strip(),
        "reference": (payment.reference or "").strip(),
        "note": (payment.note or "").strip(),
        "account_name": (getattr(payment.payment_account, "name", "") or "").strip(),
        "unallocated": payment.allocation_id is None,
        "edit_url": _endpoint_url("edit_delivery_person_payment", id=payment.id),
        "void_url": _endpoint_url("void_delivery_person_payment", id=payment.id),
        "search": " ".join(part for part in (
            _display_date(payment.date_posted),
            (payment.reference or "").strip(),
            (payment.note or "").strip(),
            (payment.method or "").strip(),
            (getattr(payment.payment_account, "name", "") or "").strip(),
        ) if part).casefold(),
    }


def _entry_payload(
    *, entry_key, kind, row_id, when, person_id, person_name, bill_ref, client_name,
    bags, rent, paid, waived, due, note="", sale_id=None, payments=None,
    sale_label="", extra_search="",
):
    return {
        "key": entry_key,
        "kind": kind,
        "id": row_id,
        "date": _display_date(when),
        "date_display": _display_date(when),
        "delivery_person_id": person_id,
        "person_name": person_name,
        "bill_ref": bill_ref or "",
        "sale_label": sale_label or bill_ref or "",
        "client_name": client_name or "",
        "bags": float(bags or 0),
        "rent": _num(rent),
        "paid": _num(paid),
        "waived": _num(waived),
        "due": _num(due),
        "note": note or "",
        "sale_id": sale_id,
        "sale_url": _endpoint_url("direct_sales_page") if sale_id else "",
        "payments": payments or [],
        "search": " ".join(part for part in (
            _display_date(when), bill_ref, client_name, person_name, note, extra_search,
        ) if part).casefold(),
    }


def _blank_group(key, *, kind, person_id, name, phone="", is_active=True,
                 opening=None, opening_date=None):
    return {
        "key": key,
        "kind": kind,
        "delivery_person_id": person_id,
        "name": name or "Unnamed driver",
        "phone": phone or "",
        "is_active": bool(is_active),
        "opening": None if opening is None else _num(opening),
        "opening_date": _display_date(opening_date) if opening else "",
        "entries": [],
        "payments": [],
        "rent": ZERO,
        "paid": ZERO,
        "waived": ZERO,
        "due": ZERO,
        "entry_count": 0,
        "payment_count": 0,
        "last_date": "",
        "ledger_url": _endpoint_url("delivery_person_ledger", id=person_id) if person_id else "",
        "search": "",
    }


def _recompute(group) -> None:
    """Roll the entry and payment lists up into the group's totals.

    ``_extra_paid`` / ``_extra_waived`` hold settlements that belong to this
    driver but not to any rent row inside the current date window (for example
    a payment posted today against last week's trip).  They reduce the payable
    but are not added to the window's rent total.
    """
    rent = paid = waived = ZERO
    last = ""
    oldest_open = ""
    for entry in group["entries"]:
        rent += _money(entry["rent"])
        paid += _money(entry["paid"])
        waived += _money(entry["waived"])
        if entry["date"] and entry["date"] > last:
            last = entry["date"]
        if _money(entry["due"]) > ZERO and entry["date"]:
            if not oldest_open or entry["date"] < oldest_open:
                oldest_open = entry["date"]
    # Payments that belong to this driver but to no rent row in range still
    # reduce what is owed, so they must be in the totals.
    for payment in group["payments"]:
        paid += _money(payment["amount_paid"])
        waived += _money(payment["waive_off_amount"])
    paid += group.get("_extra_paid") or ZERO
    waived += group.get("_extra_waived") or ZERO
    group["rent"] = _num(rent)
    group["paid"] = _num(paid)
    group["waived"] = _num(waived)
    group["due"] = _num(max(ZERO, rent - paid - waived))
    group["entry_count"] = len(group["entries"])
    group["payment_count"] = len(group["payments"]) + sum(
        len(entry["payments"]) for entry in group["entries"]
    )
    group["last_date"] = last
    group["oldest_open"] = oldest_open or last
    group["search"] = " ".join(part for part in (
        group["name"], group["phone"], group["last_date"],
    ) if part).casefold()


# --------------------------------------------------------------------------- #
# queries
# --------------------------------------------------------------------------- #
def _allocation_rows(*, date_from=None, date_to=None, driver=None):
    """Live rent allocations (one per driver per trip) inside the filters."""
    entry_date = func.coalesce(SaleDeliveryPerson.created_at, DirectSale.date_posted)
    query = (
        SaleDeliveryPerson.query.options(
            selectinload(SaleDeliveryPerson.sale).selectinload(DirectSale.invoice),
            selectinload(SaleDeliveryPerson.delivery_person),
        )
        .join(DirectSale, SaleDeliveryPerson.sale_id == DirectSale.id)
        .filter(
            SaleDeliveryPerson.is_void == False,  # noqa: E712
            DirectSale.is_void == False,  # noqa: E712
        )
    )
    if date_from:
        query = query.filter(func.date(entry_date) >= date_from)
    if date_to:
        query = query.filter(func.date(entry_date) <= date_to)
    if driver:
        query = query.join(
            DeliveryPerson, SaleDeliveryPerson.delivery_person_id == DeliveryPerson.id
        ).filter(func.lower(func.trim(DeliveryPerson.name)) == driver.lower())
    return query.order_by(entry_date.asc(), SaleDeliveryPerson.id.asc()).all()


def _sale_ids_with_allocations():
    """Sales whose driver pay is already represented by an allocation row."""
    rows = db.session.query(SaleDeliveryPerson.sale_id).filter(
        SaleDeliveryPerson.is_void == False  # noqa: E712
    ).distinct().all()
    return {sale_id for (sale_id,) in rows if sale_id is not None}


def _legacy_rows(*, date_from=None, date_to=None, driver=None, skip_sale_ids=()):
    """Old ``DeliveryRent`` rows that no allocation already represents."""
    entry_date = func.coalesce(DeliveryRent.date_posted, DirectSale.date_posted)
    query = (
        DeliveryRent.query
        .outerjoin(DirectSale, DeliveryRent.sale_id == DirectSale.id)
        .filter(
            DeliveryRent.is_void == False,  # noqa: E712
            or_(DeliveryRent.sale_id.is_(None), DirectSale.is_void == False),  # noqa: E712
        )
    )
    if skip_sale_ids:
        query = query.filter(
            or_(DeliveryRent.sale_id.is_(None), DeliveryRent.sale_id.notin_(list(skip_sale_ids)))
        )
    if date_from:
        query = query.filter(func.date(entry_date) >= date_from)
    if date_to:
        query = query.filter(func.date(entry_date) <= date_to)
    if driver:
        query = query.filter(
            func.lower(func.trim(DeliveryRent.delivery_person_name)) == driver.lower()
        )
    return query.order_by(entry_date.asc(), DeliveryRent.id.asc()).all()


def _payment_rows(*, allocation_ids=(), sale_ids=(), person_ids=()):
    """Live payments that could belong to the rows being shown.

    Payments are deliberately *not* date-filtered: a settlement is credited
    against the trip it pays for, so hiding a rent row's payment because the
    cash moved on a different day would show a debt that no longer exists.
    """
    if not allocation_ids and not sale_ids and not person_ids:
        return []
    filters = []
    if allocation_ids:
        filters.append(DeliveryPersonPayment.allocation_id.in_(list(allocation_ids)))
    if sale_ids:
        filters.append(
            (DeliveryPersonPayment.allocation_id.is_(None))
            & (DeliveryPersonPayment.sale_id.in_(list(sale_ids)))
        )
    if person_ids:
        # A payment that points nowhere may still settle this driver's payable.
        filters.append(
            (DeliveryPersonPayment.allocation_id.is_(None))
            & (DeliveryPersonPayment.delivery_person_id.in_(list(person_ids)))
        )
    return (
        DeliveryPersonPayment.query.options(
            selectinload(DeliveryPersonPayment.delivery_person),
            selectinload(DeliveryPersonPayment.payment_account),
        )
        .filter(
            DeliveryPersonPayment.is_void == False,  # noqa: E712
            or_(*filters),
        )
        .order_by(DeliveryPersonPayment.date_posted.asc(), DeliveryPersonPayment.id.asc())
        .all()
    )


# --------------------------------------------------------------------------- #
# public builder
# --------------------------------------------------------------------------- #
def build_delivery_rent_groups(
    *,
    date_from="",
    date_to="",
    driver="",
    q="",
    include_payments=True,
    include_legacy=True,
    sort="due",
    group_by="person",
):
    """Return drivers with their rent/paid/remaining totals and detail rows.

    ``group_by`` is ``'person'`` (the default: one row per delivery person) or
    ``'day'`` (one row per posting date, with the driver on each detail line —
    the compact "how did today go" view).

    ``include_payments=False`` keeps the totals but drops the per-payment
    detail, which is what the per-day view needs.

    The return value is JSON-safe apart from ``_dt`` helpers; the page route and
    the JSON endpoint share it so both always render the same numbers.
    """
    date_from = _parse_day(date_from)
    date_to = _parse_day(date_to)
    driver = (driver or "").strip()
    needle = (q or "").strip().casefold()
    group_by = "day" if str(group_by or "").strip().lower() == "day" else "person"
    sort_key = (sort or "due").strip().lower()

    groups: dict[str, dict] = {}
    day_groups: dict[str, dict] = {}

    # Driver metadata for every live person, so inactive drivers still show the
    # right name/phone/ledger link on historical rows.
    people = {
        person.id: person for person in DeliveryPerson.query.all()
    }
    people_by_name = {_norm(person.name): person for person in people.values()}

    allocations = _allocation_rows(date_from=date_from, date_to=date_to, driver=driver)
    skip_sale_ids = _sale_ids_with_allocations() if include_legacy else set()
    legacy = (
        _legacy_rows(
            date_from=date_from, date_to=date_to, driver=driver,
            skip_sale_ids=skip_sale_ids,
        )
        if include_legacy else []
    )

    # -- rent rows ---------------------------------------------------------- #
    # ``(kind, id) -> entry`` so a payment can find the one row it settles.
    by_key: dict[tuple, dict] = {}

    def _add_entry(entry, person, name, when):
        if group_by == "day":
            day = _display_date(when) or "unknown"
            group = day_groups.get(day)
            if group is None:
                group = day_groups[day] = _blank_group(
                    f"day:{day}", kind="day", person_id=None, name=day
                )
            group["entries"].append(entry)
            return
        person_id = getattr(person, "id", None)
        gkey = f"person:{person_id}" if person_id else f"legacy:{_norm(name)}"
        group = groups.get(gkey)
        if group is None:
            group = groups[gkey] = _blank_group(
                gkey,
                kind="person" if person_id else "legacy",
                person_id=person_id,
                name=name,
                phone=(getattr(person, "phone", "") or ""),
                is_active=getattr(person, "is_active", True) is not False,
                opening=getattr(person, "opening_balance", None),
                opening_date=getattr(person, "opening_balance_date", None),
            )
        group["entries"].append(entry)

    for alloc in allocations:
        person = alloc.delivery_person
        name = (getattr(person, "name", "") or "").strip() or "Unnamed driver"
        when = alloc.created_at or getattr(alloc.sale, "date_posted", None)
        rent = _money(alloc.rent_amount)
        bill_ref = _bill_ref(alloc.sale, alloc.sale_id)
        entry = _entry_payload(
            entry_key=f"alloc-{alloc.id}",
            kind="rent",
            row_id=alloc.id,
            when=when,
            person_id=alloc.delivery_person_id,
            person_name=name,
            bill_ref=bill_ref,
            client_name=(getattr(alloc.sale, "client_name", "") or ""),
            bags=alloc.bags_delivered,
            rent=rent,
            paid=ZERO,
            waived=ZERO,
            due=rent,
            sale_id=alloc.sale_id,
            sale_label=bill_ref,
            extra_search=(getattr(person, "phone", "") or ""),
        )
        entry["_person_key"] = _norm(name)
        entry["_paid"] = ZERO
        entry["_waived"] = ZERO
        by_key[("alloc", alloc.id)] = entry
        _add_entry(entry, person, name, when)

    for rent_row in legacy:
        name = (rent_row.delivery_person_name or "").strip() or "Unnamed driver"
        person = people_by_name.get(_norm(name))
        when = rent_row.date_posted or getattr(rent_row.sale, "date_posted", None)
        amount = _money(rent_row.amount)
        bill_ref = (rent_row.bill_no or "").strip() or _bill_ref(
            getattr(rent_row, "sale", None), rent_row.sale_id
        )
        entry = _entry_payload(
            entry_key=f"legacy-{rent_row.id}",
            kind="legacy_rent",
            row_id=rent_row.id,
            when=when,
            person_id=getattr(person, "id", None),
            person_name=name,
            bill_ref=bill_ref,
            client_name=(getattr(getattr(rent_row, "sale", None), "client_name", "") or ""),
            bags=0,
            rent=amount,
            paid=ZERO,
            waived=ZERO,
            due=amount,
            note=(rent_row.note or ""),
            sale_id=rent_row.sale_id,
            sale_label=bill_ref,
        )
        entry["_person_key"] = _norm(name)
        entry["_paid"] = ZERO
        entry["_waived"] = ZERO
        by_key[("legacy", rent_row.id)] = entry
        _add_entry(entry, person, name, when)

    # -- payments ----------------------------------------------------------- #
    allocation_ids = [key[1] for key in by_key if key[0] == "alloc"]
    sale_ids = {
        entry["sale_id"] for entry in by_key.values() if entry.get("sale_id")
    }
    payments = _payment_rows(
        allocation_ids=allocation_ids,
        sale_ids=sale_ids,
        person_ids=list(people) if groups else (),
    )

    orphan_payments = []
    for payment in payments:
        payload = _payment_payload(payment)
        person_key = _norm(getattr(payment.delivery_person, "name", ""))
        target = None
        if payment.allocation_id is not None:
            target = by_key.get(("alloc", payment.allocation_id))
        if target is None and payment.sale_id is not None:
            # An unallocated settlement against a bill: credit the row it pays
            # for — the legacy rent row first, then the driver's trip on that
            # same sale.
            for kind in ("legacy_rent", "rent"):
                target = next(
                    (
                        entry for entry in by_key.values()
                        if entry["kind"] == kind
                        and entry["sale_id"] == payment.sale_id
                        and entry["_person_key"] == person_key
                    ),
                    None,
                )
                if target is not None:
                    break
        if target is not None:
            if include_payments:
                target["payments"].append(payload)
            target["_paid"] += _money(payload["amount_paid"])
            target["_waived"] += _money(payload["waive_off_amount"])
            continue

        # Nothing in this window to attach it to.  The money still left the
        # business and still reduces the driver's payable, so keep it on the
        # driver's group (driver view) or in a separate list (day view).
        group = groups.get(f"person:{payment.delivery_person_id}")
        if group is not None and group_by == "person":
            if include_payments:
                group["payments"].append(payload)
            group["_extra_paid"] = group.get("_extra_paid", ZERO) + _money(payload["amount_paid"])
            group["_extra_waived"] = group.get("_extra_waived", ZERO) + _money(payload["waive_off_amount"])
        else:
            orphan_payments.append(payload)

    # -- finalise ----------------------------------------------------------- #
    for entry in by_key.values():
        paid = entry.pop("_paid", ZERO)
        waived = entry.pop("_waived", ZERO)
        entry.pop("_person_key", None)
        entry["paid"] = _num(paid)
        entry["waived"] = _num(waived)
        entry["due"] = _num(max(ZERO, _money(entry["rent"]) - paid - waived))

    group_list = list(groups.values()) + list(day_groups.values())
    for group in group_list:
        _recompute(group)
        if group["kind"] == "day":
            group["name"] = group["key"].split(":", 1)[-1]
            group["search"] = group["name"].casefold()
        group["status"] = (
            "settled" if (group["rent"] > 0 or group["entry_count"]) and group["due"] <= 0.0
            else ("inactive" if group["kind"] == "person" and not group["is_active"]
                  else "due")
        )

    if needle:
        filtered = []
        for group in group_list:
            if needle in group["search"]:
                filtered.append(group)
                continue
            matched = [e for e in group["entries"] if needle in e["search"]]
            if matched:
                # The group total keeps its real value; only the detail is
                # narrowed, so a filtered view can never understate a debt.
                group = dict(group)
                group["entries"] = matched
                group["filtered_entries"] = True
                filtered.append(group)
        group_list = filtered

    if sort_key == "name":
        group_list.sort(key=lambda g: (g["name"] or "").casefold())
    elif sort_key == "rent":
        group_list.sort(key=lambda g: (-g["rent"], (g["name"] or "").casefold()))
    elif sort_key == "oldest":
        group_list.sort(key=lambda g: (g["oldest_open"] or "~", (g["name"] or "").casefold()))
    elif sort_key == "paid":
        group_list.sort(key=lambda g: (-g["paid"], (g["name"] or "").casefold()))
    elif group_by == "day":
        group_list.sort(key=lambda g: g["name"], reverse=True)
    else:
        group_list.sort(
            key=lambda g: (-g["due"], -g["rent"], (g["name"] or "").casefold())
        )

    truncated = False
    if len(group_list) > MAX_GROUPS:
        group_list = group_list[:MAX_GROUPS]
        truncated = True
    for group in group_list:
        if len(group["entries"]) > MAX_ENTRIES_PER_GROUP:
            group["entries"] = group["entries"][:MAX_ENTRIES_PER_GROUP]
            group["truncated"] = True
            truncated = True

    totals_rent = totals_paid = totals_waived = ZERO
    total_entries = 0
    for group in group_list:
        totals_rent += _money(group["rent"])
        totals_paid += _money(group["paid"])
        totals_waived += _money(group["waived"])
        total_entries += group["entry_count"]

    orphan_paid = sum((_money(p["amount_paid"]) for p in orphan_payments), ZERO)
    orphan_waived = sum((_money(p["waive_off_amount"]) for p in orphan_payments), ZERO)

    return {
        "group_by": group_by,
        "sort": sort_key,
        "date_from": date_from,
        "date_to": date_to,
        "driver": driver,
        "q": (q or "").strip(),
        "groups": group_list,
        "totals": {
            "rent": _num(totals_rent),
            "paid": _num(totals_paid),
            "waived": _num(totals_waived),
            "due": _num(max(ZERO, totals_rent - totals_paid - totals_waived)),
            "groups": len(group_list),
            "entries": total_entries,
            "payments": sum(g["payment_count"] for g in group_list),
            "orphan_paid": _num(orphan_paid),
            "orphan_waived": _num(orphan_waived),
        },
        "orphan_payments": orphan_payments if include_payments else [],
        "driver_options": sorted(
            {
                (person.name or "").strip()
                for person in people.values()
                if (person.name or "").strip()
            }
        ),
        "truncated": truncated,
    }


__all__ = ["build_delivery_rent_groups"]
