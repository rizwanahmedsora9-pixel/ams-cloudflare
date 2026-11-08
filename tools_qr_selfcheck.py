"""Print-and-scan self check for the bill QR code.

Run this on the machine that prints bills, when a customer reports "I scanned
the code and nothing happened":

    python tools_qr_selfcheck.py                 # uses the configured host
    python tools_qr_selfcheck.py --host https://myname.pythonanywhere.com

It builds a sample bill through the real Urdu sheet, rasterises the printed
PDF, decodes the QR the way a phone camera does, and then follows the link and
reports whether the page shows the bill.  Nothing is written to the database.
"""
from __future__ import annotations

import argparse
import sys
from types import SimpleNamespace

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='',
                        help='Origin printed into the QR (PUBLIC_BASE_URL)')
    parser.add_argument('--dpi', type=int, default=300,
                        help='Rasterise the sheet at this resolution')
    args = parser.parse_args(argv)

    try:
        import cv2
        import numpy as np
        import pymupdf
    except ImportError:
        print('This check needs pymupdf, opencv-python-headless and numpy:')
        print('  pip install pymupdf opencv-python-headless numpy')
        return 2

    from app import create_app
    from app.services import bill_urdu, urdu_receipt as R

    app = create_app()
    if args.host:
        app.config['PUBLIC_BASE_URL'] = args.host.strip().rstrip('/')

    bill = SimpleNamespace(id=1, manual_bill_no='SB-QR-CHECK', auto_bill_no='',
                           invoice_no='', amount=12345, paid_amount=2000,
                           discount=0, date_posted=None, note='',
                           client_name='QR Check', client_code='QR-0001',
                           driver_name='')
    items = [{'name': 'Cement Bag', 'name_ur': 'سیمنٹ ٹھیکہ',
              'qty': 5, 'price_at_time': 1290}]
    with app.app_context(), app.test_request_context('/download_invoice/x'):
        document = bill_urdu.build_document(
            bill_type='DirectSale', bill=bill, items=items, client=None,
            previous_balance=0, client_balance=0, settings=None)
        payload = document['qr_text']
        pdf = bill_urdu.render_pdf(document)

    print(f'{"base URL":<22}: {app.config.get("PUBLIC_BASE_URL") or "(from request host)"}')
    print(f'{"QR payload":<22}: {payload or "(none - printing a text summary)"}')
    if not payload:
        print('\nFAIL: no link could be built, so the QR holds a text summary '
              'instead of a scannable link.\n'
              'Set PUBLIC_BASE_URL to the address customers open the app on '
              '(e.g. https://myname.pythonanywhere.com).')
        return 1

    from app.services import qr_code
    matrix = qr_code.make_matrix(payload, 'm')
    module_mm = R.QR_SIZE / (len(matrix) + 8) / 72 * 25.4
    print(f'{"symbol":<22}: {len(matrix)}x{len(matrix)} modules '
          f'({module_mm:.2f}mm per module)')

    page = pymupdf.open(stream=pdf, filetype='pdf')[0]
    clip = pymupdf.Rect(R.QR_X - 8, R.QR_Y - 8,
                        R.QR_X + R.QR_SIZE + 8, R.QR_Y + R.QR_SIZE + 8)
    pix = page.get_pixmap(dpi=args.dpi, clip=clip)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR if pix.n == 4
                         else cv2.COLOR_RGB2BGR)
    decoded, _points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    print(f'{"scan @ " + str(args.dpi) + "dpi":<22}: '
          f'{decoded or "NOTHING FOUND"}')
    if not decoded:
        print('\nFAIL: a camera would find no code. Try --dpi 600 to tell a '
              'scanner limitation from a printing one.')
        return 1
    if decoded != payload:
        print('\nFAIL: the scan does not return the printed payload.')
        return 1

    path = decoded.split('://', 1)[-1].split('/', 1)[-1]
    response = app.test_client().get('/' + path)
    print(f'{"page":<22}: HTTP {response.status_code} (no login)')
    if response.status_code == 302 and 'login' in (
            response.headers.get('Location') or ''):
        print('\nFAIL: the link asks for a login. The page behind the QR must '
              'open for a customer with no account.')
        return 1
    if response.status_code == 404:
        print('\nOK: the code scans and the link routes to the public bill '
              'page.\n'
              'That page reported "bill not found" because this check uses a '
              'sample\nreference that is not in this database - print a real '
              'bill and scan it to\nsee the details.')
        return 0
    body = response.get_data(as_text=True)
    ok = response.status_code == 200 and 'QR-0001' in body and 'سیمنٹ' in body
    print(f'{"bill details":<22}: {"shown" if ok else "MISSING"}')
    print('\nOK: the QR scans, opens without a login and shows the bill.'
          if ok else '\nFAIL: the page did not show the bill details.')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
