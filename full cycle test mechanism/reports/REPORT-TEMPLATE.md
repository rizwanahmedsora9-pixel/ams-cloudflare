# Full-app test report — `run-NNN-YYYYMMDDTHHMM`

**Verdict: PASS | PASS WITH KNOWN DEFECTS | BLOCKED** — <one sentence: failures,
knowns, new findings.>

| | |
|---|---|
| Repository | `<owner>/<repo>` |
| Branch / commit | `<branch>` @ `<sha>` |
| Mechanism run | `1.all files/run-NNN-…` (`<duration>` s) |
| Environment | Python `<x.y>`, venv from `requirements.txt`, SQLite scratch DB |
| Executed | 4 layers: mechanism (`<n>` assertions) · pytest (`<n>` tests) · census (`<n>` rules) · crawl (`<n>` routes) |
| Evidence | `reports/evidence/` — every figure below is reproducible from a file there |

---

## 1. Result at a glance

| Layer | Scope | Result | Time |
|---|---|---|---|
| Full-cycle mechanism | `<n>` write paths, `<n>` assertions | `<p>` pass · `<k>` known · `<f>` fail → `<%>` | `<t>` |
| Regression suite | repository tests | `<p>` passed · `<s>` skipped · `<f>` failed | `<t>` |
| Route census | `<n>` URL rules | `<c>` reached (`<%>`) · `<g>` never mentioned | `<t>` |
| URL-map crawl | every GET route | `<n>` crawled · `<x>` × 5xx | `<t>` |

Exit code of the mechanism was `<0|1>`. `<If the pass rate moved, say why in one
sentence — a new check is not a regression, and must not be allowed to look like
one.>`

---

## 2. What "full app" meant here

<The four layers and what each one cannot see. Two sentences per layer, maximum.>

---

## 3. Mechanism results

| Area | Checks | Pass | Known | Fail | Key figures verified |
|---|---|---|---|---|---|
| <area> | <n> | <n> | <n> | <n> | <figures> |
| **Total** | | | | | |

Seed: `<ok>/<total>` write paths returned the expected flash. Tables non-empty:
`<n>` of `<total>`.

### Known failures (reported, not build-breaking)

| Check | Defect | Observed | Expected | Meaning |
|---|---|---|---|---|
| `<id>` | `KF-NNN` | `<got>` | `<want>` | <what a user loses> |

---

## 4. Regression suite

```
<paste the pytest summary line verbatim>
```

* skipped: `<n>` — `<why>`, `<why>`
* warnings: `<n>` — `<the interesting one, with file:line>`

---

## 5. New findings from this audit

### 5.1 `KF-NNN` — <symptom in one line> (<severity>)

<Symptom, reproduction, root cause `file:line`, the probe that names the cause,
the consequence in business terms, and what was / was not fixed.>

### 5.2 Breadth is `<x>` %, not `<y>` %

<Census table + top gap families. State clearly that this is a floor, because
`url_for()` routes are invisible to a static census.>

### 5.3 Crawl: `<n>` × 5xx, `<n>` × 404

<What the crawl proves and what it does not. List the 404s and why each is
correct.>

---

## 6. Defect register after this audit

| ID | Severity | Title | Status | Proven by |
|---|---|---|---|---|
| `KF-NNN` | | | open / fixed in `<sha>` | `<check id>` |

<Say what was opened, what was closed, what was re-attributed. Re-attribution is
a finding: if a known check blames the wrong defect, the register is drifting.>

---

## 7. Observations that are not yet defects

<The things a careful reader needs and a suite cannot express: interacting
defects, silent fallbacks, runtime cost, warnings that are signatures of a class
of bug, deliberately skipped surface area.>

---

## 8. What this audit added to the mechanism

| Artefact | What it is |
|---|---|
| `1.all files/run-NNN-…/` | the run |
| `2.skills/KF-NNN-…md` | new defect (if any) |
| `2.skills/SKL-NNN-…md` | new technique (if any) |
| `checks.py` `<id>` | the new gap, asserted |
| `reports/…` | this report and its evidence |

<If nothing was added, say so here in one sentence — that is allowed, silence is
not.>

---

## 9. Recommendations, in priority order

1. **<highest-consequence fix>** — <why first, one line>
2. …

---

## 10. Reproducing this report

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python "full cycle test mechanism/1.all files/shared/run.py" --label <label>
.venv/bin/python -m pytest -q -rs
.venv/bin/python "full cycle test mechanism/1.all files/shared/route_census.py" --label run-NNN
.venv/bin/python "full cycle test mechanism/1.all files/shared/urlmap_smoke.py" \
    --db "full cycle test mechanism/1.all files/run-NNN-…/cycle.db" --label run-NNN
```

---

## 11. Evidence index

| File | Contents |
|---|---|
| `evidence/cycle-results.json` | every check, machine-readable |
| `evidence/cycle-report.md` | the run's auto-generated report |
| `evidence/cycle-counts.json` | row count per table |
| `evidence/route-coverage.md` / `.json` | census: reached vs gap, per blueprint |
| `evidence/urlmap-smoke.md` / `.json` | crawl: status and verdict per route |
| `evidence/pytest-full.log` | the suite, verbatim |

---

## Appendix — every check

| ID | Result | Check | Observed | Expected |
|---|---|---|---|---|
| `<id>` | PASS / KNOWN / **FAIL** | `<label>` | `<observed>` | `<expected>` |

Totals: `<p>` passed / `<n>` checks, `<k>` known, `<f>` unexpected, pass rate `<%>`.
