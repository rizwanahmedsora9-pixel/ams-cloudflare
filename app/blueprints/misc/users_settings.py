"""users_settings — split from misc.py."""
from ._common import *  # noqa
from werkzeug.security import generate_password_hash  # noqa: F401  (was missing: /add_user crashed with NameError)

@bp.route('/export_clients')
@login_required
def export_clients():
    if current_user.role not in ['admin', 'root']:
        flash('Only tenant admin or root can run import/export operations.', 'danger')
        return redirect(url_for('index'))
    from utils.excel_export import single_sheet_xlsx

    clients = Client.query.order_by(Client.name.asc()).all()
    pending_rows = db.session.query(
        PendingBill.client_code,
        func.sum(PendingBill.amount)
    ).filter(
        PendingBill.is_void == False,
        PendingBill.is_paid == False
    ).group_by(PendingBill.client_code).all()
    pending_map = {code: float(total or 0) for code, total in pending_rows if code}

    data = []
    for c in clients:
        data.append({
            'client_name': c.name,
            'client_code': c.code,
            'phone': c.phone or '',
            'address': c.address or '',
            'location_url': c.location_url or '',
            'category': c.category or '',
            'status': 'ACTIVE' if c.is_active else 'INACTIVE',
            'financial_book_no': c.financial_book_no or '',
            'financial_page_no': c.financial_page or '',
            'cement_book_no': c.cement_book_no or '',
            'cement_page_no': c.cement_page or '',
            'steel_book_no': c.steel_book_no or '',
            'steel_page_no': c.steel_page or '',
            'other_book_no': c.book_no or '',
            'notes': c.page_notes or '',
            'pending_amount': float(pending_map.get(c.code, 0.0))
        })

    output = single_sheet_xlsx('Clients', data, [
        'client_name', 'client_code', 'phone', 'address', 'location_url',
        'category', 'status', 'financial_book_no', 'financial_page_no',
        'cement_book_no', 'cement_page_no', 'steel_book_no', 'steel_page_no',
        'other_book_no', 'notes', 'pending_amount',
    ])

    return send_file(
        output,
        as_attachment=True,
        download_name=_download_filename('CLIENTLIST', 'xlsx'),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@bp.route('/add_user', methods=['POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        flash('Unauthorized', 'danger')
        return redirect(url_for('settings'))
    un = request.form.get('username', '').strip()
    raw_pw = str(request.form.get('password') or '').strip()
    if not raw_pw:
        raw_pw = os.environ.get('DEFAULT_TENANT_USER_PASSWORD', 'User@12345')
    pw = generate_password_hash(raw_pw)
    rl = request.form.get('role', 'user')

    if not un:
        flash('Username is required', 'danger')
        return redirect(url_for('settings'))
    if un.strip().lower() in ('admin', 'root'):
        flash('Admin is built into the app and cannot be created again.', 'danger')
        return redirect(url_for('settings'))
    if User.query.filter_by(username=un).first():
        flash('Username already exists', 'danger')
    else:
        permission_values = _permissions_from_request_form()
        restrict_backdated_grn_edit = ('restrict_backdated_edit' in request.form)
        access_mode = (request.form.get('access_mode') or 'read_write').strip().lower()
        if access_mode not in ('read_only', 'read_write'):
            access_mode = 'read_write'
        new_u = User(username=un,
                     password_hash=pw,
                     password_plain=None,
                     role=rl,
                     access_mode=access_mode,
                     restrict_backdated_edit=restrict_backdated_grn_edit,
                     can_manage_directory=(
                         permission_values.get('can_manage_clients', False)
                         or permission_values.get('can_manage_suppliers', False)
                         or permission_values.get('can_manage_materials', False)
                         or permission_values.get('can_manage_delivery_persons', False)
                     ),
                     **permission_values)
        db.session.add(new_u)
        db.session.commit()
        flash(f'User created. Login: {un} / {raw_pw}', 'success')
    return redirect(url_for('settings'))


@bp.route('/edit_user_permissions/<int:id>', methods=['POST'])
@login_required
def edit_user_permissions(id):
    if current_user.role != 'admin':
        flash('Unauthorized', 'danger')
        return redirect(url_for('settings'))
    u = db.session.get(User, id)
    if u and u.role != 'root' and u.username != 'admin':
        u.role = request.form.get('role', 'user')
        raw_pw = str(request.form.get('password') or '').strip()
        if raw_pw:
            u.password_hash = generate_password_hash(raw_pw)
            u.password_plain = None
        permission_values = _permissions_from_request_form()
        for field, value in permission_values.items():
            setattr(u, field, value)
        u.can_manage_directory = (
            permission_values.get('can_manage_clients', False)
            or permission_values.get('can_manage_suppliers', False)
            or permission_values.get('can_manage_materials', False)
            or permission_values.get('can_manage_delivery_persons', False)
        )
        u.restrict_backdated_edit = ('restrict_backdated_edit' in request.form)
        access_mode = (request.form.get('access_mode') or 'read_write').strip().lower()
        u.access_mode = access_mode if access_mode in ('read_only', 'read_write') else 'read_write'
        db.session.commit()
        flash('Permissions Updated', 'success')
    return redirect(url_for('settings'))


@bp.route('/delete_user/<int:id>', methods=['POST'])
@login_required
def delete_user(id):
    if current_user.role != 'admin':
        flash('Unauthorized', 'danger')
        return redirect(url_for('settings'))
    u = db.session.get(User, id)
    if u and u.role != 'root' and u.username != 'admin':
        if u.id == current_user.id:
            flash('You cannot deactivate your own account.', 'danger')
            return redirect(url_for('settings'))
        # Orphan-safe strategy: never hard-delete users. Keep historical references intact.
        u.status = 'inactive'
        if u.role != 'admin':
            u.role = 'user'
        db.session.commit()
        flash('User deactivated (kept for historical records).', 'warning')
    return redirect(url_for('settings'))


@bp.route('/toggle_user_status/<int:id>', methods=['POST'])
@login_required
def toggle_user_status(id):
    if current_user.role != 'admin':
        flash('Unauthorized', 'danger')
        return redirect(url_for('settings'))
    u = db.session.get(User, id)
    if u and u.role != 'root' and (u.username or '').strip().lower() != 'admin':
        if u.id == current_user.id:
            flash('You cannot change your own status.', 'danger')
            return redirect(url_for('settings'))
        current_status = (u.status or 'active').strip().lower()
        u.status = 'inactive' if current_status == 'active' else 'active'
        db.session.commit()
        action = 'suspended' if u.status == 'inactive' else 'activated'
        flash(f'User {u.username} {action}.', 'success')
    return redirect(url_for('settings'))


@bp.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    if current_user.role != 'admin':
        flash('Unauthorized', 'danger')
        return redirect(url_for('settings'))

    settings_obj = Settings.query.first()
    if not settings_obj:
        settings_obj = Settings()
        db.session.add(settings_obj)

    settings_obj.company_name = request.form.get('company_name', settings_obj.company_name or 'FAZAL BUILDING MATERIALS')
    settings_obj.company_address = request.form.get('company_address', settings_obj.company_address or 'JALAL PUR SOBTIAN GUJRAT')
    settings_obj.company_phone = request.form.get('company_phone', settings_obj.company_phone or '+92331-0000993 | +92340-3872722')
    # Urdu bill branding - optional, printed only on the Urdu sheet.
    settings_obj.proprietor_name_ur = (request.form.get('proprietor_name_ur') or '').strip()
    settings_obj.company_note_ur = (request.form.get('company_note_ur') or '').strip()
    settings_obj.currency = request.form.get('currency', settings_obj.currency or 'PKR')
    settings_obj.allow_global_negative_stock = 'allow_global_negative_stock' in request.form
    if 'public_base_url' in request.form:
        from app.services.public_url import normalize_public_origin
        raw_public_url = (request.form.get('public_base_url') or '').strip()
        if raw_public_url:
            normalized_url = normalize_public_origin(raw_public_url, allow_http=True)
            if not normalized_url:
                flash('Public QR / Cloudflare Worker URL must be a valid http:// or https:// origin with no path (e.g. https://still-base-ac7a.rizwanahmedsora9.workers.dev).', 'danger')
                return redirect(url_for('settings'))
            settings_obj.public_base_url = normalized_url
        else:
            settings_obj.public_base_url = ''

    db.session.commit()
    flash('Settings updated successfully', 'success')
    return redirect(url_for('settings'))


