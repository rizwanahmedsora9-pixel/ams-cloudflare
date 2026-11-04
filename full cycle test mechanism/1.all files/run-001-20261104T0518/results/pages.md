
## /  —  System Dashboard   [HTTP 200, 130012B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: Brand Name | In (Total) | Out (Total) | Current Stock | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /inventory/stock_summary  —  Stock Summary   [HTTP 200, 132191B]
- FORM GET /inventory/stock_summary id=-
    fields: date_from, date_to, material, material_category
      material options: ['All Materials', 'Chenab Sand', 'DG Cement', 'Pioneer Cement', 'TRANSPARENT SHEET']
      material_category options: ['All Categories', 'Cement', 'General', 'Sand & Gravel', 'Sheets & Covers']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Material | Received | Delivered | Net | Date | GRN Bill | Supplier | Qty Received | Material Brand | Category | Opening | Stock In | Stock Out | Closing | Physical | Diff | Table / setting | Status

## /inventory/daily_transactions  —  Daily Breakdown   [HTTP 200, 131504B]
- FORM GET /inventory/daily_transactions id=-
    fields: date_from, date_to, category, transaction_category, material_category, material, client, bill_no, show
      category options: ['All', 'General', 'Open Khata']
      transaction_category options: ['All', 'Billed', 'Unbilled', 'Open Khata']
      material_category options: ['All', 'Cement', 'General', 'Sand & Gravel', 'Sheets & Covers']
      material options: ['All', 'DG Cement', 'Pioneer Cement', 'Chenab Sand', 'TRANSPARENT SHEET', 'CEMENT RENT']
      show options: ['Active', 'Deleted', 'All']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Time | Type | Client | Material | Category | Qty | Bill No | Nimbus No | Notes | By | Action | Table / setting | Status | In | Upd | Skip | Fail | Note

## /tracking  —  History / Tracking   [HTTP 200, 135303B]
- FORM GET (self) id=-
    fields: start_date, end_date, type, has_bill, client, material, bill_no, category
      type options: ['All', 'IN (Receiving)', 'OUT (Dispatch)', 'BOOKING (Reserved)', 'PAYMENT']
      has_bill options: ['Any', 'With Bill', 'Without Bill']
      category options: ['All Categories', 'Cash (Unbilled)', 'Open Khata', 'Due Sales', 'Booking Sales', 'General', 'Walking-Customer', 'Misc']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Filter | Paid | Schedule callback
- COLUMNS: Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /grn  —  GRN (Receiving) - records tab   [HTTP 200, 301826B]
- FORM POST /grn id=grnForm
    fields: action, supplier, supplier_id, date, time:time, charge_id[], charge_type[], charge_label[], charge_amount[], charge_row_key[], charge_include_in_supplier[], charge_recipient_type[], charge_recipient[], charge_treatment[], charge_basis[], charge_grid_present, charge_supplier_billing_present, allocation_basis_default, adjustment_amount, discount, tax_percent, tax_amount, tax_type, supplier_invoice_no, manual_bill_no, bill_date, due_date, note, photo
      charge_type[] options: ['Select charge…', 'Vehicle Fare', 'Transportation', 'Loading', 'Unloading', 'Other Expenses']
      charge_recipient_type[] options: ['Select recipient…', 'Vehicle / Transporter', 'Loading / Labour', 'Other charge recipient']
      charge_treatment[] options: ['Include in material cost', 'Separate expense', 'Not material cost']
      charge_basis[] options: ['By value', 'By quantity', 'Manual']
      allocation_basis_default options: ['By line value (recommended)', 'By quantity']
      tax_type options: ['Asset', 'Expense', 'Purchase(Adv Tax)']
- FORM GET /grn id=-
    fields: start_date, end_date, search
- FORM POST /grn id=-
    fields: action, id
- FORM POST /shift_grn_supplier/6 id=-
    fields: target_supplier_id
      target_supplier_id options: ['-- Select correct supplier --', 'Kohat Traders']
- FORM POST /grn id=-
    fields: action, id
- FORM POST /shift_grn_supplier/5 id=-
    fields: target_supplier_id
      target_supplier_id options: ['-- Select correct supplier --', 'Kohat Traders']
- FORM POST /grn id=-
    fields: action, id
- FORM POST /shift_grn_supplier/4 id=-
    fields: target_supplier_id
      target_supplier_id options: ['-- Select correct supplier --', 'Kohat Traders']
- FORM POST /grn id=-
    fields: action, id
- FORM POST /shift_grn_supplier/3 id=-
    fields: target_supplier_id
      target_supplier_id options: ['-- Select correct supplier --', 'Kohat Traders']
- FORM POST /grn id=-
    fields: action, id
- FORM POST /shift_grn_supplier/2 id=-
    fields: target_supplier_id
      target_supplier_id options: ['-- Select correct supplier --', 'Kohat Traders']
- FORM POST /grn id=-
    fields: action, id
- FORM POST /shift_grn_supplier/1 id=-
    fields: target_supplier_id
      target_supplier_id options: ['-- Select correct supplier --', 'Kohat Traders']
- FORM POST /add_supplier id=addSupplierForm
    fields: name, phone, address, opening_balance
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add New Record | Use current time | Next | Add | Reset | Add charge | Save GRN | Filter | Recalculate | Cancel | Shift | Save Supplier | Paid | Schedule callback
- COLUMNS: Item | Quantity | Price | Total | Action | Charge | Label / Detail | Amount (Rs.) | Supplier Ledger | Recipient Type | Recipient / Person | Cost Treatment | Alloc. Basis | Lot consumption details | GRN # | Date & Time | Supplier | Total Qty

## /grn?tab=costs  —  GRN - costs tab   [HTTP 200, 207680B]
- FORM POST /grn id=grnForm
    fields: action, supplier, supplier_id, date, time:time, charge_id[], charge_type[], charge_label[], charge_amount[], charge_row_key[], charge_include_in_supplier[], charge_recipient_type[], charge_recipient[], charge_treatment[], charge_basis[], charge_grid_present, charge_supplier_billing_present, allocation_basis_default, adjustment_amount, discount, tax_percent, tax_amount, tax_type, supplier_invoice_no, manual_bill_no, bill_date, due_date, note, photo
      charge_type[] options: ['Select charge…', 'Vehicle Fare', 'Transportation', 'Loading', 'Unloading', 'Other Expenses']
      charge_recipient_type[] options: ['Select recipient…', 'Vehicle / Transporter', 'Loading / Labour', 'Other charge recipient']
      charge_treatment[] options: ['Include in material cost', 'Separate expense', 'Not material cost']
      charge_basis[] options: ['By value', 'By quantity', 'Manual']
      allocation_basis_default options: ['By line value (recommended)', 'By quantity']
      tax_type options: ['Asset', 'Expense', 'Purchase(Adv Tax)']
