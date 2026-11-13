"""Principal-only loan register with auditable cash/bank ledger links."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func

from models import Account, AccountTransaction, CashFlowEntry, LoanMovement, LoanParty, db
from utils.money import from_minor, to_minor
from app.services.time_money import pk_now

LOAN_SOURCE_TYPE = 'LoanPrincipal'


def _actor_name(actor) -> str:
    return str(getattr(actor, 'username', None) or actor or 'System')[:80]


def _parse_date_only(value, *, field: str = 'Date') -> date | None:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError as exc:
        raise ValueError(f'Enter a valid {field.lower()} (YYYY-MM-DD).') from exc


def _party_snapshot(party: LoanParty) -> dict:
    return {
        'id': party.id,
        'name': party.name,
        'note': party.note or '',
        'opening_principal_minor': int(party.opening_principal_minor or 0),
        'opening_principal_date': (
            party.opening_principal_date.isoformat()
            if party.opening_principal_date else None
        ),
        'is_active': bool(party.is_active),
    }


def _movement_snapshot(movement: LoanMovement) -> dict:
    return {
        'id': movement.id,
        'loan_party_id': movement.loan_party_id,
        'movement_type': movement.movement_type,
        'amount_minor': int(movement.amount_minor or 0),
        'cash_account_id': movement.cash_account_id,
        'account_tx_id': movement.account_tx_id,
        'date_posted': movement.date_posted.isoformat() if movement.date_posted else None,
        'reference': movement.reference or '',
        'note': movement.note or '',
    }


def _build_tx_description(movement_type: str, party_name: str) -> str:
    if movement_type == 'received':
        return f'Loan principal received from {party_name}'
    return f'Loan principal repaid to {party_name}'


def _build_tx_note(reference: str | None, note: str | None) -> str:
    ref = (reference or '').strip()
    nt = (note or '').strip()
    if ref and nt:
        return f'{ref} — {nt}'
    return nt or ref or ''


def _validate_cash_account(account: Account | None, *, allow_inactive: bool = False) -> Account:
    from app.services.system_accounts import is_legacy_loan_account, is_reserved_account
    if (
        account is None
        or (not account.is_active and not allow_inactive)
        or (account.category or '').strip().lower() not in ('cash', 'bank')
        or is_legacy_loan_account(account)
        or is_reserved_account(account)
    ):
        raise ValueError('Select an active company cash or bank account.')
    return account


def _tx_account_deltas(tx: AccountTransaction | None) -> dict[int, int]:
    """Return signed minor-unit effect per account for an active AccountTransaction."""
    if tx is None or bool(getattr(tx, 'is_void', False)):
        return {}
    from app.services.accounting import _tx_minor
    amt = _tx_minor(tx)
    deltas: dict[int, int] = {}
    if getattr(tx, 'to_account_id', None):
        deltas[int(tx.to_account_id)] = deltas.get(int(tx.to_account_id), 0) + amt
    if getattr(tx, 'from_account_id', None):
        deltas[int(tx.from_account_id)] = deltas.get(int(tx.from_account_id), 0) - amt
    return deltas


def _party_movement_totals(loan_party_id: int) -> tuple[int, int]:
    received = int(
        db.session.query(func.coalesce(func.sum(LoanMovement.amount_minor), 0)).filter_by(
            loan_party_id=loan_party_id, movement_type='received'
        ).scalar() or 0
    )
    repaid = int(
        db.session.query(func.coalesce(func.sum(LoanMovement.amount_minor), 0)).filter_by(
            loan_party_id=loan_party_id, movement_type='repaid'
        ).scalar() or 0
    )
    return received, repaid


def outstanding_minor(loan_party_id: int) -> int:
    """Principal borrowed less principal repaid; interest is not part of this register."""
    received, repaid = _party_movement_totals(loan_party_id)
    party = db.session.get(LoanParty, loan_party_id)
    opening = int(getattr(party, 'opening_principal_minor', 0) or 0) if party else 0
    return opening + received - repaid


def update_loan_party(
    *,
    loan_party_id: int,
    name: str,
    opening_principal=0,
    opening_date=None,
    note: str = '',
    is_active=None,
    actor=None,
) -> LoanParty:
    """Edit a lender's details while protecting principal balance & movement date invariants."""
    party = db.session.get(LoanParty, loan_party_id) if loan_party_id else None
    if party is None:
        raise ValueError('Lender not found.')

    clean_name = (name or '').strip()
    if not clean_name:
        raise ValueError('Lender name is required.')
    clean_name = clean_name[:160]

    duplicate = LoanParty.query.filter(
        func.lower(func.trim(LoanParty.name)) == clean_name.lower(),
        LoanParty.id != party.id,
    ).first()
    if duplicate:
        raise ValueError(f"Another lender named '{duplicate.name}' already exists.")

    opening_minor = to_minor(
        opening_principal if opening_principal not in (None, '') else 0,
        field='Opening principal',
    )
    if opening_minor < 0:
        raise ValueError('Opening principal cannot be negative.')

    parsed_opening_date = _parse_date_only(opening_date, field='Opening balance date')
    if opening_minor > 0 and parsed_opening_date is None:
        raise ValueError('Enter the date for the opening principal balance.')

    received, repaid = _party_movement_totals(party.id)
    if opening_minor + received - repaid < 0:
        min_opening = max(0, repaid - received)
        raise ValueError(
            f'Opening principal cannot be less than Rs. {from_minor(min_opening):,.2f} '
            f'because Rs. {from_minor(repaid):,.2f} has already been repaid '
            f'against Rs. {from_minor(received):,.2f} received.'
        )

    if parsed_opening_date is not None:
        earliest = db.session.query(func.min(LoanMovement.date_posted)).filter_by(
            loan_party_id=party.id
        ).scalar()
        if earliest is not None:
            earliest_date = earliest.date() if isinstance(earliest, datetime) else earliest
            if parsed_opening_date > earliest_date:
                raise ValueError(
                    f'Opening balance date cannot be later than existing movement on '
                    f'{earliest_date:%Y-%m-%d}.'
                )

    before = _party_snapshot(party)
    old_name = party.name

    party.name = clean_name
    party.opening_principal_minor = opening_minor
    party.opening_principal_date = parsed_opening_date
    party.note = (note or '').strip()[:500] or None
    if is_active is not None:
        party.is_active = bool(is_active)

    if clean_name != old_name:
        for movement in party.movements.all():
            if movement.account_tx_id:
                tx = db.session.get(AccountTransaction, movement.account_tx_id)
                if tx is not None:
                    tx.party_name = clean_name
                    tx.description = _build_tx_description(movement.movement_type, clean_name)

    after = _party_snapshot(party)
    from utils.accounting_audit import record_accounting_audit
    record_accounting_audit(
        actor,
        action='Edit',
        entity_type='LoanParty',
        entity_id=party.id,
        before=before,
        after=after,
        amount_before=float(from_minor(before['opening_principal_minor'])),
        amount_after=float(from_minor(opening_minor)),
        party_before_id=party.id,
        party_after_id=party.id,
        reason=party.note or 'Lender updated in the loan register',
    )
    db.session.flush()
    return party


