# P9 — Logout was triggered by a GET request

**Status:** POST-only logout and form-based controls added locally; not deployed.

`/logout` now accepts POST only. Both mobile and desktop logout controls in `templates/layout.html` are POST forms carrying the session CSRF token. A GET request now receives 405 rather than ending the session.

**Impact:** Stops cross-site links/images from forcing a logout; does not change login/account authorization.

**Validation:** Tests verify GET rejection and POST logout. Focused suite: 31 passed. Full suite: 250 passed, 5 skipped. `git diff --check` and compile checks passed. No schema/data changes.
