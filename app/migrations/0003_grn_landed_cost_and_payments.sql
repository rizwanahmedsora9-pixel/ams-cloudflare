-- 0003_grn_landed_cost_and_payments.sql
--
-- GRN receiving / landed cost / purchase payments redesign (approved 2026-11-02).
-- Additive and idempotent: no table rebuild and no historical money row is
-- modified in place.  Existing GRNs are marked LEGACY so their frozen FIFO
-- costs and their previously printed totals remain exactly as they were.
--
-- Owner rules:
--   A1  a GRN never pays; all payments come from Accounts.
--   A2  Supplier Ledger credit = sum(grn_item.qty * grn_item.price_at_time),
--       never freight/loading/unloading/other/tax/discount/adjustment.

-- The ORM creates this table through db.create_all(); this definition keeps
-- the release-deploy SQL runner self-contained on an older database.
CREATE TABLE IF NOT EXISTS grn_charge (
  id                    INTEGER PRIMARY KEY,
  grn_id                INTEGER NOT NULL REFERENCES grn(id),
  charge_type           VARCHAR(30) DEFAULT 'OTHER',
  label                 VARCHAR(160),
  amount                REAL DEFAULT 0,
  amount_minor          BIGINT DEFAULT 0,
  recipient_type        VARCHAR(30) DEFAULT 'OTHER',
  recipient_party_id    INTEGER REFERENCES cash_flow_party(id),
  recipient_name        VARCHAR(160),
  declared_status       VARCHAR(20) DEFAULT 'UNPAID',
  cost_treatment        VARCHAR(30) DEFAULT 'INVENTORY',
  allocation_basis      VARCHAR(20) DEFAULT 'VALUE',
  allocation_json       TEXT,
  is_void               BOOLEAN DEFAULT 0,
  is_legacy_mirror      BOOLEAN DEFAULT 0,
  legacy_column         VARCHAR(40),
  revision              INTEGER DEFAULT 1,
  created_by            VARCHAR(80),
  updated_by            VARCHAR(80),
  created_at            DATETIME,
  updated_at            DATETIME,
  note                  VARCHAR(500)
);

CREATE INDEX IF NOT EXISTS ix_grn_charge_grn        ON grn_charge(grn_id);
CREATE INDEX IF NOT EXISTS ix_grn_charge_party      ON grn_charge(recipient_party_id);
CREATE INDEX IF NOT EXISTS ix_grn_charge_recipient  ON grn_charge(recipient_type);
CREATE INDEX IF NOT EXISTS ix_grn_charge_grn_active ON grn_charge(grn_id, is_void);
CREATE UNIQUE INDEX IF NOT EXISTS uq_grn_charge_legacy
  ON grn_charge(grn_id, legacy_column) WHERE legacy_column IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_grn_costing_mode        ON grn(costing_mode);
CREATE INDEX IF NOT EXISTS ix_sp_grn                  ON supplier_payment(grn_id);
CREATE INDEX IF NOT EXISTS ix_sp_grn_charge           ON supplier_payment(grn_charge_id);
CREATE INDEX IF NOT EXISTS ix_sp_recipient_type       ON supplier_payment(recipient_type);
CREATE INDEX IF NOT EXISTS ix_sp_recipient_party      ON supplier_payment(recipient_party_id);
CREATE INDEX IF NOT EXISTS ix_sp_payment_kind         ON supplier_payment(payment_kind);
CREATE INDEX IF NOT EXISTS ix_atx_grn                 ON account_transaction(grn_id);
CREATE INDEX IF NOT EXISTS ix_atx_party               ON account_transaction(party_type, party_id);

-- ---------------------------------------------------------------------------
-- Backfill: every pre-existing GRN is a LEGACY document.
-- ---------------------------------------------------------------------------
UPDATE grn
   SET costing_mode = 'LEGACY',
       allocation_basis_default = COALESCE(allocation_basis_default, 'VALUE'),
       revision = COALESCE(revision, 1),
       is_cancelled = COALESCE(is_cancelled, 0)
 WHERE costing_mode IS NULL OR costing_mode = '';

UPDATE grn
   SET supplier_material_amount_minor = COALESCE((
         SELECT CAST(ROUND(SUM(gi.qty * gi.price_at_time) * 100, 0) AS INTEGER)
           FROM grn_item gi
          WHERE gi.grn_id = grn.id AND COALESCE(gi.is_void, 0) = 0
       ), 0)
 WHERE supplier_material_amount_minor IS NULL;

UPDATE grn
   SET supplier_material_amount = COALESCE(supplier_material_amount_minor, 0) / 100.0
 WHERE supplier_material_amount IS NULL;

UPDATE grn
   SET landed_cost_total_minor = COALESCE(supplier_material_amount_minor, 0)
                               + CAST(ROUND((COALESCE(loading_cost, 0)
                                            + COALESCE(freight_cost, 0)
                                            + COALESCE(other_expense, 0)
                                            + COALESCE(tax_amount, 0)
                                            - COALESCE(discount, 0)
                                            + COALESCE(adjustment_amount, 0)) * 100, 0) AS INTEGER)
 WHERE landed_cost_total_minor IS NULL;

UPDATE grn
   SET landed_cost_total = COALESCE(landed_cost_total_minor, 0) / 100.0,
       capitalised_charge_total = COALESCE(capitalised_charge_total, 0),
       capitalised_charge_total_minor = COALESCE(capitalised_charge_total_minor, 0),
       expense_charge_total = COALESCE(expense_charge_total, 0),
       expense_charge_total_minor = COALESCE(expense_charge_total_minor, 0)
 WHERE landed_cost_total IS NULL;