def toggle_loan_party(loan_party_id: int, actor=None) -> LoanParty:
    """Activate or deactivate a lender without altering historical movements."""
    party = db.session.get(LoanParty, loan_party_id) if loan_party_id else None
    if party is None:
        raise ValueError('Lender not found.')
    before = _party_snapshot(party)
    party.is_active = not bool(party.is_active)
    after = _party_snapshot(party)
    from utils.accounting_audit import record_accounting_audit
    record_accounting_audit(
        actor,
        action='Activate' if party.is_active else 'Suspend',
        entity_type='LoanParty',
        entity_id=party.id,
        before=before,
        after=after,
        party_before_id=party.id,
        party_after_id=party.id,
        reason='Lender status toggled in the loan register',
    )
    db.session.flush()
    return party


def delete_loan_party(loan_party_id: int, actor=None) -> dict:
    """Hard-delete a lender that has no recorded principal movements."""
    party = db.session.get(LoanParty, loan_party_id) if loan_party_id else None
    if party is None:
        raise ValueError('Lender not found.')

    movement_count = LoanMovement.query.filter_by(loan_party_id=party.id).count()
    if movement_count > 0:
        raise ValueError(
            f"Lender '{party.name}' has {movement_count} recorded principal movement(s) "
            "and cannot be deleted. Delete those movements first or deactivate the lender."
        )

    before = _party_snapshot(party)
    from utils.accounting_audit import record_accounting_audit
    record_accounting_audit(
        actor,
        action='Delete',
        entity_type='LoanParty',
        entity_id=party.id,
        before=before,
        after={'deleted': True},
        amount_before=float(from_minor(before['opening_principal_minor'])),
        amount_after=0,
        party_before_id=party.id,
        reason='Lender deleted from the loan register',
    )
    db.session.delete(party)
    db.session.flush()
    return before


