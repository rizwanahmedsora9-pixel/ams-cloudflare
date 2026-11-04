# Full-app audit report

- **Run label**: test-run
- **Started**: 2026-11-04T06:58:13.269876+00:00
- **Finished**: 2026-11-04T06:58:17.239409+00:00
- **Duration**: 4.0s
- **Database**: scratch file (never touches production)

## Score

| total | passed | failed | known defects | pass rate |
|---|---|---|---|---|
| 60 | 52 | 8 | 0 | 86.67% |

## App state summary

| table | count |
|---|---|
| supplier | 2 |
| material | 4 |
| material_category | 4 |
| service | 1 |
| client | 2 |
| delivery_person | 1 |
| account | 2 |
| account_transaction | 0 |
| grn | 0 |
| grn_item | 0 |
| direct_sale | 0 |
| direct_sale_item | 0 |
| booking | 0 |
| booking_item | 0 |
| payment | 0 |
| supplier_payment | 0 |
| delivery_rent | 0 |
| client_ledger | None |
| audit_log | 26 |

## Failures (unexpected — must fix)

| id | label | page | got | want |
|---|---|---|---|---|
| V-stock_summary | GET /stock_summary | /stock_summary | 302 | 200 |
| S-01 | DG stock | /materials | 0.0 | 195.0 |
| S-02 | Pioneer stock | /materials | 0.0 | 60.0 |
| S-03 | Sand stock | /materials | 0.0 | 200.0 |
| S-04 | Sheet stock | /materials | 0.0 | 40.0 |
| A-01 | Main Cash balance | /accounts/accounts | 200000.0 | 175500.0 |
| A-02 | Meezan Bank balance | /accounts/accounts | 500000.0 | 483000.0 |
| A-03 | company total | /accounts/ | 700000.0 | 658500.0 |

## Known defects (tracked)

None.

## Every check

