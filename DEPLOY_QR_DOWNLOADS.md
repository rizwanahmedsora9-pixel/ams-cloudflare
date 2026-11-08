# QR downloads through Cloudflare Workers

The app already supports a separate QR origin through `PUBLIC_BASE_URL`; no route changes are required.

## PythonAnywhere

In the PythonAnywhere Web tab, open the app's WSGI configuration file. Before importing/creating the application, add:

```python
import os
os.environ['PUBLIC_BASE_URL'] = 'https://still-base-ac7a.rizwanahmedsora9.workers.dev'
```

Keep the existing application imports and configuration. Reload the web app after saving. Do not change SERVER_NAME or the app's own domain to the Worker address.

## Cloudflare

Replace the previous forced-download Worker with the complete code in `deployment/cloudflare/worker.js` and deploy it. Set its `APP_ORIGIN` secret to the actual HTTPS PythonAnywhere origin, e.g. `https://your-account.pythonanywhere.com` (replace with the real address, no trailing route).

The Worker serves `/b/<signed-token>` as the verified bill page, allows the three required receipt fonts, and serves `/b/<signed-token>.pdf` as a download. It fetches those same paths from APP_ORIGIN without forwarding redirects. It must not proxy arbitrary paths or forward upstream error pages/headers.

## Verify before sharing

1. Generate a NEW Urdu bill PDF from the deployed app.
2. Scan its QR: the link should begin with `https://still-base-ac7a.rizwanahmedsora9.workers.dev/b/`.
3. Open the link: it should show an animated Verified Bill badge and the bill, followed by a Download PDF button. Click that button to download without navigating to PythonAnywhere. Invalid or missing bills must not show a verified badge.
4. A request to the Worker root alone should report `Bill download link required.`; this is expected.
5. An invalid or edited bill token must not return a PDF.

Previously printed or saved QR codes retain their old links. Browser/scanner confirmation dialogs cannot be disabled by the app. The Worker hides the upstream address from the normal download flow, not the visible Worker address, and does not guarantee infrastructure anonymity. The signed QR link grants access to its bill: anyone holding it can download that bill.

No live deployment or end-to-end validation is performed by adding this guide. Both the PythonAnywhere app and Worker must be deployed and available for downloads to work.

## Checks

Run `node deployment/cloudflare/worker.test.mjs` for mocked proxy checks, and `python -m pytest tests/test_bill_verify_qr.py` with the project test dependencies installed. Deploy the updated app and reload PythonAnywhere as well as replacing the Worker; the old Worker still forces immediate downloads.
