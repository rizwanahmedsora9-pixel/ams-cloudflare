import os,sys,re,sqlite3
DB='/tmp/ams_ops3.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_o3.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'; os.environ['ALLOW_EMPTY_DB']='1'; os.environ['ALLOW_DB_DROP']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
ALERT=re.compile(r'class="alert alert-(\w+) alert-dismissible[^"]*"[^>]*>\s*([^<]{3,200})')
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app); c.post('/login',data={'username':'Admin','password':'Admin@fbm12345'})
def P(l,p,d,r=True):
    x=c.post(p,data=d,follow_redirects=r)
    print('%-40s %s %s' % (l,x.status_code,[(a,' '.join(b.split())[:130]) for a,b in ALERT.findall(x.get_data(as_text=True))][:2]))
def G(l,p,labels=(),w=150):
    x=c.get(p); t=' '.join(re.sub(r'<[^>]+>',' ',re.sub(r'<script.*?</script>',' ',x.get_data(as_text=True),flags=re.S)).split())
    print('%-40s %s' % (l,x.status_code))
    for lb in labels:
        for m in list(re.finditer(re.escape(lb),t,re.I))[:1]:
            print('    ',t[max(0,m.start()-40):m.start()+w])
def Q(s): return list(sqlite3.connect(DB).execute(s))
G('pay_supplier page','/pay_supplier',['Supplier','Pay'])
G('mixed_transactions','/mixed_transactions',['Mixed'])
P('toggle bill paid pb1','/toggle_bill_paid/1',{})
print('  pb1:', Q('select id,bill_no,amount,is_paid from pending_bill where id=1'))
P('toggle bill paid pb1 again','/toggle_bill_paid/1',{})
print('  pb1:', Q('select id,is_paid from pending_bill where id=1'))
P('client opening balance','/client_opening_balance/2',{'opening_balance':'1500','opening_balance_date':'2026-10-01'})
print('  client:', Q('select id,name,opening_balance from client where id=2'))
P('supplier opening balance','/supplier_opening_balance/1',{'opening_balance':'2500','opening_balance_date':'2026-10-01'})
print('  sup1:', Q('select id,name,opening_balance from supplier where id=1'))
P('driver opening balance','/delivery_person_opening_balance/1',{'opening_balance':'500','opening_balance_date':'2026-10-01'})
print('  drv1:', Q('select id,name,opening_balance from delivery_person where id=1'))
P('notification set reminder pb1','/notifications/set_reminder/1',{'reminder_at':'2026-10-28T10:00','note':'call client'})
print('  reminders:', Q("select name from sqlite_master where type='table' and name like '%remind%'"))
G('notification bill detail','/notifications/bill/1',['Bilal','Reminder'],120)
G('settings feature matrix','/settings',['Feature Access Matrix'],200)
G('import_export datasets','/import_export/',['PENDINGBILLS','Clients'],120)
