"""GRN Costs — read-only detail of every purchase cost, filtered by kind.

Owner rules this module obeys (see app/services/grn_costing.py for the
authority itself):

* A1 — a GRN never pays.  This report is a *cost* report: it shows what the
  business owes/spent on stock and on the incidental costs of receiving it.
  It never shows a paid/unpaid declaration, because every payment lives in
  Accounts (``Accounts -> Pay GRN Expenses``).
* The supplier material amount is exactly ``sum(qty * rate)``.  Vehicle
  fare, transport, loading, unloading and other charges are listed as their
  own cost kinds.  Each expense's own billing checkbox decides whether it is
  payable through the supplier ledger or to its own recipient.

Every number comes from ``grn_costing.grn_breakdown`` — this module only
groups, filters and totals, so no screen can invent its own version of the
cost of a GRN.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import false, func, or_

from models import GRN
from app.services.grn_costing import grn_breakdown

# ---- filter vocabulary ----------------------------------------------------
STOCK = 'STOCK'
VEHICLE = 'VEHICLE'
LOADING = 'LOADING'
UNLOADING = 'UNLOADING'
OTHER = 'OTHER'
ALL = 'ALL'

COST_KINDS = (ALL, STOCK, VEHICLE, LOADING, UNLOADING, OTHER)

COST_KIND_LABELS = {
    ALL: 'All costs',
    STOCK: 'Stock / material',
    VEHICLE: 'Vehicle fare / transport',
    LOADING: 'Loading',
    UNLOADING: 'Unloading',
    OTHER: 'Other expenses',
}

#: Charge type -> filter kind.  Transportation is a vehicle cost.
KIND_BY_CHARGE_TYPE = {
    'VEHICLE_FARE': VEHICLE,
    'TRANSPORT': VEHICLE,
    'LOADING': LOADING,
    'UNLOADING': UNLOADING,
    'OTHER': OTHER,
}

KIND_ORDER = (STOCK, VEHICLE, LOADING, UNLOADING, OTHER)


def normalize_kind(value) -> str:
    """Map an arbitrary query-string value onto a supported filter kind."""
    text = str(value or '').strip().upper()
    aliases = {
        '': ALL,
        'ALL': ALL,
        'STOCK': STOCK,
        'MATERIAL': STOCK,
        'STOCK_MATERIAL': STOCK,
        'VEHICLE': VEHICLE,
        'VEHICLE_FARE': VEHICLE,
        'TRANSPORT': VEHICLE,
        'TRANSPORTER': VEHICLE,
        'FARE': VEHICLE,
        'LOADING': LOADING,
        'UNLOADING': UNLOADING,
        'OTHER': OTHER,
        'OTHERS': OTHER,
    }
    return aliases.get(text, ALL)


def parse_date(value):
    """Parse a YYYY-MM-DD query value; anything else means "no bound"."""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        return None


def _fmt_money(value) -> str:
    return f'{float(value or 0):,.2f}'


def _fmt_qty(value) -> str:
    number = float(value or 0)
    if number == int(number):
        return f'{int(number):,}'
    return f'{number:,.3f}'.rstrip('0').rstrip('.')


def grn_cost_supplier_options():
    """Supplier names that actually have (non-cancelled) GRNs, for the filter."""
    rows = (
        GRN.query.with_entities(GRN.supplier)
        .filter(
            GRN.is_void == False,  # noqa: E712
            GRN.is_cancelled == False,  # noqa: E712
            GRN.supplier.isnot(None),
        )
        .distinct()
        .all()
    )
    names = {(name or '').strip() for (name,) in rows}
    return sorted(name for name in names if name)


def _grns_in_scope(*, start=None, end=None, supplier=''):
    query = GRN.query.filter(
        GRN.is_void == False,  # noqa: E712
        GRN.is_cancelled == False,  # noqa: E712
    )
    if start is not None:
        query = query.filter(func.date(GRN.date_posted) >= start.isoformat())
    if end is not None:
        query = query.filter(func.date(GRN.date_posted) <= end.isoformat())
    supplier = (supplier or '').strip()
    if supplier:
        supplier_id = int(supplier) if supplier.isdigit() else None
        query = query.filter(or_(
            func.lower(func.trim(GRN.supplier)) == supplier.lower(),
            GRN.supplier_id == supplier_id if supplier_id is not None else false(),
        ))
    return query.order_by(GRN.date_posted.desc(), GRN.id.desc()).all()


def _stock_rows(grn, breakdown):
    """One row per material line: qty x rate is the whole stock cost (A2)."""
    rows = []
    for line in breakdown['per_line']:
        rows.append({
            'grn_id': grn.id,
            'grn_date': grn.date_posted,
            'bill_ref': breakdown['bill_ref'],
            'supplier': breakdown['supplier'],
            'kind': STOCK,
            'kind_label': COST_KIND_LABELS[STOCK],
            'cost_type': 'STOCK',
            'cost_type_label': 'Stock material',
            'detail': line['material'] or 'Material',
            'sub_detail': f"{_fmt_qty(line['qty'])} × {_fmt_money(line['supplier_rate'])}",
            'qty': line['qty'],
            'rate': line['supplier_rate'],
            'recipient': breakdown['supplier'] or '',
            'treatment': 'INVENTORY',
            'treatment_label': 'Stock cost',
            'amount': line['supplier_amount'],
            'line_landed_cost': line['line_landed_cost'],
        })
    if rows:
        return rows
    # A legacy GRN with no live item rows still carries a material figure.
    if breakdown['supplier_material_amount'] > 0:
        rows.append({
            'grn_id': grn.id,
            'grn_date': grn.date_posted,
            'bill_ref': breakdown['bill_ref'],
            'supplier': breakdown['supplier'],
            'kind': STOCK,
            'kind_label': COST_KIND_LABELS[STOCK],
            'cost_type': 'STOCK',
            'cost_type_label': 'Stock material',
            'detail': 'Material (no live lines)',
            'sub_detail': '',
            'qty': 0.0,
            'rate': 0.0,
            'recipient': breakdown['supplier'] or '',
            'treatment': 'INVENTORY',
            'treatment_label': 'Stock cost',
            'amount': breakdown['supplier_material_amount'],
            'line_landed_cost': breakdown['supplier_material_amount'],
        })
    return rows


def _charge_rows(grn, breakdown):
    rows = []
    for charge in breakdown['charges']:
        amount = float(charge.get('amount') or 0)
        if amount <= 0:
            continue
        kind = KIND_BY_CHARGE_TYPE.get((charge.get('charge_type') or '').upper(), OTHER)
        detail = (charge.get('label') or '').strip() or charge.get('charge_label') or 'Charge'
        recipient = (charge.get('recipient_name') or '').strip()
        rows.append({
            'grn_id': grn.id,
            'grn_date': grn.date_posted,
            'bill_ref': breakdown['bill_ref'],
            'supplier': breakdown['supplier'],
            'kind': kind,
            'kind_label': COST_KIND_LABELS[kind],
            'cost_type': (charge.get('charge_type') or 'OTHER').upper(),
            'cost_type_label': charge.get('charge_label') or 'Charge',
            'detail': detail,
            'sub_detail': charge.get('recipient_label') or '',
            'qty': 0.0,
            'rate': 0.0,
            'recipient': recipient or (charge.get('recipient_label') or ''),
            'treatment': (charge.get('cost_treatment') or 'INVENTORY').upper(),
            'treatment_label': ({
                'INVENTORY': 'In material cost',
                'EXPENSE': 'Separate expense',
                'NON_MATERIAL': 'Not material cost',
                'UNTRACKED_LEGACY': 'Legacy (untracked)',
            }.get((charge.get('cost_treatment') or 'INVENTORY').upper(), '')
                + (' · billed to supplier' if charge.get('included_in_supplier_bill') else '')),
            'amount': amount,
            'line_landed_cost': 0.0,
        })
    return rows


def build_grn_costs(*, start=None, end=None, supplier='', kind=ALL):
    """Rows + totals for the GRN Costs tab.

    ``kind`` filters the *detail* table only; the totals strip always shows
    every kind so the operator keeps the full picture while narrowing a list.
    """
    kind = normalize_kind(kind)
    start = parse_date(start) if not hasattr(start, 'isoformat') else start
    end = parse_date(end) if not hasattr(end, 'isoformat') else end
    supplier = (supplier or '').strip()

    grns = _grns_in_scope(start=start, end=end, supplier=supplier)

    totals = {key: 0.0 for key in KIND_ORDER}
    counts = {key: 0 for key in KIND_ORDER}
    all_rows = []
    for grn in grns:
        try:
            breakdown = grn_breakdown(grn)
        except Exception:  # pragma: no cover - defensive, never break the page
            continue
        grn_rows = _stock_rows(grn, breakdown) + _charge_rows(grn, breakdown)
        for row in grn_rows:
            totals[row['kind']] = totals.get(row['kind'], 0.0) + float(row['amount'] or 0)
            counts[row['kind']] = counts.get(row['kind'], 0) + 1
        all_rows.extend(grn_rows)

    rows = [row for row in all_rows if kind == ALL or row['kind'] == kind]

    grand_total = sum(totals.values())
    return {
        'kind': kind,
        'kind_label': COST_KIND_LABELS[kind],
        'start': start,
        'end': end,
        'supplier': supplier,
        'rows': rows,
        'all_row_count': len(all_rows),
        'row_count': len(rows),
        'grn_count': len(grns),
        'totals': totals,
        'counts': counts,
        'grand_total': grand_total,
        'filtered_total': (grand_total if kind == ALL
                           else totals.get(kind, 0.0)),
        'kinds': [
            {'kind': key, 'label': COST_KIND_LABELS[key],
             'total': totals[key], 'count': counts[key]}
            for key in KIND_ORDER
        ],
    }


__all__ = [
    'ALL', 'STOCK', 'VEHICLE', 'LOADING', 'UNLOADING', 'OTHER',
    'COST_KINDS', 'COST_KIND_LABELS', 'KIND_BY_CHARGE_TYPE', 'KIND_ORDER',
    'normalize_kind', 'parse_date', 'grn_cost_supplier_options',
    'build_grn_costs',
]
