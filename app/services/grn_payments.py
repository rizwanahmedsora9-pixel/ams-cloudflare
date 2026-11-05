"""GRN payment posting — the ONLY place purchase money moves (owner rule A1).

A payment targets exactly one obligation of one GRN:
  * MATERIAL  -> stock value only (Σ qty × rate)
  * EXPENSES  -> only the GRN costs ticked "Add to supplier ledger"
  * SUPPLIER  -> the legacy lumped supplier bill (both of the above at once);
                 still accepted so old links/forms keep working
  * CHARGE    -> one GRNCharge (vehicle / loading / unloading / other recipient)

Material and expenses are separate payables (owner rule A3): paying stock never
settles an expense and paying an expense never settles stock.

One ``SupplierPayment`` row (the existing payment table, extended), exactly one
``AccountTransaction`` (money out of a cash/bank account) and one structured
audit row are written per payment.  No inventory, GRNItem, FIFO, expense or
CashFlowEntry row is touched.  Voiding reverses the account effect but keeps
the row and its history.
"""
from __future__ import annotations

from flask import has_request_context
from sqlalchemy import func, or_

from models import (
    db, GRN, GRNCharge, SupplierPayment, Account, AccountTransaction,
    CashFlowParty, Supplier,
)
from utils.money import to_minor, from_minor
from utils.accounting_audit import record_accounting_audit
from utils.audit import audit_log
from app.services.grn_costing import (
    grn_breakdown, parse_obligation_key, supplier_obligation_paid_minor,
    OBLIGATION_MATERIAL, OBLIGATION_EXPENSES, OBLIGATION_SUPPLIER,
    OBLIGATION_CHARGE, PAYMENT_KIND_BY_OBLIGATION,
)
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
    """Resolve the posted key (or a legacy spelling) to an open obligation."""
    rows = grn_payment_obligations(grn)
    for row in rows:
        if row['key'] == obligation_key:
            return row
    # Backwards compatibility: "SUPPLIER:<id>" used to be the single lumped bill
    # and is still linked from older screens, bookmarks and API clients.
    kind, _ = parse_obligation_key(obligation_key)
    if kind == OBLIGATION_SUPPLIER:
        material = next((r for r in rows if r['kind'] == OBLIGATION_MATERIAL), None)
        if material is not None and material['remaining_minor'] > 0:
            return material
        expenses = next((r for r in rows if r['kind'] == OBLIGATION_EXPENSES), None)
        if expenses is not None and expenses['remaining_minor'] > 0:
            return expenses
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


def _payment_obligation_kind(payment):
    """Which supplier payable an existing voucher belongs to (A3)."""
    kind = (getattr(payment, 'payment_kind', None) or '').strip().upper()
    if getattr(payment, 'grn_charge_id', None) or kind == 'GRN_CHARGE':
        return OBLIGATION_CHARGE
    if kind == 'GRN_EXPENSES':
        return OBLIGATION_EXPENSES
    return OBLIGATION_MATERIAL


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
    is_supplier = obligation['kind'] in (OBLIGATION_SUPPLIER, OBLIGATION_MATERIAL,
                                         OBLIGATION_EXPENSES)
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
    # Material and supplier-billed expenses are paid separately (A3).  The
    # remaining figure comes from the same allocation that renders the screen,
    # so an amount the operator was allowed to enter can never bounce, and a
    # material voucher can never consume an expense payable.
    if is_supplier:
        remaining = int(obligation['remaining_minor'])
        if not created and (payment.payment_kind or '') in ('GRN_MATERIAL', 'GRN_EXPENSES',
                                                            'ADVANCE', ''):
            # Editing an existing supplier voucher: its own money is available
            # again, but only inside the payable it belongs to.
            if _payment_obligation_kind(payment) == obligation['kind']:
                remaining += _payment_minor(payment)
    else:
        # Every expense has its own payable.  The open amount is already net of
        # any supplier-side payment that settled the same expense, so paying the
        # recipient and paying the supplier can never pay one expense twice.
        remaining = int(obligation['remaining_minor'])
        if not created and _payment_obligation_kind(payment) == OBLIGATION_CHARGE \
                and getattr(payment, 'grn_charge_id', None) == charge.id:
            # Editing this very voucher: its own money is available again.
            remaining += _payment_minor(payment)
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
        grn_charge_id = None
        payment_kind = PAYMENT_KIND_BY_OBLIGATION.get(obligation['kind'], 'GRN_MATERIAL')
        if obligation['kind'] == OBLIGATION_SUPPLIER:
            # The legacy lumped voucher pays the supplier bill in one go.  Book
            # it against whichever part is still open (material first) so that
            # editing it later never re-opens an already settled expense.
            material_left = (int(obligation['material_original_minor'])
                             - supplier_obligation_paid_minor(grn, OBLIGATION_MATERIAL))
            if material_left <= 0:
                payment_kind = 'GRN_EXPENSES'
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
    if allow_advance and amount_minor > remaining and created:
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


