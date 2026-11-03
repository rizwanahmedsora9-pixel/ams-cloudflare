"""delivery — split from ops.py."""
from ._common import *  # noqa

from flask import current_app

from uuid import uuid4

# Symbol shown in front of an amount.  ``Settings.currency`` stores a code
# (PKR by default), not a glyph, so map the common ones and fall back to the
# code itself instead of silently rendering nothing.
_CURRENCY_SYMBOLS = {
    'PKR': 'Rs. ', 'INR': '₹', 'USD': '$', 'EUR': '€', 'GBP': '£',
    'AED': 'AED ', 'SAR': 'SAR ', 'CAD': 'C$', 'AUD': 'A$',
}

_DELIVERY_RENT_SORTS = ('due', 'name', 'rent', 'paid', 'oldest')
_DELIVERY_RENT_GROUPS = ('person', 'day')


def _delivery_rent_currency_symbol():
    try:
        settings = Settings.query.first()
        code = ((getattr(settings, 'currency', None) or 'PKR') if settings else 'PKR').strip().upper()
    except Exception:
        code = 'PKR'
    return _CURRENCY_SYMBOLS.get(code, f'{code} ' if code else '')


def _delivery_rent_safe_next(default):
    """Only ever redirect back to a path on this site."""
    candidate = (request.values.get('next') or '').strip()
    if candidate.startswith('/') and not candidate.startswith('//') and '\\' not in candidate:
        return candidate
    return default


def _delivery_rent_filters():
    """The grouping filters shared by the page, the JSON endpoint and the POST
    handlers, so a redirect can rebuild the exact view the user was looking at."""
    group_by = (request.args.get('group_by') or 'person').strip().lower()
    sort = (request.args.get('sort') or 'due').strip().lower()
    return {
        'date_from': (request.args.get('date_from') or '').strip(),
        'date_to': (request.args.get('date_to') or '').strip(),
        'driver': (request.args.get('driver') or '').strip(),
        'q': (request.args.get('q') or '').strip(),
        'group_by': group_by if group_by in _DELIVERY_RENT_GROUPS else 'person',
        'sort': sort if sort in _DELIVERY_RENT_SORTS else 'due',
    }


def _delivery_rent_view_url():
    """The page URL, with the current filters, that a POST should return to."""
    args = {key: value for key, value in request.args.items() if value}
    return url_for('delivery_rents_page', **args)


@bp.route('/delivery_rents')
@login_required
def delivery_rents_page():
    if not _user_can('can_view_delivery_rent'):
        flash('Unauthorized', 'danger')
        return redirect(url_for('index'))

    from app.services.delivery_rent_groups import build_delivery_rent_groups

    filters = _delivery_rent_filters()
    result = build_delivery_rent_groups(**filters)

    # Rendering every trip into the first paint is fine for a normal day and
    # painful for a busy quarter.  Above this many entry rows the detail is
    # fetched the first time a driver is expanded (the JSON endpoint returns
    # exactly the same markup), so the page stays fast without hiding anything.
    inline_detail_limit = int(
        current_app.config.get('DELIVERY_RENT_INLINE_DETAIL_LIMIT', 250) or 0
    )
    render_all_details = result['totals']['entries'] <= inline_detail_limit

    payment_accounts = Account.query.filter(
        func.coalesce(Account.is_active, True) == True,  # noqa: E712
        func.lower(func.trim(Account.category)).in_(['cash', 'bank']),
    ).order_by(Account.name.asc(), Account.id.asc()).all()

    can_pay = bool(_user_can('can_manage_sales'))

    return render_template(
        'delivery_rents.html',
        groups=result['groups'],
        totals=result['totals'],
        group_by=result['group_by'],
        sort=result['sort'],
        date_from=result['date_from'],
        date_to=result['date_to'],
        driver_filter=result['driver'],
        search_query=result['q'],
        driver_names=result['driver_options'],
        orphan_payments=result['orphan_payments'],
        truncated=result['truncated'],
        render_all_details=render_all_details,
        payment_accounts=payment_accounts,
        submission_token=uuid4().hex,
        can_pay=can_pay,
        currency_symbol=_delivery_rent_currency_symbol(),
        return_to=_delivery_rent_view_url(),
    )


@bp.route('/delivery_rents/group/<path:group_key>')
@login_required
def delivery_rent_group(group_key):
    """A single driver's (or day's) trip rows, for expanding the summary row."""
    if not _user_can('can_view_delivery_rent'):
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    from app.services.delivery_rent_groups import build_delivery_rent_groups

    filters = _delivery_rent_filters()
    result = build_delivery_rent_groups(**filters)
    group = next((g for g in result['groups'] if g['key'] == group_key), None)
    if group is None:
        return jsonify({'ok': False, 'error': 'This list changed. Reload the page.'}), 404

    html = render_template(
        'ops/_delivery_rent_group_rows.html',
        group=group,
        can_pay=bool(_user_can('can_manage_sales')),
        currency_symbol=_delivery_rent_currency_symbol(),
        return_to=_delivery_rent_view_url(),
    )
    summary = {
        key: group[key] for key in (
            'key', 'kind', 'name', 'delivery_person_id', 'rent', 'paid', 'waived',
            'due', 'entry_count', 'payment_count', 'status', 'last_date',
        ) if key in group
    }
    return jsonify({'ok': True, 'key': group_key, 'html': html, 'group': summary})


