# P7 — HTTP request downgraded secure-cookie configuration globally

**Status:** Global mutation removed locally; not deployed.

Removed the `before_request` hook that changed `SESSION_COOKIE_SECURE`, `REMEMBER_COOKIE_SECURE`, and SameSite settings on the shared Flask app object for each HTTP request. The existing response-only HTTP cookie compatibility handling remains, so an HTTP response no longer changes configuration seen by concurrent HTTPS requests.

**Impact:** Prevents a request on one connection from weakening cookie settings application-wide.

**Validation:** Full suite: 250 passed, 5 skipped; compile and whitespace checks passed. No dedicated concurrent HTTP/HTTPS regression test added. The response-only HTTP cookie compatibility behavior remains. No schema/data changes.
