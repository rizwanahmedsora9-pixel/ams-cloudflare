from models import db, AuditLog


def _actor_name(user):
    if not user:
        return None
    return (getattr(user, 'username', None) or '').strip() or None


def audit_log(user, action, details=None, extra=None):
    """
    Single-store audit logging. Always records the acting username.

    Accepts both:
      audit_log(user, action, details)
      audit_log(user, tenant_id, action, details)  # legacy 4-arg

    Normally uses an independent session so it never commits an in-flight
    request transaction. If SQLite already holds a write transaction, that
    separate connection would block on our own lock; stage the audit row in
    the request transaction instead, so it commits or rolls back with the work.
    """
    try:
        if extra is not None or (action is not None and not isinstance(action, str)):
            action, details = details, extra if extra is not None else details
        action = (str(action or 'unknown')).strip() or 'unknown'
        if isinstance(details, dict):
            details = ', '.join(f'{k}={v}' for k, v in details.items())
        elif details is not None:
            details = str(details)
        username = _actor_name(user)
        role = (getattr(user, 'role', None) or '').strip() if user else ''
        if username:
            prefix = f'by={username}'
            if role:
                prefix = f'{prefix} role={role}'
            details = f'{prefix} | {details}' if details else prefix
        bind = db.session.get_bind()
        row = AuditLog(
            user_id=(getattr(user, 'id', None) if user else None),
            username=username,
            action=action,
            details=details,
        )
        request_session = db.session()
        if bind.dialect.name == 'sqlite' and request_session.in_transaction():
            connection = request_session.connection()
            if connection.connection.driver_connection.in_transaction:
                request_session.add(row)
                return
        from sqlalchemy.orm import Session
        with Session(bind) as s:
            s.add(row)
            s.commit()
    except Exception:
        pass
