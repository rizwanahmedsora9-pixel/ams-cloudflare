# CheckAllApp — Full App Audit Report

- **Run label**: cement-cycle-scenario
- **Started**: 2026-11-04T07:22:33.467036+00:00
- **Finished**: 2026-11-04T07:22:38.926875+00:00
- **Duration**: 5.5s
- **Database**: scratch file (never touches production)

## Scenario Tested

- Received Dg Cement: 300
- Booked Qty: 200
- Cash Sale Qty: 50
- Credit Sale Qty: 50

## Score

| total | passed | failed | known defects | pass rate |
|---|---|---|---|---|
| 211 | 211 | 0 | 0 | 100.0% |

## App State — Record Counts

| table | count |
|---|---|
| supplier | 2 |
| material | 1 |
| material_category | 2 |
| service | 0 |
| client | 2 |
| delivery_person | 1 |
| account | 2 |
| account_transaction | 3 |
| grn | 1 |
| grn_item | 1 |
| direct_sale | 2 |
| direct_sale_item | 2 |
| booking | 1 |
| booking_item | 1 |
| payment | 0 |
| supplier_payment | 0 |
| delivery_rent | 0 |
| client_ledger | None |
| audit_log | 15 |
| entry | 3 |

## Routes Discovered

| GET routes | POST routes |
|---|---|
| 290 | 307 |

## Failures (unexpected — must fix)

None — every figure matches mathematically.

## Known Defects (tracked)

None.

## Inputs Tested

