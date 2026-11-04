# Run 001 — bootstrap verification (`2026-11-04T05:18Z`)

The run that **built** the mechanism. Unlike later runs, this one also carries
the research that produced it, because the evidence and the engine were made in
the same session.

## Score

```
checks   : 85
passed   : 82  (96.47%)
known    : 3   (KF-001, KF-005, KF-007)
failed   : 0
seed     : 31/31 write paths ok
duration : 13.3 s
commit   : 2867c3e
```

Reproduce it:

```bash
.venv/bin/python "full cycle test mechanism/1.all files/shared/run.py" \
    --label bootstrap-verification \
    --run-dir "full cycle test mechanism/1.all files/run-001-20261104T0518"
```

## What this run contributed to `2.skills`

| Artifact | Why |
|---|---|
| `KF-001` … `KF-007` | seven defects, each with reproduction + fix + the check that proves it |
| `SKL-001` … `SKL-006` | six techniques, each with paste-ready code |
| `checks.py` | 85 assertions distilled from 300 hand-written ones |

## Contents

| Path | What |
|---|---|
| `report.md` | this run's human report (start here) |
| `results.json` | every check with observed vs expected |
| `counts.json` | row count per table after the run |
| `META.json` | label + what the run contributed |
| `results/pages.md` | all 58 pages: forms, filters, buttons (800 lines) |
| `results/routes.txt` | all 566 routes with methods |
| `results/full-app-work-test.md` | the hand-runnable acceptance suite |
| `results/final_ids.json` | ids produced by the original stage-A→O probe |
| `scripts/` | the probes used to discover the above (18 files) |

## The scripts, briefly

| Script | What it does |
|---|---|
| `extract.py` / `extract_pages.py` | parse every template + route → `pages.md` |
| `crawl.py` | walk 72 URLs on a scratch DB to find 404s |
| `probe_final_a.py` | the stage A→O cycle: masters → sales → payments |
| `probe_final_b.py` | stage 13–15: screens and downloads |
| `ops*.py` | the write flows on throw-away DB copies |
| `tr*.py`, `rec*.py`, `ret2.py` | transfer, reconciliation, material-return probes |
| `dl2.py`, `pdfread.py` | download matrix + PDF text extraction |
| `batch.py`, `adm.py` | page sweeps that produced the KPI tables |

These are **superseded** by `shared/`, but kept because they are the raw
evidence for the numbers in `data.py`. Do not extend them; add to `shared/`.