- FORM GET /grn id=grnCostsFilter
    fields: tab, cost_kind, cost_supplier, cost_start, cost_end
      cost_kind options: ['All costs', 'Stock / material', 'Vehicle fare / transport', 'Loading', 'Unloading', 'Other expenses']
      cost_supplier options: ['All suppliers', 'Kohat Traders', 'Ravi Cement Supplier']
- FORM POST /add_supplier id=addSupplierForm
    fields: name, phone, address, opening_balance
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add New Record | Use current time | Next | Add | Reset | Add charge | Save GRN | Apply | Save Supplier | Paid | Schedule callback
- COLUMNS: Item | Quantity | Price | Total | Action | Charge | Label / Detail | Amount (Rs.) | Supplier Ledger | Recipient Type | Recipient / Person | Cost Treatment | Alloc. Basis | Date | GRN | Supplier | Cost kind | Detail

## /bookings  —  Bookings   [HTTP 200, 156502B]
- FORM GET /bookings id=-
    fields: show, client, bill_no, date_from, date_to, per_page
      per_page options: ['10', '20', '50']
- FORM POST /delete_transaction/Booking/1 id=-
    fields: 
- FORM POST /add_booking id=-
    fields: client_code, material_id[], service_id[], material_name[], qty[], unit_rate[], amount, paid_amount, payment_method, payment_account_id, date:datetime-local, discount, discount_reason, manual_bill_no, photo, photo_url:url, note
      payment_method options: ['Cash', 'Bank']
      payment_account_id options: ['Select account...', 'Main Cash', 'Meezan Bank (Meezan Bank)']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add Booking | Filter | Delete | - | + | + Add More Items | Reset | Save Booking | Paid | Schedule callback
- COLUMNS: Manual Bill | Auto Bill | Client | Material | Qty | Total Amount | Actually Paid | Notes | Actions | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row

## /direct_sales  —  Sales (direct sales)   [HTTP 200, 293600B]
- FORM GET /direct_sales id=-
    fields: show, page, client, bill_no, bill_state, category, material, per_page
      bill_state options: ['All', 'Billed', 'Unbilled']
      category options: ['Booked Sale', 'Booked + Due', 'Due Sale', 'Open Khata', 'Cash Sale']
      per_page options: ['10', '20', '50', '100']
- FORM POST /delete_transaction/DirectSale/3 id=-
    fields: 
- FORM POST /delete_transaction/DirectSale/2 id=-
    fields: 
- FORM POST /delete_transaction/DirectSale/1 id=-
    fields: 
- FORM POST /add_direct_sale id=-
    fields: category, client_code, client_name, manual_client_name, has_bill, create_invoice, track_as_cash, draft_id, idempotency_key, delivery_person_id[], delivery_bags[], delivery_rent_amount[], sale_date, material_id[], service_id[], product_name[], grn_item_id[], alternate_material_id[], alternate_material[], qty[], unit_rate[], ignore_booking_item[], delivery_rent, manual_bill_no, photo, photo_url:url, note, amount, discount, discount_reason, paid_amount, payment_method, payment_account_id, bank_name, account_name, account_no, allow_negative_stock
      category options: ['Booked Sale', 'Booked + Due', 'Due Sale', 'Open Khata', 'Cash Sale']
      delivery_person_id[] options: ['Select person', 'Akram Driver']
      payment_method options: ['Cash', 'Bank Transfer', 'Check']
      payment_account_id options: ['Select account...', 'Main Cash', 'Meezan Bank (Meezan Bank)']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add Sale | Filter Options | Apply | Billed Sales (Due / Booking) 3 Click to Add | Unbilled Sales (Cash) 0 Click to Add | Delete | 0 | Hold | X | + Add Delivery Person | - | + | + Add More Items | Items | Reset | Save Sale
- COLUMNS: Bill No. | System Ref | Status | Client | Date & Time | Material | Qty | Total Amount | Driver Rent | Notes | Actions | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table

## /material_returns  —  Material Return   [HTTP 200, 147106B]
- FORM GET /material_returns id=-
    fields: show, client, bill_no, material, date_from, date_to
- FORM POST /add_material_return id=-
    fields: client_code:input, date:datetime-local, return_type, manual_bill_no:input, material_id[], service_id[], material_name[]:input, qty[], unit_rate[], rent_rate[], note:input
      return_type options: ['Normal Return', 'Booked Return']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | New Return | Go | &times; | + Add Row | Cancel | Save Return | Paid | Schedule callback
- COLUMNS: Date | Bill | Client | Type | Items | Amount | Notes | Action | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason

## /pending_bills  —  Pending Bills   [HTTP 200, 153657B]
- FORM GET /pending_bills id=-
    fields: client_code, bill_no, bill_kind, is_manual, category, bill_from, bill_to
      bill_kind options: ['All (SB/MB)', 'SB (Auto)', 'MB (Manual)']
      is_manual options: ['All Types', 'Manual Bill No', 'System/Auto Bill']
      category options: ['All Categories', 'Booked Sale', 'Booked + Due', 'Due Sale', 'Open Khata', 'Cash Sale', 'Cash Paid (Open Khata)']
- FORM POST /delete_pending_bill/3 id=-
    fields: 
- FORM POST /delete_pending_bill/2 id=-
    fields: 
- FORM POST /delete_pending_bill/1 id=-
    fields: 
- FORM POST /import_pending_bills id=-
    fields: file
- FORM POST /add_pending_bill id=-
    fields: client_code, bill_no, nimbus_no, amount, reason, note, photo_url:url, photo
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add Bill | Export | Import | Search | Cancel | Import Now | Reset | Paid | Schedule callback
- COLUMNS: Client Code | Bill Ref | Client Name | Reason | Notes | Amount | Status | Actions | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Entry

## /delivery_rents  —  Delivery Rent   [HTTP 200, 156632B]
- FORM GET /delivery_rents id=-
    fields: date_from, date_to, driver, q, group_by, sort
      driver options: ['All delivery persons', 'Akram Driver']
      group_by options: ['By person', 'By day']
      sort options: ['Most due', 'Oldest unpaid', 'Highest rent', 'Most paid', 'Name']
- FORM POST /delivery_rents/void/1 id=-
    fields: next
- FORM POST /delivery_person_payments/1/void id=-
    fields: next
- FORM POST /delivery_rents/void/2 id=-
    fields: next
- FORM POST /delivery_person_payments/2/void id=-
    fields: next
- FORM POST /delivery_rents/void/3 id=-
    fields: next
- FORM POST /delivery_person_payments/3/void id=-
    fields: next
