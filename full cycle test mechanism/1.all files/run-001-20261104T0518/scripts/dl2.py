import os,sys
DB='/tmp/ams_cycle_final.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_cycle_final.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'; os.environ['ALLOW_EMPTY_DB']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app); c.post('/login',data={'username':'Admin','password':'Admin@fbm12345'})
for p in ['/download_supplier_ledger/1?scope=full&action=pdf',
          '/download_supplier_ledger/1?scope=full&action=csv',
          '/download_supplier_ledger/1?scope=range&start_date=2026-10-01&end_date=2026-10-31&action=pdf',
          '/download_delivery_person_ledger/1?scope=full&action=pdf',
          '/download_delivery_person_ledger/1?scope=full&action=csv',
          '/download_client_ledger/2?scope=full&action=csv',
          '/download_full_client_history/2','/download_client_clearance/2']:
    r=c.get(p)
    print('%-76s %s %-28s %7dB %r %s' % (p, r.status_code, r.headers.get('Content-Type','?')[:28], len(r.data), r.data[:4], r.headers.get('Content-Disposition','')[:46]))
