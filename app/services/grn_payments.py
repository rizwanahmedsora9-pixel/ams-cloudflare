"""GRN payment posting — the ONLY place purchase money moves (owner rule A1).

A payment targets exactly one obligation of one GRN:
  * SUPPLIER  -> material (Σ qty × rate) plus individually selected expenses
  * CHARGE    -> one GRNCharge (vehicle / loading / unloading / other recipient)

One ``SupplierPayment`` row (the existing payment table, extended), exactly one
``AccountTransaction`` (money out of a cash/bank account) and one structured
audit row are written per payment.  No inventory, GRNItem, FIFO, expense or
CashFlowEntry row is touched.  Voiding reverses the account effect but keeps
the row and its history.
"""
from __future__ import annotations

from flask import has_request_context
from sqlalchemy import func

from models import (
    db, GRN, GRNCharge, SupplierPayment, Account, AccountTransaction,
    CashFlowParty, Supplier,
)
from utils.money import to_minor, from_minor
from utils.accounting_audit import record_accounting_audit
from utils.audit import audit_log
from app.services.grn_costing import grn_breakdown
from app.services.time_money import pk_now, resolve_posted_datetime
from app.services.payments_crud import (
    _validate_account_for_method, _account_minor, _assert_period_open,
    _account_display_name,
)
from app.services.accounting import (
    _sync_linked_grn_payment_tx, _void_account_tx,
)


def _f(minor):
    return float(from_minor(int(minor or 0)))


def _actor_name(actor):
    return (getattr(actor, 'username', None) or None) if actor else None


def grn_payment_obligations(grn):
    """Original / paid / remaining for every obligation of one GRN."""
    return grn_breakdown(grn)['obligations']


def _find_obligation(grn, obligation_key):
    for row in grn_payment_obligations(grn):
        if row['key'] == obligation_key:
            return row
    return None


def _snapshot(payment):
    return {
        'id': payment.id,
        'grn_id': payment.grn_id,
        'grn_charge_id': payment.grn_charge_id,
        'recipient_type': payment.recipient_type,
        'recipient_name': payment.recipient_name,
        'amount': float(payment.amount or 0),
        'method': payment.method,
        'payment_account_id': payment.payment_account_id,
        'date_posted': payment.date_posted.isoformat() if payment.date_posted else None,
        'reference': payment.reference,
        'note': payment.note,
        'is_void': bool(payment.is_void),
        'source_type': payment.source_type,
        'payment_kind': payment.payment_kind,
        'revision': payment.revision or 1,
    }


def _payment_minor(payment):
    return int(getattr(payment, 'amount_minor', None) if getattr(payment, 'amount_minor', None) is not None
               else to_minor(getattr(payment, 'amount', 0)))


