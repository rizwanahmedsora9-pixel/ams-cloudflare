"""Rendered-page extractor: for every page in the app, dump the real rendered
form actions, field names, button labels and <th> headers.

Writes /home/user/git-recovered/_audit/pages.md — the field-level inventory that
`full-app-work-test.md` is built from.
"""
import os, sys, re, json, sqlite3
DB = '/tmp/ams_cycle_final.db'
os.environ['APP_DB_PATH'] = DB
os.environ['DB_HEALTH_SNAPSHOT_PATH'] = '/tmp/hs_cycle_final.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER'] = '0'
os.environ['ALLOW_EMPTY_DB'] = '1'
sys.path.insert(0, '.')
sys.path.insert(0, 'tests')
from app import create_app
from tests.conftest import make_csrf_client

PAGES = [
    ('/', 'System Dashboard'),
    ('/inventory/stock_summary', 'Stock Summary'),
    ('/inventory/daily_transactions', 'Daily Breakdown'),
    ('/tracking', 'History / Tracking'),
    ('/grn', 'GRN (Receiving) - records tab'),
    ('/grn?tab=costs', 'GRN - costs tab'),
    ('/bookings', 'Bookings'),
    ('/direct_sales', 'Sales (direct sales)'),
    ('/material_returns', 'Material Return'),
    ('/pending_bills', 'Pending Bills'),
    ('/delivery_rents', 'Delivery Rent'),
    ('/payments', 'Payments'),
    ('/accounts/', 'Accounts dashboard'),
    ('/accounts/accounts', 'Manage accounts'),
    ('/accounts/accounts/add', 'Add account'),
    ('/accounts/categories', 'Account groups'),
    ('/accounts/transfers', 'Transfers'),
    ('/accounts/receipts', 'Receipts'),
    ('/accounts/expenditures', 'Expenditures'),
    ('/accounts/reconciliations', 'Reconciliations'),
    ('/accounts/audit', 'Account audit trail'),
    ('/accounts/purchase_payables', 'Purchase payables'),
    ('/accounts/payments/clients', 'Client payments'),
    ('/accounts/payments/suppliers', 'Supplier payments'),
    ('/accounts/grn_payments', 'Pay GRN Expenses'),
    ('/cash_flow', 'Cash Flow'),
    ('/cash_flow_differences', 'Cash Flow differences'),
    ('/daily_reconciliation', 'Daily reconciliation'),
    ('/profit_reports', 'Profit & Loss'),
    ('/financial_details', 'Financial details'),
    ('/suppliers', 'Suppliers'),
    ('/clients', 'Clients'),
    ('/materials', 'Material Brands'),
    ('/services', 'Services & Charges'),
    ('/delivery_persons', 'Delivery Persons'),
    ('/ledger', 'Ledger (client list)'),
    ('/client-ledger/categories', 'Client categories'),
    ('/decision_ledger', 'Decision Ledger'),
    ('/current_payables', 'Current Payables'),
    ('/notifications', 'Notifications'),
    ('/notifications/upcoming', 'Upcoming reminders'),
    ('/settings', 'Settings'),
    ('/settings/activity', 'Settings - Who did what'),
    ('/settings/sessions', 'Settings - sessions'),
    ('/settings/sidebar', 'Sidebar settings'),
    ('/import_export/', 'Import / Export'),
    ('/legacy-migration/', 'Legacy data migration'),
    ('/data_lab/', 'Data Lab'),
    ('/admin/', 'Admin dashboard'),
    ('/admin/modules', 'Admin modules'),
    ('/system_report', 'System report'),
    ('/void_audit', 'Void audit'),
    ('/dashboard', 'dashboard alias'),
    ('/dispatching', 'Dispatching'),
    ('/receiving', 'Receiving'),
    ('/suppliers', 'Suppliers (2)'),
    ('/supplier_ledger/1', 'Supplier ledger'),
    ('/delivery_person_ledger/1', 'Delivery person ledger'),
    ('/client_ledger/2', 'Client ledger'),
]


def clean(x):
    x = re.sub(r'<[^>]+>', ' ', x)
    return ' '.join(x.replace('&amp;', '&').replace('&nbsp;', ' ').split())


def analyse(html):
    forms = []
    for m in re.finditer(r'<form\b([^>]*)>(.*?)</form>', html, re.S):
        attrs, inner = m.group(1), m.group(2)
        action = (re.search(r'action="([^"]*)"', attrs) or [None, ''])[1]
        method = (re.search(r'method="([^"]*)"', attrs) or [None, 'GET'])[1].upper()
        fid = (re.search(r'id="([^"]*)"', attrs) or [None, ''])[1]
        fields = []
        for fm in re.finditer(r'<(input|select|textarea)\b([^>]*)>', inner):
            tag, fattr = fm.group(1), fm.group(2)
            name = (re.search(r'name="([^"]+)"', fattr) or [None, None])[1]
            if not name:
                continue
            typ = (re.search(r'type="([^"]+)"', fattr) or [None, tag])[1]
            fields.append(name if typ in ('text', 'hidden', 'number', 'date', 'select', 'textarea',
                                          'search', 'email', 'radio', 'checkbox', 'file', 'tel')
                          else f'{name}:{typ}')
        forms.append({'action': action, 'method': method, 'id': fid, 'fields': fields})
    buttons = []
    for m in re.finditer(r'<button\b[^>]*>(.*?)</button>', html, re.S):
        t = clean(m.group(1))
        if t and len(t) < 45 and t not in buttons:
            buttons.append(t)
    ths = []
    for m in re.finditer(r'<th\b[^>]*>(.*?)</th>', html, re.S):
        t = clean(m.group(1))
        if t and len(t) < 40 and t not in ths:
            ths.append(t)
    tabs = re.findall(r'data-cf-tab="(\w+)"|role="tab"[^>]*>([^<]{2,40})', html)
    options = {}
    for m in re.finditer(r'<select\b[^>]*name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
        name, inner = m.group(1), m.group(2)
        opts = [clean(o) for o in re.findall(r'<option\b[^>]*>(.*?)</option>', inner, re.S)]
        opts = [o for o in opts if o][:8]
        options[name] = opts
    return {'forms': forms, 'buttons': buttons[:26], 'th': ths[:18], 'options': options}


app = create_app()
app.config['TESTING'] = True
c = make_csrf_client(app)
c.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'})

out = []
seen = set()
for path, label in PAGES:
    if path in seen:
        continue
    seen.add(path)
    r = c.get(path)
    html = r.get_data(as_text=True)
    out.append((path, label, r.status_code, len(html), analyse(html) if r.status_code == 200 else {}))

with open('_audit/pages.md', 'w') as fh:
    for path, label, code, size, info in out:
        fh.write(f'\n## {path}  —  {label}   [HTTP {code}, {size}B]\n')
        if not info:
            fh.write('  (not rendered)\n')
            continue
        for f in info['forms']:
            fields = ', '.join(dict.fromkeys(f['fields']))
            fh.write(f"- FORM {f['method']} {f['action'] or '(self)'} id={f['id'] or '-'}\n")
            fh.write(f"    fields: {fields}\n")
            opts = {k: v for k, v in info['options'].items() if k in f['fields']}
            for k, v in opts.items():
                fh.write(f"      {k} options: {v}\n")
        if info['buttons']:
            fh.write(f"- BUTTONS: {' | '.join(info['buttons'])}\n")
        if info['th']:
            fh.write(f"- COLUMNS: {' | '.join(info['th'])}\n")
print('wrote _audit/pages.md', len(out), 'pages')
