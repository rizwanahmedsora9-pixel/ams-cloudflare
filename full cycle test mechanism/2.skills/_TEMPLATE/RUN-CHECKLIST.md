# Run checklist — do these five things every run

Copy this into the run's `META.json` `contribution` field (or answer it in the PR
description). A run that answers "nothing" to every line is a smoke test, not a
learning loop — say so explicitly rather than pretending.

## 1. What changed since the last run?

```bash
git log --oneline "$(git rev-list -1 HEAD)" ^<last-run-commit> --
```

The last commit is in `2.skills/ledger.jsonl` (field `commit`).

## 2. Did any check change state?

| Was | Now | Action |
|---|---|---|
| `PASS` | `KNOWN` | a new defect — write `KF-NNN`, add the `known=` flag |
| `KNOWN` | `PASS` | fixed — **delete the `known=` flag**, the check becomes a regression guard |
| `PASS` | `FAIL` | regression — this is the run's most important output |
| `FAIL` | `FAIL` | either still broken (update the KF doc's status) or the check is flaky (fix the check) |

Diff two runs without a tool:

```bash
diff <(jq -r '.checks[]|"\(.id)\t\(.ok)\t\(.known_defect)"' run-A/results.json) \
     <(jq -r '.checks[]|"\(.id)\t\(.ok)\t\(.known_defect)"' run-B/results.json)
```

## 3. Does the new behaviour have an assertion?

If the PR added a page, a field, a total or a guard, `checks.py` must grow by at
least one line. **A merged feature with no check is a future regression.**

## 4. Does the run add a document to `2.skills`?

| Situation | Add |
|---|---|
| used a new technique | `SKL-NNN-<stamp>-<slug>.md` |
| found a defect | `KF-NNN-<slug>.md` + `known=` |
| a check proved flaky | extend an existing SKL's "Traps" table |
| nothing new | nothing — but record *why* in `META.json` |

## 5. Is the trend healthy?

```bash
tail -3 "2.skills/ledger.jsonl" | jq -r '"\(.run)  \(.passed)/\(.checks)  known=\(.known)  failed=\(.failed)"'
```

| Pattern | Reading |
|---|---|
| rate flat, `known` flat, `failed` 0 | stable — fine, but the suite is not growing |
| rate rising | skills are landing |
| `known` climbing | debt is outrunning fixes — stop adding features |
| `failed` > 0 | **do not merge** until triaged |

---

## Anti-patterns

| Don't | Why |
|---|---|
| add `known=` to a check you have not seen fail | it becomes a place to hide bugs |
| assert on HTML fragments | a CSS change red-lines the suite |
| assert on PDF byte counts | non-deterministic (see `SKL-004`) |
| put a number in two files | `data.py` is the only home for totals |
| boot a finished run's DB with `fresh=True` | it deletes the evidence (`SKL-001`) |
| keep a `known=` flag after the fix | the check stops testing anything |