| page | cid | input sent |
|---|---|---|
| /add_supplier | SUP-Ravi | {'name': 'Ravi Cement Supplier', 'phone': '0300-1234567'} |
| /add_supplier | SUP-Kohat | {'name': 'Kohat Traders', 'phone': '0301-7654321'} |
| /material_categories/add | CAT-1 | {'category_name': 'Cement'} |
| /add_material | MAT-1 | {'material_name': 'DG Cement', 'unit': 'Bag', 'code': 'DG'} |
| /add_client | CLI-1 | {'name': 'Bilal Construction', 'code': 'CYC-CL-1'} |
| /delivery_persons/add | DRV-1 | {'name': 'Akram Driver'} |
| /accounts/accounts/add | ACC-Main | {'name': 'Main Cash', 'opening_amount': '200000', 'subcategory': 'Cash', 'type': 'Main Cash', 'channel': 'cash'} |
| /accounts/accounts/add | ACC-Bank | {'name': 'Meezan Bank', 'opening_amount': '500000', 'subcategory': 'Bank', 'type': 'Operating Bank', 'channel': 'bank'} |
| /grn | GRN-1 | {'mat_name[]': 'DG Cement', 'qty[]': '300', 'price[]': '1200'} |
| /add_booking | BK-1 | {'client_code': 'CYC-CL-1', 'material_name[]': 'DG Cement', 'qty[]': '200', 'unit_rate[]': '1500', 'amount': '300000', 'paid_amount': '10000', 'payment_account_id': '1'} |
| /add_direct_sale | SALE-1 | {'category': 'Cash', 'product_name[]': 'DG Cement', 'qty[]': '50', 'unit_rate[]': '1700', 'paid_amount': '85000', 'driver_name': 'Akram Driver'} |
| /add_direct_sale | SALE-2 | {'category': 'Credit Customer', 'product_name[]': 'DG Cement', 'qty[]': '50', 'unit_rate[]': '1650', 'paid_amount': '5000', 'client_code': 'CYC-CL-1', 'driver_name': 'Akram Driver'} |
| / | V-home | {'method': 'GET', 'path': '/'} |
| /login | V-login | {'method': 'GET', 'path': '/login'} |
| /root/recovery | V-root/recovery | {'method': 'GET', 'path': '/root/recovery'} |
| /root/recovery_codes | V-root/recovery_codes | {'method': 'GET', 'path': '/root/recovery_codes'} |
| /logout | V-logout | {'method': 'GET', 'path': '/logout'} |
| /root/backup-settings | V-root/backup-settings | {'method': 'GET', 'path': '/root/backup-settings'} |
| /bookings | V-bookings | {'method': 'GET', 'path': '/bookings'} |
| /payments | V-payments | {'method': 'GET', 'path': '/payments'} |
| /direct_sales | V-direct_sales | {'method': 'GET', 'path': '/direct_sales'} |
| /material_returns | V-material_returns | {'method': 'GET', 'path': '/material_returns'} |
| /pending_bills | V-pending_bills | {'method': 'GET', 'path': '/pending_bills'} |
| /mixed_transactions | V-mixed_transactions | {'method': 'GET', 'path': '/mixed_transactions'} |
| /clients | V-clients | {'method': 'GET', 'path': '/clients'} |
| /client-ledger/categories | V-client-ledger/categories | {'method': 'GET', 'path': '/client-ledger/categories'} |
| /suppliers | V-suppliers | {'method': 'GET', 'path': '/suppliers'} |
| /materials | V-materials | {'method': 'GET', 'path': '/materials'} |
| /delivery_persons | V-delivery_persons | {'method': 'GET', 'path': '/delivery_persons'} |
| /services | V-services | {'method': 'GET', 'path': '/services'} |
| /ledger | V-ledger | {'method': 'GET', 'path': '/ledger'} |
| /decision_ledger | V-decision_ledger | {'method': 'GET', 'path': '/decision_ledger'} |
| /api/delivery_persons/search | V-api/delivery_persons/search | {'method': 'GET', 'path': '/api/delivery_persons/search'} |
| /dispatching | V-dispatching | {'method': 'GET', 'path': '/dispatching'} |
| /tracking | V-tracking | {'method': 'GET', 'path': '/tracking'} |
| /delivery_rents | V-delivery_rents | {'method': 'GET', 'path': '/delivery_rents'} |
| /grn | V-grn | {'method': 'GET', 'path': '/grn'} |
| /current_payables | V-current_payables | {'method': 'GET', 'path': '/current_payables'} |
| /unpaid_transactions | V-unpaid_transactions | {'method': 'GET', 'path': '/unpaid_transactions'} |
| /api/current_payables | V-api/current_payables | {'method': 'GET', 'path': '/api/current_payables'} |
| /export_current_payables | V-export_current_payables | {'method': 'GET', 'path': '/export_current_payables'} |
| /financial_details | V-financial_details | {'method': 'GET', 'path': '/financial_details'} |
| /profit_reports | V-profit_reports | {'method': 'GET', 'path': '/profit_reports'} |
| /profit_reports/export/pdf | V-profit_reports/export/pdf | {'method': 'GET', 'path': '/profit_reports/export/pdf'} |
| /profit_reports/export/excel | V-profit_reports/export/excel | {'method': 'GET', 'path': '/profit_reports/export/excel'} |
| /stock_summary | V-stock_summary | {'method': 'GET', 'path': '/stock_summary'} |
| /daily_transactions | V-daily_transactions | {'method': 'GET', 'path': '/daily_transactions'} |
| /cash_flow/meta/categories | V-cash_flow/meta/categories | {'method': 'GET', 'path': '/cash_flow/meta/categories'} |
| /cash_flow/meta/subcategories | V-cash_flow/meta/subcategories | {'method': 'GET', 'path': '/cash_flow/meta/subcategories'} |
| /cash_flow/meta/parties | V-cash_flow/meta/parties | {'method': 'GET', 'path': '/cash_flow/meta/parties'} |
| /cash_flow | V-cash_flow | {'method': 'GET', 'path': '/cash_flow'} |
| /cash_flow_differences | V-cash_flow_differences | {'method': 'GET', 'path': '/cash_flow_differences'} |
| /daily_reconciliation | V-daily_reconciliation | {'method': 'GET', 'path': '/daily_reconciliation'} |
| /financial_tracker | V-financial_tracker | {'method': 'GET', 'path': '/financial_tracker'} |
| /api/ui/theme | V-api/ui/theme | {'method': 'GET', 'path': '/api/ui/theme'} |
| /api/last_sold_price | V-api/last_sold_price | {'method': 'GET', 'path': '/api/last_sold_price'} |
| /api/material_next_code | V-api/material_next_code | {'method': 'GET', 'path': '/api/material_next_code'} |
| /api/client_next_code | V-api/client_next_code | {'method': 'GET', 'path': '/api/client_next_code'} |
| /api/notifications/due | V-api/notifications/due | {'method': 'GET', 'path': '/api/notifications/due'} |
| /api/ledger_revision | V-api/ledger_revision | {'method': 'GET', 'path': '/api/ledger_revision'} |
| /api/grn_consumption | V-api/grn_consumption | {'method': 'GET', 'path': '/api/grn_consumption'} |
| /api/clients/search | V-api/clients/search | {'method': 'GET', 'path': '/api/clients/search'} |
| /api/suppliers/search | V-api/suppliers/search | {'method': 'GET', 'path': '/api/suppliers/search'} |
| /api/audit/financial-integrity | V-api/audit/financial-integrity | {'method': 'GET', 'path': '/api/audit/financial-integrity'} |
| /debug/db | V-debug/db | {'method': 'GET', 'path': '/debug/db'} |
| /settings | V-settings | {'method': 'GET', 'path': '/settings'} |
| /settings/activity | V-settings/activity | {'method': 'GET', 'path': '/settings/activity'} |
| /settings/sessions | V-settings/sessions | {'method': 'GET', 'path': '/settings/sessions'} |
| /void_audit | V-void_audit | {'method': 'GET', 'path': '/void_audit'} |
| /settings/sidebar | V-settings/sidebar | {'method': 'GET', 'path': '/settings/sidebar'} |
| /notifications | V-notifications | {'method': 'GET', 'path': '/notifications'} |
| /notifications/upcoming | V-notifications/upcoming | {'method': 'GET', 'path': '/notifications/upcoming'} |
| /tenants | V-tenants | {'method': 'GET', 'path': '/tenants'} |
| /export_pending_bills | V-export_pending_bills | {'method': 'GET', 'path': '/export_pending_bills'} |
| /import_pending_bills | V-import_pending_bills | {'method': 'GET', 'path': '/import_pending_bills'} |
| /export_grn | V-export_grn | {'method': 'GET', 'path': '/export_grn'} |
| /export_unpaid_transactions | V-export_unpaid_transactions | {'method': 'GET', 'path': '/export_unpaid_transactions'} |
| /fix_system_issues | V-fix_system_issues | {'method': 'GET', 'path': '/fix_system_issues'} |
| /generate_dummy_data | V-generate_dummy_data | {'method': 'GET', 'path': '/generate_dummy_data'} |
| /system_report | V-system_report | {'method': 'GET', 'path': '/system_report'} |
| /export_clients | V-export_clients | {'method': 'GET', 'path': '/export_clients'} |
| /pay_supplier | V-pay_supplier | {'method': 'GET', 'path': '/pay_supplier'} |
| /legacy-migration/ | V-legacy-migration | {'method': 'GET', 'path': '/legacy-migration/'} |
| / | V-home | {'method': 'GET', 'path': '/'} |
| /login | V-login | {'method': 'GET', 'path': '/login'} |
| /root/recovery | V-root/recovery | {'method': 'GET', 'path': '/root/recovery'} |
| /root/recovery_codes | V-root/recovery_codes | {'method': 'GET', 'path': '/root/recovery_codes'} |
| /logout | V-logout | {'method': 'GET', 'path': '/logout'} |
| /root/backup-settings | V-root/backup-settings | {'method': 'GET', 'path': '/root/backup-settings'} |
| /bookings | V-bookings | {'method': 'GET', 'path': '/bookings'} |
| /payments | V-payments | {'method': 'GET', 'path': '/payments'} |
| /direct_sales | V-direct_sales | {'method': 'GET', 'path': '/direct_sales'} |
| /material_returns | V-material_returns | {'method': 'GET', 'path': '/material_returns'} |
| /pending_bills | V-pending_bills | {'method': 'GET', 'path': '/pending_bills'} |
| /mixed_transactions | V-mixed_transactions | {'method': 'GET', 'path': '/mixed_transactions'} |
| /clients | V-clients | {'method': 'GET', 'path': '/clients'} |
| /client-ledger/categories | V-client-ledger/categories | {'method': 'GET', 'path': '/client-ledger/categories'} |
| /suppliers | V-suppliers | {'method': 'GET', 'path': '/suppliers'} |
| /materials | V-materials | {'method': 'GET', 'path': '/materials'} |
| /delivery_persons | V-delivery_persons | {'method': 'GET', 'path': '/delivery_persons'} |
| /services | V-services | {'method': 'GET', 'path': '/services'} |
| /ledger | V-ledger | {'method': 'GET', 'path': '/ledger'} |
| /decision_ledger | V-decision_ledger | {'method': 'GET', 'path': '/decision_ledger'} |
| /api/delivery_persons/search | V-api/delivery_persons/search | {'method': 'GET', 'path': '/api/delivery_persons/search'} |
| /dispatching | V-dispatching | {'method': 'GET', 'path': '/dispatching'} |
| /tracking | V-tracking | {'method': 'GET', 'path': '/tracking'} |
| /delivery_rents | V-delivery_rents | {'method': 'GET', 'path': '/delivery_rents'} |
| /grn | V-grn | {'method': 'GET', 'path': '/grn'} |
| /current_payables | V-current_payables | {'method': 'GET', 'path': '/current_payables'} |
| /api/current_payables | V-api/current_payables | {'method': 'GET', 'path': '/api/current_payables'} |
| /export_current_payables | V-export_current_payables | {'method': 'GET', 'path': '/export_current_payables'} |
| /financial_details | V-financial_details | {'method': 'GET', 'path': '/financial_details'} |
| /profit_reports | V-profit_reports | {'method': 'GET', 'path': '/profit_reports'} |
| /profit_reports/export/pdf | V-profit_reports/export/pdf | {'method': 'GET', 'path': '/profit_reports/export/pdf'} |
| /profit_reports/export/excel | V-profit_reports/export/excel | {'method': 'GET', 'path': '/profit_reports/export/excel'} |
| /stock_summary | V-stock_summary | {'method': 'GET', 'path': '/stock_summary'} |
| /daily_transactions | V-daily_transactions | {'method': 'GET', 'path': '/daily_transactions'} |
| /cash_flow/meta/categories | V-cash_flow/meta/categories | {'method': 'GET', 'path': '/cash_flow/meta/categories'} |
| /cash_flow/meta/subcategories | V-cash_flow/meta/subcategories | {'method': 'GET', 'path': '/cash_flow/meta/subcategories'} |
| /cash_flow/meta/parties | V-cash_flow/meta/parties | {'method': 'GET', 'path': '/cash_flow/meta/parties'} |
| /cash_flow | V-cash_flow | {'method': 'GET', 'path': '/cash_flow'} |
| /cash_flow_differences | V-cash_flow_differences | {'method': 'GET', 'path': '/cash_flow_differences'} |
| /daily_reconciliation | V-daily_reconciliation | {'method': 'GET', 'path': '/daily_reconciliation'} |
| /financial_tracker | V-financial_tracker | {'method': 'GET', 'path': '/financial_tracker'} |
| /api/ui/theme | V-api/ui/theme | {'method': 'GET', 'path': '/api/ui/theme'} |
| /api/last_sold_price | V-api/last_sold_price | {'method': 'GET', 'path': '/api/last_sold_price'} |
| /api/material_next_code | V-api/material_next_code | {'method': 'GET', 'path': '/api/material_next_code'} |
| /api/client_next_code | V-api/client_next_code | {'method': 'GET', 'path': '/api/client_next_code'} |
| /api/notifications/due | V-api/notifications/due | {'method': 'GET', 'path': '/api/notifications/due'} |
| /api/ledger_revision | V-api/ledger_revision | {'method': 'GET', 'path': '/api/ledger_revision'} |
| /api/grn_consumption | V-api/grn_consumption | {'method': 'GET', 'path': '/api/grn_consumption'} |
| /api/clients/search | V-api/clients/search | {'method': 'GET', 'path': '/api/clients/search'} |
| /api/suppliers/search | V-api/suppliers/search | {'method': 'GET', 'path': '/api/suppliers/search'} |
| /api/audit/financial-integrity | V-api/audit/financial-integrity | {'method': 'GET', 'path': '/api/audit/financial-integrity'} |
| /debug/db | V-debug/db | {'method': 'GET', 'path': '/debug/db'} |
| /settings | V-settings | {'method': 'GET', 'path': '/settings'} |
| /settings/activity | V-settings/activity | {'method': 'GET', 'path': '/settings/activity'} |
| /settings/sessions | V-settings/sessions | {'method': 'GET', 'path': '/settings/sessions'} |
| /void_audit | V-void_audit | {'method': 'GET', 'path': '/void_audit'} |
| /settings/sidebar | V-settings/sidebar | {'method': 'GET', 'path': '/settings/sidebar'} |
| /notifications | V-notifications | {'method': 'GET', 'path': '/notifications'} |
| /notifications/upcoming | V-notifications/upcoming | {'method': 'GET', 'path': '/notifications/upcoming'} |
| /tenants | V-tenants | {'method': 'GET', 'path': '/tenants'} |
| /export_pending_bills | V-export_pending_bills | {'method': 'GET', 'path': '/export_pending_bills'} |
| /import_pending_bills | V-import_pending_bills | {'method': 'GET', 'path': '/import_pending_bills'} |
| /export_grn | V-export_grn | {'method': 'GET', 'path': '/export_grn'} |
| /export_unpaid_transactions | V-export_unpaid_transactions | {'method': 'GET', 'path': '/export_unpaid_transactions'} |
| /fix_system_issues | V-fix_system_issues | {'method': 'GET', 'path': '/fix_system_issues'} |
| /generate_dummy_data | V-generate_dummy_data | {'method': 'GET', 'path': '/generate_dummy_data'} |
| /system_report | V-system_report | {'method': 'GET', 'path': '/system_report'} |
| /export_clients | V-export_clients | {'method': 'GET', 'path': '/export_clients'} |
| /pay_supplier | V-pay_supplier | {'method': 'GET', 'path': '/pay_supplier'} |
| /legacy-migration/ | V-legacy-migration | {'method': 'GET', 'path': '/legacy-migration/'} |
| /accounts/audit | V-accounts/audit | {'method': 'GET', 'path': '/accounts/audit'} |
| /accounts/ | V-accounts | {'method': 'GET', 'path': '/accounts/'} |
| /accounts/payments/clients | V-accounts/payments/clients | {'method': 'GET', 'path': '/accounts/payments/clients'} |
| /accounts/payments/suppliers | V-accounts/payments/suppliers | {'method': 'GET', 'path': '/accounts/payments/suppliers'} |
| /accounts/expenditures | V-accounts/expenditures | {'method': 'GET', 'path': '/accounts/expenditures'} |
| /accounts/receipts | V-accounts/receipts | {'method': 'GET', 'path': '/accounts/receipts'} |
| /accounts/grn_payments | V-accounts/grn_payments | {'method': 'GET', 'path': '/accounts/grn_payments'} |
| /accounts/purchase_payables | V-accounts/purchase_payables | {'method': 'GET', 'path': '/accounts/purchase_payables'} |
| /accounts/accounts | V-accounts/accounts | {'method': 'GET', 'path': '/accounts/accounts'} |
| /accounts/accounts/add | V-accounts/accounts/add | {'method': 'GET', 'path': '/accounts/accounts/add'} |
| /accounts/reconciliations | V-accounts/reconciliations | {'method': 'GET', 'path': '/accounts/reconciliations'} |
| /accounts/categories | V-accounts/categories | {'method': 'GET', 'path': '/accounts/categories'} |
| /accounts/transfers | V-accounts/transfers | {'method': 'GET', 'path': '/accounts/transfers'} |
| /accounts/transfers/add | V-accounts/transfers/add | {'method': 'GET', 'path': '/accounts/transfers/add'} |
| /accounts/api/kpi/client_payments | V-accounts/api/kpi/client_payments | {'method': 'GET', 'path': '/accounts/api/kpi/client_payments'} |
| /accounts/api/kpi/supplier_payments | V-accounts/api/kpi/supplier_payments | {'method': 'GET', 'path': '/accounts/api/kpi/supplier_payments'} |
| /accounts/api/kpi/expenditures | V-accounts/api/kpi/expenditures | {'method': 'GET', 'path': '/accounts/api/kpi/expenditures'} |
| /accounts/api/kpi/receipts | V-accounts/api/kpi/receipts | {'method': 'GET', 'path': '/accounts/api/kpi/receipts'} |
| /accounts/api/kpi/company_money | V-accounts/api/kpi/company_money | {'method': 'GET', 'path': '/accounts/api/kpi/company_money'} |
| /accounts/kpi/client_payments | V-accounts/kpi/client_payments | {'method': 'GET', 'path': '/accounts/kpi/client_payments'} |
| /accounts/kpi/supplier_payments | V-accounts/kpi/supplier_payments | {'method': 'GET', 'path': '/accounts/kpi/supplier_payments'} |
| /accounts/kpi/expenditures | V-accounts/kpi/expenditures | {'method': 'GET', 'path': '/accounts/kpi/expenditures'} |
| /accounts/kpi/receipts | V-accounts/kpi/receipts | {'method': 'GET', 'path': '/accounts/kpi/receipts'} |
| /accounts/kpi/company_money | V-accounts/kpi/company_money | {'method': 'GET', 'path': '/accounts/kpi/company_money'} |
| /accounts/kpi/cash_money | V-accounts/kpi/cash_money | {'method': 'GET', 'path': '/accounts/kpi/cash_money'} |
| /accounts/kpi/cash_accounts | V-accounts/kpi/cash_accounts | {'method': 'GET', 'path': '/accounts/kpi/cash_accounts'} |
| /accounts/kpi/bank_accounts | V-accounts/kpi/bank_accounts | {'method': 'GET', 'path': '/accounts/kpi/bank_accounts'} |
| /admin/ | V-admin | {'method': 'GET', 'path': '/admin/'} |
| /admin/modules | V-admin/modules | {'method': 'GET', 'path': '/admin/modules'} |
| /admin/api/modules | V-admin/api/modules | {'method': 'GET', 'path': '/admin/api/modules'} |
| /admin/api/health | V-admin/api/health | {'method': 'GET', 'path': '/admin/api/health'} |
| /data_lab/ | V-data_lab | {'method': 'GET', 'path': '/data_lab/'} |
| /data_lab/basket | V-data_lab/basket | {'method': 'GET', 'path': '/data_lab/basket'} |
| /import_export/ | V-import_export | {'method': 'GET', 'path': '/import_export/'} |
| /import_export/full_raw_export | V-import_export/full_raw_export | {'method': 'GET', 'path': '/import_export/full_raw_export'} |
| /import_export/tenant_db_export | V-import_export/tenant_db_export | {'method': 'GET', 'path': '/import_export/tenant_db_export'} |
| /import_export/full_raw_import_history | V-import_export/full_raw_import_history | {'method': 'GET', 'path': '/import_export/full_raw_import_history'} |
| /import_export/app_upgrade | V-import_export/app_upgrade | {'method': 'GET', 'path': '/import_export/app_upgrade'} |
| /import_export/export | V-import_export/export | {'method': 'GET', 'path': '/import_export/export'} |
| /import_export/full_db_export | V-import_export/full_db_export | {'method': 'GET', 'path': '/import_export/full_db_export'} |
| /import_export/export_excel_all | V-import_export/export_excel_all | {'method': 'GET', 'path': '/import_export/export_excel_all'} |
| /import_export/master/export | V-import_export/master/export | {'method': 'GET', 'path': '/import_export/master/export'} |
| /import_export/full_raw_import_history_export | V-import_export/full_raw_import_history_export | {'method': 'GET', 'path': '/import_export/full_raw_import_history_export'} |
| /inventory/stock_summary | V-inventory/stock_summary | {'method': 'GET', 'path': '/inventory/stock_summary'} |
| /inventory/daily_transactions | V-inventory/daily_transactions | {'method': 'GET', 'path': '/inventory/daily_transactions'} |
| /inventory/inventory_log | V-inventory/inventory_log | {'method': 'GET', 'path': '/inventory/inventory_log'} |
| /import_export/uploads | V-import_export/uploads | {'method': 'GET', 'path': '/import_export/uploads'} |
| /import_export/history | V-import_export/history | {'method': 'GET', 'path': '/import_export/history'} |
| /materials | STK-1 | {'received': 300, 'cash_sale': 50, 'credit_sale': 50} |
| /grn | GRN-CNT | {'action': 'add', 'mat_name[]': 'DG Cement', 'qty[]': '300'} |
| /grn | GRN-ITEM-CNT | {'mat_name[]': 'DG Cement', 'qty[]': '300'} |
| /bookings | BK-CNT | {'client_code': 'CYC-CL-1', 'material_name[]': 'DG Cement', 'qty[]': '200'} |
| /bookings | BK-ITEM-CNT | {'qty[]': '200'} |
| /direct_sales | SALE-CNT | {'cash_sale_qty': 50, 'credit_sale_qty': 50} |
| /accounts/accounts | ACC-1 | {'opening': 200000, 'booking_paid': 10000, 'cash_sale_paid': 85000, 'credit_part_paid': 5000} |
| /accounts/accounts | ACC-2 | {'opening': 500000} |
| /accounts/ | ACC-3 | {'cash': 300000, 'bank': 500000} |
| /inventory/stock_summary | ENTRY-CNT | {'grn_received': 300} |