def record_principal_movement(*, loan_party_id, movement_type, amount, cash_account_id,
                              date_posted=None, reference='', note='', idempotency_key=None,
                              actor=None):
    """Save one principal event and exactly one matching cash/bank ledger movement."""
    movement_type = (movement_type or '').strip().lower()
    if movement_type not in ('received', 'repaid'):
        raise ValueError('Choose whether principal was received or repaid.')
    amount_minor = to_minor(amount, field='Principal amount')
    if amount_minor <= 0:
        raise ValueError('Principal amount must be greater than zero.')
    party = db.session.get(LoanParty, loan_party_id) if loan_party_id else None
    if party is None or not party.is_active:
        raise ValueError('Select an active lender.')
    account = _validate_cash_account(
        db.session.get(Account, cash_account_id) if cash_account_id else None
    )
    posted = date_posted or pk_now()
    if not isinstance(posted, datetime):
        raise ValueError('A valid posting date is required.')
    if party.opening_principal_date and posted.date() < party.opening_principal_date:
        raise ValueError('Movement date cannot be earlier than the lender opening balance date.')

    key = (idempotency_key or '').strip()[:64] or None
    if key:
        replay = LoanMovement.query.filter_by(idempotency_key=key).first()
        if replay:
            return replay, False

    if movement_type == 'repaid':
        if outstanding_minor(party.id) < amount_minor:
            raise ValueError('Repayment cannot be greater than the outstanding loan principal.')
        from app.services.accounting import _account_minor
        if _account_minor(account) < amount_minor:
            raise ValueError('Insufficient balance in the selected cash or bank account.')

    from app.services.payments_crud import _assert_day_open, _assert_period_open
    _assert_period_open(account.id, posted, operation='recorded')
    _assert_day_open(account.id, posted, operation='recorded')

    actor_str = _actor_name(actor)
    movement = LoanMovement(
        loan_party_id=party.id,
        movement_type=movement_type,
        amount_minor=amount_minor,
        cash_account_id=account.id,
        date_posted=posted,
        reference=(reference or '').strip()[:100] or None,
        note=(note or '').strip()[:500] or None,
        idempotency_key=key,
        created_by=actor_str,
    )
    db.session.add(movement)
    db.session.flush()

    amount_value = float(from_minor(amount_minor))
    received = movement_type == 'received'
    tx = AccountTransaction(
        from_account_id=None if received else account.id,
        to_account_id=account.id if received else None,
        amount=amount_value,
        amount_minor=amount_minor,
        description=_build_tx_description(movement_type, party.name),
        note=_build_tx_note(movement.reference, movement.note),
        transaction_type='Receipt' if received else 'Payment',
        source_type=LOAN_SOURCE_TYPE,
        source_id=movement.id,
        idempotency_key=key,
        created_by=actor_str,
        date_posted=posted,
        party_type='loan_lender',
        party_id=party.id,
        party_name=party.name,
    )
    db.session.add(tx)
    db.session.flush()
    from app.services.accounting import _apply_account_tx_effect
    _apply_account_tx_effect(tx)
    movement.account_tx_id = tx.id

    from utils.accounting_audit import record_accounting_audit
    record_accounting_audit(
        actor, action='Create', entity_type='LoanMovement', entity_id=movement.id,
        after={
            'loan_party_id': party.id, 'movement_type': movement_type,
            'amount_minor': amount_minor, 'cash_account_id': account.id,
            'account_tx_id': tx.id, 'reference': movement.reference,
        }, amount_after=amount_value,
        account_after_id=account.id, party_after_id=party.id,
        reason=movement.note or f'Loan principal {movement_type}',
    )
    return movement, True