- FORM POST # id=rentEntryPayForm
    fields: paid_amount, waive_off_amount, method, payment_account_id, date, reference, note, idempotency_key, next
      method options: ['Cash', 'Bank', 'Check', 'Online']
      payment_account_id options: ['Select account…', '[CASH] Main Cash (Rs. 175,500.00)', '[BANK] Meezan Bank (Rs. 483,000.00)']
- FORM POST # id=rentDriverPayForm
    fields: paid_amount, waive_off_amount, method, payment_account_id, date, reference, note, idempotency_key, next
      method options: ['Cash', 'Bank', 'Check', 'Online']
      payment_account_id options: ['Select account…', '[CASH] Main Cash (Rs. 175,500.00)', '[BANK] Meezan Bank (Rs. 483,000.00)']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Pay | reverse | Save Payment | Paid | Schedule callback
- COLUMNS: Delivery Person | Rent | Paid | Remaining | Trips | Action | Date | Bill | Client | Bags | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table

## /payments  —  Payments   [HTTP 200, 142651B]
- FORM GET /payments id=-
    fields: party, show, page_customer, page_supplier, date_from, date_to, client, method, amount_min, amount_max, per_page_customer
      method options: ['All', 'Cash', 'Bank Transfer', 'Check', 'Cheque', 'Bank Transfer (Legacy)']
      per_page_customer options: ['10', '20', '50', '100']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Manual Bill | Auto Bill | Client | Amount | Method | Notes | Actions | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /accounts/  —  Accounts dashboard   [HTTP 200, 190044B]
- FORM POST /accounts/transactions/new id=-
    fields: idempotency_key, tx_mode, date_posted:datetime-local, amount, method, receive_from_category, receive_account_id, client_input, receive_from_account_id, receive_source_label, discount, pay_from_account_id, pay_target, grn_payment_grn_id, pay_to_account_id, supplier_id, supplier_input, target_label, client_id_refund, client_input_refund, delivery_person_id, driver_input, reference, note
      method options: ['Cash', 'Bank Transfer', 'Check', 'Online']
      receive_from_category options: ['Client Ledger', 'Clients', 'Company', 'External', 'Loan', 'Own Funds', 'Other Source']
      receive_account_id options: ['Select company account receiving this payment', 'Main Cash (Rs. 175500.00)', 'Meezan Bank (Rs. 483000.00)']
      receive_from_account_id options: ['Select source account', 'Main Cash (Rs. 175500.00)', 'Meezan Bank (Rs. 483000.00)']
      pay_from_account_id options: ['Select source account', 'Main Cash (Rs. 175500.00)', 'Meezan Bank (Rs. 483000.00)']
      pay_target options: ['Company Account Transfer', 'Supplier Payment', 'PAY EXISTING GRN / GRN PAYMENT', 'Driver Service Payment', 'Client Refund', 'Loan Payment', 'Personal Expense', 'Other Expense']
      grn_payment_grn_id options: ['— Open the GRN Payments page —', 'MB NO.CYC-GRN-6 · Ravi Cement Supplier', 'MB NO.CYC-GRN-5 · Kohat Traders', 'MB NO.CYC-GRN-4 · Ravi Cement Supplier', 'MB NO.CYC-GRN-3 · Kohat Traders', 'MB NO.CYC-GRN-2 · Ravi Cement Supplier', 'MB NO.CYC-GRN-1 · Ravi Cement Supplier']
      pay_to_account_id options: ['Select destination account', 'Main Cash', 'Meezan Bank']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | New Transaction | Submit Transaction | Paid | Schedule callback
- COLUMNS: Account Name | Type | Channel | Today's Opening Balance | Total Balance | Actions | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /accounts/accounts  —  Manage accounts   [HTTP 200, 145066B]
- FORM POST /accounts/1/toggle id=-
    fields: 
- FORM POST /accounts/1/delete id=-
    fields: 
- FORM POST /accounts/2/toggle id=-
    fields: 
- FORM POST /accounts/2/delete id=-
    fields: 
- FORM POST /accounts/categories/add id=-
    fields: name, note
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | New Group | Cancel | Create Group | Paid | Schedule callback
- COLUMNS: Account | Group | Type | Channel | Balance | Status | Created | Actions | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /accounts/accounts/add  —  Add account   [HTTP 200, 157590B]
- FORM POST (self) id=accountForm
    fields: name, note, source_category, class_category, class_subcategory, class_account_type, linked_entity_type, linked_client_id, linked_supplier_id, linked_party_name, channel, cash_location, cash_responsible, bank_name, account_holder_name, account_number, branch_code, wallet_provider, wallet_number, wallet_holder, opening_amount, opening_position, opening_effective_date, account_status
      source_category options: ['Select category/group…', 'Clients', 'Company', 'External', 'Loan', 'Own Funds']
      class_category options: []
      class_subcategory options: []
      class_account_type options: []
      linked_client_id options: ['Select client…', 'Bilal Construction (CYC-CL-1)', 'OPEN KHATA (OPEN-KHATA)']
      linked_supplier_id options: ['Select supplier…', 'Kohat Traders', 'Ravi Cement Supplier']
      channel options: []
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Quick Add Group | Save | Create Account | Paid | Schedule callback
- COLUMNS: Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /accounts/categories  —  Account groups   [HTTP 200, 145666B]
- FORM POST /accounts/categories/3/toggle id=-
    fields: 
- FORM POST /accounts/categories/3/delete id=-
    fields: 
- FORM POST /accounts/categories/1/toggle id=-
    fields: 
- FORM POST /accounts/categories/4/toggle id=-
    fields: 
- FORM POST /accounts/categories/4/delete id=-
    fields: 
- FORM POST /accounts/categories/5/toggle id=-
    fields: 
- FORM POST /accounts/categories/5/delete id=-
    fields: 
- FORM POST /accounts/categories/2/toggle id=-
    fields: 
- FORM POST /accounts/categories/2/delete id=-
    fields: 
- FORM POST /accounts/categories id=-
    fields: name, note
- FORM POST (self) id=editCategoryForm
    fields: name, note
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add Category | Edit | Cancel | Create Category | Save Changes | Paid | Schedule callback
- COLUMNS: ID | Category / Group Name | Note | Accounts Count | Status | Actions | Table / setting | In | Upd | Skip | Fail | Sheet / table | Excel row | Reason | Entry

## /accounts/transfers  —  Transfers   [HTTP 200, 126646B]
- FORM GET (self) id=-
    fields: from, to, q
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Date | From | To | Amount | Description | Note | Action | Table / setting | Status | In | Upd | Skip | Fail | Sheet / table | Excel row | Reason | Entry

## /accounts/receipts  —  Receipts   [HTTP 200, 127210B]
- FORM GET (self) id=-
    fields: from, to
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Date | Client | Amount | Paid | Bill # | Note | Supplier | Total | Table / setting | Status | In | Upd | Skip | Fail | Sheet / table | Excel row | Reason | Entry

