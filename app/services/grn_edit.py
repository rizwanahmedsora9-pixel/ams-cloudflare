"""GRN editing that goes through — including lots that were already sold.

Owner rule (see ``EDIT_POLICY.md``): a save is refused only when the data would
be wrong, never because of a date, a permission or a lot that has already been
sold.  Before this module the GRN edit route refused

* **every** item quantity/rate change, add and removal once any part of the lot
  had been consumed by a cash/credit sale (``_grn_has_locked_lots``), and
* **every** landed-cost change (freight, loading, a corrected supplier rate)
  once delivered stock existed (``grn_has_consumed_quantity``).

In a working shop almost every GRN has sold stock, so the pencil looked broken
while the Client Ledger edited its payments/bookings/sales freely.

Two guarantees replace those blocks:

1. Lines are updated **in place**, so a lot keeps its ``GRNItem.id`` and the
   sale allocations that consumed it (``GRNAllocation.grn_item_id``) still
   point at the same lot.  The old code deleted and re-inserted every line,
   which silently orphaned the FIFO cost of each sale that had used it.
2. Sales that already consumed a lot are **re-costed** to the corrected landed
   cost (``GRNAllocation.cost_rate`` and ``DirectSaleItem.cost_rate_at_sale``),
   so stock value and the frozen COGS of those sales still agree afterwards
   instead of disagreeing — which is exactly why the change used to be refused.

Only what cannot be true is still refused:

* a lot cannot be shrunk below the quantity already sold from it,
* a sold lot cannot be removed,
* a delivered line cannot be renamed to another material,
* a GRN expense that Accounts has already paid cannot be lowered below the
  paid amount (handled in ``grn_costing.sync_charges_from_form``).

Every refusal names the material, the quantity already sold and the way
forward, and nothing is saved.
"""

from __future__ import annotations

import logging

from models import db
from app.services.grn_costing import lot_cost_rate

log = logging.getLogger(__name__)

# Quantity tolerance: float arithmetic on kilos/bags must not refuse a save
# because 4.0 is stored as 3.999999999.
EPS = 1e-6


def _num(raw) -> float:
    """Parse a form number, tolerating '', None and '1,500'."""
    text = str(raw if raw is not None else '').replace(',', '').strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def consumed_qty_by_item(grn) -> dict[int, float]:
    """Quantity already sold/issued from each of this GRN's lots.

    Uses the same FIFO replay that drives Profit & Loss and the GRN indicator,
    so it covers posted sale allocations *and* legacy booking/dispatch
    consumption.  A projection failure is reported, never fatal: the caller
    then simply cannot prove a lot is sold and behaves as before.
    """
    if grn is None or not getattr(grn, 'id', None):
        return {}
    try:
        from app.services.grn_consumption import build_grn_consumption

        view = build_grn_consumption(grn_ids=[int(grn.id)])
    except Exception:  # pragma: no cover - projection must never break an edit
        log.exception('GRN consumption projection failed for GRN %s', getattr(grn, 'id', None))
        return {}
    out: dict[int, float] = {}
    for key, row in (view.get('items') or {}).items():
        try:
            out[int(key)] = float((row or {}).get('consumed_qty') or 0.0)
        except (TypeError, ValueError):
            continue
    return out


def _stock_entry_rows(grn):
    """The stock-ledger rows this GRN created (type ``IN``).

    Matching on ``auto_bill_no`` alone is not enough: a GRN without an auto
    number (imported/legacy data) used to compile to ``auto_bill_no IS NULL``
    and deleted *every* unnumbered IN entry in the database.  Fall back to the
    supplier + material names of this GRN instead.
    """
    from models import Entry

    query = Entry.query.filter(Entry.type == 'IN')
    auto = (getattr(grn, 'auto_bill_no', None) or '').strip()
    if auto:
        return query.filter(Entry.auto_bill_no == auto).all()
    names = [i.mat_name for i in (grn.items or []) if getattr(i, 'mat_name', None)]
    if not names:
        return []
    return query.filter(
        Entry.auto_bill_no.is_(None),
        Entry.client == grn.supplier,
        Entry.material.in_(names),
    ).all()


