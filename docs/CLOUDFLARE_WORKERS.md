# Running the app on Cloudflare Workers

The Cloudflare deployment lives in [`cloudflare/`](../cloudflare/README.md):
Wrangler configuration, the Worker entry point (`cloudflare/src/worker.py`), the
Pyodide dependency manifest and `deploy.sh`.

Quick reference:

```bash
cd cloudflare
./deploy.sh            # deploy
./deploy.sh --dry-run  # show exactly what would be uploaded
./deploy.sh --dev      # local workers runtime on http://localhost:8787
```

Read [`cloudflare/README.md`](../cloudflare/README.md) before deploying: on
Cloudflare the filesystem is in-memory and per isolate, so the SQLite database
does not persist yet, background schedulers are disabled, and the spreadsheet /
ReportLab PDF extras are not installed (their routes show the usual
"install requirements-…" messages instead of failing).

This guide only covers the app itself. QR links printed on bills go through the
separate `deployment/cloudflare/worker.js` proxy; see
[DEPLOY_QR_DOWNLOADS.md](../DEPLOY_QR_DOWNLOADS.md) to configure `PUBLIC_BASE_URL`
and that proxy.
