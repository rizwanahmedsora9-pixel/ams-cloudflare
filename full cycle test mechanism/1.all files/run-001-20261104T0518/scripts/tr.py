import os,sys,re
DB='/tmp/ams_tr.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_tr.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'; os.environ['ALLOW_EMPTY_DB']='1'; os.environ['ALLOW_DB_DROP']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app); c.post('/login',data={'username':'Admin','password':'Admin@fbm12345'})
def txt(h):
    h=re.sub(r'<style.*?</style>',' ',h,flags=re.S); h=re.sub(r'<script.*?</script>',' ',h,flags=re.S)
    return ' '.join(re.sub(r'<[^>]+>',' ',h).split())
def show(tag):
    x=txt(c.get('/cash_flow?from_date=2026-10-01&to_date=2026-10-31').get_data(as_text=True))
    out={}
    for lb in ['Opening Balance','Total Received','Total Spent','Closing Balance','Transfers']:
        i=x.find(lb); out[lb]=x[i:i+60] if i>0 else 'MISSING'
    print(tag); [print('   ',k,'=>',v[:58]) for k,v in out.items()]
show('BEFORE')
r=c.post('/accounts/transactions/new',data={'tx_mode':'pay','pay_target':'company_transfer','pay_from_account_id':'1','pay_to_account_id':'2','amount':'10000','date_posted':'2026-10-25T10:00','method':'Cash','note':'test transfer','idempotency_key':'tr-1'},follow_redirects=True)
print('transfer status',r.status_code)
show('AFTER')
# reconciliation
r=c.post('/cash_flow',data={'action':'save_reconciliation','from_date':'2026-10-01','to_date':'2026-10-31','physical_cash_available':'175500','adjustment_date':'2026-10-31','reconciliation_reason':'count'},follow_redirects=True)
t=txt(r.get_data(as_text=True))
print('\nrecon flashes:', re.findall(r'(Excess[^.]{0,80}|Shortage[^.]{0,80}|Reconciliation saved[^.]*\.)',t)[:4])
import sqlite3
con=sqlite3.connect(DB)
print('recon row:',list(con.execute('select adjustment_date,physical_cash_available,calculated_closing,difference from cash_flow_difference_adjustment')))
print('accts:',list(con.execute('select name,balance from account')))