def update_principal_movement(
    *,
    movement_id: int,
    loan_party_id: int,
    movement_type: str,
    amount,
    cash_account_id: int,
    date_posted=None,
    reference: str = '',
    note: str = '',
    actor=None,
) -> LoanMovement:
    """Edit an existing principal movement and synchronize its cash/bank ledger entry."""
    movement = db.session.get(LoanMovement, movement_id) if movement_id else None
    if movement is None:
        raise ValueError('Loan movement not found.')

    movement_type = (movement_type or '').strip().lower()
    if movement_type not in ('received', 'repaid'):
        raise ValueError('Choose whether principal was received or repaid.')

    amount_minor = to_minor(amount, field='Principal amount')
    if amount_minor <= 0:
        raise ValueError('Principal amount must be greater than zero.')

    old_party_id = movement.loan_party_id
    old_type = movement.movement_type
    old_amount_minor = int(movement.amount_minor)
    old_account_id = movement.cash_account_id
    old_posted = movement.date_posted
    old_tx = (
        db.session.get(AccountTransaction, movement.account_tx_id)
        if movement.account_tx_id else None
    )

    party = db.session.get(LoanParty, loan_party_id) if loan_party_id else None
    if party is None:
        raise ValueError('Select a valid lender.')
    if not party.is_active and party.id != old_party_id:
        raise ValueError('Select an active lender.')

    account = _validate_cash_account(
        db.session.get(Account, cash_account_id) if cash_account_id else None,
        allow_inactive=(cash_account_id == old_account_id),
    )

    posted = date_posted or old_posted or pk_now()
    if not isinstance(posted, datetime):
        raise ValueError('A valid posting date is required.')
    if party.opening_principal_date and posted.date() < party.opening_principal_date:
        raise ValueError('Movement date cannot be earlier than the lender opening balance date.')

    # 1. Lender outstanding principal invariant (must stay >= 0 for old & new lenders)
    old_party_delta = old_amount_minor if old_type == 'received' else -old_amount_minor
    new_party_delta = amount_minor if movement_type == 'received' else -amount_minor
    if party.id == old_party_id:
        projected_outstanding = outstanding_minor(party.id) - old_party_delta + new_party_delta
        if projected_outstanding < 0:
            if movement_type == 'repaid':
                raise ValueError('Repayment cannot be greater than the outstanding loan principal.')
            raise ValueError(
                'Cannot reduce this received loan amount because existing repayments '
                'exceed the remaining borrowed principal.'
            )
    else:
        if outstanding_minor(old_party_id) - old_party_delta < 0:
            raise ValueError(
                'Cannot move this received loan to another lender because existing '
                'repayments on the original lender depend on it.'
            )
        if outstanding_minor(party.id) + new_party_delta < 0:
            raise ValueError('Repayment cannot be greater than the outstanding loan principal.')

    # 2. Cash/bank balance invariant across all affected accounts
    from app.services.accounting import (
        _account_minor,
        _apply_account_tx_effect,
        _reverse_account_tx_effect,
    )
    net_by_account: dict[int, int] = {}
    for acc_id, applied_delta in _tx_account_deltas(old_tx).items():
        net_by_account[acc_id] = net_by_account.get(acc_id, 0) - applied_delta
    new_cash_delta = amount_minor if movement_type == 'received' else -amount_minor
    net_by_account[account.id] = net_by_account.get(account.id, 0) + new_cash_delta

    for acc_id, net_delta in net_by_account.items():
        if net_delta < 0:
            target_acc = db.session.get(Account, acc_id)
            if target_acc and _account_minor(target_acc) + net_delta < 0:
                raise ValueError(
                    f"Insufficient balance in '{target_acc.name}' for this adjustment."
                )

    # 3. Reconciled period & locked cash-day guards when accounting fields change
    accounting_changed = any((
        old_party_id != party.id,
        old_type != movement_type,
        old_amount_minor != amount_minor,
        old_account_id != account.id,
        old_posted != posted,
    ))
    if accounting_changed:
        from app.services.payments_crud import _assert_day_open, _assert_period_open
        for acc_id in {old_account_id, *(_tx_account_deltas(old_tx).keys())}:
            _assert_period_open(acc_id, old_posted, operation='edited')
            _assert_day_open(acc_id, old_posted, operation='edited')
        if account.id != old_account_id or posted != old_posted:
            _assert_period_open(account.id, posted, operation='posted')
            _assert_day_open(account.id, posted, operation='posted')

    before = _movement_snapshot(movement)

    if old_tx is not None and not old_tx.is_void:
        _reverse_account_tx_effect(old_tx)

    movement.loan_party_id = party.id
    movement.movement_type = movement_type
    movement.amount_minor = amount_minor
    movement.cash_account_id = account.id
    movement.date_posted = posted
    movement.reference = (reference or '').strip()[:100] or None
    movement.note = (note or '').strip()[:500] or None

    amount_value = float(from_minor(amount_minor))
    received = movement_type == 'received'
    tx_desc = _build_tx_description(movement_type, party.name)
    tx_note = _build_tx_note(movement.reference, movement.note)

    if old_tx is not None:
        tx = old_tx
        tx.from_account_id = None if received else account.id
        tx.to_account_id = account.id if received else None
        tx.amount = amount_value
        tx.amount_minor = amount_minor
        tx.description = tx_desc
        tx.note = tx_note
        tx.transaction_type = 'Receipt' if received else 'Payment'
        tx.source_type = LOAN_SOURCE_TYPE
        tx.source_id = movement.id
        tx.date_posted = posted
        tx.party_type = 'loan_lender'
        tx.party_id = party.id
        tx.party_name = party.name
        tx.is_void = False
        tx.voided_by = None
        tx.voided_at = None
    else:
        tx = AccountTransaction(
            from_account_id=None if received else account.id,
            to_account_id=account.id if received else None,
            amount=amount_value,
            amount_minor=amount_minor,
            description=tx_desc,
            note=tx_note,
            transaction_type='Receipt' if received else 'Payment',
            source_type=LOAN_SOURCE_TYPE,
            source_id=movement.id,
            created_by=_actor_name(actor),
            date_posted=posted,
            party_type='loan_lender',
            party_id=party.id,
            party_name=party.name,
        )
        db.session.add(tx)
        db.session.flush()
        movement.account_tx_id = tx.id

    _apply_account_tx_effect(tx)

    after = _movement_snapshot(movement)
    from utils.accounting_audit import record_accounting_audit
    record_accounting_audit(
        actor,
        action='Edit',
        entity_type='LoanMovement',
        entity_id=movement.id,
        before=before,
        after=after,
        amount_before=float(from_minor(before['amount_minor'])),
        amount_after=amount_value,
        account_before_id=before['cash_account_id'],
        account_after_id=account.id,
        party_before_id=before['loan_party_id'],
        party_after_id=party.id,
        reason=movement.note or f'Loan principal {movement_type} updated',
    )
    db.session.flush()
    return movement


