# app/migrations — automatic schema migrations

Numbered SQL files here are applied **automatically at every application
start** (which includes every deployment reload), by
`app/services/auto_migrate.py`.

## How to add a migration (future module / schema change)

1. Create a file named `NNNN_short_description.sql` (zero-padded number,
   higher than any existing file). Example: `0001_add_vendor_module.sql`.
2. Write plain SQLite DDL/DML — e.g. `CREATE TABLE ...`, `ALTER TABLE ...
   ADD COLUMN ...`, `CREATE UNIQUE INDEX ...`.
3. Restart the app (or deploy). The runner applies pending files in sorted
   order, records each in the `migration_history` table, and stamps the
   highest applied number into `schema_version`.

## Rules

- **Never edit an already-applied file.** Migration history records what ran
  on each database; changing an old file does not re-run it. Add a new
  higher-numbered file instead.
- Keep statements **safe to re-run** (`IF NOT EXISTS`, `INSERT OR IGNORE`):
  if a file fails mid-way, the statements before the failure stay applied and
  the file runs again on the next boot.
- **Destructive SQL is blocked by default**: `DROP TABLE`, `TRUNCATE TABLE`,
  `DELETE FROM` require `MIGRATIONS_ALLOW_DESTRUCTIVE=1` on the server (set
  deliberately, then remove).
- Files that are not `*.sql` (like this README) are ignored.
- New ORM tables also get created by `db.create_all()` on boot — migrations
  are for everything `create_all` cannot do: new columns with defaults,
  indexes / unique constraints on existing tables, renames, backfills.

## Current state

- `0001_restore_entry_auto_bill_unique_index.sql` — restores the partial
  UNIQUE index `uq_entry_auto_bill_no` that the old-data migration relaxes
  while loading, because the legacy data carries two duplicate GRN bill
  numbers (`SB-GRN-1024`, `SB-GRN-1042`; entry ids 9084/10116 and
  9830/10117).

  **This normally applies on the first start with nothing to do**: in each
  pair one row is a *voided* row, and the migration's void policy purges it, so
  no duplicate survives and the index can be created. Re-verified 2026-09-10 on
  the committed production pair — the migration tool now recreates the index
  itself (`INDEX RESTORED` in its report), and this file is the safety net that
  keeps `migration_history` consistent for any database that still ships with
  the relaxation, e.g. a `--keep-voided` archive.

  Only if a file *still* holds live duplicates (bit-for-bit archive, or legacy
  data re-imported) does it fail at `CREATE UNIQUE INDEX`, log, and retry at
  the next boot — boot is never blocked, and
  `_ensure_auto_bill_unique_indexes()` skips the index with a warning while
  duplicates exist. Resolving such a duplicate is a business decision (keep one
  row per bill number via `tools/repair_controlled/` after a backup).

The next schema change should ship as `0002_*.sql` here instead of a new
helper function.

- `0003_grn_landed_cost_and_payments.sql` — GRN receiving / landed cost /
  purchase payments redesign (approved 2026-11-02).  Creates `grn_charge`
  (self-contained for the release-deploy runner), adds indexes, and backfills
  pre-existing rows non-destructively:

  * every existing GRN becomes `costing_mode='LEGACY'`; its FIFO lot cost stays
    at `price_at_time`, so historical P&L never changes;
  * existing `loading_cost` / `freight_cost` / `other_expense` become
    `UNTRACKED_LEGACY` charge obligations owned by an unassigned recipient,
    never by the supplier (owner rule A2);
  * existing payments are classified as `SUPPLIER` / `LEGACY_GRN_AUTO` /
    `STANDALONE`, and their `grn_id` / `cash_posted` / account-transaction
    attribution is backfilled where resolvable.

  New ORM columns are added automatically by `schema._ensure_model_columns()`.
  No table rebuild, no destructive DDL, and no historical money row is
  rewritten.  `0004_*.sql` is the next file name.

The next schema change should ship as `0004_*.sql`.
