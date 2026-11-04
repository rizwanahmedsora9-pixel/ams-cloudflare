# Full-cycle run — real-app-walkthrough

| | |
|---|---|
| Run dir | `run-007-20261104T0636` |
| Started | 2026-11-04T06:36:38.555401+00:00 |
| Duration | 15.5 s |
| Commit | `e8cdde0` on `arena/9a9e9b43-git-recovered` |
| Python | 3.11.2 |
| Checks | **82 / 86 passed** (95.35%) |
| Known defects | 4 |
| Unexpected failures | 0 |

## Seed steps

31 of 31 write paths produced the expected flash.

## Unexpected failures

None.

## Known defects still reproducing

| ID | Known | Check |
|---|---|---|
| L-07 | KF-007 | markup_pct is computed but never rendered (known gap) |
| W-06 | KF-008 | reconciliation difference 17,000 |
| W-07 | KF-005 | record-movement form present in markup |
| M-01 | KF-008 | phase-2 write flows reachable from seed.seed() |

## Every check

| ID | Result | Check | Observed | Expected |
|---|---|---|---|---|
| V-/ | PASS | GET / | `200` | `(200, 302)` |
| V-/accounts/ | PASS | GET /accounts/ | `200` | `(200,)` |
| V-/accounts/accounts | PASS | GET /accounts/accounts | `200` | `(200,)` |
| V-/accounts/payments/clients | PASS | GET /accounts/payments/clients | `200` | `(200,)` |
| V-/accounts/payments/suppliers | PASS | GET /accounts/payments/suppliers | `200` | `(200,)` |
| V-/accounts/grn_payments | PASS | GET /accounts/grn_payments | `200` | `(200,)` |
| V-/pending_bills | PASS | GET /pending_bills | `200` | `(200,)` |
| V-/decision_ledger | PASS | GET /decision_ledger | `200` | `(200,)` |
| V-/material_returns | PASS | GET /material_returns | `200` | `(200,)` |
| V-/grn | PASS | GET /grn | `200` | `(200,)` |
| V-/bookings | PASS | GET /bookings | `200` | `(200,)` |
| V-/direct_sales | PASS | GET /direct_sales | `200` | `(200,)` |
| V-/delivery_persons | PASS | GET /delivery_persons | `200` | `(200,)` |
| V-/materials | PASS | GET /materials | `200` | `(200,)` |
| V-/services | PASS | GET /services | `200` | `(200,)` |
| V-/client-ledger/categories | PASS | GET /client-ledger/categories | `200` | `(200,)` |
| V-/settings | PASS | GET /settings | `200` | `(200,)` |
| V-/admin/ | PASS | GET /admin/ | `200` | `(200,)` |
| V-/void_audit | PASS | GET /void_audit | `200` | `(200,)` |
| V-/notifications | PASS | GET /notifications | `200` | `(200,)` |
| V-/import_export/ | PASS | GET /import_export/ | `200` | `(200,)` |
| V-/legacy-migration/ | PASS | GET /legacy-migration/ | `200` | `(200,)` |
| V-/system_report | PASS | GET /system_report | `200` | `(200,)` |
| S-01 | PASS | DG stock | `195.0` | `195.0` |
| S-02 | PASS | Pioneer stock | `60.0` | `60.0` |
| S-03 | PASS | Sand stock | `200.0` | `200.0` |
| S-04 | PASS | Sheet stock (rent-word trap) | `40.0` | `40.0` |
| S-05 | PASS | stock_summary renders | `200` | `200` |
| S-06 | PASS | Total Received 530 | `see text` | `530.0` |
| S-07 | PASS | Total Delivered 35 | `see text` | `35.0` |
| S-08 | PASS | Net Movement 495 | `see text` | `495.0` |
| S-09 | PASS | tracking TOTAL BAGS 495 | `see text` | `495.0` |
| C-01 | PASS | clients page renders | `200` | `200` |
| C-02 | PASS | Payable (This Page) 20,500 | `see text` | `20500.0` |
| C-03 | PASS | ledger Total Due 46,500 | `see text` | `46500.0` |
| C-04 | PASS | ledger Total Paid 26,000 | `see text` | `26000.0` |
| C-05 | PASS | ledger Net Balance 20,500 | `see text` | `20500.0` |
| P-01 | PASS | suppliers page renders | `200` | `200` |
| P-02 | PASS | Total Purchase 418,500 | `see text` | `418500` |
| P-03 | PASS | Outstanding 338,500 | `see text` | `338500.0` |
| P-04 | PASS | Ravi payable 215,500 | `see text` | `215500.0` |
| P-05 | PASS | payables Kohat 123,000 | `see text` | `123000` |
| A-01 | PASS | Main Cash balance | `175500.0` | `175500.0` |
| A-02 | PASS | Meezan Bank balance | `483000.0` | `483000.0` |
| A-03 | PASS | company total | `658500.0` | `658500.0` |
| A-04 | PASS | accounts dashboard renders | `200` | `200` |
| A-05 | PASS | company KPI 658,500 | `see text` | `658500.0` |
| A-06 | PASS | daily recon expected 658,500 | `see text` | `658500.0` |
| A-07 | PASS | account transactions = 11 | `11` | `11` |
| R-01 | PASS | rent page renders | `200` | `200` |
| R-02 | PASS | rent earned 1,400 | `see text` | `1400.0` |
| R-03 | PASS | rent paid 1,000 | `see text` | `1000.0` |
| R-04 | PASS | rent remaining 400 | `see text` | `400.0` |
| R-05 | PASS | driver ledger closing 400 | `see text` | `400.0` |
| L-01 | PASS | P&L renders | `200` | `200` |
| L-02 | PASS | Sales 55,000 | `see text` | `55000.0` |
| L-03 | PASS | COGS 43,400 | `see text` | `43400.0` |
| L-04 | PASS | Profit 11,600 | `see text` | `11600.0` |
| L-05 | PASS | Money Received 34,500 | `see text` | `34500.0` |
| L-06 | PASS | margin 21.09% | `True` | `True` |
| L-07 | KNOWN | markup_pct is computed but never rendered (known gap) | `False` | `True` |
| F-01 | PASS | cash detail TOTAL 34,500 | `see text` | `34500.0` |
| F-02 | PASS | credit detail TOTAL 31,500 | `see text` | `31500.0` |
| F-03 | PASS | unknown type renders empty TOTAL 0 (known defect) | `True` | `False` |
| W-01 | PASS | cash flow renders | `200` | `200` |
| W-02 | PASS | opening 200,000 | `see text` | `200000.0` |
| W-03 | PASS | received 39,500 | `see text` | `39500.0` |
| W-04 | PASS | spent 81,000 | `see text` | `81000.0` |
| W-05 | PASS | closing 158,500 (cash-only opening vs all-account movement) | `see text` | `158500.0` |
| W-06 | KNOWN | reconciliation difference 17,000 | `None` | `17000.0` |
| W-07 | KNOWN | record-movement form present in markup | `False` | `True` |
| D-01 | PASS | PDF /profit_reports/export/pdf (57042B) ok | `200 57042B ok` | `200 >1kB Profit & Loss ['55,000', '11,600']` |
| D-02 | PASS | PDF /download_client_ledger/2 (46724B) ok | `200 46724B ok` | `200 >1kB Total Due ['46,500', '20,500']` |
| D-03 | PASS | PDF /download_supplier_ledger/1 (5151B) ok | `200 5151B ok` | `200 >1kB SUPPLIER LEDGER ['215,500']` |
| D-04 | PASS | PDF /download_invoice/SB-SL-1000 (44571B) ok | `200 44571B ok` | `200 >1kB INVOICE ['8,500']` |
| D-05 | PASS | PDF /download_client_clearance/2 (46240B) ok | `200 46240B ok` | `200 >1kB Outstanding ['20,500']` |
| Q-01 | PASS | receipts page renders | `200` | `200` |
| Q-02 | PASS | GRN Paid is 0 despite a 60,000 GRN payment (known defect) | `see text` | `0.0` |
| Y-01 | PASS | system report renders | `200` | `200` |
| Y-02 | PASS | missing pending bill for zero-amount delivery (known defect) | `True` | `False` |
| Y-03 | PASS | stock KPI/body disagree (known defect) | `see text` | `True` |
| X-/dashboard | PASS | /dashboard is 404 (documented dead link) | `404` | `404` |
| X-/journal | PASS | /journal is 404 (documented dead link) | `404` | `404` |
| X-/call_center | PASS | /call_center is 404 (documented dead link) | `404` | `404` |
| X-/inventory/history | PASS | /inventory/history is 404 (documented dead link) | `404` | `404` |
| M-01 | KNOWN | phase-2 write flows reachable from seed.seed() | `phase-2 stages run: 0` | `5` |