def save_grn_payment(
    *, grn_id, obligation_key, amount, method='Cash', payment_account_id=None,
    date_posted=None, reference='', note='', actor=None, idempotency_key=None,
    payment_id=None, expected_revision=None, allow_advance=False,
):
    """Create / edit one payment against a GRN obligation (atomic, no commit)."""
    grn = db.session.get(GRN, int(grn_id)) if grn_id else None
    if grn is None or bool(getattr(grn, 'is_void', False)) or bool(getattr(grn, 'is_cancelled', False)):
        raise ValueError('GRN not found or cancelled.')

    key = (idempotency_key or '').strip() or None
    if not payment_id and key:
        replay = SupplierPayment.query.filter_by(idempotency_key=key).first()
        if replay:
            replay._idempotent_replay = True
            return replay, False

    amount_minor = to_minor(amount, field='Payment amount')
    if amount_minor <= 0:
        raise ValueError('Payment amount must be greater than zero.')
    normal_method = (method or 'Cash').strip()

    # ---- locate the target obligation -------------------------------------
    obligation = _find_obligation(grn, (obligation_key or '').strip())
    if obligation is None:
        raise ValueError('Select a valid GRN recipient / charge to pay.')
    is_supplier = obligation['kind'] == 'SUPPLIER'
    charge = None
    if not is_supplier:
        charge = db.session.get(GRNCharge, int(obligation['charge_id']))
        if charge is None or charge.grn_id != grn.id or bool(getattr(charge, 'is_void', False)):
            raise ValueError('That charge no longer exists on this GRN.')

    # ---- edit vs create ----------------------------------------------------
    if payment_id:
        payment = db.session.get(SupplierPayment, int(payment_id))
        if payment is None or (getattr(payment, 'source_type', None) or '') != 'GRN_PAYMENT':
            raise ValueError('GRN payment not found.')
        if payment.is_void:
            raise ValueError('This payment is voided. Restore it before editing.')
        if expected_revision not in (None, '') and int(expected_revision) != int(payment.revision or 1):
            raise ValueError('This payment changed in another session. Reload before saving.')
        old = _snapshot(payment)
        created = False
    else:
        payment = SupplierPayment()
        old = None
        created = True

    # ---- remaining balance guard ------------------------------------------
    other_paid = 0
    q = SupplierPayment.query.filter(
        SupplierPayment.grn_id == grn.id,
        SupplierPayment.is_void == False,  # noqa: E712
        SupplierPayment.payment_kind.in_(['GRN_MATERIAL', 'GRN_CHARGE']),
    )
    if not created:
        q = q.filter(SupplierPayment.id != payment.id)
    for row in q.all():
        if is_supplier:
            if row.grn_charge_id is None and (row.recipient_type or 'SUPPLIER') == 'SUPPLIER':
                other_paid += _payment_minor(row)
        elif row.grn_charge_id == charge.id:
            other_paid += _payment_minor(row)
    remaining = int(obligation['original_minor']) - other_paid
    if amount_minor > remaining and not allow_advance:
        raise ValueError(
            f"Payment {_f(amount_minor):,.2f} exceeds the remaining payable "
            f"{_f(max(0, remaining)):,.2f} for {obligation['label']}. "
            "Use a smaller amount or tick 'Record as advance'."
        )

    # ---- account / method / date validation --------------------------------
    account = db.session.get(Account, int(payment_account_id)) if payment_account_id else None
    _validate_account_for_method(account, normal_method,
                                 allow_inactive=bool(old and old['payment_account_id'] == getattr(account, 'id', None)))
    available_minor = _account_minor(account)
    if old and old['payment_account_id'] == account.id:
        available_minor += to_minor(old['amount'])
    if available_minor + 1 < amount_minor:
        raise ValueError('Insufficient balance in the selected account.')

    posted = resolve_posted_datetime(date_posted,
                                     fallback_dt=(payment.date_posted if not created else None))
    if posted and posted > pk_now():
        if created or not payment.date_posted or payment.date_posted != posted:
            raise ValueError('The payment date cannot be in the future.')
    if created:
        _assert_period_open(account.id, posted, operation='posted')
    elif old:
        changed = any((
            old['amount'] != _f(amount_minor),
            old['payment_account_id'] != account.id,
            old['date_posted'] != (posted.isoformat() if posted else None),
        ))
        if changed:
            _assert_period_open(old['payment_account_id'], payment.date_posted, operation='edited')
            if account.id != old['payment_account_id']:
                _assert_period_open(account.id, posted, operation='posted')

    # ---- resolve recipient -------------------------------------------------
    if is_supplier:
        recipient_type = 'SUPPLIER'
        recipient_party_id = None
        recipient_name = grn.supplier or ''
        payment_kind = 'GRN_MATERIAL'
        grn_charge_id = None
        party_id_for_audit = grn.supplier_id
    else:
        recipient_type = (charge.recipient_type or 'OTHER')
        recipient_party_id = charge.recipient_party_id
        recipient_name = (charge.recipient_name or charge.label or obligation['label'])
        payment_kind = 'GRN_CHARGE'
        grn_charge_id = charge.id
        party_id_for_audit = charge.recipient_party_id

    # ---- write the payment document ---------------------------------------
    # supplier_id stays NOT NULL as a context FK (owner rule A2: recipient_type
    # alone decides which ledger gets the debit).  Resolve/create when a legacy
    # GRN was saved with only a free-text supplier name.
    context_supplier_id = grn.supplier_id
    if not context_supplier_id:
        supplier_row = Supplier.query.filter(
            func.lower(func.trim(Supplier.name)) == (grn.supplier or '').strip().lower()
        ).first()
        if supplier_row is None:
            supplier_row = Supplier(name=(grn.supplier or 'Unnamed Supplier').strip(), is_active=True)
            db.session.add(supplier_row)
            db.session.flush()
        context_supplier_id = supplier_row.id
    payment.supplier_id = context_supplier_id
    payment.grn_id = grn.id
    payment.grn_charge_id = grn_charge_id
    payment.recipient_type = recipient_type
    payment.recipient_party_id = recipient_party_id
    payment.recipient_name = recipient_name
    payment.payment_kind = payment_kind
    payment.amount_minor = amount_minor
    payment.amount = _f(amount_minor)
    payment.method = normal_method
    payment.payment_type = 'Payment'
    payment.payment_account_id = account.id
    payment.bank_name = account.bank_name or ''
    payment.account_name = _account_display_name(account)
    payment.account_no = account.account_number or ''
    payment.manual_bill_no = ''  # GRN payments use their own reference field
    payment.reference = (reference or '').strip()[:80] or ''
    payment.date_posted = posted
    payment.note = (note or '').strip()
    payment.source_type = 'GRN_PAYMENT'
    payment.source_id = grn.id
    payment.cash_posted = True
    payment.is_void = False
    payment.idempotency_key = key if created else payment.idempotency_key
    payment.updated_by = _actor_name(actor)
    payment.revision = int(payment.revision or 1) + 1
    if created:
        payment.created_by = _actor_name(actor)
        from app.services.billing import get_next_bill_no
        payment.auto_bill_no = get_next_bill_no('GP')
        db.session.add(payment)
        db.session.flush()
        payment.note = " ".join(x for x in [
            (note or '').strip(),
            f"[SRC:GRN_PAYMENT:{payment.id}] GRN #{grn.manual_bill_no or grn.auto_bill_no or grn.id} — {obligation['label']}",
        ] if x).strip()
    if allow_advance and amount_minor > remaining:
        payment.payment_kind = 'ADVANCE'
        payment.note = (payment.note or '') + ' [Advance over remaining payable]'

    db.session.flush()
    _sync_linked_grn_payment_tx(payment)
    db.session.flush()

    record_accounting_audit(
        actor,
        action='Create' if created else 'Edit',
        entity_type='SupplierPayment',
        entity_id=payment.id,
        before=old,
        after=_snapshot(payment),
        amount_before=(old['amount'] if old else None),
        amount_after=payment.amount,
        account_before_id=(old['payment_account_id'] if old else None),
        account_after_id=account.id,
        party_before_id=(old.get('grn_charge_id') if old else None),
        party_after_id=party_id_for_audit,
        reason=f"GRN payment — {obligation['label']} ({recipient_name})",
        module='grn_payments',
    )
    if has_request_context():
        try:
            audit_log(actor, 'grn.payment.save',
                      f"grn={grn.id}, obligation={obligation['key']}, amount={payment.amount}, "
                      f"recipient={recipient_type}:{recipient_name}")
        except Exception:
            pass
    return payment, created


