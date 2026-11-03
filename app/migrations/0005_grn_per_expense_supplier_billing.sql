-- Move the retired whole-GRN billing choice onto each existing expense.
-- schema._ensure_model_columns() adds the nullable column before this runs.
-- NULL means "not migrated yet"; preserve the old balance exactly once, then
-- never overwrite an explicit per-expense choice on a later deployment.
UPDATE grn_charge
SET include_in_supplier = COALESCE(
    (SELECT g.include_charges_in_supplier FROM grn g WHERE g.id = grn_charge.grn_id),
    0
)
WHERE include_in_supplier IS NULL;