@bp.route('/delivery_rents/void/<int:id>', methods=['POST'])
@login_required
def void_delivery_rent(id):
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_rents_page'))
    row = db.session.get(SaleDeliveryPerson, id)
    if row:
        # Policy: no void flags — delete the row and the driver payments that
        # were settled against it.
        DeliveryPersonPayment.query.filter_by(allocation_id=id).delete(
            synchronize_session=False)
        db.session.delete(row)
        db.session.commit()
        flash('Delivery rent entry deleted.', 'success')
    return redirect(_delivery_rent_safe_next(url_for('delivery_rents_page')))


@bp.route('/delivery_rents/pay/<int:alloc_id>', methods=['POST'])
@login_required
def pay_delivery_rent(alloc_id):
    """Per-allocation entry point — same core, same single financial transaction."""
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_rents_page'))

    alloc = db.session.get(SaleDeliveryPerson, alloc_id)
    if not alloc or alloc.is_void:
        flash('Invalid delivery rent entry.', 'danger')
        return redirect(_delivery_rent_safe_next(url_for('delivery_rents_page')))

    from app.services.driver_payments import save_driver_payment
    try:
        payment, _created = save_driver_payment(
            delivery_person_id=alloc.delivery_person_id,
            allocation_id=alloc.id,
            amount_paid=request.form.get('paid_amount', 0) or 0,
            waive_off_amount=request.form.get('waive_off_amount', 0) or 0,
            method=(request.form.get('method') or 'Cash'),
            payment_account_id=request.form.get('payment_account_id', type=int),
            reference=(request.form.get('reference') or '').strip(),
            date_posted=(request.form.get('date') or '').strip(),
            note=(request.form.get('note') or '').strip(),
            idempotency_key=(request.form.get('idempotency_key') or '').strip() or None,
            actor=current_user,
        )
        replayed = getattr(payment, '_idempotent_replay', False)
        db.session.commit()
        if replayed:
            flash('This delivery rent payment was already recorded; no duplicate was created.', 'info')
        else:
            flash('Delivery rent payment recorded. The selected account and the driver ledger were updated together.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        logging.getLogger(__name__).exception('Delivery rent payment failed')
        flash('Unable to record the delivery rent payment: the payment could not be saved. Please check the details and try again.', 'danger')
    return redirect(_delivery_rent_safe_next(url_for('delivery_rents_page')))


@bp.route('/delivery_rents/pay_driver/<int:person_id>', methods=['POST'])
@login_required
def pay_delivery_person_rent(person_id):
    """Settle one driver straight from their summary row.

    The amount is spread over that driver's open trips oldest-first by the same
    service the driver ledger uses, so a header-row payment and a ledger
    settlement are the same financial event, not two different ones.
    """
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_rents_page'))

    person = db.session.get(DeliveryPerson, person_id)
    if person is None:
        flash('Delivery person not found.', 'danger')
        return redirect(_delivery_rent_safe_next(url_for('delivery_rents_page')))

    from app.services.driver_payments import settle_driver_fifo
    try:
        rows = settle_driver_fifo(
            delivery_person_id=person.id,
            amount_paid=request.form.get('paid_amount', 0) or 0,
            waive_off_amount=request.form.get('waive_off_amount', 0) or 0,
            method=(request.form.get('method') or 'Cash'),
            payment_account_id=request.form.get('payment_account_id', type=int),
            reference=(request.form.get('reference') or '').strip(),
            date_posted=(request.form.get('date') or '').strip(),
            note=(request.form.get('note') or '').strip(),
            idempotency_key=(request.form.get('idempotency_key') or '').strip() or None,
            actor=current_user,
        )
        replayed = bool(rows) and getattr(rows[0], '_idempotent_replay', False)
        db.session.commit()
        if replayed:
            flash('This delivery payment was already recorded; no duplicate was created.', 'info')
        elif rows:
            flash(
                f'Payment recorded for {person.name} across {len(rows)} trip(s). '
                'The selected account and the driver ledger were updated together.',
                'success',
            )
        else:
            flash('No open rent was found for this delivery person.', 'info')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        logging.getLogger(__name__).exception('Delivery person settlement failed')
        flash('Unable to record the delivery payment: the payment could not be saved. Please check the details and try again.', 'danger')
    return redirect(_delivery_rent_safe_next(url_for('delivery_rents_page')))
