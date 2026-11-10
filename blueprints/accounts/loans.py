"""Dedicated lender register for principal-only borrowing and repayments."""
from datetime import datetime
from uuid import uuid4

from ._common import *  # noqa
from .helpers import _company_accounts
from app.services.loan_register import record_principal_movement


@accounts_bp.route('/loans')
@login_required
def loan_register():
    parties = LoanParty.query.order_by(LoanParty.is_active.desc(), LoanParty.name.asc()).all()
    movements = LoanMovement.query.order_by(LoanMovement.date_posted.desc(), LoanMovement.id.desc()).limit(300).all()
    totals = {}
    for party in parties:
        totals[party.id] = int(party.opening_principal_minor or 0) + sum(
            int(m.amount_minor or 0) * (1 if m.movement_type == 'received' else -1)
            for m in party.movements.all()
        )
    # Only company cash/bank accounts can fund a loan movement.  Lenders are
    # outsider parties and never appear as either side of a company transfer.
    cash_accounts = [a for a in _company_accounts()
                     if (a.category or '').strip().lower() in ('cash', 'bank')]
    return render_template(
        'accounts/loan_register.html', parties=parties, movements=movements,
        outstanding_minor=totals, cash_accounts=cash_accounts,
        idempotency_key=uuid4().hex,
        today=pk_today().strftime('%Y-%m-%d'),
    )


@accounts_bp.route('/loans/parties/add', methods=['POST'])
@login_required
def add_loan_party():
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('Lender name is required.', 'danger')
        return redirect(url_for('accounts.loan_register'))
    existing = LoanParty.query.filter(func.lower(func.trim(LoanParty.name)) == name.lower()).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
        db.session.commit()
        flash('That lender already exists; the existing register was reactivated.', 'info')
        return redirect(url_for('accounts.loan_register'))
    from utils.money import to_minor
    try:
        opening_minor = to_minor(request.form.get('opening_principal') or 0, field='Opening principal')
        if opening_minor < 0:
            raise ValueError('Opening principal cannot be negative.')
        opening_raw = (request.form.get('opening_date') or '').strip()
        opening_date = datetime.strptime(opening_raw, '%Y-%m-%d').date() if opening_raw else None
        if opening_minor > 0 and opening_date is None:
            raise ValueError('Enter the date for the opening principal balance.')
    except (TypeError, ValueError) as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('accounts.loan_register'))
    party = LoanParty(
        name=name[:160], note=(request.form.get('note') or '').strip()[:500] or None,
        opening_principal_minor=opening_minor, opening_principal_date=opening_date,
        is_active=True, created_by=getattr(current_user, 'username', None),
    )
    db.session.add(party)
    db.session.flush()
    from utils.accounting_audit import record_accounting_audit
    record_accounting_audit(
        current_user, action='Create', entity_type='LoanParty', entity_id=party.id,
        after={'name': party.name, 'opening_principal_minor': opening_minor,
               'opening_principal_date': opening_date.isoformat() if opening_date else None},
        amount_after=opening_minor / 100, party_after_id=party.id,
        reason=party.note or 'Opening principal carried into the loan register',
    )
    db.session.commit()
    audit_log(current_user, 'loan.party.create', f'name={name[:160]}, opening_principal_minor={opening_minor}')
    flash('Lender added to the loan register.', 'success')
    return redirect(url_for('accounts.loan_register'))


@accounts_bp.route('/loans/movements/add', methods=['POST'])
@login_required
def add_loan_movement():
    try:
        date_raw = (request.form.get('date_posted') or '').strip()
        posted = datetime.strptime(date_raw, '%Y-%m-%d') if date_raw else pk_now()
        movement, created = record_principal_movement(
            loan_party_id=request.form.get('loan_party_id', type=int),
            movement_type=request.form.get('movement_type'),
            amount=request.form.get('amount'),
            cash_account_id=request.form.get('cash_account_id', type=int),
            date_posted=posted,
            reference=request.form.get('reference'),
            note=request.form.get('note'),
            idempotency_key=request.form.get('idempotency_key'),
            actor=current_user,
        )
        db.session.commit()
        flash('Loan principal movement recorded.' if created else 'This loan movement was already recorded.',
              'success' if created else 'info')
    except (TypeError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc) or 'Unable to record this loan movement.', 'danger')
    except Exception:
        db.session.rollback()
        logger.exception('Loan register movement failed')
        flash('Unable to record the loan movement. No balance was changed.', 'danger')
    return redirect(url_for('accounts.loan_register'))
