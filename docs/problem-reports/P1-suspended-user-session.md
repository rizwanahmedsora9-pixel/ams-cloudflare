# P1 — Suspended user can keep using an existing session

## Status

**Fixed locally and validated on 2026-11-12. Not deployed.**

The fix is saved on branch `arena/106d413c-git-recovered`. The complete test
suite, real-process smoke checks, and a separate real-socket suspension check
passed. All testing used disposable SQLite databases, not production data.
Only P1 is addressed; P2–P9 and R1–R9 remain unchanged.

## Plain-English problem report

| Field | Details |
| --- | --- |
| ID | P1 |
| Module | Auth / Users / Permissions |
| Main page | Settings → User Permissions → Suspend |
| Main URLs | `/settings`; POST `/toggle_user_status/<id>` |
| Related screen | Settings → Live logins (`/settings/sessions`) |
| Problem | Suspension stopped a new password login, but an already authenticated browser could continue opening protected pages and saving data. |
| Expected behavior | Once suspension is committed, the suspended account cannot use an existing session or remember-me cookie on its next request. Other active users and the acting administrator remain signed in. |
| Confirmed evidence | Before the fix, 9 of 12 selected regression cases failed. A suspended account could still open `/clients` and create a client through POST in a disposable database. |
| Direct impact | Unauthorized access and writes after suspension. |
| Indirect impact | Any report fed by records the suspended user changes: client ledgers, sales, payments, stock, cash/bank balances, and profit. This is not a report-formula defect by itself. |
| Data/schema impact of fix | None. Reuses the existing `User.status` field; no financial recalculation or migration. |

## Root cause

- `app/blueprints/misc/users_settings.py` changes `User.status` to `inactive`
  when an administrator suspends or deactivates another account.
- `app/blueprints/auth.py` checked status during password login.
- `app/services/permissions.py::load_user` restored the User row for Flask-Login
  on later requests without checking that status.
- `models/core.py::User` inherited `UserMixin.is_active`, which always returns
  `True` and does not reflect this application's `status` column.
- Session protection is intentionally disabled to allow concurrent LAN logins.
  Changing that policy would risk unrelated logouts and was not necessary.

## Changes made

| File | Purpose |
| --- | --- |
| `models/core.py` | Derive `User.is_active` from the existing status field using the same case-insensitive, whitespace-tolerant rule as password login. Empty or unknown statuses fail closed. |
| `app/services/permissions.py` | Reject an inactive account in the central user loader. This covers existing sessions and remember-me restoration while preserving transient database-lock retries. |
| `app/blueprints/auth.py` | Reuse `User.is_active` for the existing password-login check, keeping both authentication paths consistent. |
| `templates/settings.html` | Explain that suspension stops access on the next request, including in open browsers, while past sales remain under the user's name. |
| `tests/test_error_handling.py` | Give the active-user stand-in in the existing retry test the newly used `is_active` property. No retry behavior was changed. |
| `tests/test_suspended_user_sessions.py` | Add 19 regression cases using real authentication/session hooks, protected reads and writes, and enforced CSRF. |
| `PROBLEM_REPORTING.md` | Add the repository-wide instructions for reporting and fixing one problem at a time. |

The application/template change is deliberately small: four tracked application
files plus one existing-test adjustment, totaling 23 added and 4 removed lines.
No financial routes, formulas, tables, passwords, CSRF policy, concurrent-login
policy, or other reported problems were changed.

## Acceptance criteria and coverage

- **Passed:** a committed suspension blocks the next protected GET and POST from
  an already logged-in browser; the attempted POST creates no record.
- **Passed:** a remember-me cookie cannot restore a suspended account, including
  when the ordinary session cookie is absent.
- **Passed:** a suspension committed through another database connection applies
  without a server restart.
- **Passed:** all tested existing devices for the suspended account lose access.
- **Passed:** the acting administrator and another active user keep working;
  the active peer can still perform an authorized write.
- **Passed:** a suspended account with an elevated role does not bypass the check.
- **Passed:** the existing soft-deactivation route also blocks open sessions and
  retains the historical User row.
- **Passed:** reactivation permits a normal new login and an authorized write.
- **Passed:** suspended password login remains blocked; active statuses with
  different capitalization/whitespace continue working; empty/unknown statuses
  are inactive.
- **Passed:** an active read-only user retains view access but cannot write;
  missing CSRF tokens still fail; the login page and public static files work;
  the existing transient database-lock retry test passes.

## Validation

Environment: `/home/user/.venv/bin/python`, repository `requirements-dev.txt`,
and `opencv-python-headless` so the QR tests could execute rather than skip.
No test was disabled to obtain these results.

