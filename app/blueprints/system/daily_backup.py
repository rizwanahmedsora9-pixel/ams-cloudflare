"""settings/daily database backup — admin UI for the automatic daily backup.

Admin-facing (``role == 'admin'`` or ``can_access_settings``).  The legacy
``require_root`` "Root Backup Settings" page stays a 404 in single-store mode,
so this is the page a real store actually uses.
"""
from ._common import *  # noqa

from flask import send_file, current_app

from app.services import daily_backup as daily_backup_svc


def _backup_admin_guard():
    """Return a redirect response when the caller is not an admin."""
    if current_user.role == 'admin' or _user_can('can_access_settings'):
        return None
    flash('Unauthorized: Admin access required.', 'danger')
    return redirect(url_for('index'))


def _settings_for_page():
    row = daily_backup_svc.get_settings(create=True)
    # Never ship the SMTP password to the browser: only whether one is set.
    return row, daily_backup_svc.status_snapshot(current_app)


@bp.route('/settings/daily-backup')
@login_required
def daily_backup_settings():
    denied = _backup_admin_guard()
    if denied:
        return denied
    row, snapshot = _settings_for_page()
    history = (
        DailyDbBackupHistory.query
        .order_by(DailyDbBackupHistory.finished_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        'daily_backup_settings.html',
        row=row,
        snapshot=snapshot,
        history=history,
        password_configured=daily_backup_svc._smtp_password() != '',
        default_smtp_password_env='AMS_BACKUP_SMTP_PASSWORD',
    )


@bp.route('/settings/daily-backup/save', methods=['POST'])
@login_required
def daily_backup_settings_save():
    denied = _backup_admin_guard()
    if denied:
        return denied
    row = daily_backup_svc.get_settings(create=True)
    form = request.form

    row.enabled = 'enabled' in form
    run_at = (form.get('run_at') or 'auto').strip().lower()
    if run_at not in ('auto', '') and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', run_at):
        flash('Run time must be "auto" or a valid HH:MM time.', 'danger')
        return redirect(url_for('system.daily_backup_settings'))
    row.run_at = run_at or 'auto'

    recipients = daily_backup_svc._parse_recipients(form.get('recipient_emails'))
    row.recipient_emails = ', '.join(recipients)

    row.include_db = 'include_db' in form
    row.include_uploads = 'include_uploads' in form
    row.email_db_attachment = 'email_db_attachment' in form

    try:
        keep_days = int(form.get('keep_days') or 1)
    except (TypeError, ValueError):
        keep_days = 1
    row.keep_days = max(1, min(365, keep_days))

    row.mail_host = (form.get('mail_host') or '').strip()
    try:
        port = int(form.get('mail_port') or 0)
    except (TypeError, ValueError):
        port = 0
    row.mail_port = max(0, min(65535, port))
    security = (form.get('mail_security') or 'starttls').strip().lower()
    row.mail_security = security if security in ('starttls', 'ssl', 'none') else 'starttls'
    row.mail_username = (form.get('mail_username') or '').strip()
    row.mail_from = (form.get('mail_from') or '').strip()
    try:
        timeout = int(form.get('smtp_timeout_seconds') or 60)
    except (TypeError, ValueError):
        timeout = 60
    row.smtp_timeout_seconds = max(5, min(600, timeout))

    if row.enabled:
        if not row.recipient_emails:
            flash('Add at least one recipient email before enabling the daily backup email.', 'danger')
            return redirect(url_for('system.daily_backup_settings'))
        if not row.mail_host:
            flash('Enter the SMTP server (e.g. smtp.gmail.com) before enabling the email.', 'danger')
            return redirect(url_for('system.daily_backup_settings'))

    db.session.commit()
    db.session.refresh(row)
    audit_log('UPDATE', 'DailyDbBackupSettings', row.id,
              'Saved daily database backup settings')
    flash('Daily database backup settings updated.', 'success')
    return redirect(url_for('system.daily_backup_settings'))


@bp.route('/settings/daily-backup/run-now', methods=['POST'])
@login_required
def daily_backup_run_now():
    denied = _backup_admin_guard()
    if denied:
        return denied
    result = daily_backup_svc.run_daily_backup(current_app, force=True, send_email=True)
    audit_log('BACKUP', 'DailyDbBackup', 0, result.get('message', '')[:200])
    flash(result.get('message') or 'Backup finished.', 'success' if result.get('ok') else 'danger')
    return redirect(url_for('system.daily_backup_settings'))


@bp.route('/settings/daily-backup/test-email', methods=['POST'])
@login_required
def daily_backup_test_email():
    denied = _backup_admin_guard()
    if denied:
        return denied
    ok, message = daily_backup_svc.send_test_email(current_app)
    flash(message, 'success' if ok else 'danger')
    return redirect(url_for('system.daily_backup_settings'))


@bp.route('/settings/daily-backup/download')
@login_required
def daily_backup_download():
    denied = _backup_admin_guard()
    if denied:
        return denied
    latest = daily_backup_svc.latest_backup(current_app)
    if latest is None:
        flash('No database backup file exists yet.', 'danger')
        return redirect(url_for('system.daily_backup_settings'))
    return send_file(latest, as_attachment=True, download_name=latest.name,
                     mimetype='application/x-sqlite3')
