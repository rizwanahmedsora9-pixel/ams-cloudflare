"""GRN landed costing and purchase-obligation arithmetic — the SINGLE authority.

Owner rules (approved 2026-11-02):

A1  A GRN NEVER pays.  It records material received, purchase costs, charge
    details and payment obligations only.  No payment/settlement/cash row is
    created here.  All money is paid from Accounts -> PAY EXISTING GRN.

A2  Supplier Ledger credit for a GRN is EXACTLY
    ``sum(GRNItem.qty * GRNItem.price_at_time)`` and nothing else: no vehicle
    fare / loading / unloading / transport / other charge, no tax, no discount,
    no adjustment.  Each charge belongs to its own non-supplier recipient.

Everything else (landed FIFO cost, COGS, expense recognition, payables, cash
actually paid, GRN detail screens) is derived from this module so no screen can
compute its own version of the truth.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func

from models import (
    db, GRN, GRNItem, GRNCharge, SupplierPayment, AccountTransaction,
    CashFlowParty,
)
from utils.money import to_minor, from_minor, decimal_money
from app.services.pricing import allocate_cents

logger = logging.getLogger(__name__)

CHARGE_TYPES = ('VEHICLE_FARE', 'TRANSPORT', 'LOADING', 'UNLOADING', 'OTHER')
CHARGE_TYPE_LABELS = {
    'VEHICLE_FARE': 'Vehicle Fare',
    'TRANSPORT': 'Transportation',
    'LOADING': 'Loading',
    'UNLOADING': 'Unloading',
    'OTHER': 'Other Expenses',
}
RECIPIENT_TYPES = ('TRANSPORTER', 'LABOUR', 'OTHER', 'UNSPECIFIED')
RECIPIENT_LABELS = {
    'TRANSPORTER': 'Vehicle / Transporter',
    'LABOUR': 'Loading / Labour',
    'OTHER': 'Other Party',
    'UNSPECIFIED': 'Unassigned (legacy charge)',
}
DEFAULT_RECIPIENT_BY_CHARGE = {
    'VEHICLE_FARE': 'TRANSPORTER',
    'TRANSPORT': 'TRANSPORTER',
    'LOADING': 'LABOUR',
    'UNLOADING': 'LABOUR',
    'OTHER': 'OTHER',
}
COST_TREATMENTS = ('INVENTORY', 'EXPENSE', 'NON_MATERIAL', 'UNTRACKED_LEGACY')
DECLARED_STATUSES = ('PAID', 'UNPAID', 'NOT_APPLICABLE')
ALLOCATION_BASES = ('VALUE', 'QUANTITY', 'MANUAL')

LEGACY_MIRRORS = (
    ('freight_cost', ('VEHICLE_FARE', 'TRANSPORT')),
    ('loading_cost', ('LOADING', 'UNLOADING')),
    ('other_expense', ('OTHER',)),
)


def _minor(value, field='Amount'):
    return to_minor(value, field=field)


def _f(minor):
    return float(from_minor(int(minor or 0)))


def active_items(grn):
    """Query directly: a cached relationship may miss rows added in this
    same request (a GRN is saved with its lines and charges in one flush)."""
    if grn is None:
        return []
    if getattr(grn, 'id', None):
        try:
            return [
                i for i in GRNItem.query.filter(
                    GRNItem.grn_id == grn.id,
                    GRNItem.is_void == False,  # noqa: E712
                    GRNItem.qty > 0,
                ).order_by(GRNItem.id.asc()).all()
            ]
        except Exception:
            pass
    return [
        i for i in (getattr(grn, 'items', None) or [])
        if not bool(getattr(i, 'is_void', False)) and float(getattr(i, 'qty', 0) or 0) > 0
    ]


def active_charges(grn):
    if grn is None:
        return []
    if getattr(grn, 'id', None):
        try:
            return GRNCharge.query.filter(
                GRNCharge.grn_id == grn.id,
                GRNCharge.is_void == False,  # noqa: E712
            ).order_by(GRNCharge.id.asc()).all()
        except Exception:
            pass
    return [
        c for c in (getattr(grn, 'charges', None) or [])
        if not bool(getattr(c, 'is_void', False))
    ]


def lot_cost_rate(item):
    """Authoritative per-unit cost for FIFO / P&L / stock valuation.

    LANDED lots carry the allocated landed cost; legacy lots fall back to the
    supplier rate so historical frozen costs never change.
    """
    rate = float(getattr(item, 'landed_unit_cost', 0) or 0)
    if rate > 0:
        return rate
    return float(getattr(item, 'price_at_time', 0) or 0)


def get_or_create_party(name, role='other', actor=None):
    """Reuse the existing CashFlowParty master for non-supplier recipients."""
    clean = (name or '').strip()
    if not clean:
        return None
    party = CashFlowParty.query.filter(
        func.lower(func.trim(CashFlowParty.name)) == clean.lower()
    ).first()
    if party is None:
        party = CashFlowParty(
            name=clean,
            party_type='person',
            party_role=role,
            is_active=True,
            is_payee_active=True,
            created_by=actor,
        )
        db.session.add(party)
        db.session.flush()
    elif not getattr(party, 'party_role', None) or party.party_role == 'other':
        if role != 'other':
            party.party_role = role
    return party


def _line_minor(item):
    return _minor(float(getattr(item, 'qty', 0) or 0) * float(getattr(item, 'price_at_time', 0) or 0),
                  field='Material line')


def supplier_material_minor(grn):
    """A2: gross material amount only.  Never tax/discount/adjustment/charges."""
    return sum(_line_minor(i) for i in active_items(grn))


def _charge_minor(charge):
    current = getattr(charge, 'amount_minor', None)
    if current is None:
        return _minor(getattr(charge, 'amount', 0), field='Charge amount')
    return int(current)


def _cash_paid_minor(grn):
    """Money that ACTUALLY left a cash/bank account for this GRN."""
    rows = AccountTransaction.query.filter(
        AccountTransaction.grn_id == grn.id,
        AccountTransaction.is_void == False,  # noqa: E712
        AccountTransaction.from_account_id.isnot(None),
    ).all()
    total = 0
    for tx in rows:
        total += int(getattr(tx, 'amount_minor', None) if getattr(tx, 'amount_minor', None) is not None
                     else _minor(getattr(tx, 'amount', 0)))
    return total


def _payment_rows(grn):
    q = SupplierPayment.query.filter(
        SupplierPayment.grn_id == grn.id,
        SupplierPayment.is_void == False,  # noqa: E712
    )
    rows = list(q.all())
    # Legacy GRNs used a marker-only auto payment without grn_id.  Keep those
    # attached so historical balances stay intact without rewriting them.
    marker = f"[auto_grn_pay:{grn.id}]".lower()
    legacy = SupplierPayment.query.filter(
        SupplierPayment.grn_id.is_(None),
        SupplierPayment.is_void == False,  # noqa: E712
        func.lower(func.coalesce(SupplierPayment.note, '')).like(f"%{marker}%"),
    ).all()
    seen = {r.id for r in rows}
    for r in legacy:
        if r.id not in seen:
            rows.append(r)
    return rows


def _is_supplier_payment(row):
    kind = (getattr(row, 'payment_kind', None) or '').strip().upper()
    recipient = (getattr(row, 'recipient_type', None) or '').strip().upper()
    if kind == 'GRN_CHARGE':
        return False
    # NULL recipient_type means a legacy/standalone supplier payment.
    return recipient in ('', 'SUPPLIER')


def grn_breakdown(grn):
    """One immutable breakdown used by every screen, report and export."""
    grn_id = getattr(grn, 'id', None)
    items = active_items(grn)
    charges = active_charges(grn)
    payments = _payment_rows(grn) if grn_id else []

    line_minors = [_line_minor(i) for i in items]
    supplier_minor = sum(line_minors)

    charge_rows = []
    capitalised_minor = 0
    expense_minor = 0
    for c in charges:
        amount = _charge_minor(c)
        treatment = (getattr(c, 'cost_treatment', None) or 'INVENTORY').upper()
        status = (getattr(c, 'declared_status', None) or 'UNPAID').upper()
        if treatment == 'INVENTORY' and amount > 0:
            capitalised_minor += amount
        if treatment == 'EXPENSE' and amount > 0:
            expense_minor += amount
        paid = sum(
            int(getattr(p, 'amount_minor', None) if getattr(p, 'amount_minor', None) is not None
                else _minor(getattr(p, 'amount', 0)))
            for p in payments if getattr(p, 'grn_charge_id', None) == c.id
        )
        applicable = amount > 0 and status != 'NOT_APPLICABLE' and treatment != 'NON_MATERIAL'
        charge_rows.append({
            'id': c.id,
            'charge_type': c.charge_type,
            'charge_label': CHARGE_TYPE_LABELS.get(c.charge_type, c.charge_type),
            'label': getattr(c, 'label', '') or '',
            'amount': _f(amount),
            'amount_minor': amount,
            'recipient_type': c.recipient_type,
            'recipient_label': RECIPIENT_LABELS.get(c.recipient_type, c.recipient_type),
            'recipient_party_id': getattr(c, 'recipient_party_id', None),
            'recipient_name': getattr(c, 'recipient_name', '') or '',
            'declared_status': status,
            'cost_treatment': treatment,
            'allocation_basis': getattr(c, 'allocation_basis', 'VALUE'),
            'allocation_json': getattr(c, 'allocation_json', None),
            'is_legacy_mirror': bool(getattr(c, 'is_legacy_mirror', False)),
            'paid': _f(paid),
            'paid_minor': paid,
            'remaining': _f(max(0, amount - paid)),
            'remaining_minor': max(0, amount - paid),
            'status': ('Paid' if paid >= amount and amount > 0 else
                       ('Partially Paid' if paid > 0 else 'Unpaid')),
            'applicable': applicable,
        })

    supplier_paid = sum(
        int(getattr(p, 'amount_minor', None) if getattr(p, 'amount_minor', None) is not None
            else _minor(getattr(p, 'amount', 0)))
        for p in payments if _is_supplier_payment(p) and getattr(p, 'grn_charge_id', None) is None
    )
    # Legacy GRNs without a canonical payment row keep their historic read-side
    # debit; LANDED GRNs never have a paid_amount (A1).
    legacy_paid_minor = 0
    if (getattr(grn, 'costing_mode', 'LEGACY') or 'LEGACY') == 'LEGACY':
        has_auto = any((getattr(p, 'payment_kind', None) or '').upper() == 'LEGACY_GRN_AUTO'
                       or (getattr(p, 'source_type', None) or '').upper() == 'GRN'
                       for p in payments)
        if not has_auto and float(getattr(grn, 'paid_amount', 0) or 0) > 0:
            legacy_paid_minor = _minor(getattr(grn, 'paid_amount', 0))
    supplier_paid += legacy_paid_minor

    charge_paid = sum(r['paid_minor'] for r in charge_rows)
    landed_minor = supplier_minor + capitalised_minor
    cash_paid_minor = _cash_paid_minor(grn) if grn_id else 0
    total_qty = sum(float(getattr(i, 'qty', 0) or 0) for i in items)
    units = {str((getattr(i, 'mat_name', '') or '')).strip() for i in items}
    # A single "average rate" only makes sense for one material/one unit.
    avg_rate = (float(from_minor(landed_minor)) / total_qty) if total_qty > 0 else 0.0

    obligations = [{
        'key': f'SUPPLIER:{grn_id}',
        'kind': 'SUPPLIER',
        'charge_id': None,
        'label': 'Supplier material amount',
        'recipient_type': 'SUPPLIER',
        'recipient_label': 'Supplier',
        'recipient_name': getattr(grn, 'supplier', '') or '',
        'recipient_party_id': None,
        'original': _f(supplier_minor),
        'original_minor': supplier_minor,
        'paid': _f(supplier_paid),
        'paid_minor': supplier_paid,
        'remaining': _f(max(0, supplier_minor - supplier_paid)),
        'remaining_minor': max(0, supplier_minor - supplier_paid),
        'status': ('Paid' if supplier_paid >= supplier_minor and supplier_minor > 0 else
                   ('Partially Paid' if supplier_paid > 0 else 'Unpaid')),
    }]
    for row in charge_rows:
        if not row['applicable'] or row['amount_minor'] <= 0:
            continue
        obligations.append({
            'key': f'CHARGE:{row["id"]}',
            'kind': 'CHARGE',
            'charge_id': row['id'],
            'label': f"{row['charge_label']}{(' — ' + row['label']) if row['label'] else ''}",
            'recipient_type': row['recipient_type'],
            'recipient_label': row['recipient_label'],
            'recipient_name': row['recipient_name'],
            'recipient_party_id': row['recipient_party_id'],
            'original': row['amount'],
            'original_minor': row['amount_minor'],
            'paid': row['paid'],
            'paid_minor': row['paid_minor'],
            'remaining': row['remaining'],
            'remaining_minor': row['remaining_minor'],
            'status': row['status'],
            'cost_treatment': row['cost_treatment'],
        })

    per_line = []
    for idx, item in enumerate(items):
        per_line.append({
            'id': item.id,
            'material': item.mat_name,
            'qty': float(getattr(item, 'qty', 0) or 0),
            'supplier_rate': float(getattr(item, 'price_at_time', 0) or 0),
            'supplier_amount': _f(line_minors[idx]),
            'allocated_charges': _f(int(getattr(item, 'allocated_charges_minor', 0) or 0)),
            'landed_unit_cost': round(lot_cost_rate(item), 6),
            'line_landed_cost': _f(int(getattr(item, 'line_landed_cost_minor', 0) or 0)),
        })

    total_obligations = supplier_minor + sum(
        r['amount_minor'] for r in charge_rows if r['applicable']
    )
    total_remaining = max(0, supplier_minor - supplier_paid) + sum(
        r['remaining_minor'] for r in charge_rows if r['applicable']
    )

    return {
        'grn_id': grn_id,
        'bill_ref': (getattr(grn, 'manual_bill_no', None) or getattr(grn, 'auto_bill_no', None)
                     or f"GRN-{grn_id or ''}"),
        'supplier': getattr(grn, 'supplier', '') or '',
        'supplier_id': getattr(grn, 'supplier_id', None),
        'costing_mode': (getattr(grn, 'costing_mode', 'LEGACY') or 'LEGACY'),
        'supplier_material_amount': _f(supplier_minor),
        'supplier_material_amount_minor': supplier_minor,
        'charges': charge_rows,
        'vehicle_fare': _f(sum(r['amount_minor'] for r in charge_rows if r['charge_type'] in ('VEHICLE_FARE', 'TRANSPORT'))),
        'loading': _f(sum(r['amount_minor'] for r in charge_rows if r['charge_type'] == 'LOADING')),
        'unloading': _f(sum(r['amount_minor'] for r in charge_rows if r['charge_type'] == 'UNLOADING')),
        'other_charges': _f(sum(r['amount_minor'] for r in charge_rows if r['charge_type'] == 'OTHER')),
        'capitalised_charge_total': _f(capitalised_minor),
        'capitalised_charge_total_minor': capitalised_minor,
        'expense_charge_total': _f(expense_minor),
        'expense_charge_total_minor': expense_minor,
        'landed_cost_total': _f(landed_minor),
        'landed_cost_total_minor': landed_minor,
        'total_qty': total_qty,
        'average_actual_rate': round(avg_rate, 6),
        'single_unit': len(units) <= 1,
        'per_line': per_line,
        'supplier_paid': _f(supplier_paid),
        'supplier_paid_minor': supplier_paid,
        'supplier_remaining': _f(max(0, supplier_minor - supplier_paid)),
        'additional_paid': _f(charge_paid),
        'additional_remaining': _f(sum(r['remaining_minor'] for r in charge_rows if r['applicable'])),
        'total_obligations': _f(total_obligations),
        'total_remaining': _f(total_remaining),
        'total_cash_paid': _f(cash_paid_minor),
        'total_cash_paid_minor': cash_paid_minor,
        'obligations': obligations,
        'payment_rows': [
            {
                'id': p.id,
                'amount': float(getattr(p, 'amount', 0) or 0),
                'date_posted': getattr(p, 'date_posted', None),
                'method': getattr(p, 'method', '') or '',
                'reference': getattr(p, 'reference', None) or getattr(p, 'manual_bill_no', '') or '',
                'recipient_type': getattr(p, 'recipient_type', None) or 'SUPPLIER',
                'recipient_name': getattr(p, 'recipient_name', '') or getattr(grn, 'supplier', '') or '',
                'charge_id': getattr(p, 'grn_charge_id', None),
                'payment_kind': getattr(p, 'payment_kind', None) or '',
                'cash_posted': bool(getattr(p, 'cash_posted', False)),
                'is_void': bool(getattr(p, 'is_void', False)),
                'note': getattr(p, 'note', '') or '',
            }
            for p in sorted(payments, key=lambda r: (getattr(r, 'date_posted', None) or '', r.id))
        ],
        # memo-only legacy fields (A2: never posted to a ledger or to inventory)
        'tax_amount': float(getattr(grn, 'tax_amount', 0) or 0),
        'discount': float(getattr(grn, 'discount', 0) or 0),
        'adjustment_amount': float(getattr(grn, 'adjustment_amount', 0) or 0),
    }


def _weights_for_charge(charge, items, line_minors):
    basis = (getattr(charge, 'allocation_basis', None) or 'VALUE').upper()
    if basis == 'QUANTITY':
        return [max(0.0, float(getattr(i, 'qty', 0) or 0)) for i in items], 'QUANTITY'
    if basis == 'MANUAL':
        try:
            raw = json.loads(getattr(charge, 'allocation_json', None) or '{}')
            weights = [int(raw.get(str(i.id), raw.get(i.id, 0)) or 0) for i in items]
            if sum(weights) == _charge_minor(charge) and all(w >= 0 for w in weights):
                return weights, 'MANUAL'
        except (TypeError, ValueError):
            pass
        logger.warning('GRN charge %s MANUAL allocation invalid; using VALUE', getattr(charge, 'id', None))
    return [max(0, m) for m in line_minors], 'VALUE'


def recompute_landed_costs(grn, *, actor=None):
    """Allocate INVENTORY charges to GRN lots and store exact landed costs.

    Charges flagged EXPENSE / NON_MATERIAL / UNTRACKED_LEGACY are never
    allocated, so they can never be counted twice (inventory AND expense).
    """
    items = active_items(grn)
    charges = active_charges(grn)
    line_minors = [_line_minor(i) for i in items]

    allocated = {i.id: 0 for i in items}
    capitalised = 0
    expense_total = 0
    for c in charges:
        amount = _charge_minor(c)
        treatment = (getattr(c, 'cost_treatment', None) or 'INVENTORY').upper()
        status = (getattr(c, 'declared_status', None) or 'UNPAID').upper()
        if amount <= 0 or status == 'NOT_APPLICABLE' or treatment in ('NON_MATERIAL', 'UNTRACKED_LEGACY'):
            continue
        if treatment == 'EXPENSE':
            expense_total += amount
            continue
        capitalised += amount
        weights, basis = _weights_for_charge(c, items, line_minors)
        shares = allocate_cents(amount, weights) if items else []
        c.allocation_json = json.dumps({str(i.id): int(s) for i, s in zip(items, shares)})
        c.allocation_basis = basis
        for i, share in zip(items, shares):
            allocated[i.id] += int(share)

    supplier_minor = sum(line_minors)
    landed_minor = supplier_minor + capitalised
    for idx, item in enumerate(items):
        line_total = line_minors[idx] + allocated[item.id]
        qty = float(getattr(item, 'qty', 0) or 0)
        unit = 0.0
        if qty > 0:
            unit = float((Decimal(line_total) / Decimal('100') / Decimal(str(qty))).quantize(
                Decimal('0.000001'), rounding=ROUND_HALF_UP))
        item.base_rate_minor = _minor(getattr(item, 'price_at_time', 0), field='Supplier rate')
        item.allocated_charges_minor = allocated[item.id]
        item.line_landed_cost_minor = line_total
        item.landed_unit_cost = unit
        item.landed_unit_cost_minor = _minor(unit, field='Landed unit cost')
        item.allocation_basis = (getattr(grn, 'allocation_basis_default', None) or 'VALUE')

    grn.supplier_material_amount_minor = supplier_minor
    grn.supplier_material_amount = _f(supplier_minor)
    grn.capitalised_charge_total_minor = capitalised
    grn.capitalised_charge_total = _f(capitalised)
    grn.landed_cost_total_minor = landed_minor
    grn.landed_cost_total = _f(landed_minor)
    grn.expense_charge_total_minor = expense_total
    grn.expense_charge_total = _f(expense_total)
    if actor:
        grn.updated_by = actor
    return grn_breakdown(grn)


def mirror_legacy_charge_columns(grn):
    """Keep the deprecated flat columns as a cache only (never a second truth)."""
    by_type = {}
    for c in active_charges(grn):
        if bool(getattr(c, 'is_legacy_mirror', False)):
            continue
        by_type.setdefault((c.charge_type or 'OTHER').upper(), 0)
        by_type[(c.charge_type or 'OTHER').upper()] += _charge_minor(c)
    for column, types in LEGACY_MIRRORS:
        setattr(grn, column, _f(sum(by_type.get(t, 0) for t in types)))


def sync_charges_from_form(grn, form, *, actor=None, preserve_legacy=True):
    """Create/replace LANDED charge rows from the wizard's charge grid.

    ``preserve_legacy`` keeps the old scalar columns intact for LEGACY GRNs
    when the browser does not post them (historical safety).
    """
    if not preserve_legacy:
        pass
    types = form.getlist('charge_type[]')
    labels = form.getlist('charge_label[]')
    amounts = form.getlist('charge_amount[]')
    recipients = form.getlist('charge_recipient_type[]')
    party_names = form.getlist('charge_recipient[]')
    # A charge carries cost facts only.  There is no paid/unpaid field on the
    # grid any more (owner: every paid control lives in Accounts), so the old
    # declaration is gone from the form; a stored value is simply kept as-is
    # and never influences a cost or a balance.
    statuses = form.getlist('charge_status[]')
    treatments = form.getlist('charge_treatment[]')
    bases = form.getlist('charge_basis[]')
    charge_ids = form.getlist('charge_id[]')

    def at(seq, idx, default=''):
        return (seq[idx] if idx < len(seq) else default) or default

    existing = {int(c.id): c for c in (grn.charges or [])}
    keep = set()

    def _paid_minor_for(charge_id):
        rows = SupplierPayment.query.filter(
            SupplierPayment.grn_charge_id == charge_id,
            SupplierPayment.is_void == False,  # noqa: E712
        ).all()
        return sum(int(getattr(r, 'amount_minor', None) if getattr(r, 'amount_minor', None) is not None
                       else _minor(getattr(r, 'amount', 0))) for r in rows)
    for idx in range(max(len(types), len(amounts), len(labels))):
        raw_amount = at(amounts, idx, '0')
        try:
            amount_minor = _minor(float(str(raw_amount).replace(',', '').strip() or 0), field='Charge amount')
        except (TypeError, ValueError):
            raise ValueError(f"Charge #{idx + 1} has an invalid amount: '{raw_amount}'.")
        ctype = at(types, idx, 'OTHER').strip().upper()
        if ctype not in CHARGE_TYPES:
            ctype = 'OTHER'
        raw_id = at(charge_ids, idx, '')
        stored_charge = existing.get(int(raw_id)) if str(raw_id).isdigit() else None
        if statuses:
            status = at(statuses, idx, 'UNPAID').strip().upper()
            if status not in DECLARED_STATUSES:
                status = 'UNPAID'
        else:
            # Field removed from the GRN screen: never invent a declaration.
            status = (getattr(stored_charge, 'declared_status', None) or 'UNPAID').upper()
            if status not in DECLARED_STATUSES:
                status = 'UNPAID'
        if status == 'NOT_APPLICABLE':
            amount_minor = 0
        treatment = at(treatments, idx, 'INVENTORY').strip().upper()
        if treatment not in COST_TREATMENTS:
            treatment = 'INVENTORY'
        basis = at(bases, idx, 'VALUE').strip().upper()
        if basis not in ALLOCATION_BASES:
            basis = 'VALUE'
        recipient = at(recipients, idx, '').strip().upper()
        if recipient not in RECIPIENT_TYPES:
            recipient = DEFAULT_RECIPIENT_BY_CHARGE.get(ctype, 'OTHER')
        party_name = at(party_names, idx, '').strip()
        party = get_or_create_party(
            party_name,
            role=('transporter' if recipient == 'TRANSPORTER' else
                  'loading_labour' if recipient == 'LABOUR' else 'other'),
            actor=actor,
        ) if party_name and recipient != 'UNSPECIFIED' else None

        charge = stored_charge
        if charge is None and amount_minor > 0:
            charge = GRNCharge(grn_id=grn.id, created_by=actor)
            db.session.add(charge)
            try:
                grn.charges.append(charge)
            except Exception:
                pass
        if charge is None:
            continue
        # A charge that already has money posted against it in Accounts must
        # not be silently rewritten: void those payments first (historical
        # safety, owner requirement 10).
        if charge.id is not None and _paid_minor_for(int(charge.id)) > 0:
            changed = (
                _charge_minor(charge) != amount_minor
                or (getattr(charge, 'recipient_type', None) or '').upper() != recipient
                or (getattr(charge, 'cost_treatment', None) or '').upper() != treatment
                or (getattr(charge, 'charge_type', None) or '').upper() != ctype
            )
            if changed:
                raise ValueError(
                    f"Charge '{charge.label or CHARGE_TYPE_LABELS.get(ctype, ctype)}' already has "
                    "payments recorded in Accounts. Void those GRN payments before changing it."
                )
        charge.charge_type = ctype
        charge.label = at(labels, idx, '').strip()
        charge.amount_minor = amount_minor
        charge.amount = _f(amount_minor)
        charge.recipient_type = recipient
        charge.recipient_party_id = party.id if party else None
        charge.recipient_name = party.name if party else party_name
        charge.declared_status = status
        charge.cost_treatment = treatment
        charge.allocation_basis = basis
        charge.is_void = False
        charge.is_legacy_mirror = False
        charge.legacy_column = None
        charge.updated_by = actor
        charge.note = at(form.getlist('charge_note[]'), idx, '').strip()
        db.session.flush()
        keep.add(int(charge.id))

    for cid, charge in existing.items():
        if cid not in keep and not bool(getattr(charge, 'is_legacy_mirror', False)):
            if _paid_minor_for(cid) > 0:
                raise ValueError(
                    f"Charge '{charge.label or charge.charge_type}' already has payments "
                    "recorded in Accounts and cannot be removed. Void those payments first."
                )
            charge.is_void = True
    db.session.flush()
    return active_charges(grn)


def calculate_grn_total(grn):
    """Backwards-compatible document total.

    LANDED GRNs: the landed cost (material + capitalised charges).  LEGACY
    GRNs: the historical formula, unchanged, so old documents/prints/reports
    keep their original numbers.  This is NEVER used as a supplier payable
    (owner rule A2) — use ``grn_breakdown()['supplier_material_amount']``.
    """
    mode = (getattr(grn, 'costing_mode', 'LEGACY') or 'LEGACY').upper()
    if mode == 'LANDED':
        return grn_breakdown(grn)['landed_cost_total']
    item_total = sum(
        float(getattr(i, 'qty', 0) or 0) * float(getattr(i, 'price_at_time', 0) or 0)
        for i in (getattr(grn, 'items', None) or [])
        if not bool(getattr(i, 'is_void', False))
    )
    expenses = sum(float(getattr(grn, col, 0) or 0) for col in ('loading_cost', 'freight_cost', 'other_expense'))
    return (item_total + expenses + float(getattr(grn, 'tax_amount', 0) or 0)
            - float(getattr(grn, 'discount', 0) or 0)
            + float(getattr(grn, 'adjustment_amount', 0) or 0))


__all__ = [
    'CHARGE_TYPES', 'CHARGE_TYPE_LABELS', 'RECIPIENT_TYPES', 'RECIPIENT_LABELS',
    'DEFAULT_RECIPIENT_BY_CHARGE', 'COST_TREATMENTS', 'DECLARED_STATUSES',
    'ALLOCATION_BASES', 'active_items', 'active_charges', 'lot_cost_rate',
    'get_or_create_party', 'supplier_material_minor', 'grn_breakdown',
    'recompute_landed_costs', 'mirror_legacy_charge_columns',
    'sync_charges_from_form', 'calculate_grn_total',
]
