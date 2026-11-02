"""Sidebar Settings — let a manager design the sidebar themselves.

Routes
------
``GET  /settings/sidebar``        the designer page (all options + categories)
``POST /settings/sidebar/save``   persist a whole layout snapshot (JSON)
``POST /settings/sidebar/reset``  back to the shipped default layout
"""
from __future__ import annotations

from ._common import *  # noqa

from app.services import sidebar_nav as sidebar_nav_service


def _can_manage_sidebar() -> bool:
    if not current_user.is_authenticated:
        return False
    if current_user.role in ('admin', 'root'):
        return True
    return _user_can('can_access_settings')


@bp.route('/settings/sidebar')
@login_required
def sidebar_settings_page():
    if not _can_manage_sidebar():
        flash('Unauthorized: Admin access required.', 'danger')
        return redirect(url_for('index'))

    layout = sidebar_nav_service.layout_payload()
    links = sidebar_nav_service.available_links()
    # Everything the browser script needs, in one JSON block (see
    # static/sidebar_settings.js).
    sidebar_config = {
        'links': links,
        'layout': layout,
        'saveUrl': url_for('system.sidebar_settings_save'),
        'resetUrl': url_for('system.sidebar_settings_reset'),
    }
    return render_template(
        'sidebar_settings.html',
        layout=layout,
        links=links,
        sidebar_config_json=sidebar_config,
        icon_choices=sidebar_nav_service.ICON_CHOICES,
        default_categories=list(sidebar_nav_service.DEFAULT_CATEGORIES),
        all_links_count=len(links),
    )


@bp.route('/settings/sidebar/save', methods=['POST'])
@login_required
def sidebar_settings_save():
    if not _can_manage_sidebar():
        return jsonify({'ok': False, 'error': 'Unauthorized: Admin access required.'}), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'ok': False, 'error': 'Invalid request body.'}), 400
    try:
        sidebar_nav_service.save_layout(payload)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception:
        logging.getLogger('app').exception('Sidebar layout save failed')
        db.session.rollback()
        return jsonify({
            'ok': False,
            'error': 'The sidebar layout could not be saved. Nothing was changed — please retry.',
        }), 500

    try:
        audit_log(current_user, 'update', 'Sidebar layout saved from Settings → Sidebar Settings')
    except Exception:
        pass
    return jsonify({
        'ok': True,
        'layout': sidebar_nav_service.layout_payload(),
        'message': 'Sidebar saved.',
    })


@bp.route('/settings/sidebar/reset', methods=['POST'])
@login_required
def sidebar_settings_reset():
    if not _can_manage_sidebar():
        return jsonify({'ok': False, 'error': 'Unauthorized: Admin access required.'}), 403
    try:
        sidebar_nav_service.reset_layout()
    except Exception:
        logging.getLogger('app').exception('Sidebar layout reset failed')
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'The sidebar layout could not be reset.'}), 500
    try:
        audit_log(current_user, 'update', 'Sidebar layout reset to defaults')
    except Exception:
        pass
    return jsonify({
        'ok': True,
        'layout': sidebar_nav_service.layout_payload(),
        'message': 'Sidebar reset to the default layout.',
    })
