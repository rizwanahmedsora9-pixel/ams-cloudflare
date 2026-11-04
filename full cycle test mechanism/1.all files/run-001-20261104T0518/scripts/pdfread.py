import os,sys,re,io
DB='/tmp/ams_chk.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_chk.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'; os.environ['ALLOW_EMPTY_DB']='1'; os.environ['ALLOW_DB_DROP']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
from pypdf import PdfReader
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app); c.post('/login',data={'username':'Admin','password':'Admin@fbm12345'})
for path in ['/profit_reports/export/pdf?start_date=2026-10-01&end_date=2026-10-31',
             '/download_client_ledger/2','/download_supplier_ledger/1?scope=full&action=pdf',
             '/download_invoice/SB-SL-1000','/cash_flow?from_date=2026-10-01&to_date=2026-10-31&export_pdf=1',
             '/download_client_clearance/2','/download_full_client_history/2']:
    r=c.get(path)
    try:
        rd=PdfReader(io.BytesIO(r.data))
        pages=len(rd.pages); txt=' '.join((p.extract_text() or '') for p in rd.pages)
        txt=' '.join(txt.split())
        print(f'\n### {path}  {len(r.data)}B pages={pages}')
        print('   ', txt[:420])
        for pat in ['55,000','11,600','20,500','215,500','8,500','1,400','34,500']:
            if pat in txt: print(f'    contains {pat}')
    except Exception as e:
        print(f'\n### {path} -> PDF READ FAILED {e}')
