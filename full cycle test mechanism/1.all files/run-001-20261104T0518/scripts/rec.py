import os,sys,re
DB='/tmp/ams_rec.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_rec.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'; os.environ['ALLOW_EMPTY_DB']='1'; os.environ['ALLOW_DB_DROP']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app); c.post('/login',data={'username':'Admin','password':'Admin@fbm12345'})
def txt(h):
    h=re.sub(r'<style.*?</style>',' ',h,flags=re.S); h=re.sub(r'<script.*?</script>',' ',h,flags=re.S)
    return ' '.join(re.sub(r'<[^>]+>',' ',h).split())
r=c.post('/cash_flow',data={'action':'reconcile','from_date':'2026-10-01','to_date':'2026-10-31',
    'physical_cash_available':'175500','adjustment_date':'2026-10-31','note':'test count','reason':'physical count'},follow_redirects=True)
print('status',r.status_code)
t=txt(r.get_data(as_text=True))
for lb in ['Difference','Excess','Shortage','recorded']:
    for m in list(re.finditer(lb,t,re.I))[:2]:
        print(' ',lb,'::',t[max(0,m.start()-120):m.start()+150])
