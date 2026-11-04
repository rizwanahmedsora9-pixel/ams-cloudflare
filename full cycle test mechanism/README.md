# Full cycle test mechanism

One command builds the whole business from an empty database, checks 85 figures
against the live app, and writes down what it learned so the **next** run is
smarter than this one.

```bash
.venv/bin/python "full cycle test mechanism/1.all files/shared/run.py" --label pr-1234
```

```
checks   : 85
passed   : 82  (96.47%)
known    : 3
failed   : 0
seed     : 31/31 steps ok
```

Exit code `0` = no **unexpected** failure. Known defects are reported, tracked
and never fail the build (see §"Why known defects exist").

---

## Layout

```
full cycle test mechanism/
├── README.md                        <- you are here
├── 1.all files/                     <- everything a run produces
│   ├── shared/                      <- the reusable engine (do not duplicate)
│   │   ├── harness.py               boot, CSRF client, text/PDF/DB helpers
│   │   ├── data.py                  every input value + every expected total
│   │   ├── seed.py                  writes the dataset through HTTP forms
│   │   ├── checks.py                read-only assertions -> pass / known / fail
│   │   ├── route_census.py          breadth: which routes does the suite touch?
│   │   ├── urlmap_smoke.py          breadth: does every GET route still render?
│   │   ├── app_walk.py              depth: the 58 documented pages, form by form
│   │   └── run.py                   one command -> report.md + results.json
│   ├── run-001-20261104T0518/       <- one directory per run, numbered + stamped
│   │   ├── scripts/                 the probes used to build that run
│   │   ├── results/                 pages.md, routes.txt, full-app-work-test.md
│   │   ├── artifacts/               seed context
│   │   ├── cycle.db                 the scratch database (the only DB touched)
│   │   ├── results.json             every check, machine-readable
│   │   ├── counts.json              row count per table
│   │   └── report.md                the human report
│   └── run-NNN-.../                 <- the next run, next number
├── reports/                         <- human-facing audits (one per review)
│   ├── README.md                    <- index: which report covers which run
│   ├── REPORT-TEMPLATE.md           <- copy this for the next audit
│   ├── run-NNN-<stamp>-<slug>.md    <- the report itself
│   ├── run-NNN-<stamp>-summary.json <- the same thing, machine-readable
│   └── evidence/                    <- census, crawl, pytest log, run copies
└── 2.skills/                        <- everything that makes run N+1 better
    ├── skills-index.md              auto-generated: inventory + history + trend
    ├── ledger.jsonl                 append-only run history (never edited)
    ├── SKL-NNN-<stamp>-<slug>.md    how-to-test skills
    ├── KF-NNN-<slug>.md             known defects, with reproduction + fix
    ├── _TEMPLATE/                   copy these when adding a skill or defect
    └── _tools/ledger.py             numbering, history, index generation
```

Three folders, each with one job: **`1.all files`** holds the artifacts of every
run, **`2.skills`** holds the distilled knowledge, **`reports/`** holds the
human-facing audit written on top of both. Everything in `1` is evidence;
everything in `2` is reusable; everything in `reports/` is a reading of the other
two and never the only copy of anything.

---

## The loop: how skills actually grow

```
    run N ──► 1.all files/run-NNN/…        evidence: what happened
                 │
                 ├── new defect found?   ──► 2.skills/KF-NNN-*.md   (+ known= in checks.py)
                 ├── new technique used? ──► 2.skills/SKL-NNN-*.md  (+ a check that uses it)
                 └── new invariant?      ──► checks.py + data.py
                 │
                 ▼
           ledger.jsonl                 one line: rate, known ids, commit
                 │
                 ▼
           skills-index.md              regenerated: what we know, and the trend
                 │
                 ▼
    run N+1 ──► knows more, checks more, fails faster
```

Concretely, **every run must add something**:

| If the run… | Then this run's contribution |
|---|---|
| merged a PR | bump `checks.py` with at least one assertion for the changed behaviour |
| found a new defect | new `KF-NNN-*.md` + a `known=` check that inverts on fix |
| fixed a defect | remove the `known=` flag; the check becomes a regression guard |
| did research | new `SKL-NNN-*.md` describing the technique, with paste-ready code |
| found nothing | the ledger line is still added — a flat trend with evidence is a result |

A run that adds nothing is allowed, but it must be *stated* in the run's
`META.json`, otherwise the mechanism is being used as a smoke test rather than a
learning loop.

---

## Numbering and timestamps

| Kind | Pattern | Example | Assigned by |
|---|---|---|---|
| Run | `run-NNN-YYYYMMDDTHHMM` | `run-001-20261104T0518` | `ledger.make_run_dir()` |
| Skill | `SKL-NNN-YYYYMMDDTHHMM-<slug>.md` | `SKL-003-20261104T0518-drive-forms…` | `ledger.next_numbers()` |
| Defect | `KF-NNN` (stable id, no timestamp) | `KF-001` | manual, next free |

`NNN` never repeats. The timestamp is UTC and is the run that produced the
document, so `ls` sorts chronologically for free. Defect ids carry **no**
timestamp on purpose: they are referenced from `checks.py` and must stay stable
across runs — the discovery date lives in the git history and in the index.

Get the next free numbers at any time:

```bash
python "2.skills/_tools/ledger.py" --next
# {"run": 2, "skill": 7, "defect": 8}
```

---

## Adding a skill (the thing you will do most)

