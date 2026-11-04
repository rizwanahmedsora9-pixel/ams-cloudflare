# SKL-004 — Assert PDF *content*, never byte counts

**Confidence:** high — byte counts changed twice during a single session
**Reuse:** every download check
**Cost:** one extra import (`pypdf`)

---

## The trap

A PDF generated twice from the same data is not byte-identical, and file size
depends on the renderer:

| Variable | Effect on bytes |
|---|---|
| generation timestamp in the footer | different every second |
| WeasyPrint vs ReportLab fallback | ~5 % swing |
| font subsetting | depends on the characters used |
| page count | dominates everything else |

The same P&L export measured **57,042 B**, then **57,154 B**, then **52,293 B**
across three runs while its *content* never changed. Asserting size would have
red-lined a healthy build three times.

## The technique

```python
status, size, text = session.pdf_text("/profit_reports/export/pdf?start_date=...&end_date=...")
assert status == 200
assert size > 1000                  # guard: not an empty/error page
assert "Profit & Loss" in text      # the document is the right one
assert "55,000" in text             # the figure is present
```

`Session.pdf_text()` extracts the text with `pypdf` and normalises whitespace, so
assertions read like assertions on the page.

## What to assert, in priority order

1. **the document's identity** — its title string (`Profit & Loss Control
   Center`, `SUPPLIER LEDGER STATEMENT`, `INVOICE Direct Sale (Cash)`)
2. **the headline figures** — the two or three numbers a human would check
3. **a negative** — the PDF must not contain `None`, `nan`, or an empty table
4. **size, only as a floor** (`> 1000`), never as an equality

## Why this matters more here than usual

WeasyPrint is **not importable** in this environment, so every PDF silently
falls back to `pdf_fallback._render_reportlab_pdf` (14.8 × 21 cm, 1 cm margins).
A byte-count assertion would pass on one machine and fail on the next while the
*content* was identical — the worst kind of red build, because it trains people
to ignore failures.

## Two real findings from reading PDF text

* **The client ledger names the client's *local* header while the supplier
  ledger uses the configured company name.** Reading the text surfaced the
  fallback constant `FAZAL BUILDING MATERIALS` in one and
  `Ahmed Cement / AMS` in another — a consistency question no size check would
  ever raise.
* **The P&L PDF carries 21.09 % (net margin) but not 26.73 % (markup)** — the
  service computes `markup_pct` and no template renders it. That became
  `KF-007`, found purely by asserting the *presence* of a specific figure in the
  exported document.

## Reusable helper shape

```python
def assert_pdf(session, R, cid, path, title, numbers):
    status, size, text = session.pdf_text(path)
    missing = [n for n in numbers if n not in text]
    ok = status == 200 and size > 1000 and title.lower() in text.lower() and not missing
    R.truth(cid, f"PDF {path.split('?')[0]} ({size}B) "
                 f"{'missing ' + str(missing) if missing else 'ok'}",
            ok, f"{status} {size}B", f"{title} {numbers}")
```

The detail string names *what* was missing, so a failure is diagnosable from the
report alone — no need to re-run to find out.

## When a byte count *is* the right assertion

Only for a **regression guard on a file you know is deterministic** — e.g. an
XLSX export with no timestamps where you want to detect a silent format change.
Even then prefer asserting the parsed content (`openpyxl` → sheet names, row
counts, cell values).
