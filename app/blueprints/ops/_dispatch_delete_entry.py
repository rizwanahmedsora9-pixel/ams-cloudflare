"""dispatch — split from ops.py."""
from ._common import *  # noqa
from app.services.edit_policy import (
    EditBlocked, authorise_edit, audit_override, form_reason,
    is_backdate_restricted, record_date_of,
)

@bp.route('/delete_entry/<int:id>', methods=['POST'])
@login_required
def delete_entry(id):
    e = db.session.get(Entry, id)
    if not e:
        return redirect(url_for('index'))

    # Same shared policy as the edit path.  The old code blocked every
    # non-admin from deleting anything that was not dated today and sent them
    # to the dashboard with no explanation; now the reason travels with the
    # request and the audit trail records who removed what.
    delete_reason = form_reason(request.form)
    try:
        authorise_edit(
            current_user,
            record_date_of(e, 'date'),
            action_label='Delete dispatch',
            reason=delete_reason or e.note,
        )
    except EditBlocked as blocked:
        flash(blocked.message, 'danger')
        return redirect(request.referrer or url_for('tracking'))

    changed = _set_entry_void_state(e, True)
    if changed:
        db.session.commit()
        if is_backdate_restricted(current_user):
            audit_override(
                current_user, action='delete', entity='Entry', entity_id=e.id,
                reason=delete_reason or None,
            )
        flash('Transaction deleted', 'warning')
    else:
        flash('Transaction already deleted', 'info')
    return redirect(request.referrer or url_for('index'))