## /accounts/expenditures  —  Expenditures   [HTTP 200, 127924B]
- FORM GET (self) id=-
    fields: from, to, category, q
      category options: ['All']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Date | Category | Amount | Method | Note | Table / setting | Status | In | Upd | Skip | Fail | Sheet / table | Excel row | Reason | Entry

## /accounts/reconciliations  —  Reconciliations   [HTTP 200, 129442B]
- FORM GET (self) id=-
    fields: from, to, account_id, status, per_page
      account_id options: ['All accounts', 'Main Cash', 'Meezan Bank']
      status options: ['All', 'Matched', 'Loss', 'Excess']
      per_page options: ['10', '25', '50', '100']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Date | Account | Previous / Opening | Period In / Out | Expected | Actual | Adjustment | Final | Type / Status | By / Time | Note | Table / setting | Status | In | Upd | Skip | Fail | Sheet / table

## /accounts/audit  —  Account audit trail   [HTTP 200, 154799B]
- FORM GET (self) id=-
    fields: from, to, type, account_id, q, show_voided
      type options: ['All Types', 'Receipt', 'Refund', 'Payment', 'Transfer', 'Supplier Payment', 'Driver Payment', 'Expense']
      account_id options: ['All Accounts', 'Main Cash', 'Meezan Bank']
- FORM POST /accounts/transactions/11/void id=-
    fields: 
- FORM POST /accounts/transactions/10/void id=-
    fields: 
- FORM POST /accounts/transactions/9/void id=-
    fields: 
- FORM POST /accounts/transactions/8/void id=-
    fields: 
- FORM POST /accounts/transactions/7/void id=-
    fields: 
- FORM POST /accounts/transactions/6/void id=-
    fields: 
- FORM POST /accounts/transactions/5/void id=-
    fields: 
- FORM POST /accounts/transactions/4/void id=-
    fields: 
- FORM POST /accounts/transactions/3/void id=-
    fields: 
- FORM POST /accounts/transactions/2/void id=-
    fields: 
- FORM POST /accounts/transactions/1/void id=-
    fields: 
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Date | Type | From | To | Amount | Description / Note | Action | When / User | Entity | Before | After | Reason / Session | Table / setting | Status | In | Upd | Skip | Fail

## /accounts/purchase_payables  —  Purchase payables   [HTTP 200, 124541B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: Recipient | Type | Outstanding | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /accounts/payments/clients  —  Client payments   [HTTP 200, 157606B]
- FORM GET (self) id=-
    fields: show, from, to, party_id, account_id, method, payment_type, per_page, q
      method options: ['Cash', 'Bank', 'Check', 'Card', 'Online']
      payment_type options: ['Receipt / Payment Received', 'Refund Paid to Client', 'Waive-Off Only']
      per_page options: ['10', '25', '50', '100']
- FORM POST /accounts/payments/clients/void/2 id=voidPaymentForm2
    fields: 
- FORM POST /accounts/payments/clients/void/1 id=voidPaymentForm1
    fields: 
- FORM POST /accounts/payments/clients/save id=clientPaymentForm
    fields: payment_id, revision, idempotency_key, show, client_code, client_name, payment_type, amount, discount, discount_reason, method, payment_account_id, manual_bill_no, date, photo, photo_url:url, note
      method options: ['Cash', 'Bank', 'Check', 'Card', 'Online']
      payment_type options: ['Receipt / Payment Received', 'Refund Paid to Client', 'Waive-Off Only']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | New Payment | Apply | Cancel | Save Payment | Paid | Schedule callback
- COLUMNS: Date | Client | Type | Account | Amount | Method | Bill # | Note | Actions | Table / setting | Status | In | Upd | Skip | Fail | Sheet / table | Excel row | Reason

## /accounts/payments/suppliers  —  Supplier payments   [HTTP 200, 156428B]
- FORM GET (self) id=-
    fields: show, from, to, party_id, account_id, method, per_page, q
      method options: ['Cash', 'Bank', 'Check', 'Card', 'Online']
      per_page options: ['10', '25', '50', '100']
- FORM POST /accounts/payments/suppliers/2/delete id=delSupplierPaymentForm2
    fields: 
- FORM POST (self) id=supplierPaymentShiftForm
    fields: target_supplier_id, return_to
      target_supplier_id options: ['-- Select supplier --', 'Kohat Traders', 'Ravi Cement Supplier']
- FORM POST /accounts/payments/suppliers/save id=supplierPaymentForm
    fields: payment_id, revision, idempotency_key, show, supplier_id, supplier_name, amount, method, payment_account_id, manual_bill_no, date, note
      method options: ['Cash', 'Bank', 'Check', 'Card', 'Online']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | New Payment | Apply | Cancel | Shift entry | Save Payment | Paid | Schedule callback
- COLUMNS: Date | Supplier | Account | Amount | Method | Bill # | Note | Actions | Table / setting | Status | In | Upd | Skip | Fail | Sheet / table | Excel row | Reason | Entry

## /accounts/grn_payments  —  Pay existing GRN   [HTTP 200, 125493B]
- FORM GET (self) id=-
    fields: grn_id
      grn_id options: ['— Select a GRN —', 'MB NO.CYC-GRN-6 · Ravi Cement Supplier · 12/Oct/2026 · cost 12,000.00 · due 12,000.00', 'MB NO.CYC-GRN-5 · Kohat Traders · 10/Oct/2026 · cost 11,000.00 · due 11,000.00', 'MB NO.CYC-GRN-4 · Ravi Cement Supplier · 08/Oct/2026 · cost 96,000.00 · due 96,000.00', 'MB NO.CYC-GRN-3 · Kohat Traders · 06/Oct/2026 · cost 112,000.00 · due 112,000.00', 'MB NO.CYC-GRN-2 · Ravi Cement Supplier · 04/Oct/2026 · cost 67,500.00 · due 67,500.00', 'MB NO.CYC-GRN-1 · Ravi Cement Supplier · 02/Oct/2026 · cost 120,000.00 · due 60,000.00']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Open GRN | Paid | Schedule callback
- COLUMNS: Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /cash_flow  —  Cash Flow   [HTTP 200, 218063B]
- FORM POST (self) id=-
    fields: action, new_category_name, new_category_direction, new_category_notes
      new_category_direction options: ['Received & Spent', 'Received only', 'Spent only']
- FORM POST (self) id=-
    fields: action, new_sub_category_id, new_subcategory_name, new_subcategory_notes
      new_sub_category_id options: ['Parent Category *', 'Owner Investment (in)']
- FORM POST (self) id=-
    fields: action, new_party_name, new_party_type, new_party_note
      new_party_type options: ['Person', 'Outsider / other party', 'Loan (person or outside lender)', 'Other']
