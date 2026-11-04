import os,sys,re,sqlite3
DB='/tmp/ams_ops4.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_o4.json'
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
def Q(s): return list(sqlite3.connect(DB).execute(s))
P('reminder','/notifications/set_reminder/1',{'remind_at':'2026-10-28T10:00','note':'call client'})
print('  reminders:', Q('select id,pending_bill_id,remind_at,note from follow_up_reminder'))
P('log contact','/notifications/log_contact/1',{'response':'promised next week'})
print('  contacts:', Q("select name from sqlite_master where type='table' and name like '%contact%'"))
P('close reminder','/notifications/close_reminder/1',{'response':'settled by phone'})
print('  reminders:', Q('select id,is_done from follow_up_reminder'))
P('set severity','/notifications/set_severity/1',{'severity':'High'})
print('  pb1:', Q('select id,severity,risk_level from pending_bill where id=1') if any('severity'==r[1] for r in Q('pragma table_info(pending_bill)')) else 'no severity col')
print('  pb cols:', [r[1] for r in Q('pragma table_info(pending_bill)')])