```bash
cp "2.skills/_TEMPLATE/SKILL-TEMPLATE.md" /tmp/new.md
# write it, then:
python - <<'PY'
import sys; sys.path.insert(0, "2.skills/_tools")
import ledger, pathlib
body = pathlib.Path("/tmp/new.md").read_text().replace("SKL-NNN", "SKL-007")
print(ledger.add_skill("verify-x-by-doing-y", body))
PY
```

`add_skill()` picks the next number, stamps it, writes the file and regenerates
`skills-index.md`.

A skill is only worth writing if it contains **paste-ready code** and **a trap
table**. Prose that restates the code is not a skill.

---

## Why known defects exist (and why they don't hide bugs)

Three states, not two:

| State | Printed | Fails the build | Meaning |
|---|---|---|---|
| pass | `PASS` | no | working |
| known defect | `KNOWN` | **no** | broken, documented as `KF-NNN` |
| unexpected failure | `FAIL` | **yes** | a regression, or a new defect |

The trick that keeps it honest: a known-defect check asserts *the broken
behaviour*, so **it flips to green the moment someone fixes the bug**. You then
delete the `known=` flag and it becomes a normal regression guard. Nothing has to
be remembered; the suite tells you when the defect dies.

Adding a `known=` is a visible edit to `checks.py`, so it cannot be used to
quietly bury a new failure — the known count in every report would move.

---

## Reports (`reports/`)

`1.all files/run-NNN/report.md` answers *"what did this run produce?"*.
`reports/` answers the wider question a reviewer asks — *"is the app tested, and
where is it blind?"* — by stacking the mechanism on top of the other evidence:

```
reports/
├── README.md                                 <- index: report -> run -> verdict
├── REPORT-TEMPLATE.md                        <- copy for the next audit
├── run-006-20261104T0615-full-app-audit.md   <- the deliverable
├── run-006-20261104T0615-summary.json        <- numbers only, for CI/diffing
└── evidence/
    ├── route-coverage.md / .json             route_census.py output
    ├── urlmap-smoke.md / .json               urlmap_smoke.py output
    ├── pytest-full.log                       the repo's own suite, verbatim
    └── cycle-results.json                    the run's results.json, copied
```

Rules that keep it honest:

| Rule | Why |
|---|---|
| one report per review, named `run-NNN-<stamp>-<slug>.md` | sorts with the runs, greppable by number |
| every claim in a report cites a check id, a file, or an evidence file | a number with no source is a rumour |
| `evidence/` holds *outputs*, never conclusions | conclusions rot, outputs can be re-read |
| a report may say "known" but never hides a `FAIL` | the three-state rule applies to prose too |
| log the verdict (`PASS` / `PASS WITH KNOWN DEFECTS` / `BLOCKED`) at the top | the first line is what people read |

Two breadth tools back the report:

```bash
.venv/bin/python "1.all files/shared/route_census.py" --label run-006 \
    --json reports/evidence/route-coverage.json --md reports/evidence/route-coverage.md

.venv/bin/python "1.all files/shared/urlmap_smoke.py" \
    --db "1.all files/run-006-.../cycle.db" --label run-006 \
    --json reports/evidence/urlmap-smoke.json --md reports/evidence/urlmap-smoke.md
```

`app_walk` closes the last gap: it replays `run-001/results/pages.md` against the
living app — 58 pages, 209 forms, 773 field names, 890 columns, every link, ten
page-vs-page tie-outs and eight workflows submitted through the real forms
(14 s, all on a copy of the database):

```bash
.venv/bin/python "1.all files/shared/app_walk.py" \
    --db "1.all files/run-007-.../cycle.db" --label run-007 \
    --json reports/evidence/app-walk.json --md reports/evidence/app-walk.md
```

`route_census` answers *"which of the 566 routes has nobody ever asked about?"*
(static, 4 s). `urlmap_smoke` answers *"does every GET route still render on a
seeded database?"* (5 s, 0 × 5xx expected). Neither can say a page is *right* —
that is what the 85 checks are for — but together they stop a green suite from
being mistaken for a tested app. See `SKL-008`.

---

## Reading a run

| File | Use it to |
|---|---|
| `report.md` | what a human reads: score, failures, known defects, every check |
| `results.json` | feed CI, diff two runs, compute your own metrics |
| `counts.json` | spot "the run created 9 payments instead of 8" instantly |
| `cycle.db` | reproduce a failure without re-seeding — boot with `fresh=False` |

**Never boot a finished run's DB with `fresh=True`** (the default). It deletes the
file first. That is the one footgun in this mechanism.

---

## CI hook (optional)

The mechanism is exit-code driven, so a PR job is three lines:

```yaml
- run: .venv/bin/python "full cycle test mechanism/1.all files/shared/run.py" --label "pr-${{ github.event.number }}"
- run: cat "full cycle test mechanism/1.all files"/run-*/report.md >> "$GITHUB_STEP_SUMMARY"
```

`cycle.db` is scratch — keep it out of git (`*.db` is already ignored repo-wide).

---

## Where the rest of the evidence lives

`1.all files/run-001-20261104T0518/results/` holds the material this mechanism
was built from:

| File | Contents |
|---|---|
| `pages.md` | all 58 pages with their forms, filters and buttons (800 lines) |
| `routes.txt` | all 566 routes with methods and endpoints |
| `full-app-work-test.md` | the hand-runnable acceptance suite, page by page |
| `final_ids.json` | the ids created by the original stage-A→O probe |