def sync_items_from_form(grn, form, *, actor=None) -> dict:
    """Apply the wizard's item rows to *grn* **in place**.

    Returns ``{'updated', 'added', 'removed', 'skipped'}`` where ``skipped``
    lists submitted lines that were not saved because their quantity was zero
    or negative (the previous behaviour, kept so the operator is told).

    Raises ``ValueError`` with a user-facing message only when the requested
    numbers cannot be true; the caller rolls back and shows it.
    """
    from models import Entry, GRNItem, Material
    from app.services.lookups import get_service_by_input, is_service_name

    mat_names = form.getlist('mat_name[]')
    qtys = form.getlist('qty[]')
    prices = form.getlist('price[]')
    raw_ids = form.getlist('grn_item_id[]')

    stored = [
        i for i in (grn.items or [])
        if getattr(i, 'id', None) is not None and not bool(getattr(i, 'is_void', False))
    ]
    stored_by_id = {int(i.id): i for i in stored}
    consumed = consumed_qty_by_item(grn)
    # Resolve the existing stock-ledger rows BEFORE the lines are mutated: a
    # legacy GRN without an auto bill number is matched by material name, and
    # after a rename those rows would no longer be found (leaving duplicates).
    existing_entries = _stock_entry_rows(grn)

    submitted: dict[int, tuple[str, float, float]] = {}
    additions: list[tuple[str, float, float]] = []
    skipped: list[str] = []

    row_count = max(len(mat_names), len(qtys), len(prices), len(raw_ids))
    for idx in range(row_count):
        name = ((mat_names[idx] if idx < len(mat_names) else '') or '').strip()
        if not name:
            continue
        qty = _num(qtys[idx] if idx < len(qtys) else '')
        price = _num(prices[idx] if idx < len(prices) else '')
        raw_id = str(raw_ids[idx] if idx < len(raw_ids) else '').strip()

        if is_service_name(name) or get_service_by_input(name):
            raise ValueError(f'"{name}" is a service/charge and cannot be received on a GRN.')
        known_row = raw_id.isdigit() and int(raw_id) in stored_by_id
        if qty <= 0:
            # Zero/negative received quantity never creates a stock movement.
            # On a stored row this is a removal (validated below); on a freshly
            # typed row it is simply not saved, and the operator is told.
            if not known_row:
                skipped.append(f"{name} (qty={qtys[idx] if idx < len(qtys) else 0})")
            continue
        if known_row:
            submitted[int(raw_id)] = (name, qty, price)
        else:
            additions.append((name, qty, price))

    # ---- Only impossible data is refused ---------------------------------
    for item in stored:
        sold = float(consumed.get(int(item.id), 0.0) or 0.0)
        if sold <= EPS:
            continue
        if int(item.id) not in submitted:
            raise ValueError(
                f"'{item.mat_name}' cannot be removed: {sold:,.2f} has already been sold "
                "from this lot. Reverse those sales first, or keep the line. Nothing was saved."
            )
        new_name, new_qty, _new_price = submitted[int(item.id)]
        if (new_name or '').strip().lower() != (item.mat_name or '').strip().lower():
            raise ValueError(
                f"'{item.mat_name}' has already been delivered ({sold:,.2f} sold), so the "
                "material on this line cannot be changed. Keep the line and add the correct "
                "material as a new line. Nothing was saved."
            )
        if new_qty < sold - EPS:
            raise ValueError(
                f"'{item.mat_name}' cannot be reduced to {new_qty:,.2f}: {sold:,.2f} has "
                f"already been sold from this lot. Enter {sold:,.2f} or more, or reverse "
                "those sales first. Nothing was saved."
            )

    def _material(name):
        clean = (name or '').strip()
        if not clean:
            return None
        return Material.query.filter_by(name=clean).first()

    # ---- Stock counter: old lines out, final lines back in ---------------
    for item in stored:
        mat = _material(item.mat_name)
        if mat is not None:
            mat.total = float(mat.total or 0) - float(item.qty or 0)

    updated = 0
    for item in stored:
        row = submitted.get(int(item.id))
        if row is None:
            continue
        name, qty, price = row
        item.mat_name = name
        item.qty = qty
        item.price_at_time = price
        item.is_void = False
        updated += 1

    removed = 0
    for item in list(stored):
        if int(item.id) in submitted:
            continue
        try:
            grn.items.remove(item)
        except ValueError:
            pass
        db.session.delete(item)
        removed += 1

    new_items = []
    for name, qty, price in additions:
        item = GRNItem(grn_id=grn.id, mat_name=name, qty=qty, price_at_time=price)
        db.session.add(item)
        try:
            grn.items.append(item)
        except Exception:  # pragma: no cover - relationship already holds it
            pass
        new_items.append(item)

    final_items = [i for i in stored if int(i.id) in submitted] + new_items
    for item in final_items:
        mat = _material(item.mat_name)
        if mat is not None:
            mat.total = float(mat.total or 0) + float(item.qty or 0)

    # ---- Stock-ledger rows: one IN entry per received line ---------------
    db.session.flush()
    for entry in existing_entries:
        db.session.delete(entry)
    db.session.flush()

    stamp = getattr(grn, 'date_posted', None)
    if stamp is None:
        from models.helpers import pk_now

        stamp = pk_now()
    for item in final_items:
        db.session.add(Entry(
            date=stamp.strftime('%Y-%m-%d'),
            time=stamp.strftime('%H:%M:%S'),
            type='IN',
            material=item.mat_name,
            client=grn.supplier,
            qty=item.qty,
            bill_no=grn.manual_bill_no or '',
            auto_bill_no=grn.auto_bill_no,
            created_by=actor or getattr(grn, 'created_by', None),
            note=grn.note,
        ))
    db.session.flush()

    # ``is_locked`` drives the GRN screens: refresh it from the real
    # allocations instead of leaving the flag behind on a rebuilt line.
    try:
        from app.services.sales_core import _refresh_grn_item_locks

        _refresh_grn_item_locks([i.id for i in final_items if i.id])
    except Exception:  # pragma: no cover - a flag must never fail the save
        log.exception('GRN lock refresh failed for GRN %s', getattr(grn, 'id', None))

    return {'updated': updated, 'added': len(new_items), 'removed': removed, 'skipped': skipped}


