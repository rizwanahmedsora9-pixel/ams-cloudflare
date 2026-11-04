# KF-NNN — <symptom in one line>

**Severity:** high | medium | low — <the consequence, not the code smell>
**Status:** open | fixed in `<commit>` | accepted (won't fix)
**Found by:** SKL-NNN / <which run>

---

## Symptom

<What a user sees. Real numbers from a real run, never paraphrased.>

```
<page output>
```

## Reproduction

```bash
<exact command>
```

## Root cause

`<file>:<line>`

```python
<the offending code>
```

## The proof that names the cause

<The difference that factors cleanly into a known quantity.>

## Impact

* <who is hurt and how>

## Fix

```python
<the change>
```

## Acceptance

| Check | Before | After |
|---|---|---|
| `<id>` | <observed> | <expected> |

Remove `known=D_<NAME>` from the check when it goes green.

> **Rule:** every defect must name the check id that proves it. A defect with no
> failing check is a rumour.
