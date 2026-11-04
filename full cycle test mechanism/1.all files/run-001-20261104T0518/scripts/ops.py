import os,sys,re,sqlite3
DB='/tmp/ams_cycle_ops.db'
os.environ['APP_DB_PATH']=DB; os.environ['DB_HEALTH_SNAPSHOT_PATH']='/tmp/hs_ops.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER']='0'; os.environ['ALLOW_EMPTY_DB']='1'; os.environ['ALLOW_DB_DROP']='1'
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from app import create_app
from tests.conftest import make_csrf_client
ALERT=re.compile(r'class="alert alert-(\w+) alert-dismissible[^"]*"[^>]*>\s*([^<]{3,220})')
app=create_app(); app.config['TESTING']=True
c=make_csrf_client(app); c.post('/login',data={'username':'Admin','password':'Admin@fbm12345'})
def P(label,path,data):
    r=c.post(path,data=data,follow_redirects=True)
    print('%-42s %s %s' % (label, r.status_code, [(a,' '.join(b.split())[:120]) for a,b in ALERT.findall(r.get_data(as_text=True))][:2]))
def Q(s):
    con=sqlite3.connect(DB)
    return list(con.execute(s))
# 1. cash flow OUT with an OUT-category
P('cf add out category','/cash_flow',{'action':'add_category','new_category_name':'Site Expense','new_category_direction':'out','new_category_notes':'x'})
P('cf out 2000','/cash_flow',{'action':'record_movement','direction':'out','amount':'2000','cash_account_id':'1',
   'category_name':'Site Expense','party_name':'Tea Vendor','party_type':'other','description':'Site tea',
   'reference':'CYC-CF-OUT','movement_date':'2026-10-24','idempotency_key':'cf-out-1'})
print('  cash balance now:', Q('select name,balance from account'))
# 2. account transfer
P('transfer 10000 cash->bank','/accounts/transfers/add',{'from_account':'1','to_account':'2','amount':'10000','description':'cash to bank','date_posted':'2026-10-25','idempotency_key':'tr-1'})
print('  accounts:', Q('select name,balance from account'))
print('  tx last:', Q('select id,from_account_id,to_account_id,amount,transaction_type from account_transaction order by id desc limit 2'))
# 3. reconcile cash
P('reconcile cash 168500','/accounts/1/reconcile',{'actual_balance':'168500','reconciliation_date':'2026-10-25','note':'counted'})
print('  recon rows:', Q('select id,account_id,expected_balance,actual_balance,difference from account_reconciliation order by id desc limit 3'))
# 4. normal material return (DG 2 bags @1700)
P('material return normal','/add_material_return',{'client_code':'CYC-CL-1','date':'2026-10-26','return_type':'normal',
  'material_id[]':'1','material_name[]':'DG Cement','qty[]':'2','unit_rate[]':'1650','rent_rate[]':'','manual_bill_no':'CYC-RET-1','note':'2 bags returned'})
print('  returns:', Q('select id,client_name,return_type,manual_bill_no,auto_bill_no from material_return order by id'))
print('  ret items:', Q('select id,material_return_id,material_name,qty,unit_rate from material_return_item'))
print('  stock:', Q('select name,total from material order by id'))
# 5. pending bill add
P('add pending bill','/add_pending_bill',{'client_code':'CYC-CL-1','bill_no':'CYC-PB-1','nimbus_no':'NB-1','amount':'4500','reason':'old dues','note':'manual'})
print('  pending:', Q('select id,client_name,bill_no,amount,is_paid from pending_bill order by id desc limit 2'))
# 6. client ledger edit
P('edit payment via ledger','/edit_ledger_transaction/Payment/1',{'client_name':'Bilal Construction','amount':'9000','method':'Cash','manual_bill_no':'MB NO.CYC-RCPT-1','date_posted':'2026-10-18','note':'corrected'})
print('  payments:', Q('select id,amount,manual_bill_no from payment order by id'))
# 7. void + restore a client payment
P('void payment 2','/accounts/payments/clients/void/2',{})
print('  p2:', Q('select id,is_void,amount from payment where id=2'), ' cash:', Q('select balance from account where id=2'))
P('restore payment 2','/accounts/payments/clients/restore/2',{})
print('  p2:', Q('select id,is_void from payment where id=2'), ' bank:', Q('select balance from account where id=2'))
# 8. GRN cancel
P('cancel GRN 6','/grn',{'action':'delete','id':'6'})
print('  grn6:', Q('select id,is_void,is_cancelled,cancel_reason from grn where id=6'))
print('  stock:', Q('select name,total from material order by id'))