| Check | Result |
| --- | --- |
| Before-fix reproduction | **9 failed, 3 passed, 7 deselected** in 11.69 s. The 12 selected cases came from the 19 new regression cases. |
| Targeted regression suite | **40 passed, 0 failed, 0 skipped** in 64.22 s: all 19 P1 cases, 16 error-handling cases, and 5 lazy-modal CSRF cases. |
| Complete existing suite plus P1 tests | **249 passed, 0 failed, 0 skipped** in 350.11 s; process exit 0. |
| Real-process HTTP smoke | **1,270/1,270 checks passed**, 1,168 requests, 670 page checks, **0 failed checks, 0 failed journeys, 0 server errors**; process exit 0. Includes populated-data passes and an empty-database pass after wipe/restart. |
| Separate real-socket P1 check | **Passed.** Active session worked before suspension; suspended GET, POST, and remember-me access redirected to login; blocked write created zero rows; active peer and administrator stayed usable; reactivated login worked; no server errors. |
| Static checks | `git diff --check`, Python compilation, and Jinja parsing of `templates/settings.html` passed. |

The earlier full-suite baseline was 225 passed and 5 skipped. This run adds the
19 P1 cases and executes the 5 previously skipped QR cases, giving 249 passes.

### Reproduction commands

Run from the repository root after installing the development dependencies:

```bash
/home/user/.venv/bin/python -m pytest -q \
  tests/test_suspended_user_sessions.py \
  tests/test_error_handling.py \
  tests/test_lazy_modal_csrf.py

/home/user/.venv/bin/python -m pytest -q

SECRET_KEY=p1-disposable-smoke-key \
SMOKE_SECRET_KEY=p1-disposable-smoke-key \
PUBLIC_BASE_URL=https://p1-smoke.example.invalid \
SMOKE_PUBLIC_BASE_URL=https://p1-smoke.example.invalid \
AUTO_RECONCILE_ENABLED=0 AUTO_RECONCILE_FIX=0 \
/home/user/.venv/bin/python scratch/smoke/run_smoke.py \
  --cycles 1 --out _audit/p1/smoke
```

The first command passes with the fix; the recorded pre-fix reproduction used
`-k 'existing_session_get_and_write or remember_me_cookie or another_connection or user_active_flag'`
against the new P1 test file. The smoke harness starts and stops its own
servers and uses disposable databases. The separate socket probe also used a
fresh disposable database and was stopped after verification.

Local evidence (ignored by Git): `_audit/p1/before.xml`,
`_audit/p1/targeted.xml`, `_audit/p1/full.xml`, `_audit/p1/smoke/summary.json`,
the three `cycleA-*.json` reports, and `_audit/p1/http-results.json`.
These local artifacts are not required to run the committed regression tests.

## Data and deployment safety

- **No migration, data conversion, balance recalculation, or password change.**
- Normal active accounts keep their existing permissions and login behavior.
  Suspending an account changes only that account's access, not other users'
  sessions. Historical records remain linked to the original User row.
- **Deploying the code requires the normal application/server restart** so the
  changed Python code is loaded. Once this version is running, future suspend
  and reactivate actions take effect on the next request without a restart.
- No production deployment has been requested or performed, and no Vercel
  settings or production data were changed.
- Use the normal verified-backup procedure before any actual deployment; this
  fix itself does not rewrite business data.

## Rollback

Restore the five modified tracked files listed above to their pre-P1 versions
(or revert the P1 change once it is committed), and remove the new P1 test file
if rolling back the entire change. Keep `PROBLEM_REPORTING.md` and this report
as documentation, updating the status to record the rollback. Restart the app
after reverting Python code. No database rollback or business-data deletion is
needed because the fix makes no schema or data migration.

Rolling back reintroduces P1; it does not repair any unrelated accounting,
stock, upload, cookie, migration, or logout issues.

## Remaining limitations

- This is a local code fix, not a verified production deployment.
- A request already executing when suspension is committed is not interrupted;
  the new rule applies to subsequent requests. No claim is made about cancelling
  an in-flight write.
- Existing `UserLoginSession` rows are not rewritten by suspension. This fix
  enforces access through the authentication loader; session-history cleanup
  and unrelated login-security risks were left outside P1's scope.
- Interactive Chromium coverage was unavailable because the sandbox lacks
  `libnspr4.so`. Template parsing, the rendered confirmation text, and real HTTP
  journeys were checked instead; no browser-test pass is claimed.
- Passing the suite does not mean the other audited problems are fixed.
  **P2–P9 and R1–R9 still await individual authorization.**