def recost_consuming_sales(grn) -> dict:
    """Re-price the sales that already consumed this GRN's lots.

    Called after the landed costs are recomputed.  ``GRNAllocation.cost_rate``
    is the frozen FIFO cost of one sold line and ``DirectSaleItem
    .cost_rate_at_sale`` the line-level average; both are rewritten so the
    corrected GRN cost and the Profit & Loss of those sales agree.  Every
    allocation of an affected sale line is re-averaged, not just this GRN's,
    because a line can be split across several lots.

    Returns ``{'allocations', 'sale_items', 'sales'}`` counts for the flash.
    """
    from models import DirectSale, DirectSaleItem, GRNAllocation

    result = {'allocations': 0, 'sale_items': 0, 'sales': 0}
    items = [
        i for i in (grn.items or [])
        if getattr(i, 'id', None) is not None and not bool(getattr(i, 'is_void', False))
    ]
    item_ids = [int(i.id) for i in items]
    if not item_ids:
        return result

    allocations = (
        GRNAllocation.query
        .join(DirectSale, DirectSale.id == GRNAllocation.sale_id)
        .filter(
            GRNAllocation.grn_item_id.in_(item_ids),
            GRNAllocation.is_void == False,  # noqa: E712
            DirectSale.is_void == False,  # noqa: E712
        )
        .all()
    )
    if not allocations:
        return result

    by_item = {int(i.id): i for i in items}
    sale_item_ids: set[int] = set()
    for alloc in allocations:
        lot = by_item.get(int(alloc.grn_item_id))
        rate = float(lot_cost_rate(lot) or 0.0) if lot is not None else float(alloc.cost_rate or 0.0)
        if abs(float(alloc.cost_rate or 0.0) - rate) > 1e-9:
            alloc.cost_rate = rate
            result['allocations'] += 1
        if getattr(alloc, 'sale_item_id', None):
            sale_item_ids.add(int(alloc.sale_item_id))

    sale_ids: set[int] = set()
    for sale_item_id in sale_item_ids:
        sale_item = db.session.get(DirectSaleItem, sale_item_id)
        if sale_item is None:
            continue
        rows = [a for a in (sale_item.grn_allocations or []) if not bool(getattr(a, 'is_void', False))]
        qty = sum(float(a.qty or 0) for a in rows)
        if qty <= EPS:
            continue
        cost = sum(float(a.qty or 0) * float(a.cost_rate or 0) for a in rows)
        sale_item.cost_rate_at_sale = cost / qty
        result['sale_items'] += 1
        if getattr(sale_item, 'sale_id', None):
            sale_ids.add(int(sale_item.sale_id))

    result['sales'] = len(sale_ids)
    if result['sale_items']:
        log.info(
            'GRN_RECOST grn=%s allocations=%d sale_items=%d sales=%d',
            getattr(grn, 'id', None), result['allocations'], result['sale_items'], result['sales'],
        )
    return result


__all__ = ['consumed_qty_by_item', 'sync_items_from_form', 'recost_consuming_sales', 'EPS']
