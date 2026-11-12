# Problem reporting and safe-fix instructions

This repository is repaired **one reported problem at a time**. A fix for one
ID must not silently include fixes for other IDs. These instructions apply to
both human contributors and coding agents.

## 1. Explain the problem before changing code

Start every fix with a short, plain-English report containing:

| Field | What to include |
| --- | --- |
| ID and title | Stable ID, such as `P1`, and a descriptive title |
| Module | Business area and relevant code package/service |
| Page/screen | The actual user-facing screen and action |
| URL/route | Page URL and the route that performs the action |
| Problem | What happens now, in ordinary language |
| Expected behavior | What should happen instead |
| Evidence | Reproduction steps and observed result; distinguish confirmed bugs from suspected risks |
| Impact | Whether it can change stored data, calculations, reports, access, privacy, or availability |
| Reports/screens affected | Direct effects and indirect/downstream effects, clearly separated |
| Proposed scope | The smallest change that addresses this ID |
| Safety checks | Existing behavior that must remain unchanged |
| Acceptance tests | Conditions that prove the fix works without unrelated regressions |

Do not say that live data is corrupted merely because a test reproduced a bug.
State whether testing used a disposable database, a backup, or live data.
Never put real passwords, session cookies, recovery codes, or customer data in
a report, test fixture, screenshot, or log.

## 2. Keep a report for each fix

Store completed and in-progress reports at:

```text
docs/problem-reports/<ID>-<short-name>.md
```

Use the headings above, followed by:

1. **Root cause** — relevant files/functions and why the failure occurs.
2. **Changes made** — exact files and the purpose of each change.
3. **Validation** — commands, pass/fail counts, and what was not tested.
4. **Data and deployment safety** — schema changes, backups, restart needs,
   compatibility, and any operational action required.
5. **Rollback** — how to undo the code change without deleting business data.
6. **Status** — reported, reproduced, fixed locally, validated, deployed, or closed.
7. **Remaining limitations** — do not mark unrelated risks as fixed.

Update the report as work progresses. Do not claim success before tests finish.
Keep raw databases, backups, virtual environments, coverage output, and temporary
logs out of Git. Small, reviewed text summaries belong in the problem report.

## 3. Make the smallest safe change

- Work only on the current Arena working branch. Never create or switch branches.
- Inspect the existing route, model, service, templates, and tests before editing.
- Reproduce the problem with a failing regression test when practical.
- Prefer an existing central guard/service over copying checks into many pages.
- Preserve financial formulas, stored amounts, schema, and unrelated permissions
  unless the selected problem explicitly requires changing them.
- Do not combine security, accounting, UI, dependency, and refactoring changes
  merely because they are nearby in the code.
- Use disposable databases for tests. Never run destructive tests against live data.
- If a schema/data migration is necessary, explain it first and include a backup,
  compatibility, verification, and recovery plan. Do not improvise one silently.
- Do not deploy, change Vercel settings, or alter production data unless the user
  explicitly requests that action.

## 4. Validate in layers

Run checks appropriate to the change, recording exact results:

1. **Reproduction:** show the old behavior fails the new regression test.
2. **Targeted tests:** the selected problem, boundary cases, and nearby behavior.
3. **Existing regressions:** relevant auth/CRUD/report tests, then the broader
   suite when practical. A long suite may run as a background process.
4. **Static checks:** whitespace/error checks and Python compilation for changed
   code; template/browser checks when UI behavior changes.
5. **End-to-end smoke:** real HTTP requests with CSRF enabled for affected user
   journeys; verify both a protected page and a protected write where relevant.
6. **Data safety:** confirm no unintended schema/data changes and a clean,
   reviewable diff containing only the selected fix, tests, and documentation.

A skipped or unavailable test is not a pass. Report missing native libraries,
browser coverage, production checks, and other limitations honestly.

## 5. Explain the result to the user

After validation, report:

- the original problem and affected module/page again, briefly;
- what actually changed;
- what now happens to the affected user/action;
- which existing behavior was checked and preserved;
- exact test results and any remaining limitations;
- whether a restart, migration, backup, or deployment is needed;
- the path to the detailed problem report.

Use plain English first, technical details second. Say **“fixed locally and
tested”** rather than “fixed in production” unless deployment was explicitly
performed and verified. Wait for the user's next problem before starting another
ID. Changes are saved on the current working branch; do not switch branches or
push/deploy merely to preserve them.