- FORM POST (self) id=-
    fields: category_id, category_name, category_direction, category_notes
      category_direction options: ['Both', 'Received', 'Spent']
- FORM POST (self) id=-
    fields: party_id, party_name, party_type, party_note
      party_type options: ['Person', 'Outsider / other party', 'Loan (person or outside lender)', 'Other']
- FORM GET /cash_flow#tab-transactions id=ftForm
    fields: ft_preset, ft_direction, ft_category, ft_account, ft_client, ft_supplier, ft_partner, ft_worker, ft_vehicle, ft_method, ft_q
      ft_preset options: ['Today', 'Yesterday', 'This Week', 'This Month', 'Last 30 Days', 'All']
      ft_direction options: ['All Directions', 'In (Received)', 'Out (Spent)', 'Transfer']
      ft_category options: ['All Categories']
      ft_account options: ['All Accounts', 'Main Cash · CASH · Rs. 175,500', 'Meezan Bank · BANK · Rs. 483,000']
      ft_client options: ['All Clients']
      ft_supplier options: ['All Suppliers']
      ft_partner options: ['All Partners']
      ft_worker options: ['All Workers']
      ft_vehicle options: ['All Vehicles']
      ft_method options: ['All Payment Methods', 'Cash', 'Bank', 'Check']
- FORM GET /cash_flow#tab-reconcile id=-
    fields: recon_day
- FORM POST /daily_reconciliation id=-
    fields: day, return_to, _csrf_token
- FORM POST /daily_reconciliation id=-
    fields: action, day, _csrf_token, return_to, shift_name:input, shift_note:input
- FORM POST /daily_reconciliation id=-
    fields: action, day, account_id, _csrf_token, return_to, counted
- FORM POST /daily_reconciliation id=-
    fields: action, day, account_id, _csrf_token, return_to
- FORM POST /daily_reconciliation id=-
    fields: action, day, account_id, _csrf_token, return_to, counted
- FORM POST /daily_reconciliation id=-
    fields: action, day, account_id, _csrf_token, return_to
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Financial Details Balances & totals | Transactions Filter matrix & ledger | Master Data Categories & parties | Cash Amount (in hand) Rs. 175,500 1 account | Bank Amount Rs. 483,000 1 account | Create Category | Create Sub-category | Create Party | Save | Disable | Delete | Apply Filters | Finalize & Lock Day | Record Shift Close | Paid | Schedule callback
- COLUMNS: Cash account | Period in | Period out | Balance | Bank account | Bank / details | Account | Type | Current balance | Category | In | Out | Party | ID | Name | Direction | Notes | Status

## /cash_flow_differences  —  Cash Flow differences   [HTTP 200, 126068B]
- FORM GET /cash_flow_differences id=-
    fields: from_date, to_date, workflow_filter
      workflow_filter options: ['All', 'New (Physical Cash)', 'Legacy (Differences)']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Filter | Paid | Schedule callback
- COLUMNS: Date | Opening Balance | Cash In | Cash Out | Calculated Closing | Physical Cash | Difference | Reason | Created By | Edits | Last Updated | Actions | Table / setting | Status | In | Upd | Skip | Fail

## /daily_reconciliation  —  Daily reconciliation   [HTTP 200, 144628B]
- FORM GET (self) id=-
    fields: day
- FORM POST /daily_reconciliation id=-
    fields: day, _csrf_token
- FORM POST /daily_reconciliation id=-
    fields: action, day, _csrf_token, shift_name:input, shift_note:input
- FORM POST /daily_reconciliation id=-
    fields: action, day, account_id, _csrf_token, counted
- FORM POST /daily_reconciliation id=-
    fields: action, day, account_id, _csrf_token
- FORM POST /daily_reconciliation id=-
    fields: action, day, account_id, _csrf_token, counted
- FORM POST /daily_reconciliation id=-
    fields: action, day, account_id, _csrf_token
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Finalize & Lock Day | Record Shift Close | Paid | Schedule callback
- COLUMNS: Account | Opening | In | Out | Transfer In | Transfer Out | Expected Closing | Actual Counted | Difference | Action | Table / setting | Status | Upd | Skip | Fail | Note | Sheet / table | Excel row

## /profit_reports  —  Profit & Loss   [HTTP 200, 184059B]
- FORM GET /profit_reports id=plFilterForm
    fields: period, start_date, end_date, entity_type, client, client_category, material, transaction_group, payment_status, booking_status, grn_id, category, supplier, q, per_page
      period options: ['This month to date', 'Today', 'Yesterday', 'This week to date', 'Last 7 days', 'Last 30 days', 'Last full month', 'This year to date']
      entity_type options: ['Customer', 'Client category (group)']
      transaction_group options: ['All transaction types', 'Goods sales (delivered)', 'Services', 'Returns', 'Operating expenses', 'Other income / other']
      payment_status options: ['All payment statuses', 'Paid', 'Partially paid', 'Unpaid', 'Credit outstanding (any unpaid balance)']
      booking_status options: ['All booking statuses', 'Open (nothing delivered)', 'Partially delivered', 'Completed', 'Cancelled / void']
      grn_id options: ['All GRN lots', 'MB NO.CYC-GRN-6 · Ravi Cement Supplier · 2026-10-12', 'MB NO.CYC-GRN-5 · Kohat Traders · 2026-10-10', 'MB NO.CYC-GRN-4 · Ravi Cement Supplier · 2026-10-08', 'MB NO.CYC-GRN-3 · Kohat Traders · 2026-10-06', 'MB NO.CYC-GRN-2 · Ravi Cement Supplier · 2026-10-04', 'MB NO.CYC-GRN-1 · Ravi Cement Supplier · 2026-10-02']
      category options: ['All recognized activity', 'Cash Sales', 'Credit Sales', 'Booking Supplies', 'Other / Excess Sales', 'Delivery Revenue', 'Sale Returns', 'Booked Returns']
      per_page options: ['25', '50', '100']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: From goods sales to gross profit | Amount (Rs.) | What is included | Inventory cost view | Supplier material | Capitalised costs | Total landed value | Item | Delivered qty | Goods sales | Landed costs | COGS (FIFO) | Gross profit | Margin | Remaining stock (FIFO value) | Service | Qty | Revenue earned

## /financial_details  —  Financial details   [HTTP 200, 129271B]
- FORM GET (self) id=-
    fields: type, start_date, end_date, client, min_price, max_price
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply Filters | Paid | Schedule callback
- COLUMNS: Date | Client | Type | Reference | Notes | Amount | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /suppliers  —  Suppliers   [HTTP 200, 176791B]
- FORM GET /suppliers id=-
    fields: q, status, balance_min, balance_max, sort
      status options: ['All statuses', 'Payable', 'Settled', 'Advance / prepaid', 'Inactive suppliers']
      sort options: ['Name (A–Z)', 'Name (Z–A)', 'Balance (high → low)', 'Balance (low → high)', 'Purchase (high → low)', 'Purchase (low → high)', 'Paid (high → low)']
