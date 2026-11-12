# P8 — App booted after automatic migration failure

**Status:** Startup now fails closed on migration errors; not deployed.

If `run_sql_migrations()` raises, the app factory logs a critical error and raises `RuntimeError` instead of serving requests on a potentially partial schema. Migration SQL itself is not made transactional by this change; the app simply refuses to serve until the operator repairs/retries the migration.

**Impact:** Avoids users generating reports or writes against a known partial schema. Availability is intentionally sacrificed rather than risking data/report inconsistency.

**Validation:** Full suite: 250 passed, 5 skipped; ordinary startup is covered. No fault-injection test for migration failure was added. No schema/data changes.
