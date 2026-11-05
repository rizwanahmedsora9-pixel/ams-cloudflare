"""Pay GRN Expenses — the ONLY place purchase money is paid.

Owner rule A1: GRN entry never pays.  These screens (and the "Make New
Transaction" modal's `grn_payment` target) are where full, partial and repeated
payments to the supplier, transporter, labourer or other charge recipient are
recorded, each linked to its original GRN and obligation.

Owner rule A3: a GRN shows TWO supplier payables — the stock / material amount
and the GRN expenses ticked "Add to supplier ledger" — plus one payable per
unticked expense recipient.  ``/accounts/pay_grn`` is the screen that keeps
them apart; ``/accounts/grn_payments`` remains the full obligation breakdown.

Owner rule (2026-11-05): the "Make New Transaction" modal posts the per-expense
payments itself (``/accounts/grn_expenses/pay``, one voucher per filled box),
and reads its rows from ``/accounts/api/grn_expense_payments/<grn_id>``.  Those
rows are the expenses the supplier ledger does NOT carry — no stock, no qty, no
rate — each with its own Total / Paid / To pay.
"""
from ._common import *  # noqa
import secrets
from models import GRN, GRNCharge, SupplierPayment, CashFlowParty, Supplier
from app.services.grn_costing import (
    grn_breakdown, supplier_bill_breakdown, payment_obligation_label,
    grn_expense_payment_rows,
    OBLIGATION_MATERIAL, OBLIGATION_EXPENSES, OBLIGATION_SUPPLIER,
    OBLIGATION_CHARGE, parse_obligation_key,
)
from app.services.grn_payments import (
    save_grn_payment, save_grn_payment_expanded, void_grn_payment,
    restore_grn_payment, open_supplier_obligations,
    supplier_open_obligation_options,
)


def _grn_payments_permission_ok():
    return (current_user.role in ('admin', 'root')
            or getattr(current_user, 'can_manage_payments', False)
            or getattr(current_user, 'can_manage_accounts', False))


def _grn_payment_accounts():
    return _active_accounts().filter(
        func.lower(func.trim(Account.category)).in_(['cash', 'bank'])
    ).order_by(Account.category.asc(), Account.name.asc(), Account.id.asc()).all()


MODE_SUPPLIER = 'SUPPLIER'
MODE_EXPENSES = 'EXPENSES'

#: Payment modes of Pay GRN Expenses.  The single-amount supplier form and the
#: per-expense boxes are mutually exclusive: GRN expenses have their own unique
#: payment system (one money field per expense), so the supplier amount field
#: must not be on screen while an expense is being paid.
PAYMENT_MODES = (
    {
        'key': MODE_SUPPLIER,
        'label': 'Supplier bill',
        'icon': 'bi-cash-stack',
        'hint': 'Stock / material (qty × rate) plus the expenses still ticked to the supplier.',
    },
    {
        'key': MODE_EXPENSES,
        'label': 'GRN expenses (one by one)',
        'icon': 'bi-truck',
        'hint': 'Every expense — vehicle fare, loading, unloading, other — with its own amount field.',
    },
)


def _expenses_open_total(bd):
    return sum((ob.get('remaining') or 0.0) for ob in (bd or {}).get('obligations', [])
               if ob.get('kind') == OBLIGATION_CHARGE)


def _grn_expense_rows(bd):
    """One row per GRN expense, newest-payable order, with its own open amount.

    This is the per-expense payment system: every vehicle fare / loading /
    unloading / other expense the operator entered on the GRN is listed with
    the amount still payable, whoever it is owed to.
    """
    rows = []
    for ob in (bd or {}).get('obligations', []):
        if ob.get('kind') != OBLIGATION_CHARGE:
            continue
        rows.append({
            'key': ob['key'],
            'charge_id': ob.get('charge_id'),
            'label': ob.get('label') or 'GRN expense',
            'recipient_label': ob.get('recipient_label') or '',
            'recipient_name': ob.get('recipient_name') or '',
            'original': ob.get('original') or 0.0,
            'paid': ob.get('paid') or 0.0,
            'remaining': ob.get('remaining') or 0.0,
            'status': ob.get('status') or 'Unpaid',
            'billed_to_supplier': bool(ob.get('billed_to_supplier')),
            'supplier_paid': ob.get('supplier_paid') or 0.0,
            'recipient_paid': ob.get('recipient_paid') or 0.0,
            'cost_treatment': ob.get('cost_treatment') or 'INVENTORY',
            'is_landed': (ob.get('cost_treatment') or 'INVENTORY').upper() == 'INVENTORY',
        })
    return rows