| id | result | label | page | observed | expected |
|---|---|---|---|---|---|
| V-home | PASS | GET / | / | 200 | 200 |
| V-accounts | PASS | GET /accounts/ | /accounts/ | 200 | 200 |
| V-accounts/accounts | PASS | GET /accounts/accounts | /accounts/accounts | 200 | 200 |
| V-accounts/payments/clients | PASS | GET /accounts/payments/clients | /accounts/payments/clients | 200 | 200 |
| V-accounts/payments/suppliers | PASS | GET /accounts/payments/suppliers | /accounts/payments/suppliers | 200 | 200 |
| V-accounts/grn_payments | PASS | GET /accounts/grn_payments | /accounts/grn_payments | 200 | 200 |
| V-accounts/receipts | PASS | GET /accounts/receipts | /accounts/receipts | 200 | 200 |
| V-pending_bills | PASS | GET /pending_bills | /pending_bills | 200 | 200 |
| V-decision_ledger | PASS | GET /decision_ledger | /decision_ledger | 200 | 200 |
| V-material_returns | PASS | GET /material_returns | /material_returns | 200 | 200 |
| V-grn | PASS | GET /grn | /grn | 200 | 200 |
| V-bookings | PASS | GET /bookings | /bookings | 200 | 200 |
| V-direct_sales | PASS | GET /direct_sales | /direct_sales | 200 | 200 |
| V-delivery_persons | PASS | GET /delivery_persons | /delivery_persons | 200 | 200 |
| V-delivery_rents | PASS | GET /delivery_rents | /delivery_rents | 200 | 200 |
| V-materials | PASS | GET /materials | /materials | 200 | 200 |
| V-services | PASS | GET /services | /services | 200 | 200 |
| V-client-ledger/categories | PASS | GET /client-ledger/categories | /client-ledger/categories | 200 | 200 |
| V-settings | PASS | GET /settings | /settings | 200 | 200 |
| V-admin | PASS | GET /admin/ | /admin/ | 200 | 200 |
| V-void_audit | PASS | GET /void_audit | /void_audit | 200 | 200 |
| V-notifications | PASS | GET /notifications | /notifications | 200 | 200 |
| V-import_export | PASS | GET /import_export/ | /import_export/ | 200 | 200 |
| V-legacy-migration | PASS | GET /legacy-migration/ | /legacy-migration/ | 200 | 200 |
| V-system_report | PASS | GET /system_report | /system_report | 200 | 200 |
| V-inventory/stock_summary | PASS | GET /inventory/stock_summary | /inventory/stock_summary | 200 | 200 |
| V-tracking | PASS | GET /tracking | /tracking | 200 | 200 |
| V-cash_flow | PASS | GET /cash_flow | /cash_flow | 200 | 200 |
| V-profit_reports | PASS | GET /profit_reports | /profit_reports | 200 | 200 |
| V-cash_flow_differences | PASS | GET /cash_flow_differences | /cash_flow_differences | 200 | 200 |
| V-current_payables | PASS | GET /current_payables | /current_payables | 200 | 200 |
| V-daily_reconciliation | PASS | GET /daily_reconciliation | /daily_reconciliation | 200 | 200 |
| V-stock_summary | FAIL | GET /stock_summary | /stock_summary | 302 | 200 |
| S-01 | FAIL | DG stock | /materials | 0.0 | 195.0 |
| S-02 | FAIL | Pioneer stock | /materials | 0.0 | 60.0 |
| S-03 | FAIL | Sand stock | /materials | 0.0 | 200.0 |
| S-04 | FAIL | Sheet stock | /materials | 0.0 | 40.0 |
| A-01 | FAIL | Main Cash balance | /accounts/accounts | 200000.0 | 175500.0 |
| A-02 | FAIL | Meezan Bank balance | /accounts/accounts | 500000.0 | 483000.0 |
| A-03 | FAIL | company total | /accounts/ | 700000.0 | 658500.0 |
| P-02 | PASS | Total Purchase | /accounts/payments/suppliers | 418500.0 | 418500.0 |
| P-03 | PASS | Outstanding | /accounts/payments/suppliers | 338500.0 | 338500.0 |
| P-04 | PASS | Ravi payable | /accounts/payments/suppliers | 215500.0 | 215500.0 |
| P-05 | PASS | Kohat payable | /accounts/payments/suppliers | 123000.0 | 123000.0 |
| C-02 | PASS | Payable (This Page) | /accounts/payments/clients | 20500.0 | 20500.0 |
| C-03 | PASS | ledger Total Due | /accounts/payments/clients | 46500.0 | 46500.0 |
| C-04 | PASS | ledger Total Paid | /accounts/payments/clients | 26000.0 | 26000.0 |
| C-05 | PASS | ledger Net Balance | /accounts/payments/clients | 20500.0 | 20500.0 |
| R-02 | PASS | rent earned | /delivery_rents | 1400.0 | 1400.0 |
| R-03 | PASS | rent paid | /delivery_rents | 1000.0 | 1000.0 |
| R-04 | PASS | rent remaining | /delivery_rents | 400.0 | 400.0 |
| R-05 | PASS | driver ledger closing | /delivery_rents | 400.0 | 400.0 |
| L-02 | PASS | Sales | /profit_reports | 55000.0 | 55000.0 |
| L-03 | PASS | COGS | /profit_reports | 43400.0 | 43400.0 |
| L-04 | PASS | Profit | /profit_reports | 11600.0 | 11600.0 |
| L-05 | PASS | Money Received | /profit_reports | 34500.0 | 34500.0 |
| W-02 | PASS | opening | /cash_flow | 200000.0 | 200000.0 |
| W-03 | PASS | received | /cash_flow | 39500.0 | 39500.0 |
| W-04 | PASS | spent | /cash_flow | 81000.0 | 81000.0 |
| W-05 | PASS | closing | /cash_flow | 175500.0 | 175500.0 |