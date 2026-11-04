#!/usr/bin/env python3
"""URL-map smoke crawl — visit every read-only route on a *seeded* database.

The check suite asserts figures on the pages it knows about.  This tool asks the
complementary question: **does every GET route still render at all?**  It boots
the app on a *copy* of a run's ``cycle.db`` (never the evidence itself), walks
every rule whose only verb is GET/HEAD, and classifies the response.

    python "1.all files/shared/urlmap_smoke.py" \\
        --db "1.all files/run-005-20261104T0538/cycle.db" \\
        --json gaps.json --md gaps.md

Only 5xx counts as a defect: a 404 for ``/ledger/<id>`` is the correct answer
when id doesn't exist, and a 302 is a normal login/permission redirect.

The copied database is deleted on the way out; nothing here writes to a run
directory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# routes that are expensive or side-effecting even on GET; skipped by name
HEAVY = re.compile(r"(export|download|backup|snapshot|sync|import|migrate|seed|"
                   r"admin|wipe|drop|reset|restore|repair|rebuild)", re.I)
SKIP_RULES = {"/static/<path:filename>"}


def build_url(rule: str) -> str:
    """Rule -> a concrete URL that the app can route (ids = 1, slugs = 'test')."""
    def sub(match: re.Match) -> str:
        conv = (match.group("conv") or "string").lower()
        name = (match.group("name") or "").lower()
        if conv == "int":
            return "1"
        if conv == "float":
            return "1.0"
        if conv == "path":
            return "test"
        if conv == "uuid":
            return "00000000-0000-0000-0000-000000000001"
        if name.endswith("date") or name in {"start", "end", "from", "to"}:
            return "2026-10-01"
        return "test"

    url = re.sub(r"<(?:(?P<conv>[a-zA-Z_]+):)?(?P<name>[a-zA-Z_]+)>", sub, rule)
    return url


def crawl(db_path: str, include_heavy: bool) -> dict:
    from harness import boot

    with tempfile.TemporaryDirectory() as tmp:
        scratch = os.path.join(tmp, "smoke.db")
        shutil.copy(db_path, scratch)          # never touch the run's evidence
        session = boot(scratch, fresh=False)   # fresh=False keeps the seeded data
        rules = [r for r in session.app.url_map.iter_rules()
                 if set(r.methods) <= {"GET", "HEAD", "OPTIONS"}]
        rows = []
        for rule in sorted(rules, key=lambda r: str(r.rule)):
            path = str(rule.rule)
            if path in SKIP_RULES:
                continue
            if not include_heavy and HEAVY.search(rule.endpoint):
                rows.append({"rule": path, "endpoint": rule.endpoint,
                             "status": None, "verdict": "skipped"})
                continue
            url = build_url(path)
            try:
                status = session.get(url).status_code
                verdict = ("ok" if 200 <= status < 300 else
                           "redirect" if 300 <= status < 400 else
                           "not-found" if status == 404 else
                           "error" if status >= 500 else "other")
            except Exception as exc:                       # a crash is a finding
                status, verdict = 0, f"exception: {type(exc).__name__}"
            rows.append({"rule": path, "endpoint": rule.endpoint,
                         "status": status, "verdict": verdict,
                         "url": url})
    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    errors = [r for r in rows if r["verdict"] not in
              ("ok", "redirect", "not-found", "skipped")]
    return {"routes": len(rows), "counts": dict(sorted(counts.items())),
            "errors": errors, "rows": rows}


def render_markdown(result: dict, label: str) -> str:
    lines = [
        f"# URL-map smoke crawl — {label}",
        "",
        "| Verdict | Routes |",
        "|---|---|",
    ]
    for verdict, count in result["counts"].items():
        lines.append(f"| {verdict} | {count} |")
    lines += ["", f"Routes visited: **{result['routes']}**; "
                  f"5xx or exceptions: **{len(result['errors'])}**.", ""]
    if result["errors"]:
        lines += ["## Failures", "", "| Rule | Status | Verdict |", "|---|---|---|"]
        lines += [f"| `{r['rule']}` | {r['status']} | {r['verdict']} |"
                  for r in result["errors"]]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="a run's cycle.db (a copy is used)")
    ap.add_argument("--label", default="local")
    ap.add_argument("--include-heavy", action="store_true",
                    help="also GET export/backup/admin routes")
    ap.add_argument("--json", help="write per-route detail here")
    ap.add_argument("--md", help="write the summary here")
    args = ap.parse_args()

    result = crawl(args.db, args.include_heavy)
    print(f"label  : {args.label}")
    print(f"routes : {result['routes']}")
    for verdict, count in result["counts"].items():
        print(f"  {count:>4}  {verdict}")
    for row in result["errors"]:
        print(f"  ERROR {row['rule']} -> {row['status']} {row['verdict']}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result, fh, indent=1)
    if args.md:
        with open(args.md, "w") as fh:
            fh.write(render_markdown(result, args.label))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
