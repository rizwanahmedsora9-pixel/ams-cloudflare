"""Safe GRN cancellation (owner requirement 10).

Cancellation is a *soft* reversal: the GRN, its lots, its charge obligations
and every Accounts payment stay in the database as history.  Only quantities
are reversed (void the IN stock rows and rebuild Material.total).  Cash rows
are NEVER deleted or rewritten — if money was already paid it must be handled
explicitly (refund or advance) before the GRN can be cancelled.
"""
from __future__ import annotations

from models import (
    db, GRN, GRNItem, GRNCharge, Entry, SupplierPayment,
    Material,
)
from utils.accounting_audit import record_accounting_audit
from utils.audit import audit_log
from app.services.grn_costing import active_items
from app.services.time_money import pk_now


def _actor_name(actor):
    return (getattr(actor, 'username', None) or None) if actor else None


def grn_linked_payments(grn):
    return SupplierPayment.query.filter(
        SupplierPayment.grn_id == grn.id,
        SupplierPayment.source_type == 'GRN_PAYMENT',
        SupplierPayment.is_void == False,  # noqa: E712
    ).all()


def cancel_grn(grn, *, actor=None, reason='', allow_paid=False):
    """Void a GRN safely.  Returns a dict describing what was reversed."""
    if grn is None:
        raise ValueError('GRN not found.')
    if bool(getattr(grn, 'is_void', False)) or bool(getattr(grn, 'is_cancelled', False)):
        raise ValueError('This GRN is already cancelled.')

    from app.services.sales_core import _grn_has_locked_lots
    if _grn_has_locked_lots(grn):
        raise ValueError(
            'Cannot cancel GRN: its stock has already been delivered/sold. '
            'Reverse those sales first.'
        )

    payments = grn_linked_payments(grn)
    if payments and not allow_paid:
        raise ValueError(
            'This GRN has %d payment(s) recorded in Accounts. Historical cash '
            'rows are never deleted: refund them or keep the GRN open and '
            'reallocate the payments as advances first.' % len(payments)
        )

    items = active_items(grn)
    reversed_qty = {}
    for item in items:
        reversed_qty[item.mat_name] = reversed_qty.get(item.mat_name, 0.0) + float(item.qty or 0)

    entry_rows = Entry.query.filter(
        Entry.auto_bill_no == grn.auto_bill_no,
        Entry.type == 'IN',
        Entry.is_void == False,  # noqa: E712
    ).all() if getattr(grn, 'auto_bill_no', None) else []
    for entry in entry_rows:
        entry.is_void = True

    for item in items:
        item.is_void = True
    charge_rows = GRNCharge.query.filter(
        GRNCharge.grn_id == grn.id,
        GRNCharge.is_void == False,  # noqa: E712
    ).all()
    for charge in charge_rows:
        charge.is_void = True

    grn.is_void = True
    grn.is_cancelled = True
    grn.cancelled_at = pk_now()
    grn.cancelled_by = _actor_name(actor)
    grn.cancel_reason = (reason or '').strip()[:500]
    grn.updated_by = _actor_name(actor)
    grn.revision = int(getattr(grn, 'revision', 1) or 1) + 1

    from app.services.void_rebuild import _rebuild_material_totals
    _rebuild_material_totals()
    db.session.flush()

    record_accounting_audit(
        actor, action='Cancel', entity_type='GRN', entity_id=grn.id,
        before={'is_void': False, 'items': len(items), 'charges': len(charge_rows)},
        after={'is_void': True, 'is_cancelled': True, 'reason': grn.cancel_reason},
        reason=grn.cancel_reason or 'GRN cancelled', module='grn',
    )
    try:
        audit_log(actor, 'grn.cancel',
                  f'grn={grn.id}, items={len(items)}, charges={len(charge_rows)}')
    except Exception:
        pass
    return {
        'grn_id': grn.id,
        'items_reversed': len(items),
        'charges_voided': len(charge_rows),
        'entries_voided': len(entry_rows),
        'reversed_qty': reversed_qty,
        'payments_preserved': len(payments),
    }


__all__ = ['cancel_grn', 'grn_linked_payments']