def _grn_payment_summary(grn, breakdown=None):
    """Display facts for one GRN: date, supplier dues and off-ledger expenses.

    The off-ledger figure is the amount of expenses whose "Add to supplier
    ledger" box was NOT ticked.  They are still payable, just to their own
    recipient, so the GRN picker must never show them as zero.
    """
    bd = breakdown or grn_breakdown(grn)
    posted = getattr(grn, 'date_posted', None)
    return {
        'bill_ref': bd.get('bill_ref') or f"GRN-{grn.id}",
        'supplier': bd.get('supplier') or '',
        'date_posted': posted,
        'date_label': posted.strftime('%d/%b/%Y') if posted else 'Date not recorded',
        'date_iso': posted.strftime('%Y-%m-%d') if posted else '',
        'material_remaining': bd.get('material_remaining', 0.0),
        'expenses_remaining': bd.get('expenses_remaining', 0.0),
        # Every GRN expense is its own payable, so this is the open amount of
        # all expenses (ticked and unticked), not only the off-ledger ones.
        'recipient_expenses_remaining': _expenses_open_total(bd),
        'supplier_ledger_remaining': (bd.get('material_remaining', 0.0)
                                      + bd.get('expenses_remaining', 0.0)),
        'expense_count': sum(1 for ob in bd.get('obligations', [])
                             if ob.get('kind') == OBLIGATION_CHARGE),
        'total_remaining': bd.get('total_remaining', 0.0),
    }


