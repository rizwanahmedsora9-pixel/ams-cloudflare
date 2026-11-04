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
con=sqlite3.connect(DB)
r=c.post('/add_material_return',data={'return_type':'normal','client':'Bilal Construction','client_code':'CYC-CL-1',
 'date':'2026-10-26','material_name[]':'DG Cement','material_id[]':'1','qty[]':'2','unit_rate[]':'1650',
 'manual_bill_no':'CYC-RTN-1','note':'2 bags returned'},follow_redirects=True)
print('status',r.status_code)
print('alerts:',re.findall(r'alert-(\w+)[^>]*>\s*([^<]{3,160})', r.get_data(as_text=True))[:3])
print('stock:',list(con.execute("select name,total from material where id=1")))
print('material_return:',[tuple(x) for x in con.execute('select id,client_name,manual_bill_no,auto_bill_no,amount,is_void from material_return')])
print('entries:',[tuple(x) for x in con.execute("select id,type,material,qty,bill_no from entry where bill_no like '%RTN%'")])
x=txt(c.get('/material_returns').get_data(as_text=True)); i=x.find('RTN')
print('page:', x[max(0,i-260):i+200] if i>0 else x[x.find('Logout')+6:][:300])
