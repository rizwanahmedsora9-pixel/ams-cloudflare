import os,sys,re
DB='/tmp/ams_chk.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_chk.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'; os.environ['ALLOW_EMPTY_DB']='1'; os.environ['ALLOW_DB_DROP']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app); c.post('/login',data={'username':'Admin','password':'Admin@fbm12345'})
def t(p):
    r=c.get(p); h=r.get_data(as_text=True); h=re.sub(r'<script.*?</script>',' ',h,flags=re.S)
    return r.status_code,' '.join(re.sub(r'<[^>]+>',' ',h).split())
pages={
 '/pending_bills?show=active':['Pending Bills','Total'],
 '/decision_ledger':['Decision','Total','Waive'],
 '/payments':['Customer Payments','Total'],
 '/call_center':['Call','Total'],
 '/supplier_ledger/1':['Total Debit','Total Credit','Closing'],
 '/client_ledger/2':['Total'],
 '/ledger/2':['Total Due','Total Paid','Net Balance'],
 '/profit_reports?start_date=2026-10-01&end_date=2026-10-31':['Profit','Revenue','COGS'],
 '/daily_reconciliation':['Opening','Expected','Physical'],
 '/accounts/expenditures?from=2026-10-01&to=2026-10-31':['Total Cash Movement','No expense'],
 '/void_audit':['Deleted','Suspended','Total'],
 '/journal':['Journal','Total'],
}
for p,lbs in pages.items():
    s,x=t(p); print(f'\n### {p} -> {s}')
    for lb in lbs:
        i=x.find(lb)
        print('   ',x[max(0,i-40):i+150] if i>0 else 'MISSING: '+lb)
