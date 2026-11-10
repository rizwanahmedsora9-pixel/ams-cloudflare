"""Atomic full business-data reset. Identity, configuration and system audit survive.

Keep deletion explicit: unknown tables are preserved, not silently deleted. New
business tables must be classified here and covered by the schema inventory test.

Why this module is defensive
----------------------------
A shop-floor database is a moving target while the wipe runs: another manager may
have the app open, an import may be finishing and the background backup/reconcile
workers write on their own schedule.  The first version of this reset simply ran
``DELETE FROM`` per table inside one transaction, so a single ``database is
locked`` (or one legacy constraint) aborted the whole reset — the operator saw
"a data error, no changes were saved" and the store stayed dirty.

Two guarantees are enforced here:

1.  **The reset either completes or changes nothing.**  Every delete runs inside
    the caller's transaction (savepoint protected), and the tables are verified
    empty plus ``PRAGMA foreign_key_check`` clean before returning.
2.  **A failure explains itself.**  Failures raise :class:`WipeError` with a
    message that is safe to show (no SQL) but still names the step, and transient
    SQLite contention is retried instead of surfacing as a dead end.
"""
from __future__ import annotations

import logging
import os
import time

from sqlalchemy import MetaData, Table, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.ddl import sort_tables_and_constraints

from models import BillCounter, db
from app.services.constants import AUTO_BILL_NS_DEFAULT

LOG = logging.getLogger('wipe')

FULL_WIPE_TARGETS = frozenset({
    'clients', 'suppliers', 'supplier_payments', 'pending_bills', 'notifications',
    'bookings', 'dispatching', 'receiving', 'grn', 'materials', 'material_categories',
    'services', 'direct_sales', 'material_returns', 'delivery_rents', 'delivery_persons',
    'delivery_person_payments', 'invoices', 'payments', 'direct_sale_drafts',
    'accounts', 'account_categories', 'account_transactions', 'account_reconciliations',
    'cash_flow_entries', 'cash_flow_categories', 'daily_reconciliation',
    'cash_reconciliation_data', 'cash_reconciliation_audit', 'cash_drawer_entries',
    'cash_drawer_categories', 'fbm_rentals', 'fbm_rental_clients', 'fbm_rental_items',
})

BUSINESS_TABLES = frozenset({
    'account', 'account_category', 'account_reconciliation', 'account_transaction',
    'accounting_audit_log', 'future_account_audit_log', 'bill_counter',
    'loan_movement', 'loan_party',
    'booking', 'booking_item', 'booking_allocation', 'booking_allocation_repair_archive',
    'cash_day_account_position', 'cash_day_difference', 'cash_day_lock',
    'cash_day_shift_close', 'cash_day_shift_close_position', 'cash_flow_category',
    'cash_flow_difference_adjustment', 'cash_flow_entry', 'cash_flow_entry_audit',
    'cash_flow_party', 'cash_flow_reconciliation_audit', 'cash_flow_subcategory',
    'client', 'client_category', 'delivery', 'delivery_item', 'delivery_person',
    'delivery_person_payment', 'delivery_rent', 'direct_sale', 'direct_sale_draft',
    'direct_sale_item', 'entry', 'fbm_cash_drawer_category', 'fbm_cash_drawer_entry',
    'fbm_client', 'fbm_rental', 'fbm_rental_item', 'follow_up_contact',
    'follow_up_reminder', 'grn', 'grn_allocation', 'grn_charge', 'grn_item',
    'invoice', 'material', 'material_category', 'material_return', 'material_return_item',
    'payment', 'pending_bill', 'recon_basket', 'sale_delivery_persons', 'service',
    'staff_email', 'supplier', 'supplier_payment', 'waive_off',
    'migration_mapping', 'migration_row', 'migration_run',
    'import_history_entry', 'import_job', 'import_upload',
})

# Deliberately preserved: authentication, configuration, system history and backup records.
PRESERVED_TABLES = frozenset({
    'audit_log', 'daily_db_backup_history', 'daily_db_backup_settings',
    'root_backup_email_history', 'root_backup_settings', 'root_recovery_code',
    'schema_version', 'migration_history', 'settings', 'sidebar_category', 'sidebar_item', 'system_lock',
    'tenant_wipe_backup_history', 'terms_and_conditions', 'user', 'user_login_session',
})

