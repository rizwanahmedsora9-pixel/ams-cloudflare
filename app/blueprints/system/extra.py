"""extra — split from system.py.

Diagnostics for the "500 Internal Server Error" reports: an admin-only JSON
view of the most recent unhandled failures, so the cause can be read from the
yard PC instead of guessing from the error page.
"""
from ._common import *  # noqa

from app.services.errors import error_log_path, recent_errors


@bp.route('/debug/recent_errors')
@login_required
def recent_errors_feed():
    """Newest unhandled failures, newest first (admin/root only).

    Each entry carries the reference printed on the error page, the endpoint,
    the exception and the traceback tail, so a report like "page X showed
    E-1a2b3c" can be resolved without shell access to the server.
    """
    if getattr(current_user, 'role', None) not in ('admin', 'root'):
        abort(403)
    limit = request.args.get('limit', '20')
    try:
        limit_value = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        limit_value = 20
    records = recent_errors(limit=limit_value)
    for record in records:
        traceback_text = record.get('traceback') or ''
        record['traceback_tail'] = traceback_text[-1200:]
        record.pop('traceback', None)
    response = jsonify({
        'ok': True,
        'count': len(records),
        'log_path': str(error_log_path()),
        'errors': records,
    })
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response
