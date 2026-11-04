# Reports — what was tested, what it proved, where the blind spots are

`1.all files/run-NNN/` answers *"what did this run produce?"*.
This folder answers the question a reviewer actually asks: **"is the app tested,
and where is it blind?"**

One report per review, never edited after the fact. A new review means a new
report; the old one stays as the record of what was true on that date.

---

## Index

| Report | Run | Verdict | Mechanism | pytest | Breadth | New findings |
|---|---|---|---|---|---|---|
| [`run-006-20261104T0609-full-app-audit.md`](run-006-20261104T0609-full-app-audit.md) | `run-006-20261104T0609` | **PASS WITH KNOWN DEFECTS** | 82/86 · 4 known · 0 fail (95.35 %) | 531 passed · 6 skipped · 0 failed | 566 rules · 267 reached (47.17 %) · 257 crawled · 0 × 5xx | `KF-008` |

Machine-readable twin of the same report: [`run-006-20261104T0609-summary.json`](run-006-20261104T0609-summary.json).

---

## What a report here is made of

Four layers of evidence, because any one of them alone flatters the app:

| Layer | Command | Answers | Cost |
|---|---|---|---|
| Mechanism | `shared/run.py` | are the rupee figures right, and do the write forms work? | 15 s |
| Regression suite | `pytest -q` | do units and endpoints still behave? | ~26 m |
| Route census | `shared/route_census.py` | which of the 566 routes has no suite ever mentioned? | 4 s |
| URL-map crawl | `shared/urlmap_smoke.py` | does every read-only route still render on seeded data? | 5 s |

The mechanism is the only layer that builds the business from an empty database;
the other three assume it (or a copy of its `cycle.db`).

---

## Layout

```
reports/
├── README.md                                  <- you are here: the index
├── REPORT-TEMPLATE.md                         <- copy this for the next audit
├── run-NNN-<stamp>-<slug>.md                  <- the report
├── run-NNN-<stamp>-summary.json               <- the same numbers, for diffing/CI
└── evidence/
    ├── cycle-results.json                     the run's results.json (copy)
    ├── cycle-report.md                        the run's auto-generated report (copy)
    ├── cycle-counts.json                      row count per table (copy)
    ├── route-coverage.md / .json              census output
    ├── urlmap-smoke.md / .json                crawl output
    ├── pytest-full.log                        the suite, verbatim
    └── probe-mutate-gap.json                  probe behind KF-008
```

`evidence/` holds **outputs, never conclusions**. Conclusions live in the report
and rot; outputs can be re-read, re-diffed and re-argued a year later.

---

## Rules

1. **The verdict goes on line 3.** `PASS` / `PASS WITH KNOWN DEFECTS` /
   `BLOCKED`. It is the only line most readers will see.
2. **Every number cites a source** — a check id, a file in `evidence/`, or a
   command in §Reproducing. A figure with no source is a rumour.
3. **A report may say "known"; it may never hide a `FAIL`.** The mechanism's
   three-state rule (pass / known / fail) applies to prose too.
4. **A falling pass rate can be the correct outcome.** Adding a check that
   documents a real gap lowers the percentage and raises the truth; say so
   explicitly, as `run-006` does.
5. **Never claim coverage from a pass rate.** 82/86 is 95 % of the *assertions*,
   not of the app. The census is the number that answers the other question.
6. **Copy, never move.** `evidence/` files are copies; the authoritative versions
   stay in the run directory.
7. **Do not crawl with `fresh=True`.** It deletes `cycle.db` first. The crawl tool
   copies the file for exactly this reason.

---

## Writing the next one

```bash
cp "full cycle test mechanism/reports/REPORT-TEMPLATE.md" \
   "full cycle test mechanism/reports/run-007-<stamp>-<slug>.md"
```

then run the four layers, drop their outputs in `evidence/`, fill the template,
and add a row to the index above. Update the mechanism's `2.skills/` **only** if
the report found a defect (`KF-NNN`) or a new technique (`SKL-NNN`) — the
mechanism's own rule: a run that adds nothing must still say so in `META.json`.
