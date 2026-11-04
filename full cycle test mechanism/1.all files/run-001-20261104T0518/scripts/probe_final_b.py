"""Stage B: read every report screen and PDF for the seeded cycle and print the
figures the test document must assert."""
import os, sys, re, json, sqlite3, io
DB = '/tmp/ams_cycle_final.db'
os.environ['APP_DB_PATH'] = DB
os.environ['DB_HEALTH_SNAPSHOT_PATH'] = '/tmp/hs_cycle_final.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER'] = '0'
os.environ['ALLOW_EMPTY_DB'] = '1'
sys.path.insert(0, '.')
sys.path.insert(0, 'tests')
from app import create_app
from tests.conftest import make_csrf_client

IDS = json.load(open('/tmp/final_ids.json'))
CLI, DRV, CASH, BANK = IDS['CLI'], IDS['DRV'], IDS['CASH'], IDS['BANK']
CLI_ID = CLI['id'] if isinstance(CLI, dict) else CLI


def txt(html):
    t = re.sub(r'<script.*?</script>', ' ', html, flags=re.S)
    t = re.sub(r'<style.*?</style>', ' ', t, flags=re.S)
    t = re.sub(r'<[^>]+>', ' ', t)
    return ' '.join(t.split())


def nums(s, label, window=160):
    hits = []
    for m in re.finditer(re.escape(label), s, re.I):
        seg = s[m.start():m.start() + window]
        hits.append(' '.join(seg.split())[:window])
    return hits[:3]


def hit(c, path, label=None, window=170, expect=None):
    r = c.get(path)
    body = r.get_data(as_text=True)
    print(f'\n### GET {path} -> {r.status_code} ({len(body)} bytes)')
    if r.status_code != 200:
        print('   !!', txt(body)[:200])
        return body
    if label:
        for h in nums(txt(body), label, window):
            print('   ', h)
    return body


app = create_app()
app.config['TESTING'] = True
c = make_csrf_client(app)
c.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'})

print('#' * 70)
print('# 13. STOCK / CUSTOMER / LEDGER SCREENS')
print('#' * 70)
hit(c, '/inventory/stock_summary?date_from=2026-10-01&date_to=2026-10-31', 'DG Cement', 240)
hit(c, '/materials', 'DG Cement', 200)
hit(c, '/clients', 'Bilal Construction', 200)
hit(c, '/suppliers', 'Ravi Cement Supplier', 260)
hit(c, '/grn', 'CYC-GRN-1', 260)
hit(c, '/grn?tab=costs', 'Landed', 200)
hit(c, '/bookings', 'CYC-BK-1', 240)
hit(c, '/direct_sales', 'CYC-CASH-1', 240)
hit(c, '/payments', 'CYC-RCPT-1', 200)
hit(c, '/material_returns', 'No', 120)
hit(c, '/pending_bills', 'Bilal', 200)
hit(c, '/accounts/dashboard', 'Main Cash', 200)
hit(c, '/accounts/accounts', 'Main Cash', 160)
hit(c, '/accounts/payments/clients', 'CYC-RCPT-1', 200)
hit(c, '/accounts/grn_payments', 'Ravi Cement Supplier', 250)
hit(c, '/accounts/receipts', 'Main Cash', 150)
hit(c, '/accounts/transfers', 'Transfer', 120)
hit(c, '/accounts/audit', 'GRN payment', 200)
hit(c, '/delivery_rents', 'Akram Driver', 250)
hit(c, f'/delivery_person_ledger/{DRV}', 'Akram Driver', 260)

print('\n' + '#' * 70)
print('# 14. PROFIT & LOSS')
print('#' * 70)
hit(c, '/profit_reports?start_date=2026-10-01&end_date=2026-10-31', 'Net revenue', 260)
hit(c, '/profit_reports?start_date=2026-10-01&end_date=2026-10-31&period=custom', 'Gross sales', 220)
hit(c, '/financial_details', 'Walk-in', 220)
hit(c, '/decision_ledger', 'Bilal Construction', 260)
hit(c, '/current_payables', 'Bilal', 200)
hit(c, '/daily_transactions?date_from=2026-10-01&date_to=2026-10-31', 'Akram Driver', 150)
hit(c, '/tracking', 'DG Cement', 150)
hit(c, '/ledger', 'Bilal', 200)
hit(c, f'/client_ledger/{CLI_ID}', 'CYC-CR-1', 240)
hit(c, '/supplier_ledger/1', 'Ravi Cement Supplier', 240)
hit(c, '/cash_flow?from_date=2026-10-01&to_date=2026-10-31', 'Physical Cash', 200)
hit(c, '/system_report', 'Discrepan', 160)
hit(c, '/void_audit', 'Total', 120)

print('\n' + '#' * 70)
print('# 15. PDFs / DOWNLOADS')
print('#' * 70)
for path in ['/profit_reports/export/pdf?start_date=2026-10-01&end_date=2026-10-31',
             f'/download_client_ledger/{CLI_ID}',
             '/download_supplier_ledger/1',
             f'/download_delivery_person_ledger/{DRV}',
             '/export_grn',
             '/export_pending_bills',
             '/profit_reports/export/excel?start_date=2026-10-01&end_date=2026-10-31',
             '/cash_flow?from_date=2026-10-01&to_date=2026-10-31&export_pdf=1',
             '/cash_flow?from_date=2026-10-01&to_date=2026-10-31&export_csv=1']:
    r = c.get(path)
    data = r.data
    sig = data[:5]
    print(f'  {path} -> {r.status_code} {r.headers.get("Content-Type","?")[:40]} '
          f'{len(data)}B start={sig!r} cd={r.headers.get("Content-Disposition","")[:60]}')
