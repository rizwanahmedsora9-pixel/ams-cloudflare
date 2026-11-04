import os, sys, re, json
os.environ['APP_DB_PATH']='/tmp/ams_crawl.db'
os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs3.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'
os.environ['ALLOW_EMPTY_DB']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app)
c.post('/login', data={'username':'Admin','password':'Admin@fbm12345'})

urls = """/
/inventory/stock_summary
/stock_summary
/daily_transactions
/inventory/daily_transactions
/tracking
/inventory/inventory_log
/grn
/grn?tab=costs
/bookings
/direct_sales
/material_returns
/pending_bills
/delivery_rents
/payments
/accounts
/accounts/payments/clients
/accounts/payments/suppliers
/accounts/grn_payments
/accounts/manage/accounts
/accounts/accounts
/accounts/categories
/accounts/transfers
/accounts/receipts
/accounts/expenditures
/accounts/reconciliations
/accounts/audit
/accounts/purchase_payables
/accounts/kpi/company_money
/accounts/kpi/cash_money
/accounts/kpi/cash_accounts
/accounts/kpi/bank_accounts
/accounts/kpi/client_payments
/accounts/kpi/supplier_payments
/accounts/kpi/receipts
/accounts/kpi/expenditures
/cash_flow
/cash_flow_differences
/daily_reconciliation
/pay_supplier
/profit_reports
/financial_details
/mixed_transactions
/suppliers
/supplier_ledger
/clients
/ledger
/client-ledger/categories
/delivery_persons
/delivery_persons?src=dir
/decision_ledger
/current_payables
/unpaid_transactions
/notifications
/notifications/upcoming
/materials
/services
/import_export
/import_export/new
/import_export/history
/import_export/full_raw_import_history
/legacy-migration
/settings
/settings/activity
/settings/sessions
/settings/sidebar
/void_audit
/system_report
/tenants
/admin/modules
/admin/
/activity_log
""".split()
seen=set(); out=[]
for u in urls:
    if not u or u in seen: continue
    seen.add(u)
    try:
        r=c.get(u)
        body=r.data.decode('utf8','ignore')
        title=re.search(r'<title>(.*?)</title>', body, re.S)
        h1=re.search(r'<h1[^>]*>(.*?)</h1>', body, re.S)
        txt=lambda m: re.sub(r'\s+',' ',re.sub('<[^>]+>','',m.group(1))).strip()[:70] if m else ''
        out.append((u, r.status_code, txt(title), txt(h1), len(body)))
    except Exception as e:
        out.append((u, 'ERR', str(e)[:80], '', 0))
for row in out: print(row)
print('total', len(out))
