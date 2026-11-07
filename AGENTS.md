# AGENTS.md

Orientation for an AI agent (or a human in a hurry). **Read this before opening
any file.** It exists so that finding the right 200 lines takes seconds, not a
tour of 125,000 lines.

---

## 1. What this is

AMS — a Flask 3 + SQLAlchemy 2 + SQLite ERP for a cement / building-materials
business in Pakistan. Sales, bookings, stock, GRN, dispatch, rentals, client and
supplier ledgers, chart of accounts, cash flow, reconciliation, reports, PDFs
(English + Urdu), Excel import/export.

One process, one database, no build step, no frontend bundler.

## 2. Commands

```bash
pip install -r requirements.txt          # core app (small, fast install)
pip install -r requirements-dev.txt      # + pandas, PyMuPDF, WeasyPrint (slow, native deps)
pytest                                   # tests/ — 1,100+ cases
pytest tests/test_services_master.py -x -q          # one module
pytest -k "grn and not slow" -x -q                  # by name
python main.py                           # dev server
```

`requirements-dev.txt` pulls WeasyPrint, which needs Pango/Cairo/GDK-PixBuf. If
that install is painful, `pip install -r requirements.txt` plus pytest is enough
for everything except PDF-layout tests — those skip themselves automatically.

## 3. Where the code is

| You want | Go to |
|---|---|
| App factory, config, extensions | `app/__init__.py` |
| Business logic | `app/services/` — 40+ modules, one concern each |
| HTTP routes | `app/blueprints/` (registered at boot by `utils/module_loader.py`) |
| Second route tree | `blueprints/` — auto-registered packages (accounts, inventory, import_export, …) |
| Data model | `models/` — SQLAlchemy classes, one file per domain |
| Schema migrations | `app/migrations/NNNN_*.sql`, auto-applied by `app/services/auto_migrate.py` |
| HTML | `templates/` — `layout.html` is the shell for everything |
| JS/CSS | `static/` (vendored Bootstrap 5.3 + Flatpickr; no build step) |
| Full-DB snapshot export/import | `full_db_sync/` (stdlib only) |
| Maintenance / audit scripts | `tools/` |

Both route trees are real. A URL may be served from `app/blueprints/` **or**
`blueprints/` — search for the path string in both before concluding a route
does not exist.

## 4. Ignore these (they cost you context and give nothing back)

| Path | Why |
|---|---|
| `LEGACY DATA/*.amsdb` | 10 MB SQLite snapshots, binary. `AMS_SMOOTH_IMPORT.amsdb` is a live pytest fixture — do not move or delete it. |
| `static/vendor/**` | Vendored Bootstrap/Icons/Flatpickr. Never edit; sourcemaps are git-ignored. |
| `static/fonts/JameelNooriNastaleeq.ttf` | 10.5 MB Urdu font. Only relevant to PDF work. |
| `full cycle test mechanism/1.all files/run-*` | 72 committed run artifacts from November 2026. History, not code. Latest runs live here. |
| `docs/history/` | Dated session reports. Not a description of today's tree. |
| `dummy_data/AMS_DUMMY_DATA_FULL.xlsx` | Generated sample workbook. |
| `instance/`, `backups/` | Runtime DB and backups. Git-ignored. |

## 5. Big files — read the function, not the file

These are monoliths. Use `grep -n` to find the function, then read ±80 lines.
Do not open them whole; several are larger than a comfortable context budget.

| File | Lines | Notes |
|---|---|---|
| `app/services/profit_loss.py` | ~3,090 | P&L, COGS, FIFO allocation |
| `setup_Deploy.py` | ~3,360 | PythonAnywhere installer, standalone stdlib script |
| `app/services/financial_ledgers.py` | ~2,090 | Client/supplier ledger projections |
| `app/services/void_rebuild.py` | ~1,920 | Void / restore / rebuild invariants |
| `app/blueprints/reports/cash.py` | ~1,820 | Cash-flow reports |
| `app/services/cash_flow_svc.py` | ~1,700 | Cash-flow engine |
| `templates/direct_sales.html` | ~3,140 | Largest screen |
| `templates/grn_wizard.html` | ~1,920 | GRN entry wizard |
| `templates/layout.html` | ~2,340 | Shell: sidebar, modals, global JS |

## 6. Invariants you must not break

1. **Balances are derived, never stored.** Account balances come from
   `AccountTransaction` rows. Σ of all balances is constant — a posting moves
   money between accounts, it does not create or destroy it.
2. **Every posted document has a symmetric reverse.** Edit / void / restore /
   hard-delete must undo exactly what the original applied. `app/services/void_rebuild.py`
   is the reference.
3. **Stock and material totals are recomputed, not patched.** Use
   `_rebuild_material_totals` rather than adjusting a total field.
4. **Mutating routes are CSRF-protected and idempotent.** Sale POST is
   idempotent by key; double-submit must not double-post.
5. **Permissions are enforced per user, per route.** A customised sidebar must
   never reveal a page a user could not otherwise open.
6. **A finalised reconciliation day is frozen.** Unlock first, then edit.

`tests/test_services_master.py`, `tests/test_predator_regressions.py` and
`tests/test_fifo_grn_profit_realtime.py` encode most of the above. If you change
one of those areas, run them.

## 7. House rules for changes

* Prefer a small edit in `app/services/` over a large one in a template.
* Comments in code have been kept meaningful — read them before rewriting a
  block, they usually record a bug that was fixed there.
* Add or extend a pytest for any behaviour change; the suite is the contract.
* Do not add root-level markdown. Docs go in `docs/` (see `docs/INDEX.md`).
* Do not rename or reorganise `LEGACY DATA/`, `checking tool/`, or
  `full cycle test mechanism/` without checking every reference — several tools
  build paths from those exact strings.
* Nothing here is committed by a hook except a co-author trailer.

## 8. Current known gaps

See the "Remaining work" section of `README.md` — it is kept honest. Anything in
`docs/history/` older than the latest commit is not a to-do list.