# =========================================================================
#  One shared entry point for EVERY "pay a supplier" screen
# =========================================================================
#  Accounts -> Pay Supplier and the supplier ledger used to post a free-floating
#  SupplierPayment that no GRN knew about: the supplier ledger dropped, but
#  every GRN stayed "Unpaid" and Pay GRN Expenses still demanded the money again.
#  These helpers resolve the *same* GRN obligations so one payment settles one
#  payable exactly once, whichever screen the operator used.

OPEN_OBLIGATION_STATUSES = ('Unpaid', 'Partially Paid')


def open_supplier_obligations(supplier_id=None, *, grn_id=None, include_advance=False):
    """Every open supplier payable (material / GRN expenses / advance first).

    One row per open obligation, oldest first, carrying the exact remaining
    amount from :func:`grn_costing.grn_breakdown` — the same figure the GRN
    page and the supplier ledger show.
    """
    query = GRN.query.filter(
        GRN.is_void == False,  # noqa: E712
        GRN.is_cancelled == False,  # noqa: E712
    )
    if grn_id:
        query = query.filter(GRN.id == int(grn_id))
    if supplier_id:
        supplier = db.session.get(Supplier, int(supplier_id))
        if supplier is None:
            return []
        query = query.filter(or_(GRN.supplier_id == supplier.id,
                                 func.lower(func.trim(GRN.supplier)) == (supplier.name or '').strip().lower()))
    rows = []
    for grn in query.order_by(GRN.date_posted.asc(), GRN.id.asc()).all():
        breakdown = grn_breakdown(grn)
        for obligation in breakdown['obligations']:
            if obligation['kind'] not in (OBLIGATION_MATERIAL, OBLIGATION_EXPENSES):
                continue
            if include_advance and obligation['kind'] == OBLIGATION_EXPENSES:
                # Stock comes first; an expense voucher may only be created once
                # the material payable is closed (or there is no material at all).
                material_open = any(
                    o['kind'] == OBLIGATION_MATERIAL and o['remaining_minor'] > 0
                    for o in breakdown['obligations']
                )
                if material_open:
                    continue
            if obligation['remaining_minor'] <= 0:
                continue
            rows.append({
                'grn': grn,
                'breakdown': breakdown,
                'obligation': obligation,
                'key': obligation['key'],
                'label': obligation['label'],
                'detail': obligation['hint'],
                'original': obligation['original'],
                'paid': obligation['paid'],
                'remaining': obligation['remaining'],
                'remaining_minor': obligation['remaining_minor'],
                'supplier_name': breakdown['supplier'],
                'supplier_id': breakdown['supplier_id'],
                'bill_ref': breakdown['bill_ref'],
                'date_posted': getattr(grn, 'date_posted', None),
                'kind': obligation['kind'],
            })
    return rows


def supplier_open_obligation_options(supplier_id):
    """Ready-to-render rows for a supplier (Pay Supplier page / ledger)."""
    return [
        {
            'key': row['key'],
            'grn_id': row['grn'].id,
            'bill_ref': row['bill_ref'],
            'label': row['label'],
            'detail': row['detail'],
            'remaining': row['remaining'],
            'paid': row['paid'],
            'original': row['original'],
            'kind': row['kind'],
            'date_posted': row['date_posted'],
            'date_label': row['date_posted'].strftime('%d/%b/%Y') if row['date_posted'] else '',
        }
        for row in open_supplier_obligations(supplier_id)
    ]


