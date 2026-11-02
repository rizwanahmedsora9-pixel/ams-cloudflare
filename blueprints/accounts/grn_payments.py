"""PAY EXISTING GRN / GRN PAYMENT — the ONLY place purchase money is paid.

Owner rule A1: GRN entry never pays.  This page (and the "Make New
Transaction" modal's `grn_payment` target) is where full, partial and repeated
payments to the supplier, transporter, labourer or other charge recipient are
recorded, each linked to its original GRN and obligation.
"""
from ._common import *  # noqa
import secrets
from models import GRN, GRNCharge, SupplierPayment, CashFlowParty
from app.services.grn_costing import grn_breakdown
from app.services.grn_payments import (
    save_grn_payment, void_grn_payment, restore_grn_payment,
)


def _grn_payments_permission_ok():
    return (current_user.role in ('admin', 'root')
            or getattr(current_user, 'can_manage_payments', False)
            or getattr(current_user, 'can_manage_accounts', False))


def _grn_payment_accounts():
    return _active_accounts().filter(
        func.lower(func.trim(Account.category)).in_(['cash', 'bank'])
    ).order_by(Account.category.asc(), Account.name.asc(), Account.id.asc()).all()


@accounts_bp.route('/grn_payments', methods=['GET'])
@login_required
def grn_payments():
    """Select a GRN, see every obligation with paid/remaining, then pay."""
    selected_id = request.args.get('grn_id', type=int)
    selected_charge = request.args.get('charge_id', type=int)
    grns = GRN.query.filter(
        GRN.is_void == False,  # noqa: E712
        GRN.is_cancelled == False,  # noqa: E712
    ).order_by(GRN.date_posted.desc(), GRN.id.desc()).limit(500).all()
    selected = db.session.get(GRN, selected_id) if selected_id else None
    breakdown = grn_breakdown(selected) if selected else None
    selected_obligation = None
    if breakdown and selected_charge:
        for row in breakdown['obligations']:
            if row['charge_id'] == selected_charge:
                selected_obligation = row
                break
    if breakdown and selected_obligation is None and selected_charge is None:
        # default: the supplier material obligation
        selected_obligation = next(
            (r for r in breakdown['obligations'] if r['kind'] == 'SUPPLIER'), None)

    page_rows = []
    for g in grns:
        try:
            bd = grn_breakdown(g)
        except Exception:
            bd = None
        page_rows.append({
            'grn': g,
            'breakdown': bd,
        })

    return render_template(
        'accounts/grn_payments.html',
        page_rows=page_rows,
        selected=selected,
        breakdown=breakdown,
        selected_obligation=selected_obligation,
        accounts=_grn_payment_accounts(),
        parties=CashFlowParty.query.order_by(CashFlowParty.name.asc()).all(),
        today_date=pk_today().strftime('%Y-%m-%d'),
        submission_token=secrets.token_hex(8),
        can_edit=_grn_payments_permission_ok(),
    )


@accounts_bp.route('/grn_payments/save', methods=['POST'])
@login_required
def grn_payment_save():
    if not _grn_payments_permission_ok():
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.grn_payments'))
    grn_id = request.form.get('grn_id', type=int)
    try:
        payment, created = save_grn_payment(
            grn_id=grn_id,
            obligation_key=(request.form.get('obligation_key') or '').strip(),
            amount=request.form.get('amount', 0),
            method=request.form.get('method', 'Cash'),
            payment_account_id=request.form.get('payment_account_id'),
            date_posted=request.form.get('date_posted', ''),
            reference=(request.form.get('reference') or '').strip(),
            note=(request.form.get('note') or '').strip(),
            idempotency_key=(request.form.get('idempotency_key') or '').strip() or None,
            payment_id=request.form.get('payment_id', type=int),
            expected_revision=request.form.get('expected_revision'),
            allow_advance=bool(request.form.get('allow_advance')),
            actor=current_user,
        )
        db.session.commit()
        flash(f'GRN payment of Rs. {payment.amount:,.2f} recorded from Accounts.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception:
        db.session.rollback()
        logger.exception('GRN payment save failed')
        flash('Unable to save the GRN payment. Please check the details and try again.', 'danger')
    args = {'grn_id': grn_id} if grn_id else {}
    return redirect(url_for('accounts.grn_payments', **args))


@accounts_bp.route('/grn_payments/<int:payment_id>/void', methods=['POST'])
@login_required
def grn_payment_void(payment_id):
    if not _grn_payments_permission_ok():
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.grn_payments'))
    payment = db.session.get(SupplierPayment, payment_id)
    try:
        if void_grn_payment(payment, actor=current_user,
                            reason=(request.form.get('reason') or '').strip()):
            db.session.commit()
            flash('GRN payment voided. Cash and balances reversed; history preserved.', 'success')
        else:
            flash('Payment is already voided.', 'warning')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(url_for('accounts.grn_payments', grn_id=(payment.grn_id if payment else None)))


@accounts_bp.route('/grn_payments/<int:payment_id>/restore', methods=['POST'])
@login_required
def grn_payment_restore(payment_id):
    if not _grn_payments_permission_ok():
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.grn_payments'))
    payment = db.session.get(SupplierPayment, payment_id)
    try:
        if restore_grn_payment(payment, actor=current_user):
            db.session.commit()
            flash('GRN payment restored. Balances re-applied.', 'success')
        else:
            flash('Payment is already active.', 'warning')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(url_for('accounts.grn_payments', grn_id=(payment.grn_id if payment else None)))


@accounts_bp.route('/api/grn_obligations/<int:grn_id>')
@login_required
def grn_obligations_api(grn_id):
    grn = db.session.get(GRN, grn_id)
    if not grn:
        return jsonify({'ok': False, 'error': 'GRN not found'}), 404
    bd = grn_breakdown(grn)
    return jsonify({
        'ok': True,
        'grn': {'id': grn.id, 'bill_ref': bd['bill_ref'], 'supplier': bd['supplier'],
                'landed_cost_total': bd['landed_cost_total'],
                'total_cash_paid': bd['total_cash_paid']},
        'obligations': bd['obligations'],
        'payment_rows': [
            {**row, 'date_posted': row['date_posted'].isoformat() if row['date_posted'] else None}
            for row in bd['payment_rows']
        ],
    })


@accounts_bp.route('/purchase_payables')
@login_required
def purchase_payables():
    """Outstanding purchase payables: supplier + transporter/labour/other."""
    from app.services.financial_ledgers import build_purchase_payables
    try:
        report = build_purchase_payables()
    except Exception:
        logger.exception('Purchase payables projection failed')
        report = {'suppliers': [], 'parties': [], 'unassigned_legacy_charges': 0.0, 'total': 0.0}
    return render_template('accounts/purchase_payables.html', report=report)
