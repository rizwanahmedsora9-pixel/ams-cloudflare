"""Terms and conditions for Urdu sales receipts — admin management.

Settings -> Terms & Conditions: add, enable/disable and reorder the terms
that can be printed on Urdu receipts.  More terms can be added here at any
time without touching code.
"""
from ._common import *  # noqa


@bp.route('/settings/terms-conditions', methods=['GET', 'POST'])
@login_required
def terms_conditions():
    if current_user.role != 'admin' and not current_user.can_access_settings:
        flash('Unauthorized — only an admin can manage receipt terms.', 'danger')
        return redirect(url_for('settings'))

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        content_ur = (request.form.get('content_ur') or '').strip()
        try:
            sort_order = int(request.form.get('sort_order') or '0')
        except ValueError:
            sort_order = 0
        if not title:
            flash('Title is required', 'danger')
            return redirect(url_for('terms_conditions'))
        try:
            row = TermsAndCondition(title=title, content_ur=content_ur, sort_order=sort_order)
            db.session.add(row)
            db.session.commit()
            try:
                audit_log('terms_conditions_add', f'Added Urdu receipt term "{title}"')
            except Exception:
                pass
            flash('Term added successfully', 'success')
        except Exception:
            db.session.rollback()
            logging.getLogger(__name__).exception('Could not add terms and condition row')
            flash('Could not save the term', 'danger')
        return redirect(url_for('terms_conditions'))

    terms = (TermsAndCondition.query
             .order_by(TermsAndCondition.sort_order.asc(),
                       TermsAndCondition.title.asc())
             .all())
    return render_template('terms_conditions.html', terms=terms)


@bp.route('/settings/terms-conditions/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_term(id):
    if current_user.role != 'admin' and not current_user.can_access_settings:
        flash('Unauthorized', 'danger')
        return redirect(url_for('settings'))
    row = db.session.get(TermsAndCondition, id)
    if not row:
        flash('Term not found', 'danger')
        return redirect(url_for('terms_conditions'))
    row.is_active = not bool(row.is_active)
    db.session.commit()
    try:
        audit_log('terms_conditions_toggle',
                  f'Term id={id} active={bool(row.is_active)}')
    except Exception:
        pass
    flash(('Term activated' if row.is_active else 'Term deactivated'), 'success')
    return redirect(url_for('terms_conditions'))


@bp.route('/settings/terms-conditions/<int:id>/delete', methods=['POST'])
@login_required
def delete_term(id):
    if current_user.role != 'admin' and not current_user.can_access_settings:
        flash('Unauthorized', 'danger')
        return redirect(url_for('settings'))
    row = db.session.get(TermsAndCondition, id)
    if not row:
        flash('Term not found', 'danger')
        return redirect(url_for('terms_conditions'))
    title = row.title
    db.session.delete(row)
    db.session.commit()
    try:
        audit_log('terms_conditions_delete', f'Deleted Urdu receipt term "{title}"')
    except Exception:
        pass
    flash('Term deleted', 'success')
    return redirect(url_for('terms_conditions'))
