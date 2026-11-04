# SKL-009 — Walk the real app page by page, form by form — then say what is still unproved

**Confidence:** high — one 14 s walk covered 58 pages, 209 forms, 773 fields, 890
columns, 243 routes, 214 links, 10 tie-outs and 8 end-to-end workflows with 0
hard findings, on `e8cdde0`
**Reuse:** whenever someone asks "did you test the app or just the tests?"
**Cost:** ~14 s after a seeded database exists; no browser, no Selenium
**Prereqs:** a seeded `cycle.db` (any finished run), the page inventory
(`run-001/results/pages.md`), and `shared/harness.py`

---

## What this replaces

Reading a green pass-rate and answering "yes, the app works". A figure suite is
deep and narrow: 86 assertions over 31 flows say nothing about whether the other
50 pages still render, whether an input was renamed, or whether a link dead-ends.
The walk answers those with the same test client the suite already uses.

## The technique

**1. Turn the documentation into expectations — once.**

```python
PAGE_RE = re.compile(r"^## (\S+)\s+—\s+(.*?)\s+\[HTTP (\d+), (\d+)B\]")
FORM_RE = re.compile(r"^- FORM (GET|POST) (\S+) id=(\S*)")
# -> [{"path", "title", "status", "forms": [{"method","action","fields"}]}]
```

`pages.md` was produced by crawling the app, so it is a snapshot of intent that
can be *replayed* as a test. 58 pages, 209 forms, 773 field names, 890 columns.

**2. Read the real page, with the scripts removed.**

```python
class _FormSpy(HTMLParser):
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"method": (a.get("method") or "GET").upper(),
                               "action": a.get("action") or "", "fields": set()})
        elif self.forms and tag in ("input", "select", "textarea", "button"):
            if a.get("name"):
                self.forms[-1]["fields"].add(a["name"])

html = re.sub(r"<script.*?</script>", "", html, flags=re.S)   # <-- the whole point
```

Removing `<script>` is not tidiness: a form that exists only inside a JS template
is not a form a human can submit. That single line is the difference between
"the page defines a cash-flow form" and `KF-005`.

**3. Compare as sets, keyed by `(method, action)`.** Field order changes, ids
change, CSRF tokens appear and disappear; the pair plus a field *set* does not.

**4. Assert three witnesses per workflow.** flash message, listing page, database
row. Then reverse it: create → void, submit → replay, toggle → toggle back.

```python
cash0 = balance("Main Cash")
post("/accounts/payments/clients/save", {..., "amount": 1000})
cash1 = balance("Main Cash")          # 175500 -> 176500
assert post(f"/accounts/payments/clients/void/{payment_id}")
cash2 = balance("Main Cash")          # back to 175500, is_void=1, audit row
```

**5. Print what remains unproved.** The walk proves *pages and flows*; it cannot
prove a total. Close the report with the defects that live in the other half
(`KF-001` … `KF-008`) or the reader will assume green means correct.

## Why it works

Documentation is a *specification with a commit hash*. Replaying it against the
current app converts prose into a diff: 209 forms either resolve to markup or
they do not, 773 names either exist or they do not, 214 links either answer or
they 404. Nothing here is a judgement call, which is why the result fits in one
screen and takes 14 seconds.

The three-witness rule is what makes a workflow check survive contact with
reality: the flash can lie (a handler can flash success and roll back), the
listing can lag (a redirect can land on a cached page), the row cannot.

## Traps

| Trap | What actually happened | Correct |
|---|---|---|
| Follow every href | `/logout` is a GET link; the session died mid-walk and the next 30 assertions all "failed" | skip logout/login/wipe/reset/backup by regex, and report how many were skipped |
| `resp.text` on downloads | PDF/XLSX exports raised `UnicodeDecodeError` → 15 phantom route failures | `resp.data.decode("utf-8", "replace")`; judge status, not text |
| Assert a form on an empty table | `/cash_flow` "missing" the party-edit form because `cash_flow_party` had 0 rows | create the prerequisite row first, then assert |
| Compare raw HTML text | `Date &amp; Time` made 8 real columns look missing | `html.unescape` on both sides |
| Re-use an idempotency key across runs | the second walk's receipt was refused as a duplicate → a "failed" workflow | derive the key from the database name or a timestamp |
| Compare long doc "buttons" | `Financial Details Balances & totals` is a button + a description in one cell | only compare labels ≤ 40 chars |
| Treat a doc label as the page title | `Ledger (client list)` is a description; page says "Client Ledgers" | report title mismatches as *informational*, never as a failure |

Six of the seven traps produced **false defects on the first run** (15 bad routes,
1 failed page, 1 failed workflow). A walker that is not debugged against a known-
good app is a rumour generator.

## When NOT to use it

* As a substitute for the figure checks: every page in this walk reported 200
  while `KF-001` was understating cash on hand by 17,000.
* On a UI that renders client-side from an API — there is no server markup to
  compare, so you get 0 forms and a false green.
* Before the documentation is validated once by hand: a stale `pages.md` will
  report the app as broken when the app is the thing that moved.

## Acceptance / how you know it worked

| Check | Before | After |
|---|---|---|
| Documented pages verified live | 0 of 58 | **58 of 58 PASS** |
| Documented forms / fields in markup | unknown | **209 / 209 forms, 0 of 773 fields missing** |
| Read-only routes that 5xx | unknown | **0 of 243** |
| Dead links followed from those pages | unknown | **0 of 214** |
| Page-vs-page agreements | partially (86 figure checks) | **+10 independent tie-outs, 10/10** |
| End-to-end workflows driven by hand | 31 (mechanism) | **+8, including void and replay** |
| False defects before debugging the walker | — | 17 (all in the walker, all listed above) |
