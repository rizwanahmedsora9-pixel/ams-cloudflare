"""Self-test for the ledger.  Run it after editing ledger.py.

    .venv/bin/python "2.skills/_tools/test_ledger.py"
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger


def sandbox():
    tmp = tempfile.mkdtemp()
    for d in ("1.all files", "2.skills"):
        os.makedirs(os.path.join(tmp, d))
    open(os.path.join(tmp, "2.skills", "ledger.jsonl"), "w").close()
    ledger.MECH = tmp
    ledger.FILES_DIR = os.path.join(tmp, "1.all files")
    ledger.SKILLS_DIR = os.path.join(tmp, "2.skills")
    ledger.LEDGER_PATH = os.path.join(tmp, "2.skills", "ledger.jsonl")
    ledger.INDEX_PATH = os.path.join(tmp, "2.skills", "skills-index.md")
    return tmp


def check(name, got, want):
    ok = got == want
    print(f"  [{'ok ' if ok else 'FAIL'}] {name}: {got!r}")
    return ok


def main() -> int:
    failures = 0
    tmp = sandbox()

    failures += not check("empty numbers", ledger.next_numbers(),
                          {"run": 1, "skill": 1, "defect": 1})

    made = ledger.make_run_dir("first", when=__import__("datetime").datetime(
        2026, 11, 4, 5, 18))
    failures += not check("run dir name",
                          os.path.basename(made), "run-001-20261104T0518")
    failures += not check("run dir has 3 subdirs",
                          sorted(d for d in os.listdir(made) if os.path.isdir(
                              os.path.join(made, d))),
                          ["artifacts", "results", "scripts"])

    failures += not check("numbers after one run", ledger.next_numbers()["run"], 2)

    path = ledger.add_skill("first skill", "# SKL-001 — first\n\n**Confidence:** high\n",
                            when=__import__("datetime").datetime(2026, 11, 4, 5, 18))
    failures += not check("skill filename",
                          os.path.basename(path),
                          "SKL-001-20261104T0518-first-skill.md")
    failures += not check("numbers after one skill", ledger.next_numbers()["skill"], 2)

    # a defect gets the next defect number and keeps a stable id
    dpath = ledger.add_skill("a defect", "# KF-001 — a defect\n\n**Severity:** high\n",
                             kind="defect",
                             when=__import__("datetime").datetime(2026, 11, 4, 5, 18))
    failures += not check("defect filename",
                          os.path.basename(dpath),
                          "KF-001-20261104T0518-a-defect.md")

    # the index must list both, and must not list itself
    ledger.write_index()
    index = open(os.path.join(tmp, "2.skills", "skills-index.md")).read()
    failures += not check("index lists the skill", "SKL-001" in index, True)
    failures += not check("index lists the defect", "KF-001" in index, True)
    failures += not check("index excludes itself", "skills-index.md" in index, False)

    # recording a run appends exactly one ledger line and updates the trend
    run_dir = os.path.join(tmp, "1.all files", "run-002-20261104T0525")
    os.makedirs(run_dir, exist_ok=True)
    results = {
        "run": {"run_dir": "run-002-20261104T0525", "label": "test",
                "finished": "2026-11-04T05:25:00+00:00", "git_commit": "abc123",
                "git_branch": "arena/x", "duration_s": 1.0},
        "score": {"total": 10, "passed": 8, "known_defects": 2, "failures": 0,
                  "pass_rate": 80.0},
        "checks": [
            {"id": "A", "ok": True, "known_defect": None},
            {"id": "B", "ok": False, "known_defect": "KF-001"},
        ],
    }
    rpath = os.path.join(run_dir, "results.json")
    json.dump(results, open(rpath, "w"))
    entry = ledger.record_run(rpath)
    failures += not check("ledger entry run", entry["run"], "run-002-20261104T0525")
    failures += not check("ledger entry known ids", entry["known_ids"], ["KF-001"])
    failures += not check("ledger has 1 line", len(ledger.read_ledger()), 1)

    # a second run must produce a trend arrow
    index = open(os.path.join(tmp, "2.skills", "skills-index.md")).read()
    failures += not check("index has a run row", "run-002-20261104T0525" in index, True)

    shutil.rmtree(tmp)
    print("\n" + ("all ledger self-tests passed" if not failures
                  else f"{failures} ledger self-test(s) FAILED"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