# An import job older than this cannot still be writing rows: it is a leftover
# from a crashed/interrupted import and is itself part of the data being reset.
ACTIVE_IMPORT_WINDOW_SECONDS = int(os.environ.get('WIPE_ACTIVE_IMPORT_WINDOW', '600') or 600)

# SQLite contention retries (another window / backup copy / worker thread).
LOCK_RETRIES = max(1, int(os.environ.get('WIPE_LOCK_RETRIES', '4') or 4))
LOCK_RETRY_DELAY = float(os.environ.get('WIPE_LOCK_RETRY_DELAY', '1.5') or 1.5)
BUSY_TIMEOUT_MS = max(0, int(os.environ.get('WIPE_BUSY_TIMEOUT_MS', '15000') or 15000))

_TRANSIENT_SIGNATURES = (
    'database is locked',
    'database table is locked',
    'database schema is locked',
    'database is busy',
    'disk i/o error',
    'busy timeout',
)


class WipeError(RuntimeError):
    """A wipe failure whose message is safe (and useful) to show the operator."""


def _q(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def is_transient_lock_error(exc: BaseException) -> bool:
    """True when SQLite refused the write because another writer held the file."""
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        blob = f'{type(current).__name__} {current}'.lower()
        if any(sig in blob for sig in _TRANSIENT_SIGNATURES):
            return True
        current = getattr(current, '__cause__', None) or getattr(current, '__context__', None)
    return False


def _active_import_jobs(conn) -> int:
    """Queued/processing imports that were touched recently enough to be live.

    The cutoff is computed with the application clock (``pk_now``), which is the
    same clock that stamps ``import_job.updated_at``.  Comparing against SQLite's
    UTC ``datetime('now')`` misjudged jobs on PK-time installations.
    """
    from datetime import timedelta

    from app.services.time_money import pk_now

    cutoff = (pk_now() - timedelta(seconds=ACTIVE_IMPORT_WINDOW_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')
    row = conn.execute(text(
        "SELECT COUNT(*) FROM import_job "
        "WHERE status IN ('queued', 'processing') "
        "AND COALESCE(updated_at, created_at) >= :cutoff"
    ), {'cutoff': cutoff}).scalar()
    return int(row or 0)


def _null_out_foreign_keys(session, conn, names, inspector):
    """Disconnect every business row before deleting anything.

    Legacy installations can carry foreign keys the ORM does not model — old
    ``RESTRICT`` links, cycles between the reconciliation and ledger tables, or
    columns that became ``NOT NULL`` over time.  Any of those abort a plain
    ``DELETE FROM`` ordering.  Nulling *nullable* links (checked against the live
    schema, not the model) first makes the delete order irrelevant.

    This is safe: every row in these tables is about to be removed; the FK graph
    is re-verified with ``PRAGMA foreign_key_check`` before commit.
    """
    columns = {}
    for name in names:
        columns[name] = {c['name']: c for c in inspector.get_columns(name)}

    nulled = 0
    for name in sorted(names):
        for fk in inspector.get_foreign_keys(name):
            target = fk.get('referred_table')
            if target not in names:
                continue
            for column in fk.get('constrained_columns') or []:
                info = columns.get(name, {}).get(column)
                if not info or not info.get('nullable'):
                    continue
                try:
                    result = conn.execute(text(
                        f'UPDATE {_q(name)} SET {_q(column)} = NULL '
                        f'WHERE {_q(column)} IS NOT NULL'
                    ))
                    nulled += max(0, int(result.rowcount or 0))
                except Exception:  # noqa: BLE001 - a blocked unlink must not abort
                    LOG.debug('Could not unlink %s.%s before wipe', name, column)
    if nulled:
        LOG.info('Full wipe pre-pass unlinked %s foreign-key values', nulled)


def _wipe_once(session):
    s = session or db.session
    conn = s.connection()
    if conn.dialect.name != 'sqlite':
        raise WipeError(
            'This build can only reset a SQLite database. No changes were saved; '
            'contact support before wiping this installation.'
        )
    if BUSY_TIMEOUT_MS:
        try:
            conn.exec_driver_sql(f'PRAGMA busy_timeout={int(BUSY_TIMEOUT_MS)}')
        except Exception:  # noqa: BLE001
            pass

    inspector = inspect(conn)
    present = set(inspector.get_table_names()) - {'sqlite_sequence'}
    unknown = present - BUSINESS_TABLES - PRESERVED_TABLES
    names = BUSINESS_TABLES & present

    # An extension table may be unrelated to the reset. Preserve it, but never
    # let ON DELETE CASCADE/SET NULL mutate any unclassified or system table.
    # We cannot infer whether unknown tables contain business data, so the
    # caller must warn that they remain after a successful reset.
    for name in sorted(present - names):
        for fk in inspector.get_foreign_keys(name):
            if fk.get('referred_table') in names:
                raise WipeError(
                    'A preserved or unrecognized table references business data; '
                    'the wipe was stopped to protect it. No changes were saved — '
                    f'contact support to review table {name}.'
                )

    if 'import_job' in names and _active_import_jobs(conn):
        raise WipeError(
            'A data import is still running or queued. Wait for it to finish (or '
            'cancel it on the Import / Export page) and retry — no changes were saved.'
        )

    # Break every nullable link between business tables first: delete order and
    # legacy constraints then cannot abort the reset.
    _null_out_foreign_keys(s, conn, names, inspector)

    metadata = MetaData()
    tables = {name: Table(name, metadata, autoload_with=conn) for name in names}
    conn.execute(text('PRAGMA defer_foreign_keys=ON'))
    # Child first; deferral handles cycles and legacy constraints not nullable.
    ordered = [table for table, _ in sort_tables_and_constraints(list(tables.values())) if table is not None]
    for table in reversed(ordered):
        try:
            with s.begin_nested():
                s.execute(table.delete())
        except IntegrityError as exc:
            LOG.exception('Full wipe blocked on table %s', table.name)
            raise WipeError(
                f'A stored rule blocked clearing "{table.name}" data. '
                'No changes were saved — run Admin → Rebuild ERP Consistency, then '
                'retry; if it still fails, contact support with the time of this attempt.'
            ) from exc

    if 'bill_counter' in tables:
        s.add(BillCounter(namespace=AUTO_BILL_NS_DEFAULT, count=1000))
    s.flush()

    violations = conn.execute(text('PRAGMA foreign_key_check')).fetchall()
    if violations:
        offending = sorted({str(row[0]) for row in violations})
        LOG.error('Full wipe left foreign-key violations in: %s', offending)
        raise WipeError(
            'The reset could not satisfy every database relationship '
            f'(affected: {", ".join(offending[:6])}). No changes were saved.'
        )
    # Delete triggers must not silently repopulate tables already processed.
    for table in tables.values():
        if s.execute(table.select().limit(1)).first() and table.name != 'bill_counter':
            raise WipeError(
                f'The full wipe could not clear all business data: "{table.name}" was '
                'repopulated while wiping (a database trigger re-inserts it). '
                'No changes were saved — contact support.'
            )
    return sorted(unknown)


def wipe_all_business_data(session=None):
    """Delete classified business tables, validate FKs, and leave commit to caller.

    Retries the whole reset when SQLite reports contention, so a backup copy or a
    second logged-in manager cannot turn the reset into "a data error".
    """
    s = session or db.session
    attempts = LOCK_RETRIES
    last_error = None
    # Background writers (auto-reconcile, hourly/daily backups) stand down while
    # the reset owns the database — that contention is what made wipes fail.
    from app.services import state

    previous_flag = getattr(state, 'WIPE_IN_PROGRESS', False)
    state.WIPE_IN_PROGRESS = True
    try:
        for attempt in range(1, attempts + 1):
            try:
                return _wipe_once(s)
            except WipeError:
                raise
            except Exception as exc:  # noqa: BLE001
                if not is_transient_lock_error(exc):
                    raise
                last_error = exc
                LOG.warning(
                    'Full wipe hit database contention (attempt %s/%s): %s',
                    attempt, attempts, str(exc).splitlines()[0][:160],
                )
                try:
                    s.rollback()
                except Exception:  # noqa: BLE001
                    pass
                if attempt < attempts:
                    time.sleep(LOCK_RETRY_DELAY * attempt)
        raise WipeError(
            'The database stayed in use while wiping (another window, a running '
            f'backup or an import). No changes were saved after {attempts} attempts — '
            'close other windows on this PC and retry in a minute.'
        ) from last_error
    finally:
        state.WIPE_IN_PROGRESS = previous_flag
