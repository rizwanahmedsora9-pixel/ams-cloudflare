import os,sys,re,sqlite3
DB='/tmp/ams_ops2.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_o2.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'; os.environ['ALLOW_EMPTY_DB']='1'; os.environ['ALLOW_DB_DROP']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
ALERT=re.compile(r'class="alert alert-(\w+) alert-dismissible[^"]*"[^>]*>\s*([^<]{3,200})')
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app); c.post('/login',data={'username':'Admin','password':'Admin@fbm12345'})
def P(label,path,data,redir=True):
    r=c.post(path,data=data,follow_redirects=redir)
    print('%-34s %s %s' % (label,r.status_code,[(a,' '.join(b.split())[:120]) for a,b in ALERT.findall(r.get_data(as_text=True))][:2]))
def Q(s):
    return list(sqlite3.connect(DB).execute(s))
# accounts dashboard New Transaction: receive from other source
P('acct new tx receive 4000','/accounts/transactions/new',{
 'tx_mode':'receive','date_posted':'2026-10-26T10:00','amount':'4000','method':'Cash',
 'receive_from_category':'other_source','receive_source_label':'Owner cash injection',
 'receive_account_id':'1','idempotency_key':'acctx-1','reference':'CYC-ACC-1','note':'owner put in'})
print('  cash:', Q('select name,balance from account'), '\n  tx:', Q('select id,from_account_id,to_account_id,amount,transaction_type,source_type from account_transaction order by id desc limit 2'))
# accounts dashboard: pay — personal expense
P('acct new tx pay 1500','/accounts/transactions/new',{
 'tx_mode':'pay','date_posted':'2026-10-26T11:00','amount':'1500','method':'Cash',
 'pay_from_account_id':'1','pay_target':'Personal Expense','pay_to_account_id':'','target_label':'Tea & misc',
 'idempotency_key':'acctx-2','reference':'CYC-ACC-2','note':'tea'})
print('  cash:', Q('select name,balance from account'))
print('  tx:', Q('select id,from_account_id,to_account_id,amount,transaction_type,source_type,source_id from account_transaction order by id desc limit 3'))
# dispatching OUT against booking remaining (booking delivered already 20/20) -> expect reject
P('dispatch OUT 5 (no booking left)','/add_record',{'type':'OUT','client':'Bilal Construction','material':'DG Cement','material_id':'1','qty':'5','date':'2026-10-27','driver_name':'Akram Driver','note':'extra'})
# dispatching IN
P('dispatch IN 10','/add_record',{'type':'IN','client':'Walk-in','material':'DG Cement','material_id':'1','qty':'10','date':'2026-10-27','note':'site return in'})
print('  stock:', Q('select name,total from material order by id'))
print('  entries:', Q('select id,date,type,material,client,qty,nimbus_no,driver_name,is_void from entry order by id desc limit 3'))
# settings save
P('settings save','/update_settings',{'company_name':'Ahmed Cement Co','company_address':'Islamabad','company_phone':'051-123','currency':'Rs.','allow_global_negative_stock':'on'})
print('  settings:', Q('select company_name,currency,allow_global_negative_stock from settings'))
