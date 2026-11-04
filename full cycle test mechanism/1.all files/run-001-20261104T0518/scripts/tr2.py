import os,sys,re,sqlite3
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
def recon(phys):
    r=c.post('/cash_flow',data={'action':'save_reconciliation','from_date':'2026-10-01','to_date':'2026-10-31',
        'physical_cash_available':str(phys),'adjustment_date':'2026-10-31','reconciliation_reason':'count'},follow_redirects=True)
    t=txt(r.get_data(as_text=True))
    m=re.search(r'Difference[^A-Za-z]{0,4}(Rs\.? ?[-0-9,\.]+)',t)
    d=re.search(r'(Excess[^.]{0,90}|Shortage[^.]{0,90}|Matched[^.]{0,60})',t,re.I)
    print(f'  physical={phys} -> flash/diff:', d.group(0)[:110] if d else 'n/a')
con=sqlite3.connect(DB)
for p in (175500, 158500, 100000):
    recon(p)
    print('   row:',list(con.execute('select physical_cash_available,calculated_closing,difference from cash_flow_difference_adjustment')))
r=c.post('/cash_flow',data={'action':'delete','from_date':'2026-10-01','to_date':'2026-10-31','adjustment_date':'2026-10-31'},follow_redirects=True)
print('delete flash:', re.findall(r'Reconciliation removed[^.]*\.', txt(r.get_data(as_text=True)))[:1])
print('row after delete:',list(con.execute('select physical_cash_available,difference,amount,note from cash_flow_difference_adjustment')))
print('audit rows:',list(con.execute('select change_type,old_physical_cash,new_physical_cash from cash_flow_reconciliation_audit')))