def supplier_open_obligation_total(supplier_id):
    return sum(row['remaining_minor'] for row in open_supplier_obligations(supplier_id)) / 100.0


def post_supplier_payment(
    *, supplier_id, amount, method='Cash', payment_account_id=None,
    date_posted=None, reference='', note='', manual_bill_no='', actor=None,
    idempotency_key=None, expected_revision=None, payment_id=None, grn_id=None,
    obligation_key=None, allow_advance=False,
):
    """Route a supplier payment through the ONE GRN payment engine.

    * a chosen ``obligation_key`` (or ``grn_id``) is paid as that exact
      obligation;
    * otherwise the amount is applied oldest-first across the supplier's open
      obligations, one voucher per obligation, so nothing is overpaid and no
      GRN is left looking unpaid.

    Returns ``(payments, created_any)``.  The caller owns the commit.
    """
    from decimal import Decimal as _D
    from app.services.payments_crud import _normalise_method, _normalise_key

    amount_minor = to_minor(amount, field='Payment amount')
    if amount_minor <= 0:
        raise ValueError('Payment amount must be greater than zero.')
    normal_method = _normalise_method(method)
    supplier = db.session.get(Supplier, int(supplier_id)) if supplier_id else None
    if supplier is None:
        raise ValueError('Supplier not found. Select a valid supplier.')
    # Validate the account/method pair once, before touching any GRN.
    account = db.session.get(Account, int(payment_account_id)) if payment_account_id else None
    _validate_account_for_method(account, normal_method)

    if obligation_key:
        parsed_kind, parsed_id = parse_obligation_key(obligation_key)
        if parsed_kind == OBLIGATION_CHARGE and parsed_id:
            payment, created = save_grn_payment(
                grn_id=grn_id, obligation_key=obligation_key, amount=from_minor(amount_minor),
                method=normal_method, payment_account_id=account.id,
                date_posted=date_posted, reference=reference, note=note, actor=actor,
                idempotency_key=_normalise_key(idempotency_key),
                payment_id=payment_id, expected_revision=expected_revision,
                allow_advance=allow_advance,
            )
            return [payment], created
        target = None
        for row in open_supplier_obligations(supplier.id, grn_id=grn_id):
            if row['key'] == obligation_key:
                target = row
                break
        if target is None:
            raise ValueError('That GRN payable is already settled or belongs to another supplier. '
                             'Reload the page and choose an open obligation.')
        payment, created = save_grn_payment(
            grn_id=target['grn'].id, obligation_key=target['key'],
            amount=from_minor(amount_minor), method=normal_method,
            payment_account_id=account.id, date_posted=date_posted,
            reference=reference, note=note or (f'Pay Supplier · {target["bill_ref"]} · {target["label"]}'),
            actor=actor, idempotency_key=_normalise_key(idempotency_key),
            payment_id=payment_id, expected_revision=expected_revision,
            allow_advance=allow_advance,
        )
        return [payment], created

    rows = open_supplier_obligations(supplier.id, grn_id=grn_id)
    if not rows:
        raise ValueError(
            'This supplier has no open GRN payable. A "Pay Supplier" voucher must settle a '
            'real GRN obligation — receive the stock on a GRN first, then pay it here.'
        )
    total_open = sum(r['remaining_minor'] for r in rows)
    if amount_minor > total_open and not allow_advance:
        raise ValueError(
            f'Payment {from_minor(amount_minor):,.2f} is more than the open GRN payable '
            f'{from_minor(total_open):,.2f}. Use a smaller amount or tick "Record extra as advance".'
        )
    left = amount_minor
    payments = []
    created_any = False
    for row in rows:
        if left <= 0:
            break
        slice_minor = min(left, row['remaining_minor'])
        if slice_minor <= 0:
            continue
        payment, created = save_grn_payment(
            grn_id=row['grn'].id, obligation_key=row['key'],
            amount=from_minor(slice_minor), method=normal_method,
            payment_account_id=account.id, date_posted=date_posted,
            reference=reference,
            note=note or f'Pay Supplier · {row["bill_ref"]} · {row["label"]}',
            actor=actor, idempotency_key=idempotency_key if len(rows) == 1 else None,
            allow_advance=False,
        )
        created_any = created_any or created
        payments.append(payment)
        left -= slice_minor
    if left > 0:
        if not allow_advance:
            raise ValueError('The payment could not be applied to an open obligation.')
        # Money above the open payables is a supplier ADVANCE, not a GRN
        # payment (A1): it is posted as its own voucher so the GRN keeps
        # showing exactly what was paid against it.
        from app.services.payments_crud import save_supplier_payment
        advance, created = save_supplier_payment(
            supplier_id=supplier.id, amount=from_minor(left), method=normal_method,
            payment_account_id=account.id, manual_bill_no=manual_bill_no,
            date_posted=date_posted,
            note=' '.join(x for x in [(note or '').strip(),
                                      f'Advance paid to {supplier.name} (above the open GRN payable)'] if x),
            actor=actor,
        )
        advance.payment_kind = 'ADVANCE'
        advance.recipient_type = 'SUPPLIER'
        advance.recipient_name = supplier.name
        created_any = created_any or created
        payments.append(advance)
    return payments, created_any