- FORM POST /edit_supplier/2 id=-
    fields: _csrf_token, name, phone, address, opening_balance, opening_balance_date, is_active
- FORM POST /delete_supplier/2 id=-
    fields: action, _csrf_token
- FORM POST /transfer_supplier/2 id=-
    fields: _csrf_token, target_supplier_id
      target_supplier_id options: ['-- Select correct supplier --', 'Kohat Traders']
- FORM POST /hard_delete_supplier/2 id=-
    fields: action, _csrf_token
- FORM POST /edit_supplier/1 id=-
    fields: _csrf_token, name, phone, address, opening_balance, opening_balance_date, is_active
- FORM POST /delete_supplier/1 id=-
    fields: action, _csrf_token
- FORM POST /transfer_supplier/1 id=-
    fields: _csrf_token, target_supplier_id
      target_supplier_id options: ['-- Select correct supplier --', 'Kohat Traders']
- FORM POST /hard_delete_supplier/1 id=-
    fields: action, _csrf_token
- FORM POST /add_supplier id=-
    fields: _csrf_token, name, phone, address, opening_balance, opening_balance_date
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add Supplier | Apply | Update | Suspend Supplier | Transfer Data | Permanently Delete & Wipe Entries | Cancel | Save Supplier | Paid | Schedule callback
- COLUMNS: Supplier Name | Supplier Code | Phone Number | Total Purchase | Total Paid | Outstanding Payable | Advance Balance | Payment Status | Actions | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row

## /clients  —  Clients   [HTTP 200, 147527B]
- FORM GET /clients id=-
    fields: category, search
      category options: ['-- Select client category --', 'General', 'Open Khata']
- FORM POST /clients/activate_all id=-
    fields: 
- FORM POST /delete_client/2 id=-
    fields: 
- FORM POST /delete_client/1 id=-
    fields: 
- FORM POST /add_client id=-
    fields: name, category, code, page_entry, phone, location_url:url, address, opening_balance, opening_balance_date
      category options: ['-- Select client category --', 'General', 'Open Khata']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Search | Activate All Suspended | + New Client | Remove | Auto | Add Page | Reset | Create Client | Paid | Schedule callback
- COLUMNS: Client Name | Code | Pages | Opening | Billed | Received | Payable / Balance | Last Activity | Phone | Actions | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table

## /materials  —  Material Brands   [HTTP 200, 155521B]
- FORM POST /materials/activate_all id=-
    fields: 
- FORM POST /merge_materials id=-
    fields: source_material_id, target_material_id
      source_material_id options: ['Select source...', 'Chenab Sand (SAND)', 'DG Cement (DG)', 'Pioneer Cement (PIO)', 'TRANSPARENT SHEET (SHT)']
      target_material_id options: ['Select target...', 'Chenab Sand (SAND)', 'DG Cement (DG)', 'Pioneer Cement (PIO)', 'TRANSPARENT SHEET (SHT)']
- FORM POST /materials/rename_label id=-
    fields: old_label:input, target_material_id
      target_material_id options: ['Select target...', 'Chenab Sand (SAND)', 'DG Cement (DG)', 'Pioneer Cement (PIO)', 'TRANSPARENT SHEET (SHT)']
- FORM POST /bulk_update_material_unit id=-
    fields: category_id, new_unit
      category_id options: ['Cement', 'General', 'Sand & Gravel', 'Sheets & Covers']
- FORM POST /delete_material/1 id=-
    fields: 
- FORM POST /delete_material/2 id=-
    fields: 
- FORM POST /delete_material/3 id=-
    fields: 
- FORM POST /delete_material/4 id=-
    fields: 
- FORM POST /edit_material/1 id=-
    fields: material_name, category_id, material_unit, material_code
      category_id options: ['Cement', 'General', 'Sand & Gravel', 'Sheets & Covers']
- FORM POST /edit_material/2 id=-
    fields: material_name, category_id, material_unit, material_code
      category_id options: ['Cement', 'General', 'Sand & Gravel', 'Sheets & Covers']
- FORM POST /edit_material/3 id=-
    fields: material_name, category_id, material_unit, material_code
      category_id options: ['Cement', 'General', 'Sand & Gravel', 'Sheets & Covers']
- FORM POST /edit_material/4 id=-
    fields: material_name, category_id, material_unit, material_code
      category_id options: ['Cement', 'General', 'Sand & Gravel', 'Sheets & Covers']
- FORM POST /add_material id=-
    fields: _csrf_token, material_name, category_id, material_unit, material_code
      category_id options: ['Cement', 'General', 'Sand & Gravel', 'Sheets & Covers']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Merge Brands | Fix Old Names | Bulk Units | Activate All Suspended | Add Brand | Apply Filter | Confirm & Merge Materials | Apply Fix | Update Units | Edit | Suspend | Update Brand Name | Auto Code | Reset | Save Brand | Paid
- COLUMNS: Brand Name | Category | Unit | Code | Status | Actions | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /services  —  Services & Charges   [HTTP 200, 137517B]
- FORM GET /services id=-
    fields: q
- FORM POST /services/toggle/1 id=-
    fields: 
- FORM POST /services/delete/1 id=-
    fields: 
- FORM POST /services/add id=-
    fields: service_name, service_code, service_unit
- FORM POST /services/edit/1 id=-
    fields: service_name, service_code, service_unit
- FORM POST /services/migrate id=-
    fields: confirm
- FORM POST /services/merge id=-
    fields: source_service_id, target_service_id
      source_service_id options: ['Select source...', 'CEMENT RENT (SRV-RENT)']
      target_service_id options: ['Select target...', 'CEMENT RENT (SRV-RENT)']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Move Rent Materials & Entries to Services | Merge Services | Add Service | Search | Edit | Suspend | Save Changes | Convert to Services | Paid | Schedule callback
- COLUMNS: Service Name | Code | Unit | Historical Records | Status | Actions | Name | Current Stock | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /delivery_persons  —  Delivery Persons   [HTTP 200, 126937B]
- FORM POST /delivery_persons/add id=-
    fields: name, phone
- FORM POST /delivery_persons/toggle/1 id=-
    fields: 
