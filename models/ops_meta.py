from .__base import *  # noqa
from .helpers import *  # noqa

class TenantWipeBackupHistory(db.Model):
    """
    Legacy multi-tenant table retained in some historical DB backups.
    In single-store mode, the application does not use tenant wipe history.
    """
    __tablename__ = 'tenant_wipe_backup_history'
    id = db.Column(db.Integer, primary_key=True)
    tenant_name = db.Column(db.String(120), nullable=True)
    performed_by = db.Column(db.String(80), nullable=True)
    targets = db.Column(db.String(1000), nullable=True)
    backup_filename = db.Column(db.String(255), nullable=True)
    backup_path = db.Column(db.String(1000), nullable=True)
    wipe_status = db.Column(db.String(20), default='pending', index=True)
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class RootBackupSettings(db.Model):
    __tablename__ = 'root_backup_settings'
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    frequency = db.Column(db.String(20), default='hourly', nullable=False)
    recipient_emails = db.Column(db.String(1000), nullable=True)
    include_full_raw_xlsx = db.Column(db.Boolean, default=True, nullable=False)
    include_sqlite_db = db.Column(db.Boolean, default=True, nullable=False)
    subject_prefix = db.Column(db.String(120), default='PWARE Root Backup', nullable=False)
    keep_history_count = db.Column(db.Integer, default=200, nullable=False)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    last_status = db.Column(db.String(20), nullable=True)
    last_message = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=pk_model_now, onupdate=pk_model_now, index=True)


class RootBackupEmailHistory(db.Model):
    __tablename__ = 'root_backup_email_history'
    id = db.Column(db.Integer, primary_key=True)
    trigger_type = db.Column(db.String(30), default='auto', nullable=False, index=True)
    status = db.Column(db.String(20), default='failed', nullable=False, index=True)
    recipient_emails = db.Column(db.String(1000), nullable=True)
    subject = db.Column(db.String(300), nullable=True)
    attachment_name = db.Column(db.String(255), nullable=True)
    attachment_size_kb = db.Column(db.Integer, nullable=True)
    backup_path = db.Column(db.String(1000), nullable=True)
    message = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class DailyDbBackupSettings(db.Model):
    """Admin-facing daily database backup + email configuration.

    One row (id = 1).  The password is never stored here: it is read from the
    ``AMS_BACKUP_SMTP_PASSWORD`` environment variable so a database copy can
    never leak the mail credential.
    """
    __tablename__ = 'daily_db_backup_settings'
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    # 'auto' → follow the app's Pakistan-time calendar day (one backup per day).
    # 'HH:MM' → run at that Pakistan-time clock time each day.
    run_at = db.Column(db.String(5), default='auto', nullable=False)
    recipient_emails = db.Column(db.String(500), nullable=True)
    include_db = db.Column(db.Boolean, default=True, nullable=False)
    include_uploads = db.Column(db.Boolean, default=False, nullable=False)
    # Empty → keep a single file (the newest replaces the old on every run).
    keep_days = db.Column(db.Integer, default=1, nullable=False)
    email_db_attachment = db.Column(db.Boolean, default=True, nullable=False)
    mail_host = db.Column(db.String(200), nullable=True)
    mail_port = db.Column(db.Integer, default=587, nullable=False)
    mail_security = db.Column(db.String(10), default='starttls', nullable=False)
    mail_username = db.Column(db.String(200), nullable=True)
    mail_from = db.Column(db.String(200), nullable=True)
    smtp_timeout_seconds = db.Column(db.Integer, default=60, nullable=False)
    last_run_at = db.Column(db.DateTime, nullable=True)
    last_status = db.Column(db.String(20), nullable=True)
    last_message = db.Column(db.String(1000), nullable=True)
    updated_at = db.Column(db.DateTime, default=pk_model_now, onupdate=pk_model_now)


class DailyDbBackupHistory(db.Model):
    """Outcome of every automatic/manual daily backup run."""
    __tablename__ = 'daily_db_backup_history'
    id = db.Column(db.Integer, primary_key=True)
    trigger_type = db.Column(db.String(20), default='auto', nullable=False, index=True)
    status = db.Column(db.String(20), default='failed', nullable=False, index=True)
    backup_path = db.Column(db.String(1000), nullable=True)
    backup_name = db.Column(db.String(255), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)
    recipients = db.Column(db.String(500), nullable=True)
    email_status = db.Column(db.String(20), nullable=True)
    email_error = db.Column(db.String(1000), nullable=True)
    message = db.Column(db.String(1000), nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class StaffEmail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class FollowUpReminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pending_bill_id = db.Column(db.Integer, db.ForeignKey('pending_bill.id'), nullable=False)
    remind_at = db.Column(db.DateTime, nullable=False)
    note = db.Column(db.String(500))
    is_done = db.Column(db.Boolean, default=False)
    alerted_at = db.Column(db.DateTime)
    acknowledged_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)

    pending_bill = db.relationship('PendingBill', backref=db.backref('reminders', lazy=True, cascade='all, delete-orphan'))


class FollowUpContact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pending_bill_id = db.Column(db.Integer, db.ForeignKey('pending_bill.id'), nullable=False)
    reminder_id = db.Column(db.Integer, db.ForeignKey('follow_up_reminder.id'))
    contacted_at = db.Column(db.DateTime, default=pk_model_now, nullable=False)
    channel = db.Column(db.String(30), default='Call')
    response = db.Column(db.String(200))
    outcome = db.Column(db.String(20))
    note = db.Column(db.String(500))
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)

    pending_bill = db.relationship('PendingBill', backref=db.backref('contact_logs', lazy=True, cascade='all, delete-orphan'))
    reminder = db.relationship('FollowUpReminder', backref=db.backref('closure_contact_logs', lazy=True))


class ReconBasket(db.Model):
    """Reconciliation Basket for Data Lab"""
    id = db.Column(db.Integer, primary_key=True)
    bill_no = db.Column(db.String(50))
    inv_date = db.Column(db.Date)
    inv_client = db.Column(db.String(100))
    fin_client = db.Column(db.String(100))
    inv_material = db.Column(db.String(100))
    inv_qty = db.Column(db.Float, default=0)
    status = db.Column(db.String(20))
    match_score = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)

