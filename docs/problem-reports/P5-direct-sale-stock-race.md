# P5 — Concurrent Direct Sales can oversell stock

**Status:** SQLite sale-creation serialization added locally; not deployed.

At the start of POST `/add_direct_sale`, the route releases only the request session's pending read/touch transaction and acquires SQLite `BEGIN IMMEDIATE` before any stock validation. SQLite serializes competing writers, so a second sale validates after the first commits rather than against the same stale stock value. Other database dialects retain their existing locking path.

**Impact:** Prevents concurrent sales from both consuming the same stock in the SQLite deployment.

**Validation:** Full suite: 250 passed, 5 skipped; compile and whitespace checks passed. No concurrent two-client regression was added/run in this turn. The serialization is specifically for SQLite. No schema/data changes.
