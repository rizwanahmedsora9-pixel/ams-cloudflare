-- 0012_public_base_url_setting.sql
--
-- Restore the Cloudflare Worker origin as the default public QR URL on any
-- existing Settings row that has never had public_base_url configured (NULL).
-- Admin-edited URLs or explicitly cleared blank strings ('') are untouched.

UPDATE settings
SET public_base_url = 'https://still-base-ac7a.rizwanahmedsora9.workers.dev'
WHERE public_base_url IS NULL;