def delete_principal_movement(*, movement_id: int, reason: str = '', actor=None) -> dict:
    """Reverse cash/bank effects and hard-delete a loan movement and its ledger row."""
    movement = db.session.get(LoanMovement, movement_id) if movement_id else None
    if movement is None:
        raise ValueError('Loan movement not found.')

    tx = (
        db.session.get(AccountTransaction, movement.account_tx_id)
        if movement.account_tx_id else None
    )
    linked_txs: list[AccountTransaction] = []
    if tx is not None:
        linked_txs.append(tx)
    for extra_tx in AccountTransaction.query.filter_by(
        source_type=LOAN_SOURCE_TYPE, source_id=movement.id
    ).all():
        if extra_tx not in linked_txs:
            linked_txs.append(extra_tx)

    from app.services.payments_crud import _assert_day_open, _assert_period_open
    affected_accounts = {movement.cash_account_id}
    for ltx in linked_txs:
        affected_accounts.update(_tx_account_deltas(ltx).keys())
    for acc_id in affected_accounts:
        _assert_period_open(acc_id, movement.date_posted, operation='deleted')
        _assert_day_open(acc_id, movement.date_posted, operation='deleted')

    if movement.movement_type == 'received':
        remaining = outstanding_minor(movement.loan_party_id) - int(movement.amount_minor)
        if remaining < 0:
            raise ValueError(
                f'Cannot delete this received loan of Rs. {from_minor(movement.amount_minor):,.2f} '
                f'because Rs. {from_minor(abs(remaining)):,.2f} of repayments would exceed '
                'the remaining borrowed principal. Edit or delete the repayment(s) first.'
            )

    from app.services.accounting import _account_minor, _reverse_account_tx_effect
    reversal_by_account: dict[int, int] = {}
    for ltx in linked_txs:
        for acc_id, applied_delta in _tx_account_deltas(ltx).items():
            reversal_by_account[acc_id] = reversal_by_account.get(acc_id, 0) - applied_delta

    for acc_id, rev_delta in reversal_by_account.items():
        if rev_delta < 0:
            acc = db.session.get(Account, acc_id)
            if acc and _account_minor(acc) + rev_delta < 0:
                raise ValueError(
                    f"Cannot delete this loan receipt because '{acc.name}' only has "
                    f'Rs. {from_minor(_account_minor(acc)):,.2f} available.'
                )

    before = _movement_snapshot(movement)

    for ltx in linked_txs:
        if not ltx.is_void:
            _reverse_account_tx_effect(ltx)

    # Delete LoanMovement first (holds FK account_tx_id -> account_transaction.id).
    db.session.delete(movement)
    db.session.flush()

    for ltx in linked_txs:
        CashFlowEntry.query.filter_by(account_tx_id=ltx.id).update(
            {'account_tx_id': None}, synchronize_session=False
        )
        db.session.delete(ltx)

    from utils.accounting_audit import record_accounting_audit
    record_accounting_audit(
        actor,
        action='Delete',
        entity_type='LoanMovement',
        entity_id=before['id'],
        before=before,
        after={'deleted': True},
        amount_before=float(from_minor(before['amount_minor'])),
        amount_after=0,
        account_before_id=before['cash_account_id'],
        party_before_id=before['loan_party_id'],
        reason=(reason or '').strip() or before['note'] or f"Loan principal {before['movement_type']} deleted",
    )
    db.session.flush()
    return before