@accounts_bp.route('/grn_payments', methods=['GET'])
@login_required
def grn_payments():
    """Select a GRN, see every obligation with paid/remaining, then pay."""
    selected_id = request.args.get('grn_id', type=int)
    selected_charge = request.args.get('charge_id', type=int)
    mode = (request.args.get('mode') or '').strip().upper()
    if mode not in (MODE_SUPPLIER, MODE_EXPENSES):
        # Opening one expense (or a GRN with no stock/expense supplier payable
        # left) starts in the per-expense system.
        mode = MODE_EXPENSES if selected_charge else MODE_SUPPLIER
    grns = GRN.query.filter(
        GRN.is_void == False,  # noqa: E712
        GRN.is_cancelled == False,  # noqa: E712
    ).order_by(GRN.date_posted.desc(), GRN.id.desc()).limit(500).all()
    selected = db.session.get(GRN, selected_id) if selected_id else None
    breakdown = grn_breakdown(selected) if selected else None
    selected_summary = _grn_payment_summary(selected, breakdown) if selected and breakdown else None
    selected_obligation = None
    if breakdown and selected_charge:
        selected_obligation = next(
            (row for row in breakdown['obligations']
             if row['charge_id'] == selected_charge),
            None,
        )
    if breakdown and selected_obligation is None:
        # Prefer an OPEN obligation.  When stock is already paid, the next
        # supplier expense or own-recipient expense must show its amount
        # instead of leaving the form on a settled Rs. 0.00 stock row.
        open_rows = [row for row in breakdown['obligations']
                     if row['remaining_minor'] > 0]
        selected_obligation = (
            next((row for row in open_rows if row['kind'] == OBLIGATION_MATERIAL), None)
            or next((row for row in open_rows if row['kind'] == OBLIGATION_EXPENSES), None)
            or (open_rows[0] if open_rows else None)
            or next((row for row in breakdown['obligations']
                     if row['kind'] == OBLIGATION_MATERIAL), None)
        )

    expense_rows = _grn_expense_rows(breakdown) if breakdown else []
    if mode == MODE_EXPENSES:
        if selected_obligation is None or selected_obligation.get('kind') != OBLIGATION_CHARGE:
            selected_obligation = next(
                (row for row in (breakdown['obligations'] if breakdown else [])
                 if row['kind'] == OBLIGATION_CHARGE and row['remaining_minor'] > 0),
                None,
            ) or next(
                (row for row in (breakdown['obligations'] if breakdown else [])
                 if row['kind'] == OBLIGATION_CHARGE),
                None,
            )
    expenses_open_total = sum(row['remaining'] for row in expense_rows)

    page_rows = []
    for g in grns:
        try:
            bd = grn_breakdown(g)
            summary = _grn_payment_summary(g, bd)
        except Exception:
            bd = None
            summary = None
        page_rows.append({
            'grn': g,
            'breakdown': bd,
            'summary': summary,
        })

    return render_template(
        'accounts/grn_payments.html',
        page_rows=page_rows,
        selected=selected,
        breakdown=breakdown,
        selected_summary=selected_summary,
        selected_obligation=selected_obligation,
        mode=mode,
        payment_modes=PAYMENT_MODES,
        expense_rows=expense_rows,
        expenses_open_total=expenses_open_total,
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
    mode = (request.form.get('mode') or MODE_SUPPLIER).strip().upper()
    try:
        payments = []
        # Per-expense payment system: every expense box that has money in it is
        # its own voucher against its own recipient.  The supplier single-amount
        # field is not part of this mode at all (it is hidden and disabled).
        expense_keys = request.form.getlist('expense_key[]')
        expense_amounts = request.form.getlist('expense_amount[]')
        if mode == MODE_EXPENSES or expense_keys:
            base = {
                'grn_id': grn_id,
                'method': request.form.get('method', 'Cash'),
                'payment_account_id': request.form.get('payment_account_id'),
                'date_posted': request.form.get('date_posted', ''),
                'reference': (request.form.get('reference') or '').strip(),
                'note': (request.form.get('note') or '').strip(),
                'allow_advance': bool(request.form.get('allow_advance')),
                'actor': current_user,
            }
            filled = [
                (str(key or '').strip(), str(amount or '').strip())
                for key, amount in zip(expense_keys, expense_amounts)
                if str(amount or '').strip() not in ('', '0', '0.00', '0.0')
            ]
            if not filled:
                raise ValueError('Enter an amount next to the GRN expense you want to pay.')
            posted_ids = set()
            for index, (key, amount) in enumerate(filled):
                kind, _ = parse_obligation_key(key)
                if kind != OBLIGATION_CHARGE:
                    raise ValueError('Select a valid GRN expense to pay.')
                payment, _created = save_grn_payment(
                    obligation_key=key, amount=amount,
                    idempotency_key=((request.form.get('idempotency_key') or '').strip() or None)
                    if len(filled) == 1 else None,
                    **base,
                )
                posted_ids.add(payment.id)
                payments.append(payment)
        else:
            payments = save_grn_payment_expanded(
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
        total = sum(float(getattr(row, 'amount', 0) or 0) for row in payments)
        paid_for = ', '.join(sorted({payment_obligation_label(row) for row in payments}))
        flash(f'GRN payment of Rs. {total:,.2f} recorded from Accounts ({paid_for}).', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception:
        db.session.rollback()
        logger.exception('GRN payment save failed')
        flash('Unable to save the GRN payment. Please check the details and try again.', 'danger')
    args = {'grn_id': grn_id} if grn_id else {}
    if mode == MODE_EXPENSES:
        args['mode'] = MODE_EXPENSES
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


@accounts_bp.route('/api/grn_expense_payments/<int:grn_id>')
@login_required
def grn_expense_payments_api(grn_id):
    """One row per GRN expense (Total / Paid / To pay) for the transaction modal.

    Read-only.  ``payment_rows`` are the expenses the supplier ledger does not
    carry (their own recipient), ``supplier_billed_rows`` the ticked ones, and
    ``accounts`` the cash / bank accounts the operator may pay from.
    """
    grn = db.session.get(GRN, grn_id)
    if grn is None or bool(getattr(grn, 'is_void', False)) or bool(getattr(grn, 'is_cancelled', False)):
        return jsonify({'ok': False, 'error': 'GRN not found or cancelled.'}), 404
    bd = grn_breakdown(grn)
    rows = grn_expense_payment_rows(grn, bd)
    date_posted = rows.get('date_posted')
    return jsonify({
        'ok': True,
        'grn': {
            'id': grn.id,
            'bill_ref': rows['bill_ref'],
            'supplier': rows['supplier'],
            'date_label': date_posted.strftime('%d/%b/%Y') if date_posted else 'Date not recorded',
            'date_iso': date_posted.strftime('%Y-%m-%d') if date_posted else '',
        },
        **{key: value for key, value in rows.items() if key != 'date_posted'},
        'accounts': [
            {'id': a.id, 'name': a.name, 'category': (a.category or '').upper(),
             'balance': float(a.balance or 0)}
            for a in _grn_payment_accounts()
        ],
        'can_edit': _grn_payments_permission_ok(),
    })


@accounts_bp.route('/grn_expenses/pay', methods=['POST'])
@login_required
def grn_expenses_pay_from_modal():
    """Post one voucher per filled expense box straight from the transaction modal.

    The modal offers the **per-expense payment system only**: the unticked
    "own recipient" expenses, each with its own amount field.  It never pays
    stock, never carries a quantity or a rate, and never posts the supplier
    bill.  Every filled box becomes its own ``GRN_CHARGE`` voucher through the
    same engine (and the same guards) as Pay GRN Expenses.
    """
    if not _grn_payments_permission_ok():
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.dashboard'))
    # These names are deliberately distinct from the ordinary transaction
    # fields (grn_id / payment_account_id) so the same modal can post either an
    # ordinary transaction or these per-expense payments without the two ever
    # reading each other's values.
    grn_id = request.form.get('grn_expense_grn_id', type=int)
    try:
        if not grn_id:
            raise ValueError('Select a GRN to pay its expenses.')
        grn = db.session.get(GRN, grn_id)
        if grn is None or bool(getattr(grn, 'is_void', False)) or bool(getattr(grn, 'is_cancelled', False)):
            raise ValueError('GRN not found or cancelled.')

        bd = grn_breakdown(grn)
        payable = {row['key']: row for row in grn_expense_payment_rows(grn, bd)['payment_rows']}

        keys = request.form.getlist('expense_key[]')
        amounts = request.form.getlist('expense_amount[]')
        filled = [
            (str(key or '').strip(), str(amount or '').strip())
            for key, amount in zip(keys, amounts)
            if str(amount or '').strip() not in ('', '0', '0.00', '0.0')
        ]
        if not filled:
            raise ValueError('Enter the amount next to at least one GRN expense you want to pay.')
        for key, _amount in filled:
            name = payable.get(key, {}).get('label') or 'this expense'
            if key not in payable:
                raise ValueError(
                    f'{name} is not an expense the supplier ledger leaves out — '
                    'pay it on Pay GRN Expenses.'
                )
        account_id = request.form.get('grn_expense_account_id', type=int)
        if not account_id:
            raise ValueError('Select the cash / bank account the money is paid from.')

        posted = []
        token = (request.form.get('grn_expense_idempotency_key') or '').strip() or None
        for index, (key, amount) in enumerate(filled):
            payment, _created = save_grn_payment(
                grn_id=grn.id,
                obligation_key=key,
                amount=amount,
                method=request.form.get('grn_expense_method', 'Cash'),
                payment_account_id=account_id,
                date_posted=request.form.get('date_posted', ''),
                reference=(request.form.get('grn_expense_reference') or '').strip(),
                note=(request.form.get('note') or '').strip(),
                idempotency_key=f'{token}-{index}' if token else None,
                actor=current_user,
            )
            posted.append(payment)
        db.session.commit()
        total = sum(float(getattr(row, 'amount', 0) or 0) for row in posted)
        paid_for = ', '.join(sorted({row.recipient_name or row.recipient_type or 'GRN expense'
                                     for row in posted}))
        flash(f'GRN expenses of Rs. {total:,.2f} paid ({paid_for}). '
              'Each expense is its own cash-out row; the supplier ledger is untouched.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception:
        db.session.rollback()
        logger.exception('Pay GRN expenses from the transaction modal failed')
        flash('Unable to pay the GRN expenses. Please check the details and try again.', 'danger')
    return redirect(url_for('accounts.dashboard'))


@accounts_bp.route('/api/supplier_open_obligations/<int:supplier_id>')
@login_required
def supplier_open_obligations_api(supplier_id):
    """Open GRN payables for one supplier (Pay Supplier / ledger pay forms)."""
    return jsonify({
        'ok': True,
        'supplier_id': supplier_id,
        'obligations': supplier_open_obligation_options(supplier_id),
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


# =========================================================================
#  PAY GRN — stock and GRN expenses side by side (owner rule A3)
# =========================================================================

def _supplier_grn_rows(supplier_id=None, *, only_open=True):
    """GRNs with their material / expenses / recipient split, newest first."""
    from app.services.grn_costing import supplier_bill_breakdown
    q = GRN.query.filter(
        GRN.is_void == False,  # noqa: E712
        GRN.is_cancelled == False,  # noqa: E712
    )
    if supplier_id:
        supplier = db.session.get(Supplier, int(supplier_id))
        if supplier is None:
            return []
        q = q.filter(or_(GRN.supplier_id == supplier.id,
                         func.lower(func.trim(GRN.supplier)) == (supplier.name or '').strip().lower()))
    rows = []
    for grn in q.order_by(GRN.date_posted.desc(), GRN.id.desc()).limit(400).all():
        try:
            row = supplier_bill_breakdown(grn)
        except Exception:
            logger.exception('GRN supplier split failed for GRN %s', grn.id)
            continue
        if only_open and row['material_remaining'] <= 0.004 \
                and row['expenses_remaining'] <= 0.004 and row['recipient_remaining'] <= 0.004:
            continue
        rows.append(row)
    return rows


@accounts_bp.route('/pay_grn', methods=['GET'])
@login_required
def pay_grn():
    """Pay one GRN: stock (material) and GRN expenses as separate payables."""
    from app.services.grn_costing import supplier_bill_breakdown
    supplier_id = request.args.get('supplier_id', type=int)
    grn_id = request.args.get('grn_id', type=int)
    obligation = (request.args.get('obligation') or '').strip().upper()

    selected = db.session.get(GRN, grn_id) if grn_id else None
    if selected is not None and (bool(selected.is_void) or bool(selected.is_cancelled)):
        selected = None
    bill = supplier_bill_breakdown(selected) if selected is not None else None

    selected_key = None
    if bill:
        if obligation == OBLIGATION_EXPENSES and bill['expenses']:
            selected_key = bill['expenses']['key']
        elif bill['material']:
            selected_key = bill['material']['key']

    suppliers = _active_suppliers()
    if grn_id and supplier_id is None and selected is not None:
        supplier_id = getattr(selected, 'supplier_id', None)
    rows = _supplier_grn_rows(supplier_id) if supplier_id else []
    if not rows:
        # "Show me everything still owed", so the picker is never empty by
        # accident when a supplier filter was not supplied.
        rows = _supplier_grn_rows(None)
    # The picked GRN must always be visible even when it is not in the filtered list.
    if bill and all(r['grn_id'] != bill['grn_id'] for r in rows):
        rows.insert(0, bill)

    return render_template(
        'accounts/pay_grn.html',
        suppliers=suppliers,
        supplier_id=supplier_id,
        selected=selected,
        bill=bill,
        selected_key=selected_key,
        grn_rows=rows,
        accounts=_grn_payment_accounts(),
        today_date=pk_today().strftime('%Y-%m-%d'),
        submission_token=secrets.token_hex(8),
        can_edit=_grn_payments_permission_ok(),
    )


@accounts_bp.route('/pay_grn/save', methods=['POST'])
@login_required
def pay_grn_save():
    """Post material / GRN-expense / recipient payments for one GRN."""
    if not _grn_payments_permission_ok():
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.pay_grn'))
    grn_id = request.form.get('grn_id', type=int)
    obligation_key = (request.form.get('obligation_key') or '').strip()
    posted = []
    try:
        targets = request.form.getlist('pay_obligation_key[]')
        amounts = request.form.getlist('pay_amount[]')
        lines = [(key, amount) for key, amount in zip(targets, amounts)
                 if str(amount or '').strip() not in ('', '0', '0.00')]
        if not lines and obligation_key:
            lines = [(obligation_key, request.form.get('amount', 0))]
        if not lines:
            raise ValueError('Enter an amount for the stock / material or the GRN expenses you want to pay.')
        for index, (key, amount) in enumerate(lines):
            payment, _created = save_grn_payment(
                grn_id=grn_id,
                obligation_key=key,
                amount=amount,
                method=request.form.get('method', 'Cash'),
                payment_account_id=request.form.get('payment_account_id'),
                date_posted=request.form.get('date_posted', ''),
                reference=(request.form.get('reference') or '').strip(),
                note=(request.form.get('note') or '').strip(),
                idempotency_key=((request.form.get('idempotency_key') or '').strip() or None)
                if len(lines) == 1 else None,
                allow_advance=bool(request.form.get('allow_advance')),
                actor=current_user,
            )
            posted.append(payment)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(url_for('accounts.pay_grn', grn_id=grn_id, obligation=request.form.get('focus', '')))
    except Exception:
        db.session.rollback()
        logger.exception('PAY GRN save failed')
        flash('Unable to save the GRN payment. Please check the details and try again.', 'danger')
        return redirect(url_for('accounts.pay_grn', grn_id=grn_id))
    total = sum(float(getattr(p, 'amount', 0) or 0) for p in posted)

    def _paid_for_label(payment):
        kind = (getattr(payment, 'payment_kind', '') or '').upper()
        if kind == 'GRN_EXPENSES':
            return 'GRN expenses billed to supplier'
        if kind == 'GRN_CHARGE':
            return 'GRN expenses to their own recipients'
        return 'stock'

    labels = ', '.join(sorted({_paid_for_label(p) for p in posted}))
    flash(f'Rs. {total:,.2f} paid for {labels} on this GRN. Cash Flow and the ledgers are updated.', 'success')
    return redirect(url_for('accounts.pay_grn', grn_id=grn_id))


@accounts_bp.route('/api/pay_grn/<int:grn_id>')
@login_required
def pay_grn_api(grn_id):
    """JSON material/expense split for one GRN (used by the live pay form)."""
    from app.services.grn_costing import supplier_bill_breakdown
    grn = db.session.get(GRN, grn_id)
    if grn is None or bool(grn.is_void):
        return jsonify({'ok': False, 'error': 'GRN not found'}), 404
    bill = supplier_bill_breakdown(grn)
    return jsonify({
        'ok': True,
        'grn_id': bill['grn_id'],
        'bill_ref': bill['bill_ref'],
        'supplier': bill['supplier'],
        'material': {'key': (bill['material'] or {}).get('key'),
                     'original': bill['material_original'],
                     'paid': bill['material_paid'],
                     'remaining': bill['material_remaining']},
        'expenses': {'key': (bill['expenses'] or {}).get('key'),
                     'original': bill['expenses_original'],
                     'paid': bill['expenses_paid'],
                     'remaining': bill['expenses_remaining']},
        'recipient_charges': [
            {'key': o['key'], 'label': o['label'], 'recipient': o['recipient_name'],
             'remaining': o['remaining']} for o in bill['recipient_charges']
        ],
        'total_remaining': bill['total_remaining'],
    })
