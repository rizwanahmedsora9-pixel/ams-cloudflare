"""One-shot acceptance-cycle probe (stages A→O) on a clean DB.

Prints every figure `full-app-work-test.md` asserts.  Any mismatch here is a
finding, not a typo: the numbers below are the app's real behaviour.
"""
import os, sys, re, json, sqlite3
DB = '/tmp/ams_cycle_final.db'
for suffix in ('', '-wal', '-shm'):
    if os.path.exists(DB + suffix):
        os.remove(DB + suffix)
os.environ['APP_DB_PATH'] = DB
os.environ['DB_HEALTH_SNAPSHOT_PATH'] = '/tmp/hs_cycle_final.json'
os.environ['BACKUP_EMBEDDED_SCHEDULER'] = '0'
os.environ['ALLOW_EMPTY_DB'] = '1'
sys.path.insert(0, '.')
sys.path.insert(0, 'tests')
from app import create_app
from tests.conftest import make_csrf_client

ALERT = re.compile(r'<div class="alert alert-(\w+) alert-dismissible[^"]*" role="alert">\s*(.*?)\s*<button', re.S)
OUT = {}


def body(r):
    return r.get_data(as_text=True) if not isinstance(r, str) else r


def flashes(r):
    return [(c, ' '.join(re.sub(r'<[^>]+>', ' ', m).split())) for c, m in ALERT.findall(body(r))]


def step(label, resp, expect=''):
    fl = flashes(resp)
    got = ' || '.join(f'{c}: {m}' for c, m in fl) or '(no flash)'
    print(f'[{label}] {resp.status_code} | {got[:190]}')
    if expect:
        print(f'        expect: {expect}')
    return resp