## Outputs Observed

| page | cid | output received |
|---|---|---|
| /add_supplier | SUP-Ravi | success: Supplier Added — by Admin |
| /add_supplier | SUP-Kohat | success: Supplier Added — by Admin |
| /material_categories/add | CAT-1 | success: Category added — by Admin |
| /add_material | MAT-1 | success: Brand Added — by Admin |
| /add_client | CLI-1 | success: Client Registered — by Admin |
| /delivery_persons/add | DRV-1 | success: Delivery person saved — by Admin |
| /accounts/accounts/add | ACC-Main | success: Account added successfully! — by Admin |
| /accounts/accounts/add | ACC-Bank | success: Account added successfully! — by Admin |
| /grn | GRN-1 | success: GRN added successfully! — by Admin |
| /add_booking | BK-1 | success: Booking added successfully (Bill: MB NO.BK-SCENARIO-001) â€” Pending amount: 290000.0 — by Admin |
| /add_direct_sale | SALE-1 | success: Direct sale added successfully — by Admin |
| /add_direct_sale | SALE-2 | success: Direct sale added successfully — by Admin |
| / | V-home | HTTP 200 (1649 chars) |
| /login | V-login | HTTP 302 (115 chars) |
| /root/recovery | V-root/recovery | HTTP 404 (144 chars) |
| /root/recovery_codes | V-root/recovery_codes | HTTP 404 (144 chars) |
| /logout | V-logout | HTTP 302 (120 chars) |
| /root/backup-settings | V-root/backup-settings | HTTP 302 (151 chars) |
| /bookings | V-bookings | HTTP 302 (137 chars) |
| /payments | V-payments | HTTP 302 (137 chars) |
| /direct_sales | V-direct_sales | HTTP 302 (141 chars) |
| /material_returns | V-material_returns | HTTP 302 (145 chars) |
| /pending_bills | V-pending_bills | HTTP 302 (142 chars) |
| /mixed_transactions | V-mixed_transactions | HTTP 302 (147 chars) |
| /clients | V-clients | HTTP 302 (136 chars) |
| /client-ledger/categories | V-client-ledger/categories | HTTP 302 (155 chars) |
| /suppliers | V-suppliers | HTTP 302 (138 chars) |
| /materials | V-materials | HTTP 302 (138 chars) |
| /delivery_persons | V-delivery_persons | HTTP 302 (145 chars) |
| /services | V-services | HTTP 302 (137 chars) |
| /ledger | V-ledger | HTTP 302 (135 chars) |
| /decision_ledger | V-decision_ledger | HTTP 302 (144 chars) |
| /api/delivery_persons/search | V-api/delivery_persons/search | HTTP 302 (160 chars) |
| /dispatching | V-dispatching | HTTP 302 (140 chars) |
| /tracking | V-tracking | HTTP 302 (137 chars) |
| /delivery_rents | V-delivery_rents | HTTP 302 (143 chars) |
| /grn | V-grn | HTTP 302 (132 chars) |
| /current_payables | V-current_payables | HTTP 302 (145 chars) |
| /unpaid_transactions | V-unpaid_transactions | HTTP 302 (148 chars) |
| /api/current_payables | V-api/current_payables | HTTP 302 (151 chars) |
| /export_current_payables | V-export_current_payables | HTTP 302 (152 chars) |
| /financial_details | V-financial_details | HTTP 302 (146 chars) |
| /profit_reports | V-profit_reports | HTTP 302 (143 chars) |
| /profit_reports/export/pdf | V-profit_reports/export/pdf | HTTP 302 (158 chars) |
| /profit_reports/export/excel | V-profit_reports/export/excel | HTTP 302 (160 chars) |
| /stock_summary | V-stock_summary | HTTP 302 (142 chars) |
| /daily_transactions | V-daily_transactions | HTTP 302 (147 chars) |
| /cash_flow/meta/categories | V-cash_flow/meta/categories | HTTP 302 (158 chars) |
| /cash_flow/meta/subcategories | V-cash_flow/meta/subcategories | HTTP 302 (161 chars) |
| /cash_flow/meta/parties | V-cash_flow/meta/parties | HTTP 302 (155 chars) |
| /cash_flow | V-cash_flow | HTTP 302 (138 chars) |
| /cash_flow_differences | V-cash_flow_differences | HTTP 302 (150 chars) |
| /daily_reconciliation | V-daily_reconciliation | HTTP 302 (149 chars) |
| /financial_tracker | V-financial_tracker | HTTP 302 (146 chars) |
| /api/ui/theme | V-api/ui/theme | HTTP 200 (14 chars) |
| /api/last_sold_price | V-api/last_sold_price | HTTP 302 (150 chars) |
| /api/material_next_code | V-api/material_next_code | HTTP 302 (153 chars) |
| /api/client_next_code | V-api/client_next_code | HTTP 302 (151 chars) |
| /api/notifications/due | V-api/notifications/due | HTTP 302 (154 chars) |
| /api/ledger_revision | V-api/ledger_revision | HTTP 302 (150 chars) |
| /api/grn_consumption | V-api/grn_consumption | HTTP 302 (150 chars) |
| /api/clients/search | V-api/clients/search | HTTP 302 (151 chars) |
| /api/suppliers/search | V-api/suppliers/search | HTTP 302 (153 chars) |
| /api/audit/financial-integrity | V-api/audit/financial-integrity | HTTP 302 (162 chars) |
| /debug/db | V-debug/db | HTTP 302 (139 chars) |
| /settings | V-settings | HTTP 302 (137 chars) |
| /settings/activity | V-settings/activity | HTTP 302 (148 chars) |
| /settings/sessions | V-settings/sessions | HTTP 302 (148 chars) |
| /void_audit | V-void_audit | HTTP 302 (139 chars) |
| /settings/sidebar | V-settings/sidebar | HTTP 302 (147 chars) |
| /notifications | V-notifications | HTTP 302 (142 chars) |
| /notifications/upcoming | V-notifications/upcoming | HTTP 302 (153 chars) |
| /tenants | V-tenants | HTTP 302 (136 chars) |
| /export_pending_bills | V-export_pending_bills | HTTP 302 (149 chars) |
| /import_pending_bills | V-import_pending_bills | HTTP 302 (149 chars) |
| /export_grn | V-export_grn | HTTP 302 (139 chars) |
| /export_unpaid_transactions | V-export_unpaid_transactions | HTTP 302 (155 chars) |
| /fix_system_issues | V-fix_system_issues | HTTP 302 (146 chars) |
| /generate_dummy_data | V-generate_dummy_data | HTTP 302 (148 chars) |
| /system_report | V-system_report | HTTP 302 (142 chars) |
| /export_clients | V-export_clients | HTTP 302 (143 chars) |
| /pay_supplier | V-pay_supplier | HTTP 302 (141 chars) |
| /legacy-migration/ | V-legacy-migration | HTTP 302 (148 chars) |
| / | V-home | HTTP 302 (129 chars) |
| /login | V-login | HTTP 200 (2484 chars) |
| /root/recovery | V-root/recovery | HTTP 404 (144 chars) |
| /root/recovery_codes | V-root/recovery_codes | HTTP 302 (150 chars) |
| /logout | V-logout | HTTP 302 (135 chars) |
| /root/backup-settings | V-root/backup-settings | HTTP 302 (151 chars) |
| /bookings | V-bookings | HTTP 302 (137 chars) |
| /payments | V-payments | HTTP 302 (137 chars) |
| /direct_sales | V-direct_sales | HTTP 302 (141 chars) |
| /material_returns | V-material_returns | HTTP 302 (145 chars) |
| /pending_bills | V-pending_bills | HTTP 302 (142 chars) |
| /mixed_transactions | V-mixed_transactions | HTTP 302 (147 chars) |
| /clients | V-clients | HTTP 302 (136 chars) |
| /client-ledger/categories | V-client-ledger/categories | HTTP 302 (155 chars) |
| /suppliers | V-suppliers | HTTP 302 (138 chars) |
| /materials | V-materials | HTTP 302 (138 chars) |
| /delivery_persons | V-delivery_persons | HTTP 302 (145 chars) |
| /services | V-services | HTTP 302 (137 chars) |
| /ledger | V-ledger | HTTP 302 (135 chars) |
| /decision_ledger | V-decision_ledger | HTTP 302 (144 chars) |
| /api/delivery_persons/search | V-api/delivery_persons/search | HTTP 302 (160 chars) |
| /dispatching | V-dispatching | HTTP 302 (140 chars) |
| /tracking | V-tracking | HTTP 302 (137 chars) |
| /delivery_rents | V-delivery_rents | HTTP 302 (143 chars) |
| /grn | V-grn | HTTP 302 (132 chars) |
| /current_payables | V-current_payables | HTTP 302 (145 chars) |
| /api/current_payables | V-api/current_payables | HTTP 302 (151 chars) |
| /export_current_payables | V-export_current_payables | HTTP 302 (152 chars) |
| /financial_details | V-financial_details | HTTP 302 (146 chars) |
| /profit_reports | V-profit_reports | HTTP 302 (143 chars) |
| /profit_reports/export/pdf | V-profit_reports/export/pdf | HTTP 302 (158 chars) |
| /profit_reports/export/excel | V-profit_reports/export/excel | HTTP 302 (160 chars) |
| /stock_summary | V-stock_summary | HTTP 302 (142 chars) |
| /daily_transactions | V-daily_transactions | HTTP 302 (147 chars) |
| /cash_flow/meta/categories | V-cash_flow/meta/categories | HTTP 302 (158 chars) |
| /cash_flow/meta/subcategories | V-cash_flow/meta/subcategories | HTTP 302 (161 chars) |
| /cash_flow/meta/parties | V-cash_flow/meta/parties | HTTP 302 (155 chars) |
| /cash_flow | V-cash_flow | HTTP 302 (138 chars) |
| /cash_flow_differences | V-cash_flow_differences | HTTP 302 (150 chars) |
| /daily_reconciliation | V-daily_reconciliation | HTTP 302 (149 chars) |
| /financial_tracker | V-financial_tracker | HTTP 302 (146 chars) |
| /api/ui/theme | V-api/ui/theme | HTTP 200 (14 chars) |
| /api/last_sold_price | V-api/last_sold_price | HTTP 302 (150 chars) |
| /api/material_next_code | V-api/material_next_code | HTTP 302 (153 chars) |
| /api/client_next_code | V-api/client_next_code | HTTP 302 (151 chars) |
| /api/notifications/due | V-api/notifications/due | HTTP 302 (154 chars) |
| /api/ledger_revision | V-api/ledger_revision | HTTP 302 (150 chars) |
| /api/grn_consumption | V-api/grn_consumption | HTTP 302 (150 chars) |
| /api/clients/search | V-api/clients/search | HTTP 302 (151 chars) |
| /api/suppliers/search | V-api/suppliers/search | HTTP 302 (153 chars) |
| /api/audit/financial-integrity | V-api/audit/financial-integrity | HTTP 302 (162 chars) |
| /debug/db | V-debug/db | HTTP 302 (139 chars) |
| /settings | V-settings | HTTP 302 (137 chars) |
| /settings/activity | V-settings/activity | HTTP 302 (148 chars) |
| /settings/sessions | V-settings/sessions | HTTP 302 (148 chars) |
| /void_audit | V-void_audit | HTTP 302 (139 chars) |
| /settings/sidebar | V-settings/sidebar | HTTP 302 (147 chars) |
| /notifications | V-notifications | HTTP 302 (142 chars) |
| /notifications/upcoming | V-notifications/upcoming | HTTP 302 (153 chars) |
| /tenants | V-tenants | HTTP 302 (136 chars) |
| /export_pending_bills | V-export_pending_bills | HTTP 302 (149 chars) |
| /import_pending_bills | V-import_pending_bills | HTTP 302 (149 chars) |
| /export_grn | V-export_grn | HTTP 302 (139 chars) |
| /export_unpaid_transactions | V-export_unpaid_transactions | HTTP 302 (155 chars) |
| /fix_system_issues | V-fix_system_issues | HTTP 302 (146 chars) |
| /generate_dummy_data | V-generate_dummy_data | HTTP 302 (148 chars) |
| /system_report | V-system_report | HTTP 302 (142 chars) |
| /export_clients | V-export_clients | HTTP 302 (143 chars) |
| /pay_supplier | V-pay_supplier | HTTP 302 (141 chars) |
| /legacy-migration/ | V-legacy-migration | HTTP 302 (148 chars) |
| /accounts/audit | V-accounts/audit | HTTP 302 (145 chars) |
| /accounts/ | V-accounts | HTTP 302 (140 chars) |
| /accounts/payments/clients | V-accounts/payments/clients | HTTP 302 (158 chars) |
| /accounts/payments/suppliers | V-accounts/payments/suppliers | HTTP 302 (160 chars) |
| /accounts/expenditures | V-accounts/expenditures | HTTP 302 (152 chars) |
| /accounts/receipts | V-accounts/receipts | HTTP 302 (148 chars) |
| /accounts/grn_payments | V-accounts/grn_payments | HTTP 302 (152 chars) |
| /accounts/purchase_payables | V-accounts/purchase_payables | HTTP 302 (157 chars) |
| /accounts/accounts | V-accounts/accounts | HTTP 302 (148 chars) |
| /accounts/accounts/add | V-accounts/accounts/add | HTTP 302 (154 chars) |
| /accounts/reconciliations | V-accounts/reconciliations | HTTP 302 (155 chars) |
| /accounts/categories | V-accounts/categories | HTTP 302 (150 chars) |
| /accounts/transfers | V-accounts/transfers | HTTP 302 (149 chars) |
| /accounts/transfers/add | V-accounts/transfers/add | HTTP 302 (155 chars) |
| /accounts/api/kpi/client_payments | V-accounts/api/kpi/client_payments | HTTP 302 (167 chars) |
| /accounts/api/kpi/supplier_payments | V-accounts/api/kpi/supplier_payments | HTTP 302 (169 chars) |
| /accounts/api/kpi/expenditures | V-accounts/api/kpi/expenditures | HTTP 302 (164 chars) |
| /accounts/api/kpi/receipts | V-accounts/api/kpi/receipts | HTTP 302 (160 chars) |
| /accounts/api/kpi/company_money | V-accounts/api/kpi/company_money | HTTP 302 (165 chars) |
| /accounts/kpi/client_payments | V-accounts/kpi/client_payments | HTTP 302 (161 chars) |
| /accounts/kpi/supplier_payments | V-accounts/kpi/supplier_payments | HTTP 302 (163 chars) |
| /accounts/kpi/expenditures | V-accounts/kpi/expenditures | HTTP 302 (158 chars) |
| /accounts/kpi/receipts | V-accounts/kpi/receipts | HTTP 302 (154 chars) |
| /accounts/kpi/company_money | V-accounts/kpi/company_money | HTTP 302 (159 chars) |
| /accounts/kpi/cash_money | V-accounts/kpi/cash_money | HTTP 302 (156 chars) |
| /accounts/kpi/cash_accounts | V-accounts/kpi/cash_accounts | HTTP 302 (159 chars) |
| /accounts/kpi/bank_accounts | V-accounts/kpi/bank_accounts | HTTP 302 (159 chars) |
| /admin/ | V-admin | HTTP 403 (150 chars) |
| /admin/modules | V-admin/modules | HTTP 403 (150 chars) |
| /admin/api/modules | V-admin/api/modules | HTTP 403 (150 chars) |
| /admin/api/health | V-admin/api/health | HTTP 403 (150 chars) |
| /data_lab/ | V-data_lab | HTTP 302 (140 chars) |
| /data_lab/basket | V-data_lab/basket | HTTP 302 (146 chars) |
| /import_export/ | V-import_export | HTTP 302 (145 chars) |
| /import_export/full_raw_export | V-import_export/full_raw_export | HTTP 302 (160 chars) |
| /import_export/tenant_db_export | V-import_export/tenant_db_export | HTTP 302 (161 chars) |
| /import_export/full_raw_import_history | V-import_export/full_raw_import_history | HTTP 302 (168 chars) |
| /import_export/app_upgrade | V-import_export/app_upgrade | HTTP 302 (156 chars) |
| /import_export/export | V-import_export/export | HTTP 302 (151 chars) |
| /import_export/full_db_export | V-import_export/full_db_export | HTTP 302 (159 chars) |
| /import_export/export_excel_all | V-import_export/export_excel_all | HTTP 302 (161 chars) |
| /import_export/master/export | V-import_export/master/export | HTTP 302 (160 chars) |
| /import_export/full_raw_import_history_export | V-import_export/full_raw_import_history_export | HTTP 302 (175 chars) |
| /inventory/stock_summary | V-inventory/stock_summary | HTTP 302 (154 chars) |
| /inventory/daily_transactions | V-inventory/daily_transactions | HTTP 302 (159 chars) |
| /inventory/inventory_log | V-inventory/inventory_log | HTTP 302 (154 chars) |
| /import_export/uploads | V-import_export/uploads | HTTP 302 (152 chars) |
| /import_export/history | V-import_export/history | HTTP 302 (152 chars) |
| /materials | STK-1 | stock_dg=200.0 |
| /grn | GRN-CNT | grn_count=1 |
| /grn | GRN-ITEM-CNT | grn_item_count=1 |
| /bookings | BK-CNT | booking_count=1 |
| /bookings | BK-ITEM-CNT | booking_item_count=1 |
| /direct_sales | SALE-CNT | direct_sale_count=2 |
| /accounts/accounts | ACC-1 | balance=300000.0 |
| /accounts/accounts | ACC-2 | balance=500000.0 |
| /accounts/ | ACC-3 | total=800000.0 |
| /inventory/stock_summary | ENTRY-CNT | entry_count=3 |