-- Legacy lots keep their historical cost rate (never rewritten).
UPDATE grn_item
   SET landed_unit_cost = COALESCE(price_at_time, 0),
       base_rate_minor = CAST(ROUND(COALESCE(price_at_time, 0) * 100, 0) AS INTEGER),
       allocated_charges_minor = 0,
       line_landed_cost_minor = CAST(ROUND(COALESCE(qty, 0) * COALESCE(price_at_time, 0) * 100, 0) AS INTEGER),
       landed_unit_cost_minor = CAST(ROUND(COALESCE(price_at_time, 0) * 100, 0) AS INTEGER),
       cost_revision = 0
 WHERE landed_unit_cost IS NULL OR landed_unit_cost = 0;

-- ---------------------------------------------------------------------------
-- Backfill: move legacy flat charges into their own (unassigned) obligations.
-- UNTRACKED_LEGACY keeps them out of inventory and P&L, so no historical
-- profit or COGS figure changes; they are simply no longer supplier payables.
-- ---------------------------------------------------------------------------
INSERT INTO grn_charge
  (grn_id, charge_type, label, amount, amount_minor, recipient_type,
   recipient_name, declared_status, cost_treatment, allocation_basis,
   is_void, is_legacy_mirror, legacy_column, created_at)
SELECT g.id, 'LOADING', 'Loading (legacy)',
       COALESCE(g.loading_cost, 0),
       CAST(ROUND(COALESCE(g.loading_cost, 0) * 100, 0) AS INTEGER),
       'UNSPECIFIED', 'Unassigned (legacy charge)', 'UNPAID',
       'UNTRACKED_LEGACY', 'VALUE', 0, 1, 'loading_cost', CURRENT_TIMESTAMP
  FROM grn g
 WHERE COALESCE(g.loading_cost, 0) > 0
   AND NOT EXISTS (SELECT 1 FROM grn_charge c
                    WHERE c.grn_id = g.id AND c.legacy_column = 'loading_cost');

INSERT INTO grn_charge
  (grn_id, charge_type, label, amount, amount_minor, recipient_type,
   recipient_name, declared_status, cost_treatment, allocation_basis,
   is_void, is_legacy_mirror, legacy_column, created_at)
SELECT g.id, 'VEHICLE_FARE', 'Vehicle fare / freight (legacy)',
       COALESCE(g.freight_cost, 0),
       CAST(ROUND(COALESCE(g.freight_cost, 0) * 100, 0) AS INTEGER),
       'UNSPECIFIED', 'Unassigned (legacy charge)', 'UNPAID',
       'UNTRACKED_LEGACY', 'VALUE', 0, 1, 'freight_cost', CURRENT_TIMESTAMP
  FROM grn g
 WHERE COALESCE(g.freight_cost, 0) > 0
   AND NOT EXISTS (SELECT 1 FROM grn_charge c
                    WHERE c.grn_id = g.id AND c.legacy_column = 'freight_cost');

INSERT INTO grn_charge
  (grn_id, charge_type, label, amount, amount_minor, recipient_type,
   recipient_name, declared_status, cost_treatment, allocation_basis,
   is_void, is_legacy_mirror, legacy_column, created_at)
SELECT g.id, 'OTHER', 'Other expense (legacy)',
       COALESCE(g.other_expense, 0),
       CAST(ROUND(COALESCE(g.other_expense, 0) * 100, 0) AS INTEGER),
       'UNSPECIFIED', 'Unassigned (legacy charge)', 'UNPAID',
       'UNTRACKED_LEGACY', 'VALUE', 0, 1, 'other_expense', CURRENT_TIMESTAMP
  FROM grn g
 WHERE COALESCE(g.other_expense, 0) > 0
   AND NOT EXISTS (SELECT 1 FROM grn_charge c
                    WHERE c.grn_id = g.id AND c.legacy_column = 'other_expense');

-- ---------------------------------------------------------------------------
-- Backfill: existing payments remain supplier/standalone documents.
-- ---------------------------------------------------------------------------
UPDATE supplier_payment
   SET recipient_type = 'SUPPLIER'
 WHERE recipient_type IS NULL OR recipient_type = '';

UPDATE supplier_payment
   SET payment_kind = 'LEGACY_GRN_AUTO'
 WHERE payment_kind IS NULL
   AND ((source_type = 'GRN' AND source_id IS NOT NULL)
        OR instr(lower(COALESCE(note, '')), '[auto_grn_pay:') > 0);

UPDATE supplier_payment
   SET payment_kind = 'STANDALONE'
 WHERE payment_kind IS NULL;

UPDATE supplier_payment
   SET grn_id = source_id
 WHERE grn_id IS NULL AND source_type = 'GRN' AND source_id IS NOT NULL;

UPDATE supplier_payment
   SET cash_posted = CASE WHEN EXISTS (
        SELECT 1 FROM account_transaction t
         WHERE t.source_type = 'SupplierPayment'
           AND t.source_id = supplier_payment.id
           AND COALESCE(t.is_void, 0) = 0
       ) THEN 1 ELSE 0 END
 WHERE cash_posted IS NULL;

UPDATE account_transaction
   SET grn_id = (SELECT p.grn_id FROM supplier_payment p WHERE p.id = account_transaction.source_id)
 WHERE grn_id IS NULL
   AND source_type = 'SupplierPayment'
   AND source_id IS NOT NULL
   AND EXISTS (SELECT 1 FROM supplier_payment p WHERE p.id = account_transaction.source_id AND p.grn_id IS NOT NULL);