## Table counts after the run

```json
{
 "account": 2,
 "account_category": 5,
 "account_reconciliation": 0,
 "account_transaction": 11,
 "accounting_audit_log": 9,
 "audit_log": 34,
 "bill_counter": 14,
 "booking": 1,
 "booking_allocation": 1,
 "booking_allocation_repair_archive": 0,
 "booking_item": 1,
 "cash_day_account_position": 0,
 "cash_day_lock": 0,
 "cash_day_shift_close": 0,
 "cash_day_shift_close_position": 0,
 "cash_flow_category": 1,
 "cash_flow_difference_adjustment": 0,
 "cash_flow_entry": 1,
 "cash_flow_entry_audit": 1,
 "cash_flow_party": 0,
 "cash_flow_reconciliation_audit": 0,
 "cash_flow_subcategory": 0,
 "client": 2,
 "client_category": 2,
 "delivery": 0,
 "delivery_item": 0,
 "delivery_person": 1,
 "delivery_person_payment": 3,
 "delivery_rent": 3,
 "direct_sale": 3,
 "direct_sale_draft": 0,
 "direct_sale_item": 3,
 "entry": 9,
 "fbm_cash_drawer_category": 0,
 "fbm_cash_drawer_entry": 0,
 "fbm_client": 0,
 "fbm_rental": 0,
 "fbm_rental_item": 0,
 "follow_up_contact": 0,
 "follow_up_reminder": 0,
 "future_account_audit_log": 0,
 "grn": 6,
 "grn_allocation": 2,
 "grn_charge": 0,
 "grn_item": 6,
 "import_history_entry": 0,
 "import_job": 0,
 "import_upload": 0,
 "invoice": 0,
 "material": 4,
 "material_category": 4,
 "material_return": 0,
 "material_return_item": 0,
 "migration_history": 5,
 "migration_mapping": 0,
 "migration_row": 0,
 "migration_run": 0,
 "payment": 2,
 "pending_bill": 3,
 "recon_basket": 0,
 "root_backup_email_history": 0,
 "root_backup_settings": 0,
 "root_recovery_code": 0,
 "sale_delivery_persons": 3,
 "schema_version": 1,
 "service": 1,
 "settings": 0,
 "sidebar_category": 0,
 "sidebar_item": 0,
 "staff_email": 0,
 "supplier": 2,
 "supplier_payment": 2,
 "system_lock": 0,
 "tenant_wipe_backup_history": 0,
 "user": 1,
 "user_login_session": 1,
 "waive_off": 0
}
```
