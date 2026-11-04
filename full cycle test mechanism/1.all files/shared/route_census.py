#!/usr/bin/env python3
"""Route census — how much of the URL map does the suite actually touch?

The full-cycle mechanism answers "are the numbers right?"; it does not answer
"how much of the app did we even visit?".  This tool closes that second gap:
it enumerates every rule on ``app.url_map`` and marks it **covered** when some
path string in the suites matches it.

Coverage is *static*: it reads URL literals out of the test sources with
``ast``, so a route counts as covered when the suite mentions a path that the
rule can serve.  It is deliberately conservative — a route that is only reached
through ``url_for()`` shows up as a gap even when a test exercises it.  Treat
the list as "places to look", not as a claim of untested code.

    python "1.all files/shared/route_census.py"            # human summary
    python "1.all files/shared/route_census.py" --json out.json --md gap.md

Nothing is written unless ``--json`` / ``--md`` is given, and the app is booted
on a throw-away database inside a temp dir, exactly like ``harness.boot``.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

METHOD_RE = re.compile(r"^[A-Z]+$")
VERB_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


# --------------------------------------------------------------------------
# 1. the rule table
# --------------------------------------------------------------------------
def load_rules(db_path: str) -> list[dict]:
    """Boot the app once and turn ``url_map`` into plain dicts."""
    from harness import prepare_env

    prepare_env(db_path, fresh=True)
    from app import create_app  # noqa: E402  (import after env is set)

    app = create_app()
    rules = []
    for rule in app.url_map.iter_rules():
        methods = sorted(m for m in rule.methods if m in VERB_METHODS)
        rules.append({
            "rule": str(rule.rule),
            "endpoint": rule.endpoint,
            "methods": methods,
            "read_only": methods in (["GET"], ["GET", "HEAD"], ["HEAD"]),
        })
    rules.sort(key=lambda r: (r["rule"], r["endpoint"]))
    return rules


# --------------------------------------------------------------------------
# 2. the paths the suites mention
# --------------------------------------------------------------------------
def _usable(value: str) -> bool:
    value = value.strip()
    return (value.startswith("/") and not value.startswith("//")
            and len(value) <= 160 and " " not in value and "<" not in value)


def url_literals(paths: list[str]) -> dict[str, list[str]]:
    """``{url_literal: [file, ...]}`` for every URL-looking string constant.

    An f-string like ``f"/ledger/{client_id}"`` contributes the *prefix*
    ``/ledger/`` — matched later as ``/ledger/<any>`` — because the interesting
    part of a templated URL is the static part at the front.
    """
    found: dict[str, list[str]] = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except (OSError, SyntaxError):
            continue
        rel = os.path.relpath(path, REPO_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if _usable(value):
                    found.setdefault(value.split("?")[0], []).append(rel)
            elif isinstance(node, ast.JoinedStr) and node.values:
                head = node.values[0]
                if isinstance(head, ast.Constant) and isinstance(head.value, str):
                    prefix = head.value.strip()
                    if _usable(prefix) and len(node.values) > 1:
                        found.setdefault(prefix, []).append(rel)
    return found


def source_files() -> list[str]:
    """Every suite source: the mechanism engine + the pytest suite."""
    out = []
    shared = HERE
    for name in os.listdir(shared):
        if name.endswith(".py"):
            out.append(os.path.join(shared, name))
    tests_dir = os.path.join(REPO_ROOT, "tests")
    for root, _dirs, files in os.walk(tests_dir):
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(root, name))
    return out


# --------------------------------------------------------------------------
# 3. matching
# --------------------------------------------------------------------------
def compiled(rule: str) -> re.Pattern:
    """Flask rule -> regex.  ``<int:id>`` matches ``12``, ``<slug:x>`` matches a word."""
    pattern = re.sub(r"<(?:(?P<conv>[a-zA-Z_]+):)?(?P<name>[a-zA-Z_]+)>", _conv, rule)
    return re.compile("^" + pattern + "/?$")


def _conv(match: re.Match) -> str:
    conv = (match.group("conv") or "string").lower()
    if conv == "int":
        return r"-?\d+"
    if conv == "float":
        return r"-?\d+(?:\.\d+)?"
    if conv == "path":
        return r".+"
    if conv == "uuid":
        return r"[0-9a-fA-F-]{32,36}"
    return r"[^/]+"


def census(rules: list[dict], literals: dict[str, list[str]]) -> dict:
    """Match every rule against every URL literal.

    Two ways to match:

    * **exact** — the literal satisfies the rule's regex (``/ledger/2``)
    * **prefix** — the literal is the static head of a templated URL and the
      rule starts with it (``/ledger/`` reaches ``/ledger/<int:client_id>``)

    Exact wins; prefix matches are kept in ``examples`` so a reader can tell a
    real visit from an f-string that merely mentions the family.
    """
    hits = {r["rule"] + "::" + r["endpoint"]: [] for r in rules}
    exact = {r["rule"] + "::" + r["endpoint"]: 0 for r in rules}
    for rule in rules:
        key = rule["rule"] + "::" + rule["endpoint"]
        rx = compiled(rule["rule"])
        head = rule["rule"].split("<")[0]
        for literal in literals:
            if literal == rule["rule"] or rx.match(literal):
                hits[key].append(literal)
                exact[key] += 1
            elif head and len(head) > 1 and literal.rstrip("/") == head.rstrip("/"):
                hits[key].append(literal + "…")

    covered, gaps = [], []
    for rule in rules:
        key = rule["rule"] + "::" + rule["endpoint"]
        row = dict(rule, examples=sorted(hits[key])[:4], hits=len(hits[key]),
                   exact_hits=exact[key])
        (covered if row["hits"] else gaps).append(row)

    return {
        "rules": len(rules),
        "endpoints": len({r["endpoint"] for r in rules}),
        "covered": len(covered),
        "exact_only": sum(1 for r in covered if r["exact_hits"]),
        "prefix_only": sum(1 for r in covered if not r["exact_hits"]),
        "gap": len(gaps),
        "coverage_pct": round(100.0 * len(covered) / len(rules), 2) if rules else 0.0,
        "read_only_rules": sum(1 for r in rules if r["read_only"]),
        "covered_rows": covered,
        "gap_rows": gaps,
    }


def by_blueprint(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        name = row["endpoint"].split(".")[0] if "." in row["endpoint"] else "(app)"
        out[name] = out.get(name, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


# --------------------------------------------------------------------------
# 4. output
# --------------------------------------------------------------------------
def render_markdown(result: dict, label: str) -> str:
    gaps_bp = by_blueprint(result["gap_rows"])
    cov_bp = by_blueprint(result["covered_rows"])
    lines = [
        f"# Route census — {label}",
        "",
        f"| | |",
        "|---|---|",
        f"| URL rules | {result['rules']} |",
        f"| Unique endpoints | {result['endpoints']} |",
        "| Reached by the suites | "
        f"{result['covered']} (exact {result['exact_only']}, "
        f"prefix {result['prefix_only']}) |",
        f"| Not reached by any URL literal | {result['gap']} |",
        f"| Coverage (static) | **{result['coverage_pct']}%** |",
        "",
        "> Static coverage only: a rule counts as reached when a URL literal in",
        "> `shared/*.py` or `tests/**/*.py` matches it.  Routes built with",
        "> `url_for()` are counted as gaps even when a test exercises them, so read",
        "> the gap list as *places to inspect*, not as untested code.",
        "",
        "## Gaps per blueprint",
        "",
        "| Blueprint | Gaps | Reached |",
        "|---|---|---|",
    ]
    for name, count in gaps_bp.items():
        lines.append(f"| `{name}` | {count} | {cov_bp.get(name, 0)} |")
    lines += ["", "## Gap list", "", "| Rule | Endpoint | Methods |", "|---|---|---|"]
    for row in result["gap_rows"]:
        lines.append(f"| `{row['rule']}` | `{row['endpoint']}` | {', '.join(row['methods'])} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="local")
    ap.add_argument("--json", help="write the full census here")
    ap.add_argument("--md", help="write a markdown gap list here")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        rules = load_rules(os.path.join(tmp, "census.db"))
    result = census(rules, url_literals(source_files()))

    print(f"label    : {args.label}")
    print(f"rules    : {result['rules']}  endpoints: {result['endpoints']}")
    print(f"reached  : {result['covered']}  gaps: {result['gap']}  "
          f"({result['coverage_pct']}%)")
    print("\ngaps per blueprint:")
    for name, count in by_blueprint(result["gap_rows"]).items():
        print(f"  {count:>3}  {name}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result, fh, indent=1)
        print(f"\nwrote {args.json}")
    if args.md:
        with open(args.md, "w") as fh:
            fh.write(render_markdown(result, args.label))
        print(f"wrote {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
