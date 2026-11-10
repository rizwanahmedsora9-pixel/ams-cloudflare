"""Atomic full business-data reset. Identity, configuration and system audit survive.

Keep deletion explicit: unknown tables are preserved, not silently deleted. New
business tables must be classified here and covered by the schema inventory test.
"""
from sqlalchemy import MetaData, Table, inspect, text
from sqlalchemy.sql.ddl import sort_tables_and_constraints

from models import BillCounter, db
from app.services.constants import AUTO_BILL_NS_DEFAULT

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


def wipe_all_business_data(session=None):
    """Delete classified business tables, validate FKs, and leave commit to caller.

    Reflect the live database, not just ORM FKs: older installations may have
    additional constraints. Do not disable FK checking or commit partway through.
    """
    s = session or db.session
    conn = s.connection()
    if conn.dialect.name != 'sqlite':
        raise RuntimeError('Full wipe currently requires SQLite')
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
                raise RuntimeError(
                    'A preserved or unrecognized table references business data; '
                    'the wipe was stopped to protect it. Contact support to review '
                    f'table {name}. No data was changed.'
                )

    metadata = MetaData()
    tables = {name: Table(name, metadata, autoload_with=conn) for name in names}
    # Self-references (such as merged clients and reconciliation chains) can
    # otherwise block bulk DELETE on immediate SQLite FK checks.
    for table in tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name == table.name and fk.parent.nullable:
                s.execute(table.update().where(fk.parent.is_not(None)).values({fk.parent.name: None}))
    if 'import_job' in tables:
        active = s.execute(
            text("SELECT COUNT(*) FROM import_job WHERE status IN ('queued', 'processing')")
        ).scalar_one()
        if active:
            raise RuntimeError('A data import is still running or queued. Finish or cancel it before wiping.')
    conn.execute(text('PRAGMA defer_foreign_keys=ON'))
    # Child first; deferral handles cycles and legacy constraints not nullable.
    ordered = [table for table, _ in sort_tables_and_constraints(list(tables.values())) if table is not None]
    for table in reversed(ordered):
        s.execute(table.delete())
    s.add(BillCounter(namespace=AUTO_BILL_NS_DEFAULT, count=1000))
    s.flush()
    violations = conn.execute(text('PRAGMA foreign_key_check')).fetchall()
    if violations:
        raise RuntimeError('Full wipe failed database relationship verification; no data was changed.')
    # Delete triggers must not silently repopulate tables already processed.
    for table in tables.values():
        if s.execute(table.select().limit(1)).first() and table.name != 'bill_counter':
            raise RuntimeError('Full wipe could not clear all business data. No data was changed.')
    return sorted(unknown)