def void_grn_payment(payment, *, actor=None, reason=''):
    """Void (never delete) a GRN payment, reversing its cash effect."""
    if payment is None or (getattr(payment, 'source_type', None) or '') != 'GRN_PAYMENT':
        raise ValueError('GRN payment not found.')
    if payment.is_void:
        return False
    _assert_period_open(payment.payment_account_id, payment.date_posted, operation='voided')
    before = _snapshot(payment)
    payment.is_void = True
    payment.updated_by = _actor_name(actor)
    payment.revision = int(payment.revision or 1) + 1
    _sync_linked_grn_payment_tx(payment)
    db.session.flush()
    record_accounting_audit(
        actor, action='Delete', entity_type='SupplierPayment', entity_id=payment.id,
        before=before, after=_snapshot(payment),
        amount_before=before['amount'], amount_after=0,
        account_before_id=before['payment_account_id'],
        reason=(reason or payment.note), module='grn_payments',
    )
    return True


def restore_grn_payment(payment, *, actor=None):
    """Restore a voided GRN payment (balance re-applied, history preserved)."""
    if payment is None or (getattr(payment, 'source_type', None) or '') != 'GRN_PAYMENT':
        raise ValueError('GRN payment not found.')
    if not payment.is_void:
        return False
    _assert_period_open(payment.payment_account_id, payment.date_posted, operation='restored')
    account = db.session.get(Account, payment.payment_account_id) if payment.payment_account_id else None
    if account and _account_minor(account) < _payment_minor(payment):
        raise ValueError('Insufficient balance to restore this GRN payment.')
    before = _snapshot(payment)
    payment.is_void = False
    payment.updated_by = _actor_name(actor)
    payment.revision = int(payment.revision or 1) + 1
    _sync_linked_grn_payment_tx(payment)
    db.session.flush()
    record_accounting_audit(
        actor, action='Restore', entity_type='SupplierPayment', entity_id=payment.id,
        before=before, after=_snapshot(payment),
        amount_before=0, amount_after=payment.amount,
        account_after_id=payment.payment_account_id,
        reason=payment.note, module='grn_payments',
    )
    return True


def grn_payment_integrity():
    """Read-only checks used by financial_integrity_audit()."""
    issues = []
    rows = SupplierPayment.query.filter(
        SupplierPayment.source_type == 'GRN_PAYMENT',
        SupplierPayment.is_void == False,  # noqa: E712
    ).all()
    for p in rows:
        txs = AccountTransaction.query.filter(
            AccountTransaction.source_type == 'GRN_PAYMENT',
            AccountTransaction.source_id == p.id,
            AccountTransaction.is_void == False,  # noqa: E712
        ).all()
        if len(txs) != 1:
            issues.append({'kind': 'grn_payment_tx_count', 'payment_id': p.id, 'count': len(txs)})
        elif abs(int(txs[0].amount_minor or 0) - _payment_minor(p)) > 1:
            issues.append({'kind': 'grn_payment_tx_amount', 'payment_id': p.id, 'tx_id': txs[0].id})
        if not db.session.get(GRN, p.grn_id):
            issues.append({'kind': 'orphan_grn_payment', 'payment_id': p.id, 'grn_id': p.grn_id})
        if p.grn_charge_id and not db.session.get(GRNCharge, p.grn_charge_id):
            issues.append({'kind': 'orphan_grn_charge_payment', 'payment_id': p.id,
                           'charge_id': p.grn_charge_id})
    return issues


__all__ = [
    'grn_payment_obligations', 'save_grn_payment', 'void_grn_payment',
    'restore_grn_payment', 'grn_payment_integrity',
]