def save_grn_payment_expanded(**kwargs):
    """Post one operator amount against a GRN, honouring the legacy lumped key.

    ``save_grn_payment`` writes exactly one payment for exactly one obligation.
    Older screens/links send ``SUPPLIER:<id>`` meaning "the whole supplier
    bill", so that amount is split here: stock first, then the supplier-billed
    expenses, each as its own voucher (A3).  Every other key is passed through
    unchanged.
    """
    grn = db.session.get(GRN, int(kwargs.get('grn_id'))) if kwargs.get('grn_id') else None
    kind, _ = parse_obligation_key(kwargs.get('obligation_key'))
    if grn is None or kind != OBLIGATION_SUPPLIER:
        return [save_grn_payment(**kwargs)]
    amount_minor = to_minor(kwargs.get('amount', 0), field='Payment amount')
    breakdown = grn_breakdown(grn)
    targets = [o for o in breakdown['obligations']
               if o['kind'] in (OBLIGATION_MATERIAL, OBLIGATION_EXPENSES) and o['remaining_minor'] > 0]
    if not targets:
        raise ValueError('This GRN has no open supplier payable left to pay.')
    payments = []
    left = amount_minor
    for obligation in targets:
        if left <= 0:
            break
        share = min(left, obligation['remaining_minor'])
        base = dict(kwargs)
        base['obligation_key'] = obligation['key']
        base['amount'] = from_minor(share)
        if payments:
            base['idempotency_key'] = None
        payments.append(save_grn_payment(**base))
        left -= share
    if left > 0 and not kwargs.get('allow_advance'):
        raise ValueError(
            f'Payment {from_minor(amount_minor):,.2f} exceeds the open supplier payable '
            f'for this GRN. Use a smaller amount or allow an advance.'
        )
    if left > 0:
        base = dict(kwargs)
        base['obligation_key'] = targets[-1]['key']
        base['amount'] = from_minor(left)
        base['idempotency_key'] = None
        base['allow_advance'] = True
        payments.append(save_grn_payment(**base))
    return payments


def pay_grn_payable_for_supplier(
    *, supplier_id, grn_id, obligation_key, amount, method='Cash',
    payment_account_id=None, date_posted=None, reference='', note='', actor=None,
    idempotency_key=None,
):
    """Convenience wrapper used by the ledger / GRN screens."""
    return post_supplier_payment(
        supplier_id=supplier_id, grn_id=grn_id, obligation_key=obligation_key,
        amount=amount, method=method, payment_account_id=payment_account_id,
        date_posted=date_posted, reference=reference, note=note, actor=actor,
        idempotency_key=idempotency_key,
    )


__all__ = [
    'grn_payment_obligations', 'save_grn_payment', 'void_grn_payment',
    'restore_grn_payment', 'grn_payment_integrity',
    'open_supplier_obligations', 'supplier_open_obligation_options',
    'supplier_open_obligation_total', 'post_supplier_payment',
    'pay_grn_payable_for_supplier', 'save_grn_payment_expanded',
]
