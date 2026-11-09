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

The Worker serves `/b/<signed-token>` as the verified bill page, allows the three required receipt fonts, and serves `/b/<signed-token>.pdf` as a download. It also serves `/c/<43-character-token>` as a read-only, live client-ledger HTML page (never a PDF route). It fetches only those allowlisted paths from APP_ORIGIN without forwarding redirects. It must not proxy arbitrary paths or forward upstream error pages/headers.

For client ledgers, `PUBLIC_BASE_URL` must be the HTTPS Worker origin. In the app, open the client's ledger and choose **Client QR** (admin/client-management permission required). Generate a new QR to print it. Generating a replacement immediately revokes the earlier QR; the client view reflects the latest ledger data each time it is opened. Use the QR settings page to revoke access. The database stores only a SHA-256 digest of the random 256-bit token, not the token itself. Inactive/transferred clients' links stop working. The public view is standalone HTML with no app navigation or built-in download links, and responses are marked private/no-store and noindex.

Treat the printed QR as a private key: anyone who has a copy can view that client's ledger. A browser may still let someone save or screenshot a page; the site only omits its own download feature.

## Verify before sharing

1. Generate a NEW Urdu bill PDF from the deployed app.
2. Scan its QR: the link should begin with `https://still-base-ac7a.rizwanahmedsora9.workers.dev/b/`.
3. Open the link: it should show an animated Verified Bill badge and the bill, followed by a Download PDF button. Click that button to download without navigating to PythonAnywhere. Invalid or missing bills must not show a verified badge.
4. Print one client ledger QR from the client's ledger page. Scanning it should open the full, current ledger as standalone HTML, with no app controls or built-in download links. Confirm a malformed token is rejected, then use QR settings to revoke and verify the old code returns unavailable.
5. A request to the Worker root alone should return the generic `Link unavailable.` response; this is expected.
6. An invalid or edited bill token must not return a PDF.

Previously printed bill QR codes retain their old links; rotating a client-ledger QR deliberately revokes the previous link for that client. Browser/scanner confirmation dialogs cannot be disabled by the app. The Worker hides the upstream address from the normal flow, not the visible Worker address, and does not guarantee infrastructure anonymity. A signed bill QR grants access to that bill; anyone holding a client-ledger QR can view that client's live ledger.

No live deployment or end-to-end validation is performed by adding this guide. Both the PythonAnywhere app and Worker must be deployed and available for downloads to work.

## Checks

Run `node deployment/cloudflare/worker.test.mjs` for mocked proxy checks, and `python -m pytest tests/test_bill_verify_qr.py` with the project test dependencies installed. Deploy the updated app and reload PythonAnywhere as well as replacing the Worker; the old Worker still forces immediate downloads.
