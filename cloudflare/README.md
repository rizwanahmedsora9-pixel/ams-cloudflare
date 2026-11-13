# AMS ERP on Cloudflare Workers (Python)

The Flask app in this repository can run on **Cloudflare Python Workers** through
`workers.wsgi`. Everything Cloudflare needs lives in this folder:

| File | Purpose |
| --- | --- |
| `wrangler.jsonc` | Worker config: `main`, `python_workers`, module discovery, static assets, limits |
| `pyproject.toml` | Pyodide-compatible dependencies for `pywrangler sync` (the Worker's `requirements.txt`) |
| `src/worker.py` | Entry point — `Default` is the WSGI adapter for `app.create_app()` |
| `build_bundle.py` | Copies the application packages + templates into `src/` before upload |
| `deploy.sh` | One-command sync → deploy (or `--dev` / `--dry-run`) |

## Quick start

```bash
cd cloudflare
./deploy.sh                 # bundle + deploy
```

For Cloudflare Git builds, use `cloudflare` as the root directory, set the
build command to `python3 -m pip install uv`, and set the deploy command to:

```bash
UV_BIN="$(python3 -c 'import uv; print(uv.find_uv_bin())')" && PATH="$(dirname "$UV_BIN"):$PATH" "$UV_BIN" run --python 3.14.10 pywrangler deploy --name ams-cloudflare
```

Invoke the uv binary directly rather than `python3 -m uv`: the module wrapper
sets a parent interpreter that can cause Pyodide dependency installation to use
the build host's Python instead. The PATH adjustment also ensures pywrangler's
subprocesses use the installed uv rather than an older system version.

First time only:

```bash
npx wrangler login                      # Cloudflare account
npx wrangler secret put SECRET_KEY             # long random string
npx wrangler secret put DEFAULT_ADMIN_PASSWORD # first Admin password
```

Local development (same runtime as production, in-memory filesystem):

```bash
cd cloudflare
./deploy.sh --dev           # http://localhost:8787
```

Inspect exactly what would be uploaded, without touching the account:

```bash
cd cloudflare
npx wrangler deploy --dry-run --outdir=dist
```

## What the entry point does

`src/worker.py` is deliberately close to the documented Flask sketch:

```python
from workers import wsgi
from app import create_app

app = create_app()
Default = wsgi.entrypoint(app)
```

with four differences that the Workers runtime requires:

1. **The app is created on the first request.** Wrangler evaluates the entry
   module once at deploy time and snapshots the memory; the filesystem (bundled
   files under `/session/metadata`, SQLite, uploads) is *not* part of that
   snapshot and is recreated per isolate. An app built at import time would come
   back pointing at a database file that no longer exists. `Default` is a
   `WorkerEntrypoint` whose `fetch` calls `wsgi.fetch(app, request, env)`.
2. **Worker `vars`/secrets are copied into `os.environ`.** The Flask factory is
   environment-driven (`APP_DB_PATH`, `SECRET_KEY`, `PUBLIC_BASE_URL`, …), while
   Workers expose configuration on `self.env`.
3. **Writable paths are redirected.** `/session/metadata` is mounted read-only, so
   the SQLite database, logs, uploads, backups and temp files go to the
   per-isolate in-memory filesystem (`AMS_INSTANCE_DIR`, default
   `$TMPDIR/ams-erp`). Journal mode is forced to `DELETE` (no POSIX shared memory
   for WAL), and the in-process backup/reconciliation schedulers are switched off
   because `threading` cannot start threads under Pyodide.
4. **`/static/...` is served from Cloudflare Assets.** The `static/` tree is
   ~14 MB (mostly Urdu and Latin fonts), which would dominate the Worker bundle,
   so it is published as static assets (`assets.directory` in `wrangler.jsonc`)
   and `worker.py` proxies `app.static` through the `ASSETS` binding. `run_worker_first`
   keeps Flask routes in front of the asset worker. Flask's own static view stays
   as the fallback when the binding is absent.

## What `build_bundle.py` uploads

Wrangler uploads only the files below the Worker's module root — the directory
of `main`, i.e. `cloudflare/src/`. The repository is a whole-server Flask layout,
so the script copies the runtime code next to the entry point:

```
cloudflare/src/
  worker.py
  app/  blueprints/  models/  utils/      # application packages
  templates/                              # uploaded as Text modules
  cash_flow_reconciliation_helpers.py
```

The copies are git-ignored; the sources stay at the repository root.
`--link` symlinks instead of copying (used by `--dev`). `wrangler.jsonc` runs
`python3 build_bundle.py` through `build.command`, so a Cloudflare Git build
regenerates the bundle without an extra step. The resulting upload is ~5.6 MB
(~1.2 MB gzipped) across ~420 modules, comfortably inside the 10 MB Worker limit
on the free plan.

## Configuration

Worker vars (`wrangler.jsonc` → `vars`) or secrets, all optional:

| Name | Default on Workers | Notes |
| --- | --- | --- |
| `SECRET_KEY` | generated per isolate | **Set as a secret**: sessions are useless if it changes |
| `DEFAULT_ADMIN_USER` / `DEFAULT_ADMIN_PASSWORD` | `Admin` / `Admin@fbm12345` | Used only to seed a fresh database |
| `PUBLIC_BASE_URL` | empty | Origin printed into QR codes / links |
| `AMS_INSTANCE_DIR` | `$TMPDIR/ams-erp` | Writable root for the DB, logs, uploads |
| `APP_DB_PATH` | `<instance>/ahmed_cement_v44_fresh.db` | SQLite file |
| `SQLITE_JOURNAL_MODE` | `DELETE` | WAL needs shared memory |
| `MAX_UPLOAD_MB` | `256` | Import uploads |
| `SESSION_COOKIE_SECURE` / `AMS_HTTPS` | on | HTTPS-only deployment |
| `TZ` | unset | `Asia/Karachi` is the app default |

Secrets are never committed:

```bash
cd cloudflare
npx wrangler secret put SECRET_KEY
npx wrangler secret put DEFAULT_ADMIN_PASSWORD
```

## Limitations on Workers — read before using it in production

**Data is not persistent.** The Workers filesystem is in-memory and per isolate:
the SQLite database, uploads and logs disappear when the isolate is recycled, and
two isolates never share a database. The app runs (bootstrap, login, pages,
writes) but every cold start begins from an empty database again. For real data
the storage layer has to move to a durable store — Cloudflare D1 (SQLAlchemy
dialect for D1 bindings), Durable Objects (SQLite-backed, with a SQLAlchemy
dialect) or an external database — this is an application change, not a
configuration flag.

**No background threads.** `threading.Thread` raises under Pyodide, so the
hourly backup, daily backup and auto-reconcile schedulers are disabled on
Workers (`AMS_DAILY_BACKUP_SCHEDULER=0`, `BACKUP_EMBEDDED_SCHEDULER=0`,
`AUTO_RECONCILE_ENABLED=0`). Use a Cron Trigger or keep those jobs on a normal
server.

**Optional features degrade, they do not crash.** Excel export/import
(`openpyxl`), pandas imports and ReportLab PDFs are not installed for the Worker;
those routes keep their existing "install requirements-…" messages. QR codes use
the built-in pure-Python encoder, so bills and client-ledger QR links still
render. WeasyPrint/ReportLab PDF downloads are not available.

**CPU time.** The account's default CPU limit applies. The entry point preloads
SQLAlchemy during Worker initialization so Cloudflare can include its import in
the Python startup snapshot; app creation and SQLite initialization still occur
on the first request. This is not a guarantee that startup or other requests fit
the Free plan's CPU limit. The Free plan does not support configuring
`limits.cpu_ms`. A paid plan can configure a higher limit, but that does not
resolve the lack of persistent storage.

**Upload flow.** The Worker does not serve `static/` from the script; the assets
binding must stay configured, and `run_worker_first` must remain `true` for the
app's own assets routes to keep working.

## Verifying a deployment

1. `GET /login` renders the login page.
2. Log in with the seeded Admin account; the dashboard loads.
3. Add a client/material, save a bill, open it — the write path works.
4. Open `/static/css/<file>.css` directly: it is served (assets binding).
5. Check `npx wrangler tail` while doing an import that needs `openpyxl` — the
   page shows the "requirements-…" message rather than a 500.
6. Restart the isolate (redeploy) and confirm the data reset — this is expected
   until storage is moved to D1 / Durable Objects.

## Tests

`tests/test_cloudflare_worker.py` stubs the `workers` module and verifies the
entry point contract (lazy app creation, `os.environ` propagation, Workers-safe
defaults, precedence of explicit vars), that `build_bundle.py` produces the module
root, and that `wrangler.jsonc` is valid JSONC with the documented keys:

```bash
python -m pytest tests/test_cloudflare_worker.py
```

`npx wrangler deploy --dry-run` is the end-to-end check of the upload itself (it
does not contact Cloudflare).