def q(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def one(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def dump(label, sql, args=()):
    rows = q(sql, args)
    print(f'  -- {label} ({len(rows)})')
    for r in rows:
        print('     ', r)
    OUT[label] = rows


app = create_app()
app.config['TESTING'] = True
c = make_csrf_client(app)
step('A0 login', c.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'},
                        follow_redirects=True), 'System Dashboard')

# ---------------------------------------------------------------- 1 suppliers
step('1a supplier Ravi', c.post('/add_supplier', data={
    'name': 'Ravi Cement Supplier', 'phone': '0300-1234567', 'address': 'Ravi Road, Lahore',
    'opening_balance': '0', 'opening_balance_date': '2026-10-01'}, follow_redirects=True), 'Supplier Added')
step('1b supplier Kohat', c.post('/add_supplier', data={
    'name': 'Kohat Traders', 'phone': '0301-7654321', 'address': 'Kohat Bazaar',
    'opening_balance': '0', 'opening_balance_date': '2026-10-01'}, follow_redirects=True), 'Supplier Added')

# ----------------------------------------------------------- 2 categories
for cat in ('Cement', 'Sand & Gravel', 'Sheets & Covers'):
    step(f'2 category {cat}', c.post('/material_categories/add', data={'category_name': cat},
                                     follow_redirects=True), 'Category added')
CAT = {r['name']: r['id'] for r in q('select id,name from material_category')}

# --------------------------------------------------------------- 3 materials
for name, cat, unit, code in (('DG Cement', 'Cement', 'Bag', 'DG'),
                              ('Pioneer Cement', 'Cement', 'Bag', 'PIO'),
                              ('Chenab Sand', 'Sand & Gravel', 'Cft', 'SAND'),
                              ('TRANSPARENT SHEET', 'Sheets & Covers', 'Pcs', 'SHT')):
    step(f'3 brand {name}', c.post('/add_material', data={
        'material_name': name, 'category_id': str(CAT[cat]),
        'material_unit': unit, 'material_code': code}, follow_redirects=True), 'Brand Added')
MAT = {r['name']: r['id'] for r in q('select id,name from material')}

# ---------------------------------------------------------------- 4 services
step('4 service CEMENT RENT', c.post('/services/add', data={
    'service_name': 'CEMENT RENT', 'service_unit': 'Trip', 'service_code': 'SRV-RENT'},
    follow_redirects=True), 'Service "CEMENT RENT" added.')
SVC = one("select id from service where name='CEMENT RENT'")['id']

# ------------------------------------------------------ 5 client + driver
step('5a client Bilal', c.post('/add_client', data={
    'name': 'Bilal Construction', 'code': 'CYC-CL-1', 'category': 'General',
    'opening_balance': '0', 'opening_balance_date': '2026-10-01',
    'phone': '0321-1112223', 'address': 'Islamabad'}, follow_redirects=True), 'Client Registered')
CLI = one("select id,name,code from client where name='Bilal Construction'")
step('5b driver Akram', c.post('/delivery_persons/add', data={
    'name': 'Akram Driver', 'phone': '0333-9998887'}, follow_redirects=True), 'Delivery person saved')
DRV = one("select id from delivery_person where name='Akram Driver'")['id']

# -------------------------------------------------------------- 6 accounts
step('6a Main Cash', c.post('/accounts/accounts/add', data={
    'name': 'Main Cash', 'class_category': 'Assets', 'class_subcategory': 'Cash',
    'class_account_type': 'Main Cash', 'account_status': 'active', 'opening_amount': '200000',
    'opening_position': 'debit', 'opening_effective_date': '2026-10-01'}, follow_redirects=True),
    'Account added successfully!')
step('6b Meezan Bank', c.post('/accounts/accounts/add', data={
    'name': 'Meezan Bank', 'class_category': 'Assets', 'class_subcategory': 'Bank',
    'class_account_type': 'Operating Bank', 'account_status': 'active', 'opening_amount': '500000',
    'opening_position': 'debit', 'opening_effective_date': '2026-10-01',
    'bank_name': 'Meezan Bank', 'account_holder_name': 'Ahmed Cement',
    'account_number': '0123456789'}, follow_redirects=True), 'Account added successfully!')
ACC = {r['name']: r['id'] for r in q('select id,name from account')}
CASH, BANK = ACC['Main Cash'], ACC['Meezan Bank']

print('\n########## STAGE 1-6 MASTERS ##########')
dump('material_category', 'select id,name from material_category order by id')
dump('material', 'select id,name,category_id,unit,total from material order by id')
dump('service', 'select id,name,code,unit from service')
dump('client', 'select id,name,code,category,opening_balance from client order by id')
dump('delivery_person', 'select id,name from delivery_person')
dump('account', 'select id,name,category,channel,opening_balance,balance,class_category,class_subcategory,class_account_type from account order by id')
dump('supplier', 'select id,name,phone,address from supplier order by id')

# ------------------------------------------------------------------ 7 GRNs
GRNS = [('CYC-GRN-1', 1, 'Ravi Cement Supplier', '2026-10-02', 'DG Cement', 100, 1200),
        ('CYC-GRN-2', 1, 'Ravi Cement Supplier', '2026-10-04', 'DG Cement', 50, 1350),
        ('CYC-GRN-3', 2, 'Kohat Traders', '2026-10-06', 'DG Cement', 80, 1400),
        ('CYC-GRN-4', 1, 'Ravi Cement Supplier', '2026-10-08', 'Pioneer Cement', 60, 1600),
        ('CYC-GRN-5', 2, 'Kohat Traders', '2026-10-10', 'Chenab Sand', 200, 55),
        ('CYC-GRN-6', 1, 'Ravi Cement Supplier', '2026-10-12', 'TRANSPARENT SHEET', 40, 300)]
for bill, sup, supname, dt, mat, qty, price in GRNS:
    step(f'7 GRN {bill} {qty}x{price}', c.post('/grn', data={
        'action': 'add', 'supplier': supname, 'supplier_id': str(sup), 'date': dt, 'time': '09:00',
        'manual_bill_no': bill, 'mat_name[]': mat, 'qty[]': str(qty), 'price[]': str(price),
        'allocation_basis_default': 'VALUE'}, follow_redirects=True), f'{qty*price:,.0f}')

print('\n########## STAGE 7 GRN ##########')
dump('grn', 'select id,manual_bill_no,auto_bill_no,supplier,date_posted,supplier_material_amount,landed_cost_total,costing_mode,is_void from grn order by id')
dump('grn_item', 'select id,grn_id,mat_name,qty,price_at_time,landed_unit_cost from grn_item order by id')
dump('material_stock', 'select name,total from material order by id')

# --------------------------------------------------------------- 8 booking
step('8 booking 20x1500 paid 10000', c.post('/add_booking', data={
    'client_code': CLI['code'], 'date': '2026-10-13', 'material_name[]': 'DG Cement',
    'material_id[]': str(MAT['DG Cement']), 'qty[]': '20', 'unit_rate[]': '1500',
    'amount': '30000', 'paid_amount': '10000', 'payment_method': 'Cash',
    'payment_account_id': str(CASH), 'manual_bill_no': 'CYC-BK-1',
    'note': '20 bags booked at 1500'}, follow_redirects=True),
    'Booking added successfully (Bill: MB NO.CYC-BK-1) - Pending amount: 20000.0')

# ------------------------------------------------------------ 9 cash sale
step('9 cash sale 5x1700', c.post('/add_direct_sale', data={
    'category': 'Cash', 'manual_client_name': 'Walk-in Customer', 'has_bill': 'on',
    'sale_date': '2026-10-14', 'delivery_person_id[]': str(DRV), 'delivery_bags[]': '5',
    'delivery_rent_amount[]': '200', 'material_id[]': str(MAT['DG Cement']),
    'product_name[]': 'DG Cement', 'qty[]': '5', 'unit_rate[]': '1700',
    'ignore_booking_item[]': '1', 'delivery_rent': '200', 'manual_bill_no': 'CYC-CASH-1',
    'amount': '8500', 'discount': '0', 'paid_amount': '8500', 'payment_method': 'Cash',
    'payment_account_id': str(CASH), 'idempotency_key': 'cyc-cash-1'}, follow_redirects=True),
    'Direct sale added successfully')

# ---------------------------------------------------------- 10 credit sale
step('10 credit sale 10x1650 paid 5000', c.post('/add_direct_sale', data={
    'category': 'Credit Customer', 'client_code': CLI['code'], 'has_bill': 'on',
    'sale_date': '2026-10-15', 'delivery_person_id[]': str(DRV), 'delivery_bags[]': '10',
    'delivery_rent_amount[]': '400', 'material_id[]': str(MAT['DG Cement']),
    'product_name[]': 'DG Cement', 'qty[]': '10', 'unit_rate[]': '1650',
    'ignore_booking_item[]': '1', 'delivery_rent': '400', 'manual_bill_no': 'CYC-CR-1',
    'amount': '16500', 'paid_amount': '5000', 'payment_method': 'Cash',
    'payment_account_id': str(CASH), 'idempotency_key': 'cyc-cr-1'}, follow_redirects=True),
    'Direct sale added successfully')

# ------------------------------------------------------ 11 booking delivery
step('11 booking delivery 20x1500', c.post('/add_direct_sale', data={
    'category': 'Booking Delivery', 'client_code': CLI['code'], 'has_bill': 'on',
    'sale_date': '2026-10-16', 'delivery_person_id[]': str(DRV), 'delivery_bags[]': '20',
    'delivery_rent_amount[]': '800', 'material_id[]': str(MAT['DG Cement']),
    'product_name[]': 'DG Cement', 'qty[]': '20', 'unit_rate[]': '1500',
    'ignore_booking_item[]': '0', 'delivery_rent': '800', 'manual_bill_no': 'CYC-BD-1',
    'amount': '30000', 'paid_amount': '0', 'payment_method': 'Cash',
    'payment_account_id': str(CASH), 'idempotency_key': 'cyc-bd-1'}, follow_redirects=True),
    'Direct sale added successfully')

print('\n########## STAGE 8-11 SALES ##########')
dump('booking', 'select id,client_name,amount,paid_amount,manual_bill_no,auto_bill_no,receive_in_account_id from booking')
dump('booking_item', 'select id,material_name,qty,price_at_time from booking_item')
dump('direct_sale', 'select id,category,client_name,client_code,amount,paid_amount,discount,manual_bill_no,auto_bill_no,driver_name,delivery_rent_cost,rent_item_revenue,rent_variance_loss from direct_sale order by id')
dump('direct_sale_item', 'select id,sale_id,product_name,qty,price_at_time,cost_rate_at_sale from direct_sale_item order by id')
dump('delivery_rent', 'select id,sale_id,delivery_person_name,bill_no,amount from delivery_rent order by id')
dump('entry', 'select id,date,type,material,client,qty,bill_no,auto_bill_no,nimbus_no,client_category,driver_name,is_void from entry order by id')
dump('account_after_sales', 'select id,name,balance from account order by id')
dump('acct_tx_after_sales', 'select id,from_account_id,to_account_id,amount,description,transaction_type,source_type,source_id from account_transaction order by id')
dump('stock_after_sales', 'select name,total from material order by id')

# ------------------------------------------------------------ 12 payments
step('12a client receipt 8000', c.post('/accounts/payments/clients/save', data={
    'client_code': CLI['code'], 'amount': '8000', 'date': '2026-10-18', 'discount': '0',
    'method': 'Cash', 'payment_account_id': str(CASH), 'manual_bill_no': 'CYC-RCPT-1',
    'note': 'part receipt against credit sale', 'show': 'active',
    'idempotency_key': 'cyc-rcpt-1'}, follow_redirects=True), 'Payment saved successfully.')
step('12b client receipt 3000 bank', c.post('/accounts/payments/clients/save', data={
    'client_code': CLI['code'], 'amount': '3000', 'date': '2026-10-19', 'discount': '0',
    'method': 'Bank Transfer', 'payment_account_id': str(BANK), 'manual_bill_no': 'CYC-RCPT-2',
    'note': 'bank receipt', 'show': 'active', 'idempotency_key': 'cyc-rcpt-2'},
    follow_redirects=True), 'Payment saved successfully.')
GRN1 = one("select id from grn where manual_bill_no like '%CYC-GRN-1'")['id']
step('12c GRN payment 60000', c.post('/accounts/grn_payments/save', data={
    'grn_id': str(GRN1), 'obligation_key': 'SUPPLIER:1', 'amount': '60000', 'method': 'Cash',
    'payment_account_id': str(CASH), 'date_posted': '2026-10-20', 'reference': 'CYC-GRNPAY-1',
    'idempotency_key': 'cyc-grnpay-1'}, follow_redirects=True),
    'GRN payment of Rs. 60,000.00 recorded from Accounts.')
step('12d supplier payment 20000', c.post('/add_supplier_payment', data={
    'return_to': '/suppliers', 'supplier_id': '1', 'date': '2026-10-21', 'amount': '20000',
    'payment_account_id': str(BANK), 'method': 'Bank Transfer',
    'note': 'part payment Ravi', 'manual_bill_no': 'CYC-SUPPAY-1'}, follow_redirects=True),
    'Supplier payment recorded.')
step('12e driver payment 1000', c.post(f'/delivery_person_ledger/{DRV}/pay', data={
    'paid_amount': '1000', 'waive_off_amount': '0', 'method': 'Cash',
    'payment_account_id': str(CASH), 'reference': 'CYC-DRV-1', 'date': '2026-10-22',
    'note': 'part driver settlement', 'idempotency_key': 'cyc-drv-1'}, follow_redirects=True),
    'Driver payment recorded across 3 rent item(s).')

print('\n########## STAGE 12 PAYMENTS ##########')
dump('client_payment', 'select id,client_name,amount,discount,method,payment_type,payment_account_id,manual_bill_no,auto_bill_no from payment order by id')
dump('supplier_payment', 'select id,supplier_id,amount,method,payment_account_id,manual_bill_no,auto_bill_no,source_type,grn_id,recipient_type from supplier_payment order by id')
dump('driver_payment', 'select id,delivery_person_id,sale_id,allocation_id,amount_paid,waive_off_amount,payment_account_id,reference from delivery_person_payment order by id')
dump('account_after_payments', 'select id,name,balance,opening_balance from account order by id')
dump('acct_tx_after_payments', 'select id,from_account_id,to_account_id,amount,description,transaction_type,source_type,source_id,grn_id,party_type,party_name,is_void from account_transaction order by id')

json.dump({'CLI': CLI, 'DRV': DRV, 'CASH': CASH, 'BANK': BANK, 'MAT': MAT, 'SVC': SVC,
           'CAT': CAT, 'GRN1': GRN1}, open('/tmp/final_ids.json', 'w'), default=str)
print('\n== PROBE A: masters, GRN, sales, payments complete ==')
