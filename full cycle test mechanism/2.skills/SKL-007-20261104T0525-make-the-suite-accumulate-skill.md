# SKL-007 — Make a test suite accumulate skill instead of accumulating files

**Confidence:** high — the loop is implemented and three consecutive runs were recorded
**Reuse:** every run, forever; this is the meta-skill the other six sit inside
**Cost:** one JSON line per run; no extra test time

---

## The problem this solves

Most "test suites" are write-only: they run, print green, and teach nobody
anything. Ten runs later the team has ten log files and the same knowledge it had
at run one. The evidence grew; the *capability* did not.

A suite accumulates skill only if three things are true:

1. **every run is recorded somewhere machine-readable** (so you can compare),
2. **every lesson becomes a document with a number** (so it can be cited), and
3. **the next run is forced to look at both** (so nothing is silently repeated).

## The three artifacts that make it work

| Artifact | Write pattern | Answers |
|---|---|---|
| `1.all files/run-NNN-<stamp>/` | append-only, immutable | *what happened on this run?* |
| `2.skills/ledger.jsonl` | append-only, one line per run | *is the trend getting better?* |
| `2.skills/SKL-NNN` / `KF-NNN` | append-only, numbered | *what do we know now that we did not?* |
| `2.skills/skills-index.md` | regenerated, never hand-edited | *what is our current capability?* |

The index is **derived**. If it is ever deleted, `ledger.py --index` rebuilds it
from the other three. That is intentional: it prevents the index from becoming
the source of truth and drifting.

## The ledger line

```json
{"run":"run-003-20261104T0525","label":"numbering-and-meta-proof","commit":"2867c3e",
 "checks":85,"passed":82,"known":3,"failed":0,"pass_rate":96.47,
 "known_ids":["KF-001","KF-005","KF-007"],"failed_ids":[],"duration_s":13.9}
```

Five questions become one-liners:

```bash
# which defects have survived the last five runs?
tail -5 "2.skills/ledger.jsonl" | jq -r '.known_ids[]' | sort | uniq -c

# has the suite grown?
tail -2 "2.skills/ledger.jsonl" | jq -r '"\(.run) \(.checks) checks"'

# when did it last fail?
grep -v '"failed": 0' "2.skills/ledger.jsonl" | tail -1

# how long does a run take now vs the first?
jq -s 'map(.duration_s)' "2.skills/ledger.jsonl"
```

`known_ids` is the important field. A defect that appears in ten consecutive
lines is not "known" — it is **ignored**, and the ledger makes that impossible to
pretend otherwise.

## The contribution rule

Every run must write one line into its own `META.json`:

```json
{"label":"numbering-and-meta-proof",
 "contribution":"3 known defect(s) still reproduce: KF-001, KF-005, KF-007 · 31/31 write paths ok"}
```

`run.py` generates this automatically. The rule it enforces:

> A run that contributes nothing is allowed — but it must **say** so.

Because the field is generated from the actual results, a hollow run is visible
in one glance, and a run that found something cannot forget to record it.

## Numbering is the load-bearing detail

| Kind | Pattern | Why this shape |
|---|---|---|
| Run | `run-NNN-YYYYMMDDTHHMM` | sorts chronologically, number survives a rename |
| Skill | `SKL-NNN-YYYYMMDDTHHMM-slug` | citable from a PR ("see SKL-004"), date for context |
| Defect | `KF-NNN` **no timestamp** | must stay stable — `checks.py` hard-codes it |

The asymmetry is deliberate. Skills are *discovered* (the date matters). Defects
are *referenced* (the id must never move, or every `known=D_*` breaks).

`ledger.next_numbers()` scans the directories, so it works even if someone adds a
file by hand — the next number is `max + 1`, never a counter that can drift.

## Why "known defects" is what makes growth possible

Without a third state, a suite with three broken behaviours is permanently red,
so nobody reads it, so nothing is learned. With the `KNOWN` state:

* the run is green at `failed: 0`, so attention is available for *new* failures
* the known count is visible and trended, so debt cannot hide
* each known-defect check **inverts on fix**, so the suite tells you when a
  defect dies (see `SKL-006`)

That last property is the one that converts a test suite into a learning system:
the suite is not just checking the product, it is tracking its own knowledge of
the product's defects, and updating it automatically.

## The failure mode to watch

The only way this mechanism rots is if `known=` becomes a dumping ground. Two
guards:

1. `known=` can only be added in a `checks.py` diff — it is reviewable.
2. `REVIEW` in the run checklist asks explicitly: *"did any check move PASS →
   KNOWN, and if so, is there a KF document?"*

If a defect has been `KNOWN` for more than ~5 runs with no `status:` change in its
KF document, the honest move is either to fix it or to **document it as accepted
behaviour and turn the check into an assertion of the accepted behaviour**. Both
are fine. Letting it sit as `KNOWN` forever is the only wrong answer.

## When NOT to use this pattern

It is heavier than a plain test suite. It earns its cost when:

* the system has **money** in it (so a wrong number matters),
* the domain is **wide** (566 routes, 126 templates — you cannot hold it in mind),
* and defects are **tolerated temporarily** (so you need a way to stay green
  without lying).

For a small library with a fast CI and zero known debt, plain `pytest` is better.
The three-state machinery exists to make *imperfect* systems testable.
