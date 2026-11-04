# SKL-008 — Measure breadth, not just correctness: census the URL map, smoke-crawl it, then audit the harness itself

**Confidence:** high — one run produced three findings the 85 checks could not
(`KF-008` plus 299 unrouted gaps and 8 permanent 404s), all in under 10 s
**Reuse:** whenever a suite is green and someone asks "so is the app tested?"
**Cost:** ~4 s for the census, ~5 s for the crawl, both read-only
**Prereqs:** a seeded `cycle.db` (any finished run, `--keep-db` not needed — the
file is kept by default) and `1.all files/shared/harness.py`

---

## What this replaces

Reading the check list and assuming it covers the app. A suite of 85 assertions
on one page each is deep on the pages it names and blind everywhere else; nobody
notices the blindness because the pass rate looks like a percentage of the app
rather than a percentage of the assertions.

Three questions, three tools, none of them a rewrite:

| Question | Tool | Answer on `e8cdde0` |
|---|---|---|
| Which routes exist? | `shared/route_census.py` | 566 rules / 563 endpoints |
| Does each GET route still render? | `shared/urlmap_smoke.py` | 257 crawled, **0 × 5xx** |
| Is every flow the harness *defines* actually *run*? | `inspect.getsource` check (`M-01`) | 31 of 36 flows — `KF-008` |

## The technique

**1. Census: rule table × URL literals = a gap list.** Static, no browser, no
coverage plugin.

```python
import ast, re
from app import create_app

rules = [str(r.rule) for r in create_app().url_map.iter_rules()]

def literals(path):
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
           and node.value.startswith("/"):
            yield node.value.split("?")[0]            # "/ledger/2"
        elif isinstance(node, ast.JoinedStr) and node.values:
            head = node.values[0]                     # f"/ledger/{id}"
            if isinstance(head, ast.Constant):
                yield head.value                      # "/ledger/"  -> prefix
```

Then match twice — **exact** (`/ledger/2` against `^/ledger/-?\d+$`) and
**prefix** (`/ledger/` against the static head of `/ledger/<int:id>`). Report
both counts; a rule reached only by a prefix is a family someone mentioned, not a
page someone visited.

```bash
python "1.all files/shared/route_census.py" --label run-005 \
       --json reports/evidence/route-coverage.json \
       --md   reports/evidence/route-coverage.md
# rules 566 | reached 267 (exact 165, prefix 102) | gaps 299 (47.17%)
```

**2. Smoke-crawl every read-only rule on a *copy* of a seeded database.** The
copy is the whole trick: a crawl is allowed to be sloppy because it cannot hurt
the evidence.

```python
import shutil, tempfile
shutil.copy(run_db, os.path.join(tmp, "smoke.db"))
session = boot(os.path.join(tmp, "smoke.db"), fresh=False)   # fresh=False keeps data

for rule in session.app.url_map.iter_rules():
    if not set(rule.methods) <= {"GET", "HEAD", "OPTIONS"}:
        continue                                  # never wander into writes
    url = re.sub(r"<int:[^>]+>", "1", str(rule.rule))
    status = session.get(url).status_code
    # 5xx == defect. 404 = the id really doesn't exist. 302 = login/permission.
```

```bash
python "1.all files/shared/urlmap_smoke.py" \
       --db "1.all files/run-005-20261104T0538/cycle.db" --label run-005
# routes 257 | ok 117 | redirect 76 | not-found 8 | skipped 56 | 5xx 0
```

Only `5xx` (and a raised exception) is a finding. Treating `404` as failure makes
the crawl cry wolf on every `<int:id>` route and the report stops being read;
`/delivery_rents/group/test` and `/legacy-migration/run/1` are *correctly* 404.

**3. Audit the harness with the harness.** The cheapest way to find a silently
skipped flow is to ask the source whether the function is reachable:

```python
import inspect, seed
wired = "mutate(" in inspect.getsource(seed.seed)      # False on e8cdde0
```

Wrap that in a check (`M-01`) with `known=` so it (a) fails loudly today and
(b) turns green the day someone wires it, with no edit beyond deleting the flag.

## Why it works

Correctness checks and breadth checks fail in opposite directions, which is why
they need each other:

* a figure assertion is *brittle* — it breaks on a format change — and *narrow*;
* a crawl is *coarse* — it only sees 5xx/404 — and *wide*.

The census sits between them: it cannot say a page is right, but it says, once,
which pages nobody has ever asked about. And because route count is a stable
number (566), coverage becomes a metric you can watch across runs instead of a
feeling.

The `getsource` trick works because Python keeps the body as text: "is this flow
reachable" is a question about the program's *shape*, answerable without running
anything, and immune to the suite's own reporting.

## Traps

| Trap | Correct |
|---|---|
| Count `url_for(...)`-built links as covered | Static census cannot see them — say so in the report, and keep the gap list as "places to look" |
| Crawl with `fresh=True` | Deletes the run's `cycle.db` first — always `fresh=False` on a **copy** |
| Crawl write routes "to see if they render" | A crawl that POSTs is a fuzz test; restrict to GET/HEAD/OPTIONS, and skip export/backup/admin by name |
| Report 47% as "47% of the app is untested" | 47% of *rules* have no URL literal; many are covered by pytest through `url_for` |
| Treat `404` on `/ledger/1` as a defect | Only 5xx is; a missing id is a correct 404 |
| Trust "31/31 steps ok" as "every flow ran" | It is 31 of the 36 *defined* stages — `KF-008` |

## When NOT to use it

* On a schema-less API where every path is a query — the census degenerates.
* As a replacement for the figure checks: a crawl passes on a page that renders
  `Rs. 0` for every total.
* Before the app boots without warnings — a crawl over a broken boot reports 566
  findings and zero information.

## Acceptance / how you know it worked

| Check | Before | After |
|---|---|---|
| Route census | none existed | 566 rules, 267 reached, 299 gaps (`evidence/route-coverage.md`) |
| URL-map crawl | none existed | 257 GET routes, 0 × 5xx (`evidence/urlmap-smoke.md`) |
| `M-01` phase-2 flows reachable | not asked | `False` → `KF-008` written, 5 flows named |
| Findings from one 20 s run | 0 | 1 new defect, 2 blind spots, 8 verified 404s |
