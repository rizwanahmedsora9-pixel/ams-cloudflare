# Data reset scope and safety

A full reset requires **every** dataset checkbox, the hard-cleanup override and
`DELETE ALL DATA`. The server determines full-reset mode from the boxes actually
submitted, not from automatically expanded dependencies. Admin and root are
permitted. A partial selection is a different operation, even if it selects many
boxes; partial resets may also remove related datasets. The partial preview is
an estimate, not a complete dependency graph.

Full reset deletes the business tables classified in `app/services/full_wipe.py`:
clients and categories; suppliers; inventory and GRNs; sales, bookings, invoices,
returns, payments and drivers; rentals; all account and cash/ledger/reconciliation
state; financial audit records, migration mappings and import job records. This
avoids stale identifiers and old migration mappings attaching to new data. A fresh
bill counter is installed. Built-in default categories and the walk-in client
may be recreated by the app when needed or on restart.

It preserves users, passwords, login sessions, settings, terms, navigation, schema
migration history, system audit and backup history. Backups and uploaded files on
disk are not erased. It does not securely erase data from disk, backups, exports,
logs or external systems. **Automatic pre-wipe backups are disabled**: create and
verify a separate backup before resetting if the data may be needed again.

The full reset uses the live SQLite foreign-key graph and is transactional.
Unrecognized tables are preserved and reported after a successful reset; they
may contain old data. If a preserved or unrecognized table has a foreign key
to a business table, the reset stops rather than modifying it through a cascade.
A relationship violation or deletion failure also blocks the reset and rolls
back the business-data changes. Queued or processing import jobs also block a
full reset. Stop other users and background imports while resetting to prevent
new writes after it completes. New database tables must be explicitly
classified as business or preserved and covered by the schema inventory test;
never add an unknown table to the deletion list without reviewing its contents.
