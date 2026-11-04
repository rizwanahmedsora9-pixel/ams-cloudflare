"""Skill ledger — the mechanism's memory.

The ledger is what turns a pile of runs into *accumulating* skill:

* every run appends one line to ``ledger.jsonl`` (append-only, never edited)
* ``skills-index.md`` is regenerated from the ledger + the skill files on disk
* :func:`next_numbers` hands out the next free numbering for a new skill and
  for a new run directory, so nothing ever collides

Naming contract
---------------
    run directory : run-NNN-YYYYMMDDTHHMM
    skill file    : SKL-NNN-YYYYMMDDTHHMM-<slug>.md
    defect        : KF-NNN   (stable id, referenced from checks.py)

``NNN`` is zero-padded and assigned by :func:`next_numbers`; the timestamp is
the run's start in UTC.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

MECH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FILES_DIR = os.path.join(MECH, "1.all files")
SKILLS_DIR = os.path.join(MECH, "2.skills")
LEDGER_PATH = os.path.join(SKILLS_DIR, "ledger.jsonl")
INDEX_PATH = os.path.join(SKILLS_DIR, "skills-index.md")

RUN_RE = re.compile(r"^run-(\d{3})-")
SKILL_RE = re.compile(r"^SKL-(\d{3})-")
DEFECT_RE = re.compile(r"^KF-(\d{3})")


def _max_number(pattern: re.Pattern, names) -> int:
    best = 0
    for name in names:
        m = pattern.match(name)
        if m:
            best = max(best, int(m.group(1)))
    return best


def next_numbers() -> dict:
    """Next free run number, skill number and defect number."""
    run_dirs = [d for d in os.listdir(FILES_DIR)] if os.path.isdir(FILES_DIR) else []
    skill_files = [f for f in os.listdir(SKILLS_DIR)
                   if f.endswith(".md")] if os.path.isdir(SKILLS_DIR) else []
    defect_files = [f for f in skill_files if f.startswith("KF-")]
    return {
        "run": _max_number(RUN_RE, run_dirs) + 1,
        "skill": _max_number(SKILL_RE, skill_files) + 1,
        "defect": _max_number(DEFECT_RE, defect_files) + 1,
    }


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit] or "skill"


def make_run_dir(label: str, when: datetime | None = None) -> str:
    """Create and return a fresh, correctly numbered run directory."""
    when = when or datetime.now(timezone.utc)
    num = next_numbers()["run"]
    name = f"run-{num:03d}-{when.strftime('%Y%m%dT%H%M')}"
    path = os.path.join(FILES_DIR, name)
    os.makedirs(os.path.join(path, "scripts"), exist_ok=True)
    os.makedirs(os.path.join(path, "results"), exist_ok=True)
    os.makedirs(os.path.join(path, "artifacts"), exist_ok=True)
    with open(os.path.join(path, "META.json"), "w") as fh:
        json.dump({"run": f"{num:03d}", "label": label,
                   "created": when.isoformat()}, fh, indent=1)
    return path


def record_run(results_path: str) -> dict | None:
    """Append one entry to the ledger from a ``results.json``."""
    if not os.path.exists(results_path):
        return None
    with open(results_path) as fh:
        payload = json.load(fh)
    run = payload["run"]
    score = payload["score"]
    entry = {
        "ts": run["finished"],
        "run": run["run_dir"],
        "label": run["label"],
        "commit": run["git_commit"],
        "branch": run["git_branch"],
        "checks": score["total"],
        "passed": score["passed"],
        "known": score["known_defects"],
        "failed": score["failures"],
        "pass_rate": score["pass_rate"],
        "duration_s": run["duration_s"],
        "known_ids": sorted({c["known_defect"] for c in payload["checks"]
                             if c.get("known_defect") and not c["ok"]}),
        "failed_ids": [c["id"] for c in payload["checks"]
                       if not c["ok"] and not c.get("known_defect")],
    }
    os.makedirs(SKILLS_DIR, exist_ok=True)
    with open(LEDGER_PATH, "a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    write_index()
    return entry


def read_ledger() -> list[dict]:
    if not os.path.exists(LEDGER_PATH):
        return []
    entries = []
    with open(LEDGER_PATH) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def skill_inventory() -> list[dict]:
    """Every skill on disk, newest first, with its header metadata."""
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for name in sorted(os.listdir(SKILLS_DIR)):
        path = os.path.join(SKILLS_DIR, name)
        if (not name.endswith(".md") or name.startswith("_")
                or name == "skills-index.md"):
            continue
        meta = {"file": name, "id": "", "title": "", "kind": "skill",
                "confidence": "", "reuse": "", "defect": ""}
        m = SKILL_RE.match(name)
        if m:
            meta["id"] = f"SKL-{m.group(1)}"
        dm = DEFECT_RE.match(name)
        if dm:
            meta["id"] = f"KF-{dm.group(1)}"
            meta["kind"] = "defect"
        try:
            with open(path) as fh:
                head = [next(fh, "") for _ in range(30)]
        except OSError:
            head = []
        for line in head:
            line = line.strip()
            if line.startswith("# ") and not meta["title"]:
                meta["title"] = line[2:].strip()
            for key in ("Confidence", "Reuse", "Severity"):
                if line.lower().startswith(f"**{key.lower()}:**"):
                    meta[key.lower()] = line.split(":**", 1)[-1].strip()
        out.append(meta)
    out.sort(key=lambda m: m["file"], reverse=True)
    return out


def write_index() -> str:
    """Regenerate ``skills-index.md`` from the ledger and the skill files."""
    entries = read_ledger()
    skills = skill_inventory()
    trend = _trend(entries)
    lines = [
        "# Skills index — full cycle test mechanism",
        "",
        "Auto-generated by `2.skills/_tools/ledger.py` on every run. **Do not edit by hand**;",
        "add a skill file instead and re-run any test.",
        "",
        f"* runs recorded: **{len(entries)}**",
        f"* skill + defect documents: **{len(skills)}**",
        f"* latest pass rate: **{entries[-1]['pass_rate']}%**"
        if entries else "* latest pass rate: — (no runs yet)",
        f"* trend: {trend}",
        "",
        "## How the numbering works",
        "",
        "| Kind | Pattern | Assigned by |",
        "|---|---|---|",
        "| Run | `run-NNN-YYYYMMDDTHHMM` | `ledger.make_run_dir()` |",
        "| Skill | `SKL-NNN-YYYYMMDDTHHMM-<slug>.md` | `ledger.next_numbers()` |",
        "| Defect | `KF-NNN` (stable, referenced from `checks.py`) | `ledger.next_numbers()` |",
        "",
        "`NNN` never repeats. A new run gets the next run number; a new skill gets the",
        "next skill number; a new defect gets the next defect number. The timestamp is",
        "the UTC start of the run that produced it, so files sort chronologically.",
        "",
        "## Skills (how to test — reusable)",
        "",
    ]
    plain = [s for s in skills if s["kind"] == "skill"]
    defects = [s for s in skills if s["kind"] == "defect"]
    if plain:
        lines += ["| ID | File | Title | Confidence | Reuse |", "|---|---|---|---|---|"]
        for s in plain:
            lines.append(f"| {s['id']} | `{s['file']}` | {s['title'] or '—'} | "
                         f"{s.get('confidence') or '—'} | {s.get('reuse') or '—'} |")
    else:
        lines.append("_none yet_")
    lines += ["", "## Known defects (what is broken — with reproduction)", "",
              "| ID | File | Title | Severity |", "|---|---|---|---|"]
    if defects:
        for s in defects:
            lines.append(f"| {s['id']} | `{s['file']}` | {s['title'] or '—'} | "
                         f"{s.get('severity') or '—'} |")
    else:
        lines.append("_none yet_")

    lines += ["", "## Run history", ""]
    if entries:
        lines += ["| # | Run | Label | Commit | Checks | Passed | Known | Failed | Rate |",
                  "|---|---|---|---|---|---|---|---|---|"]
        rows = []
        for i, e in enumerate(reversed(entries), 1):
            rows.append(
                f"| {len(entries) - i + 1} | `{e['run']}` | {e['label']} | `{e['commit']}` | "
                f"{e['checks']} | {e['passed']} | {e['known']} | {e['failed']} | "
                f"{e['pass_rate']}% |")
        lines += rows
        lines += ["", "### Pass-rate trend", ""]
        for e in entries[-20:]:
            bar = "█" * max(1, int(round(e["pass_rate"] / 4)))
            lines.append(f"    {e['run']:<24} {e['pass_rate']:>6.2f}%  {bar}")
        lines.append("")
    else:
        lines += ["_no runs yet — run `python \"1.all files/shared/run.py\"`_", ""]

    text = "\n".join(lines)
    with open(INDEX_PATH, "w") as fh:
        fh.write(text)
    return INDEX_PATH


def _trend(entries: list[dict]) -> str:
    if len(entries) < 2:
        return "—"
    delta = entries[-1]["pass_rate"] - entries[0]["pass_rate"]
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "▬")
    return f"{arrow} {abs(delta):.2f} pts vs first run"


def add_skill(title: str, body: str, kind: str = "skill", defect_id: str | None = None,
              when: datetime | None = None) -> str:
    """Write a new numbered skill/defect document and refresh the index."""
    when = when or datetime.now(timezone.utc)
    nums = next_numbers()
    if kind == "defect":
        ident = defect_id or f"KF-{nums['defect']:03d}"
        name = f"{ident}-{when.strftime('%Y%m%dT%H%M')}-{slugify(title)}.md"
    else:
        name = f"SKL-{nums['skill']:03d}-{when.strftime('%Y%m%dT%H%M')}-{slugify(title)}.md"
    path = os.path.join(SKILLS_DIR, name)
    with open(path, "w") as fh:
        fh.write(body)
    write_index()
    return path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="skill ledger")
    ap.add_argument("--index", action="store_true", help="regenerate skills-index.md")
    ap.add_argument("--record", metavar="RESULTS_JSON", help="append a run to the ledger")
    ap.add_argument("--next", action="store_true", help="show the next free numbers")
    args = ap.parse_args()
    if args.next:
        print(json.dumps(next_numbers(), indent=1))
    if args.record:
        print(json.dumps(record_run(args.record), indent=1))
    if args.index or not any(vars(args).values()):
        print(write_index())
