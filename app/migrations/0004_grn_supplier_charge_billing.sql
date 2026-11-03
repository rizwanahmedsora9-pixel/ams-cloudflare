-- 0004_grn_supplier_charge_billing.sql
-- Optional per-GRN billing choice: include applicable GRN charges in the
-- supplier ledger / Accounts payable.  The column is created by the ORM /
-- _ensure_model_columns before this migration runs.  Existing GRNs keep the
-- previous material-only supplier billing (0).  Inventory/COGS is unchanged.
UPDATE grn SET include_charges_in_supplier = 0 WHERE include_charges_in_supplier IS NULL;
