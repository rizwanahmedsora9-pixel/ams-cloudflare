"""Principal-only loan register with auditable cash/bank ledger links."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func

from models import Account, AccountTransaction, LoanMovement, LoanParty, db
from utils.money import from_minor, to_minor
from app.services.time_money import pk_now

LOAN_SOURCE_TYPE = 'LoanPrincipal'


def outstanding_minor(loan_party_id: int) -> int:
    """Principal borrowed less principal repaid; interest is not part of this register."""
    received = db.session.query(func.coalesce(func.sum(LoanMovement.amount_minor), 0)).filter_by(
        loan_party_id=loan_party_id, movement_type='received'
    ).scalar() or 0
    repaid = db.session.query(func.coalesce(func.sum(LoanMovement.amount_minor), 0)).filter_by(
        loan_party_id=loan_party_id, movement_type='repaid'
    ).scalar() or 0
    party = db.session.get(LoanParty, loan_party_id)
    opening = int(getattr(party, 'opening_principal_minor', 0) or 0) if party else 0
    return opening + int(received) - int(repaid)


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
    party = db.session.get(LoanParty, loan_party_id)
    if party is None or not party.is_active:
        raise ValueError('Select an active lender.')
    account = db.session.get(Account, cash_account_id)
    from app.services.system_accounts import is_legacy_loan_account, is_reserved_account
    if (account is None or not account.is_active
            or (account.category or '').strip().lower() not in ('cash', 'bank')
            or is_legacy_loan_account(account) or is_reserved_account(account)):
        raise ValueError('Select an active company cash or bank account.')
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
        current_minor = int(account.balance_minor) if account.balance_minor is not None else to_minor(account.balance or 0)
        if current_minor < amount_minor:
            raise ValueError('Insufficient balance in the selected cash or bank account.')

    from app.services.payments_crud import _assert_period_open
    _assert_period_open(account.id, posted, operation='recorded')

    movement = LoanMovement(
        loan_party_id=party.id,
        movement_type=movement_type,
        amount_minor=amount_minor,
        cash_account_id=account.id,
        date_posted=posted,
        reference=(reference or '').strip()[:100] or None,
        note=(note or '').strip()[:500] or None,
        idempotency_key=key,
        created_by=str(getattr(actor, 'username', None) or actor or 'System')[:80],
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
        description=(f'Loan principal received from {party.name}' if received
                     else f'Loan principal repaid to {party.name}'),
        note=(f"{movement.reference} — {movement.note}" if movement.reference and movement.note
              else movement.note or movement.reference or ''),
        transaction_type='Receipt' if received else 'Payment',
        source_type=LOAN_SOURCE_TYPE,
        source_id=movement.id,
        idempotency_key=key,
        created_by=str(getattr(actor, 'username', None) or actor or 'System')[:80],
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
        }, amount_after=float(from_minor(amount_minor)),
        account_after_id=account.id, party_after_id=party.id,
        reason=movement.note or f'Loan principal {movement_type}',
    )
    return movement, True
