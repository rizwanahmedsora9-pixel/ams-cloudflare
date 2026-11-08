-- 0010_company_address_gujrat.sql
--
-- The shop address is Jalal Pur Sobtian, Gujrat.  Databases created before
-- this release carry the old default ('JALAL PUR SOBTIAN' without the district
-- on Settings, and the same short address on printed receipts).
--
-- Only the untouched legacy default is completed: an address an admin has
-- edited is never rewritten.
--
-- Re-run safety: after the first run the row no longer matches the WHERE
-- clause, so a second run is a no-op.

UPDATE settings
SET company_address = 'JALAL PUR SOBTIAN GUJRAT'
WHERE UPPER(TRIM(company_address)) = 'JALAL PUR SOBTIAN';
