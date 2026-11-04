#!/usr/bin/env python3
"""Full-cycle run — one command, one report.

    python "1.all files/shared/run.py" --label pr-1234

What it does
------------
1. builds a scratch SQLite file under the run directory
2. seeds the canonical dataset **through the UI** (see ``seed.py``)
3. runs every assertion in ``checks.py`` against the live app
4. writes ``results.json``, ``report.md`` and ``counts.json``
5. bumps the skill ledger so the next run starts from what this one learned

Exit code is 0 when no *hard* check fails.  Known defects (see the defect
register) are reported but do not fail the build.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# ledger lives with the skills, because it *is* the skill memory
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "2.skills", "_tools")))

import checks          # noqa: E402
import seed            # noqa: E402
from harness import Db, boot, text_of  # noqa: E402


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="local", help="what triggered the run, e.g. pr-1234")
    ap.add_argument("--run-dir", default=None, help="directory for this run's outputs")
    ap.add_argument("--keep-db", action="store_true", help="leave the scratch DB in place")
    args = ap.parse_args()

    started = now_utc()
    stamp = started.strftime("%Y%m%dT%H%M")
    if args.run_dir:
        run_dir = args.run_dir
    else:
        import ledger as _ledger
        run_dir = _ledger.make_run_dir(args.label, started)
    run_dir = os.path.abspath(run_dir)
    os.makedirs(run_dir, exist_ok=True)

    db_path = os.path.join(run_dir, "cycle.db")
    print(f"run      : {os.path.basename(run_dir)}")
    print(f"label    : {args.label}")
    print(f"database : {db_path}")

    session = boot(db_path, health_path=os.path.join(run_dir, "health.json"))
    db = Db(db_path)
    print(f"booted   : {len(db.tables())} tables")

    results = checks.Results()
    try:
        ctx = seed.seed(session, db, artifact_dir=os.path.join(run_dir, "artifacts"))
        seed_info = seed.summary()
        checks.run_all(session, db, results)
    except Exception:
        traceback.print_exc()
        seed_info = seed.summary()
        results.truth("RUN", "run completed without an exception", False, "exception", True)

    finished = now_utc()
    score = results.score()
    counts = db.counts()

    payload = {
        "run": {
            "label": args.label,
            "started": started.isoformat(),
            "finished": finished.isoformat(),
            "duration_s": round((finished - started).total_seconds(), 1),
            "git_commit": _git("rev-parse --short HEAD"),
            "git_branch": _git("rev-parse --abbrev-ref HEAD"),
            "python": sys.version.split()[0],
            "run_dir": os.path.basename(run_dir),
            "database": os.path.basename(db_path),
        },
        "score": score,
        "seed": seed_info,
        "table_counts": counts,
        "checks": results.rows,
    }

    try:
        import ledger as _ledger
        with open(os.path.join(run_dir, "META.json"), "w") as fh:
            json.dump({"label": args.label, "started": started.isoformat(),
                       "contribution": _contribution(results, seed_info), }, fh, indent=1)
    except Exception:
        pass
    with open(os.path.join(run_dir, "results.json"), "w") as fh:
        json.dump(payload, fh, indent=1, default=str)
    with open(os.path.join(run_dir, "counts.json"), "w") as fh:
        json.dump(counts, fh, indent=1, sort_keys=True)
    with open(os.path.join(run_dir, "report.md"), "w") as fh:
        fh.write(render_markdown(payload))

    if not args.keep_db:
        for suffix in ("-wal", "-shm"):
            p = db_path + suffix
            if os.path.exists(p):
                os.remove(p)

    print("\n" + "=" * 62)
    print(f"checks   : {score['total']}")
    print(f"passed   : {score['passed']}  ({score['pass_rate']}%)")
    print(f"known    : {score['known_defects']}")
    print(f"failed   : {score['failures']}")
    print(f"seed     : {seed_info['total'] - seed_info['failed']}/{seed_info['total']} steps ok")
    print(f"report   : {os.path.join(run_dir, 'report.md')}")
    print("=" * 62)

    for row in results.failures:
        print(f"  FAIL {row['id']} {row['label']} | got {row['observed']!r} "
              f"want {row['expected']!r}")
    for row in results.knowns:
        print(f"  KNOWN {row['id']} ({row['known_defect']}) {row['label']}")

    try:
        import ledger
        ledger.record_run(os.path.join(run_dir, "results.json"))
    except Exception as exc:  # never let bookkeeping break the run
        print(f"  (ledger not updated: {exc})")

    return 0 if score["failures"] == 0 else 1


def _contribution(results, seed_info) -> str:
    """What this run added to the mechanism (the discipline that makes it grow)."""
    bits = []
    if results.knowns:
        bits.append(f"{len(results.knowns)} known defect(s) still reproduce: "
                    + ", ".join(sorted({r["known_defect"] for r in results.knowns})))
    if results.failures:
        bits.append(f"{len(results.failures)} NEW failure(s) to turn into a KF document")
    if not results.failures and not results.knowns:
        bits.append("no defects observed")
    bits.append(f"{seed_info['total'] - seed_info['failed']}/{seed_info['total']} write paths ok")
    return " · ".join(bits)


def _git(args: str) -> str:
    import subprocess
    try:
        return subprocess.check_output(
            f"git {args}", shell=True, cwd=HERE, text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def render_markdown(payload: dict) -> str:
    run, score = payload["run"], payload["score"]
    lines = [
        f"# Full-cycle run — {run['label']}",
        "",
        f"| | |",
        f"|---|---|",
        f"| Run dir | `{run['run_dir']}` |",
        f"| Started | {run['started']} |",
        f"| Duration | {run['duration_s']} s |",
        f"| Commit | `{run['git_commit']}` on `{run['git_branch']}` |",
        f"| Python | {run['python']} |",
        f"| Checks | **{score['passed']} / {score['total']} passed** "
        f"({score['pass_rate']}%) |",
        f"| Known defects | {score['known_defects']} |",
        f"| Unexpected failures | {score['failures']} |",
        "",
        "## Seed steps",
        "",
        f"{payload['seed']['total'] - payload['seed']['failed']} of "
        f"{payload['seed']['total']} write paths produced the expected flash.",
        "",
    ]
    if payload["seed"]["failed_stages"]:
        lines += ["| Step | Flash seen |", "|---|---|"]
        lines += [f"| {s['stage']} | {s['detail']} |" for s in payload["seed"]["failed_stages"]]
        lines.append("")

    fails = [c for c in payload["checks"] if not c["ok"] and not c["known_defect"]]
    knowns = [c for c in payload["checks"] if not c["ok"] and c["known_defect"]]

    if fails:
        lines += ["## Unexpected failures", "", "| ID | Check | Observed | Expected |",
                  "|---|---|---|---|"]
        lines += [f"| {c['id']} | {c['label']} | `{c['observed']}` | `{c['expected']}` |"
                  for c in fails]
        lines.append("")
    else:
        lines += ["## Unexpected failures", "", "None.", ""]

    if knowns:
        lines += ["## Known defects still reproducing", "",
                  "| ID | Known | Check |", "|---|---|---|"]
        lines += [f"| {c['id']} | {c['known_defect']} | {c['label']} |" for c in knowns]
        lines.append("")

    lines += ["## Every check", "", "| ID | Result | Check | Observed | Expected |",
              "|---|---|---|---|---|"]
    for c in payload["checks"]:
        mark = "PASS" if c["ok"] else ("KNOWN" if c["known_defect"] else "**FAIL**")
        lines.append(f"| {c['id']} | {mark} | {c['label']} | `{c['observed']}` | "
                     f"`{c['expected']}` |")
    lines.append("")
    lines += ["## Table counts after the run", "", "```json",
              json.dumps(payload["table_counts"], indent=1, sort_keys=True), "```", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