- FORM POST /delivery_persons/edit/1 id=-
    fields: name, phone
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add Driver | Edit | Deactivate | Save Changes | Paid | Schedule callback
- COLUMNS: Name | Phone | Status | Actions | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /ledger  —  Ledger (client list)   [HTTP 200, 124584B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /client-ledger/categories  —  Client categories   [HTTP 200, 131074B]
- FORM POST /client-ledger/categories/add id=-
    fields: name
- FORM POST /client-ledger/categories/1/toggle id=-
    fields: 
- FORM POST /client-ledger/categories/1/delete id=-
    fields: 
- FORM POST /client-ledger/categories/2/toggle id=-
    fields: 
- FORM POST /client-ledger/categories/2/delete id=-
    fields: 
- FORM POST /client-ledger/categories/1/rename id=-
    fields: name
- FORM POST /client-ledger/categories/2/rename id=-
    fields: name
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Add Category | Rename | Deactivate | Delete | Save Name | Paid | Schedule callback
- COLUMNS: Category | Clients | Status | Created | Actions | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /decision_ledger  —  Decision Ledger   [HTTP 200, 133154B]
- FORM GET (self) id=-
    fields: q, category, balance, per_page
      category options: ['All', 'General', 'Misc', 'Open Khata', 'Walking-Customer']
      balance options: ['All', 'Due (Owed)', 'Advance (Paid Extra)', 'Settled']
      per_page options: ['10', '20', '50', '100']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: Material | Booked qty | Booked value | Delivered qty | Delivered value | Remaining qty | Remaining value | Client | Category | Pending | Material status & gross value | Action | Table / setting | Status | In | Upd | Skip | Fail

## /current_payables  —  Current Payables   [HTTP 200, 132129B]
- FORM GET /current_payables id=payablesFilterForm
    fields: client, amount_operator, amount_min, amount_max, exact_amount, start_date, end_date, status
      amount_operator options: ['Between / range', 'Exactly', 'Greater than', 'Less than']
      status options: ['Outstanding only', 'All balances', 'Settled only', 'Credit balances']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply filters | Paid | Schedule callback
- COLUMNS: Client | Account / Code | Outstanding | Last transaction | Last payment | Status | Actions | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /notifications  —  Notifications   [HTTP 200, 132634B]
- FORM GET (self) id=-
    fields: q:input, category, status, risk
      category options: ['All', 'Billed', 'Unbilled', 'Cash Unbilled', 'Open Khata', 'Cash Paid']
      status options: ['All', 'Pending', 'Paid']
      risk options: ['All', 'Very High', 'High', 'Medium', 'Low']
- FORM POST /notifications/add_email id=-
    fields: email
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Test Alarm | Apply | Add | Paid | Schedule callback
- COLUMNS: Client | Bill | Amount | Risk | Next Reminder | Last Response | Contacts | Action | Client / Bill | Reminder Deadline | Completed | Outcome | Customer Response | Table / setting | Status | In | Upd | Skip

## /notifications/upcoming  —  Upcoming reminders   [HTTP 200, 125513B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: Client | Bill | Reminder Time | Countdown | Note | Action | Table / setting | Status | In | Upd | Skip | Fail | Sheet / table | Excel row | Reason | Entry

## /settings  —  Settings   [HTTP 200, 208098B]
- FORM POST /update_settings id=-
    fields: company_name, company_address, company_phone, currency, allow_global_negative_stock
- FORM POST /material_categories/add id=-
    fields: category_name
- FORM POST /material_categories/2/rename id=-
    fields: category_name
- FORM POST /material_categories/2/toggle id=-
    fields: 
- FORM POST /material_categories/1/rename id=-
    fields: category_name
- FORM POST /material_categories/1/toggle id=-
    fields: 
- FORM POST /material_categories/3/rename id=-
    fields: category_name
- FORM POST /material_categories/3/toggle id=-
    fields: 
- FORM POST /material_categories/4/rename id=-
    fields: category_name
- FORM POST /material_categories/4/toggle id=-
    fields: 
- FORM POST /change_password id=-
    fields: password:password
- FORM POST /import_export/transfer/export id=-
    fields: sections
- FORM POST /reconcile_data id=-
    fields: apply_fixes
- FORM POST /reconcile_data id=-
    fields: apply_fixes
- FORM POST /delete_selected_data id=-
    fields: delete_targets
- FORM POST /delete_selected_data id=wipeConfirmForm
    fields: confirm_text, hard_delete_override
- FORM POST /add_user id=-
    fields: username, password:password, role, access_mode, can_view_dashboard, can_manage_grn, can_view_stock, can_view_daily, can_view_history, can_manage_bookings, can_manage_sales, can_manage_payments, can_manage_pending_bills, can_view_delivery_rent, can_view_client_ledger, can_view_supplier_ledger, can_view_decision_ledger, can_view_reports, can_view_cash_flow, can_manage_clients, can_manage_suppliers, can_manage_materials, can_manage_delivery_persons, can_manage_accounts, can_manage_notifications, can_import_export, can_access_settings, restrict_backdated_edit
      role options: ['Standard User', 'Administrator']
      access_mode options: ['Read & Write (can save, edit, delete)', 'Read Only (viewing only — all saves/edits/deletes blocked)']
- FORM POST /edit_user_permissions/1 id=-
    fields: role, access_mode, password, can_view_dashboard, can_manage_grn, can_view_stock, can_view_daily, can_view_history, can_manage_bookings, can_manage_sales, can_manage_payments, can_manage_pending_bills, can_view_delivery_rent, can_view_client_ledger, can_view_supplier_ledger, can_view_decision_ledger, can_view_reports, can_view_cash_flow, can_manage_clients, can_manage_suppliers, can_manage_materials, can_manage_delivery_persons, can_manage_accounts, can_manage_notifications, can_import_export, can_access_settings, restrict_backdated_edit
      role options: ['Standard User', 'Administrator']
      access_mode options: ['Read & Write (can save, edit, delete)', 'Read Only (viewing only — all saves/edits/deletes blocked)']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Save General Settings | Add | Save | Disable | + New User | Update | Download XLSX Backup | Scan Only | Scan + Auto Fix | Wipe Selected | Confirm Wipe | Create Account | Update Permissions | Paid | Schedule callback
- COLUMNS: Name | Status | Actions | User | Role | Permissions | Feature | Admin | When | Action | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row

## /settings/activity  —  Settings - Who did what   [HTTP 200, 143616B]
- FORM GET (self) id=-
    fields: q
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Search | Paid | Schedule callback
- COLUMNS: When | User | Action | Details | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /settings/sessions  —  Settings - sessions   [HTTP 200, 134345B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: User | Role | IP | Signed in | Last seen | Browser | In | Out | Table / setting | Status | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /settings/sidebar  —  Sidebar settings   [HTTP 200, 148246B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Reset to default | Add category | Cancel | Save category | Use defaults | Save option | Paid | Schedule callback
- COLUMNS: Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /import_export/  —  Import / Export   [HTTP 200, 160401B]
- FORM POST /import_export/full_db_import id=-
    fields: file, mode
      mode options: ['Append — keep existing rows (recommended)', 'Overwrite — replace tables supplied by workbook']
- FORM POST /import_export/transfer/export id=-
    fields: sections, modules
- FORM POST /import_export/transfer/import id=-
    fields: sections, file, mode, modules
      mode options: ['Append — keep existing rows (recommended)', 'Overwrite — replace tables supplied by workbook']
- FORM POST /import_export/transfer/export id=-
    fields: sections
- FORM POST /import_export/transfer/import id=-
    fields: sections, file, mode
      mode options: ['Append — keep existing rows (recommended)', 'Overwrite — replace tables supplied by workbook']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Import Full .db Snapshot | Download Selected Modules Backup | Restore Selected Modules | Export Full XLSX (Legacy) | Import Full XLSX | Paid | Schedule callback
- COLUMNS: Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /legacy-migration/  —  Legacy data migration   [HTTP 200, 129803B]
- FORM POST /legacy-migration/upload id=-
    fields: template_type, file
      template_type options: ['1. Clients', '2. Suppliers', '3. Materials', '4. Accounts', '5. Grn', '6. Bookings', '7. Sales', '8. Direct Sales']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Validate upload only | Paid | Schedule callback
- COLUMNS: Run | Template | File | Status | Validated totals | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /data_lab/  —  Data Lab   [HTTP 200, 2259B]
- FORM POST (self) id=-
    fields: index_file, finance_file, dispatch_file
- BUTTONS: Dark | Process

## /admin/  —  Admin dashboard   [HTTP 200, 126473B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: Module | Blueprints | Status | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /admin/modules  —  Admin modules   [HTTP 200, 125896B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: Module Name | Blueprints | Blueprint Count | Status | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /system_report  —  System report   [HTTP 200, 125317B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: Type | Description | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /void_audit  —  Void audit   [HTTP 200, 126395B]
- FORM GET (self) id=-
    fields: section, q
      section options: ['All', 'Deleted Only', 'Suspended Only', 'Transactions', 'Directory']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Apply | Paid | Schedule callback
- COLUMNS: When | Type | Title | Details | Status | Action | Table / setting | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /dashboard  —  dashboard alias   [HTTP 404, 207B]
  (not rendered)

## /dispatching  —  Dispatching   [HTTP 200, 134215B]
- FORM POST /add_record id=-
    fields: type, client, material_id, service_id, material, qty, bill_no, has_bill, create_invoice, track_as_cash, nimbus_no, note, date
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Reset | Confirm | Paid | Schedule callback
- COLUMNS: Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row | Reason | Entry

## /receiving  —  Receiving   [HTTP 404, 207B]
  (not rendered)

## /supplier_ledger/1  —  Supplier ledger   [HTTP 200, 158305B]
- FORM GET (self) id=-
    fields: supplier_search:input, start_date, end_date, type, q, account, status, amount_min, amount_max
      status options: ['All movements', 'Debit / due', 'Credit / paid', 'Zero movement']
- FORM GET /download_supplier_ledger/1 id=supplierLedgerDownloadForm
    fields: scope, start_date, end_date, action
- FORM POST /grn id=-
    fields: action, id
- FORM POST /grn id=-
    fields: action, id
- FORM POST /grn id=-
    fields: action, id
- FORM POST /grn id=-
    fields: action, id
- FORM POST /accounts/payments/suppliers/1/delete id=-
    fields: 
- FORM POST /accounts/payments/suppliers/2/delete id=-
    fields: 
- FORM POST /supplier_opening_balance/1 id=-
    fields: opening_balance, opening_balance_date
- FORM POST (self) id=ledgerRowShiftForm
    fields: target_supplier_id, return_to
      target_supplier_id options: ['-- Select supplier --', 'Kohat Traders']
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Download ledger | Opening balance | Apply | Cancel | Download | Save opening balance | Shift entry | Paid | Schedule callback
- COLUMNS: Date | Type | Reference | Description | Account | Notes | Qty | Rate | Amount | Debit | Credit | Running balance | Actions | Table / setting | Status | In | Upd | Skip

## /delivery_person_ledger/1  —  Delivery person ledger   [HTTP 200, 156686B]
- FORM GET (self) id=-
    fields: driver_search:input, start_date, end_date, type, q, account, status, amount_min, amount_max
      status options: ['All movements', 'Debit / due', 'Credit / paid', 'Zero movement']
- FORM POST /delivery_person_payments/1/void id=-
    fields: 
- FORM POST /delivery_person_payments/2/void id=-
    fields: 
- FORM POST /delivery_person_payments/3/void id=-
    fields: 
- FORM POST /delivery_person_payments/1/edit id=-
    fields: amount_paid, waive_off_amount, method, payment_account_id, date, reference, note, expected_revision
      method options: ['Cash', 'Bank', 'Check', 'Online']
      payment_account_id options: ['Select account…', '[CASH] Main Cash (Rs. 175,500.00)', '[BANK] Meezan Bank (Rs. 483,000.00)']
- FORM POST /delivery_person_payments/2/edit id=-
    fields: amount_paid, waive_off_amount, method, payment_account_id, date, reference, note, expected_revision
      method options: ['Cash', 'Bank', 'Check', 'Online']
      payment_account_id options: ['Select account…', '[CASH] Main Cash (Rs. 175,500.00)', '[BANK] Meezan Bank (Rs. 483,000.00)']
- FORM POST /delivery_person_payments/3/edit id=-
    fields: amount_paid, waive_off_amount, method, payment_account_id, date, reference, note, expected_revision
      method options: ['Cash', 'Bank', 'Check', 'Online']
      payment_account_id options: ['Select account…', '[CASH] Main Cash (Rs. 175,500.00)', '[BANK] Meezan Bank (Rs. 483,000.00)']
- FORM POST /delivery_person_ledger/1/pay id=-
    fields: paid_amount, waive_off_amount, method, payment_account_id, date, reference, note, idempotency_key
      method options: ['Cash', 'Bank', 'Check', 'Online']
      payment_account_id options: ['Select account…', '[CASH] Main Cash (Rs. 175,500.00)', '[BANK] Meezan Bank (Rs. 483,000.00)']
- FORM POST /delivery_person_opening_balance/1 id=-
    fields: opening_balance, opening_balance_date
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Pay driver | Opening balance | Apply | Update payment | Save payment | Save opening balance | Paid | Schedule callback
- COLUMNS: Date | Type | Reference | Description | Account | Notes | Debit | Credit | Running balance | Actions | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table

## /client_ledger/2  —  Client ledger   [HTTP 200, 128603B]
- BUTTONS: Close & reload | Close | Reload | Dark | Inventory | Transactions | Accounts | Ledger | Directory | System | Paid | Schedule callback
- COLUMNS: Material | Net Qty (IN - OUT) | Date | Time | Type | Qty | Bill No | Notes | Photo | Table / setting | Status | In | Upd | Skip | Fail | Note | Sheet / table | Excel row
