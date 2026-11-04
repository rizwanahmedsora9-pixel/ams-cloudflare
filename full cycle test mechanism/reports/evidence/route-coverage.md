# Route census — run-006-20261104T0609

| | |
|---|---|
| URL rules | 566 |
| Unique endpoints | 563 |
| Reached by the suites | 267 (exact 165, prefix 102) |
| Not reached by any URL literal | 299 |
| Coverage (static) | **47.17%** |

> Static coverage only: a rule counts as reached when a URL literal in
> `shared/*.py` or `tests/**/*.py` matches it.  Routes built with
> `url_for()` are counted as gaps even when a test exercises them, so read
> the gap list as *places to inspect*, not as untested code.

## Gaps per blueprint

| Blueprint | Gaps | Reached |
|---|---|---|
| `(app)` | 127 | 113 |
| `misc` | 28 | 15 |
| `accounts` | 26 | 28 |
| `system` | 22 | 10 |
| `import_export` | 19 | 9 |
| `sales` | 12 | 17 |
| `ledgers` | 11 | 11 |
| `masters` | 11 | 31 |
| `api` | 10 | 5 |
| `reports` | 9 | 12 |
| `auth` | 7 | 2 |
| `legacy_migration` | 6 | 1 |
| `data_lab` | 4 | 0 |
| `admin` | 3 | 1 |
| `ops` | 3 | 9 |
| `inventory` | 1 | 2 |

## Gap list

| Rule | Endpoint | Methods |
|---|---|---|
| `/accounts/api/grn_obligations/<int:grn_id>` | `accounts.grn_obligations_api` | GET |
| `/accounts/api/kpi/client_payments` | `accounts.api_client_payments_today` | GET |
| `/accounts/api/kpi/company_money` | `accounts.api_company_money` | GET |
| `/accounts/api/kpi/expenditures` | `accounts.api_expenditures_today` | GET |
| `/accounts/api/kpi/receipts` | `accounts.api_receipts_today` | GET |
| `/accounts/api/kpi/supplier_payments` | `accounts.api_supplier_payments_today` | GET |
| `/accounts/audit` | `accounts.audit_trail` | GET |
| `/accounts/categories/add` | `accounts.add_account_category` | POST |
| `/accounts/expenditures` | `accounts.expenditures` | GET |
| `/accounts/kpi/bank_accounts` | `accounts.kpi_bank_accounts` | GET |
| `/accounts/kpi/cash_accounts` | `accounts.kpi_cash_accounts` | GET |
| `/accounts/kpi/cash_money` | `accounts.kpi_cash_money` | GET |
| `/accounts/kpi/client_payments` | `accounts.kpi_client_payments` | GET |
| `/accounts/kpi/company_money` | `accounts.kpi_company_money` | GET |
| `/accounts/kpi/expenditures` | `accounts.kpi_expenditures` | GET |
| `/accounts/kpi/receipts` | `accounts.kpi_receipts` | GET |
| `/accounts/kpi/supplier_payments` | `accounts.kpi_supplier_payments` | GET |
| `/accounts/ledger/<int:account_id>` | `accounts.account_ledger` | GET |
| `/accounts/payments/clients/restore/<int:id>` | `accounts.client_payment_restore` | POST |
| `/accounts/payments/clients/void/<int:id>` | `accounts.client_payment_void` | POST |
| `/accounts/reconciliations` | `accounts.reconciliations` | GET |
| `/accounts/transactions/<int:tx_id>/delete` | `accounts.delete_account_transaction` | POST |
| `/accounts/transactions/<int:tx_id>/edit` | `accounts.edit_account_transaction` | POST |
| `/accounts/transactions/<int:tx_id>/void` | `accounts.void_transaction` | POST |
| `/accounts/transfers` | `accounts.transfers` | GET |
| `/accounts/transfers/add` | `accounts.add_transfer` | GET, POST |
| `/add_sale` | `add_sale` | POST |
| `/add_sale` | `sales.add_sale` | POST |
| `/add_supplier_payment` | `add_supplier_payment` | POST |
| `/add_supplier_payment` | `misc.add_supplier_payment` | POST |
| `/add_user` | `add_user` | POST |
| `/add_user` | `misc.add_user` | POST |
| `/admin/accounts_domain_wipe` | `admin_accounts_domain_wipe` | POST |
| `/admin/accounts_domain_wipe` | `misc.admin_accounts_domain_wipe` | POST |
| `/admin/api/health` | `admin.api_health_check` | GET |
| `/admin/api/modules` | `admin.api_get_modules` | GET |
| `/admin/modules` | `admin.modules_list` | GET |
| `/admin/rebuild_erp_consistency` | `admin_rebuild_erp_consistency` | POST |
| `/admin/rebuild_erp_consistency` | `misc.admin_rebuild_erp_consistency` | POST |
| `/api/audit/financial-integrity` | `api.api_financial_integrity_audit` | GET |
| `/api/audit/financial-integrity` | `api_financial_integrity_audit` | GET |
| `/api/client_financial_summary/<client_code>` | `api.api_client_financial_summary` | GET |
| `/api/client_financial_summary/<client_code>` | `api_client_financial_summary` | GET |
| `/api/client_next_code` | `api.api_client_next_code` | GET |
| `/api/client_next_code` | `api_client_next_code` | GET |
| `/api/clients/search` | `api.api_clients_search` | GET |
| `/api/clients/search` | `api_clients_search` | GET |
| `/api/delivery_person_ledger/<int:id>` | `delivery_person_ledger_api` | GET |
| `/api/delivery_person_ledger/<int:id>` | `ledgers.delivery_person_ledger_api` | GET |
| `/api/delivery_persons/search` | `delivery_person_search_api` | GET |
| `/api/delivery_persons/search` | `ledgers.delivery_person_search_api` | GET |
| `/api/last_sold_price` | `api.api_last_sold_price` | GET |
| `/api/last_sold_price` | `api_last_sold_price` | GET |
| `/api/material_next_code` | `api.api_material_next_code` | GET |
| `/api/material_next_code` | `api_material_next_code` | GET |
| `/api/notifications/contact_history/<int:bill_id>` | `api.api_notifications_contact_history` | GET |
| `/api/notifications/contact_history/<int:bill_id>` | `api_notifications_contact_history` | GET |
| `/api/supplier_balance/<int:id>` | `api.api_supplier_balance` | GET |
| `/api/supplier_balance/<int:id>` | `api_supplier_balance` | GET |
| `/api/suppliers/search` | `api.api_suppliers_search` | GET |
| `/api/suppliers/search` | `api_suppliers_search` | GET |
| `/api/ui/theme` | `api.ui_theme_preference_api` | GET, POST |
| `/api/ui/theme` | `ui_theme_preference_api` | GET, POST |
| `/bulk_update_material_unit` | `bulk_update_material_unit` | POST |
| `/bulk_update_material_unit` | `misc.bulk_update_material_unit` | POST |
| `/cash_flow/entry/<int:entry_id>.json` | `cash_flow_entry_json` | GET |
| `/cash_flow/entry/<int:entry_id>.json` | `reports.cash_flow_entry_json` | GET |
| `/cash_flow/meta/categories` | `cash_flow_categories_meta` | GET, POST |
| `/cash_flow/meta/categories` | `reports.cash_flow_categories_meta` | GET, POST |
| `/cash_flow/meta/parties` | `cash_flow_parties_meta` | GET, POST |
| `/cash_flow/meta/parties` | `reports.cash_flow_parties_meta` | GET, POST |
| `/cash_flow/meta/subcategories` | `cash_flow_subcategories_meta` | GET, POST |
| `/cash_flow/meta/subcategories` | `reports.cash_flow_subcategories_meta` | GET, POST |
| `/cash_flow_differences` | `cash_flow_differences` | GET |
| `/cash_flow_differences` | `reports.cash_flow_differences` | GET |
| `/cash_flow_differences/<int:rec_id>` | `cash_flow_reconciliation_detail` | GET |
| `/cash_flow_differences/<int:rec_id>` | `reports.cash_flow_reconciliation_detail` | GET |
| `/change_password` | `change_password` | POST |
| `/change_password` | `misc.change_password` | POST |
| `/client_booking_cancel/<int:client_id>` | `client_booking_cancel` | POST |
| `/client_booking_cancel/<int:client_id>` | `ledgers.client_booking_cancel` | POST |
| `/client_booking_cancel_revert/<int:client_id>/<int:entry_id>` | `client_booking_cancel_revert` | POST |
| `/client_booking_cancel_revert/<int:client_id>/<int:entry_id>` | `ledgers.client_booking_cancel_revert` | POST |
| `/client_opening_balance/<int:id>` | `client_opening_balance` | POST |
| `/client_opening_balance/<int:id>` | `masters.client_opening_balance` | POST |
| `/client_toggle_active/<int:client_id>` | `client_toggle_active` | POST |
| `/client_toggle_active/<int:client_id>` | `ledgers.client_toggle_active` | POST |
| `/clients/activate_all` | `activate_all_clients` | POST |
| `/clients/activate_all` | `masters.activate_all_clients` | POST |
| `/daily_transactions` | `daily_transactions_redirect` | GET |
| `/daily_transactions` | `reports.daily_transactions_redirect` | GET |
| `/data_lab/` | `data_lab.upload` | GET, POST |
| `/data_lab/basket` | `data_lab.view_basket` | GET |
| `/data_lab/correct_bill` | `data_lab.correct_bill` | POST |
| `/data_lab/legacy_import` | `data_lab.legacy_import` | POST |
| `/data_wipe_preview` | `data_wipe_preview` | POST |
| `/data_wipe_preview` | `misc.data_wipe_preview` | POST |
| `/debug/db` | `debug_db` | GET |
| `/debug/db` | `system.debug_db` | GET |
| `/delete_all_data` | `delete_all_data` | POST |
| `/delete_all_data` | `misc.delete_all_data` | POST |
| `/delete_bill/<string:type>/<int:id>` | `delete_bill` | POST |
| `/delete_bill/<string:type>/<int:id>` | `sales.delete_bill` | POST |
| `/delete_entry/<int:id>` | `delete_entry` | POST |
| `/delete_entry/<int:id>` | `ops.delete_entry` | POST |
| `/delete_supplier_payment/<int:id>` | `delete_supplier_payment` | POST |
| `/delete_supplier_payment/<int:id>` | `misc.delete_supplier_payment` | POST |
| `/delete_user/<int:id>` | `delete_user` | POST |
| `/delete_user/<int:id>` | `misc.delete_user` | POST |
| `/delivery_ledger/<int:id>` | `delivery_person_ledger` | GET |
| `/delivery_ledger/<int:id>` | `ledgers.delivery_person_ledger` | GET |
| `/delivery_person_opening_balance/<int:id>` | `delivery_person_opening_balance` | POST |
| `/delivery_person_opening_balance/<int:id>` | `ledgers.delivery_person_opening_balance` | POST |
| `/delivery_person_payments/<int:id>/edit` | `edit_delivery_person_payment` | POST |
| `/delivery_person_payments/<int:id>/edit` | `ledgers.edit_delivery_person_payment` | POST |
| `/delivery_person_payments/<int:id>/restore` | `ledgers.restore_delivery_person_payment` | POST |
| `/delivery_person_payments/<int:id>/restore` | `restore_delivery_person_payment` | POST |
| `/delivery_person_payments/<int:id>/void` | `ledgers.void_delivery_person_payment` | POST |
| `/delivery_person_payments/<int:id>/void` | `void_delivery_person_payment` | POST |
| `/direct_sales/hold` | `hold_direct_sale` | POST |
| `/direct_sales/hold` | `sales.hold_direct_sale` | POST |
| `/direct_sales/hold/<int:draft_id>/delete` | `delete_direct_sale_draft` | POST |
| `/direct_sales/hold/<int:draft_id>/delete` | `sales.delete_direct_sale_draft` | POST |
| `/direct_sales/hold/<int:draft_id>/resume` | `resume_direct_sale_draft` | POST |
| `/direct_sales/hold/<int:draft_id>/resume` | `sales.resume_direct_sale_draft` | POST |
| `/download_delivery_person_ledger/<int:id>` | `download_delivery_person_ledger` | GET |
| `/download_delivery_person_ledger/<int:id>` | `ledgers.download_delivery_person_ledger` | GET |
| `/download_supplier_payment/<int:payment_id>` | `download_supplier_payment` | GET |
| `/download_supplier_payment/<int:payment_id>` | `misc.download_supplier_payment` | GET |
| `/edit_bill/Payment/<int:id>` | `edit_payment` | POST |
| `/edit_bill/Payment/<int:id>` | `sales.edit_payment` | POST |
| `/edit_entry/<int:id>` | `edit_entry` | POST |
| `/edit_entry/<int:id>` | `ops.edit_entry` | POST |
| `/edit_ledger_transaction/<string:trans_type>/<int:trans_id>` | `edit_ledger_transaction` | POST |
| `/edit_ledger_transaction/<string:trans_type>/<int:trans_id>` | `sales.edit_ledger_transaction` | POST |
| `/edit_material_return/<int:id>` | `edit_material_return` | POST |
| `/edit_material_return/<int:id>` | `sales.edit_material_return` | POST |
| `/edit_supplier_payment/<int:id>` | `edit_supplier_payment` | POST |
| `/edit_supplier_payment/<int:id>` | `misc.edit_supplier_payment` | POST |
| `/edit_user_permissions/<int:id>` | `edit_user_permissions` | POST |
| `/edit_user_permissions/<int:id>` | `misc.edit_user_permissions` | POST |
| `/export_clients` | `export_clients` | GET |
| `/export_clients` | `misc.export_clients` | GET |
| `/export_pending_bills` | `export_pending_bills` | GET |
| `/export_pending_bills` | `misc.export_pending_bills` | GET |
| `/fix_system_issues` | `fix_system_issues` | GET |
| `/fix_system_issues` | `misc.fix_system_issues` | GET |
| `/generate_dummy_data` | `generate_dummy_data` | GET |
| `/generate_dummy_data` | `misc.generate_dummy_data` | GET |
| `/import_dispatch_data` | `import_dispatch_data` | POST |
| `/import_dispatch_data` | `ops.import_dispatch_data` | POST |
| `/import_export/app_upgrade` | `import_export.app_upgrade` | GET, POST |
| `/import_export/app_upgrade/migrate` | `import_export.app_upgrade_migrate` | POST |
| `/import_export/app_upgrade/rollback` | `import_export.app_upgrade_rollback` | POST |
| `/import_export/app_upgrade/start` | `import_export.app_upgrade_start` | POST |
| `/import_export/app_upgrade/status/<job_id>` | `import_export.app_upgrade_status` | GET |
| `/import_export/email_file` | `import_export.email_file` | POST |
| `/import_export/execute_import` | `import_export.execute_import` | POST |
| `/import_export/export_excel_all` | `import_export.export_excel_all` | GET |
| `/import_export/full_raw_export` | `import_export.full_raw_export` | GET |
| `/import_export/full_raw_import_history` | `import_export.full_raw_import_history` | GET, POST |
| `/import_export/full_raw_import_history_export` | `import_export.full_raw_import_history_export` | GET |
| `/import_export/history` | `import_browse_history` | GET |
| `/import_export/jobs/<int:job_id>/cancel` | `import_cancel_job` | POST |
| `/import_export/jobs/<int:job_id>/history` | `import_job_history` | GET |
| `/import_export/jobs/<int:job_id>/progress` | `import_job_progress` | GET |
| `/import_export/master/export` | `import_export.export_master` | GET |
| `/import_export/master/import` | `import_export.import_master` | POST |
| `/import_export/master/import/start` | `import_export.master_import_start` | POST |
| `/import_export/master/import/status/<job_id>` | `import_export.master_import_status` | GET |
| `/import_export/preview` | `import_export.preview_import` | POST |
| `/import_export/template/<dataset>` | `import_export.get_template` | GET |
| `/import_export/tenant_db_export` | `import_export.tenant_db_export` | GET |
| `/import_export/tenant_db_restore` | `import_export.tenant_db_restore` | POST |
| `/import_export/upload` | `import_upload_file` | POST |
| `/import_export/uploads` | `import_list_uploads` | GET |
| `/import_export/uploads/<upload_id>` | `import_delete_upload` | DELETE |
| `/import_export/uploads/<upload_id>` | `import_get_upload` | GET |
| `/import_export/uploads/<upload_id>/start` | `import_start_job` | POST |
| `/import_pending_bills` | `import_pending_bills` | GET, POST |
| `/import_pending_bills` | `misc.import_pending_bills` | GET, POST |
| `/inventory/inventory_log` | `inventory.inventory_log` | GET |
| `/legacy-migration/run/<int:run_id>` | `legacy_migration.preview` | GET |
| `/legacy-migration/run/<int:run_id>` | `preview` | GET |
| `/legacy-migration/run/<int:run_id>/dry-run` | `dry_run` | POST |
| `/legacy-migration/run/<int:run_id>/dry-run` | `legacy_migration.dry_run` | POST |
| `/legacy-migration/run/<int:run_id>/errors.xlsx` | `errors` | GET |
| `/legacy-migration/run/<int:run_id>/errors.xlsx` | `legacy_migration.errors` | GET |
| `/legacy-migration/run/<int:run_id>/import` | `do_import` | POST |
| `/legacy-migration/run/<int:run_id>/import` | `legacy_migration.do_import` | POST |
| `/legacy-migration/template/<kind>` | `download` | GET |
| `/legacy-migration/template/<kind>` | `legacy_migration.download` | GET |
| `/legacy-migration/upload` | `legacy_migration.upload` | POST |
| `/legacy-migration/upload` | `upload` | POST |
| `/material_categories/<int:id>/rename` | `misc.rename_material_category` | POST |
| `/material_categories/<int:id>/rename` | `rename_material_category` | POST |
| `/material_categories/<int:id>/toggle` | `misc.toggle_material_category` | POST |
| `/material_categories/<int:id>/toggle` | `toggle_material_category` | POST |
| `/materials/activate_all` | `activate_all_materials` | POST |
| `/materials/activate_all` | `masters.activate_all_materials` | POST |
| `/materials/rename_label` | `masters.rename_material_label` | POST |
| `/materials/rename_label` | `rename_material_label` | POST |
| `/merge_materials` | `merge_materials` | POST |
| `/merge_materials` | `misc.merge_materials` | POST |
| `/mixed_transactions` | `mixed_transactions` | GET |
| `/mixed_transactions` | `sales.mixed_transactions` | GET |
| `/notifications/ack_reminder/<int:id>` | `notifications_ack_reminder` | POST |
| `/notifications/ack_reminder/<int:id>` | `system.notifications_ack_reminder` | POST |
| `/notifications/add_email` | `notifications_add_email` | POST |
| `/notifications/add_email` | `system.notifications_add_email` | POST |
| `/notifications/close_reminder/<int:id>` | `notifications_close_reminder` | POST |
| `/notifications/close_reminder/<int:id>` | `system.notifications_close_reminder` | POST |
| `/notifications/delete_email/<int:id>` | `notifications_delete_email` | POST |
| `/notifications/delete_email/<int:id>` | `system.notifications_delete_email` | POST |
| `/notifications/log_contact/<int:bill_id>` | `notifications_log_contact` | POST |
| `/notifications/log_contact/<int:bill_id>` | `system.notifications_log_contact` | POST |
| `/notifications/set_reminder/<int:bill_id>` | `notifications_set_reminder` | POST |
| `/notifications/set_reminder/<int:bill_id>` | `system.notifications_set_reminder` | POST |
| `/notifications/set_severity/<int:bill_id>` | `notifications_set_severity` | POST |
| `/notifications/set_severity/<int:bill_id>` | `system.notifications_set_severity` | POST |
| `/notifications/toggle_email/<int:id>` | `notifications_toggle_email` | POST |
| `/notifications/toggle_email/<int:id>` | `system.notifications_toggle_email` | POST |
| `/notifications/upcoming` | `notifications_upcoming` | GET |
| `/notifications/upcoming` | `system.notifications_upcoming` | GET |
| `/party_ledger/<int:id>` | `misc.party_ledger` | GET |
| `/party_ledger/<int:id>` | `party_ledger` | GET |
| `/pay_supplier` | `misc.pay_supplier_page` | GET |
| `/pay_supplier` | `pay_supplier_page` | GET |
| `/reclaim_client/<int:id>` | `masters.reclaim_client` | POST |
| `/reclaim_client/<int:id>` | `reclaim_client` | POST |
| `/reclaim_supplier_ledger/<int:id>` | `masters.reclaim_supplier_ledger` | POST |
| `/reclaim_supplier_ledger/<int:id>` | `reclaim_supplier_ledger` | POST |
| `/reconcile_data` | `misc.reconcile_data` | POST |
| `/reconcile_data` | `reconcile_data` | POST |
| `/restore_supplier_payment/<int:id>` | `misc.restore_supplier_payment` | POST |
| `/restore_supplier_payment/<int:id>` | `restore_supplier_payment` | POST |
| `/root/backup-settings` | `auth.root_backup_settings` | GET |
| `/root/backup-settings` | `root_backup_settings` | GET |
| `/root/backup-settings/history/clear` | `auth.root_backup_settings_history_clear` | POST |
| `/root/backup-settings/history/clear` | `root_backup_settings_history_clear` | POST |
| `/root/backup-settings/history/download/<int:history_id>` | `auth.root_backup_settings_history_download` | GET |
| `/root/backup-settings/history/download/<int:history_id>` | `root_backup_settings_history_download` | GET |
| `/root/backup-settings/save` | `auth.root_backup_settings_save` | POST |
| `/root/backup-settings/save` | `root_backup_settings_save` | POST |
| `/root/backup-settings/send-now` | `auth.root_backup_settings_send_now` | POST |
| `/root/backup-settings/send-now` | `root_backup_settings_send_now` | POST |
| `/root/recovery` | `auth.root_recovery` | GET, POST |
| `/root/recovery` | `root_recovery` | GET, POST |
| `/root/recovery_codes` | `auth.root_recovery_codes` | GET, POST |
| `/root/recovery_codes` | `root_recovery_codes` | GET, POST |
| `/services/merge` | `masters.merge_services` | POST |
| `/services/merge` | `merge_services` | POST |
| `/settings/sessions` | `login_sessions_page` | GET |
| `/settings/sessions` | `system.login_sessions_page` | GET |
| `/shift_grn_supplier/<int:id>` | `masters.shift_grn_supplier` | POST |
| `/shift_grn_supplier/<int:id>` | `shift_grn_supplier` | POST |
| `/stock_summary` | `reports.stock_summary_redirect` | GET |
| `/stock_summary` | `stock_summary_redirect` | GET |
| `/supplier_opening_balance/<int:id>` | `masters.supplier_opening_balance` | POST |
| `/supplier_opening_balance/<int:id>` | `supplier_opening_balance` | POST |
| `/tenants` | `system.tenants_dashboard` | GET |
| `/tenants` | `tenants_dashboard` | GET |
| `/tenants/<tenant_id>/backup_history` | `system.tenants_backup_history` | GET |
| `/tenants/<tenant_id>/backup_history` | `tenants_backup_history` | GET |
| `/tenants/<tenant_id>/delete` | `system.tenants_delete` | POST |
| `/tenants/<tenant_id>/delete` | `tenants_delete` | POST |
| `/tenants/<tenant_id>/reset_admin` | `system.tenants_reset_admin` | POST |
| `/tenants/<tenant_id>/reset_admin` | `tenants_reset_admin` | POST |
| `/tenants/<tenant_id>/reset_missing_passwords` | `system.tenants_reset_missing_passwords` | POST |
| `/tenants/<tenant_id>/reset_missing_passwords` | `tenants_reset_missing_passwords` | POST |
| `/tenants/<tenant_id>/status` | `system.tenants_update_status` | POST |
| `/tenants/<tenant_id>/status` | `tenants_update_status` | POST |
| `/tenants/<tenant_id>/update` | `system.tenants_update` | POST |
| `/tenants/<tenant_id>/update` | `tenants_update` | POST |
| `/tenants/backup_history/download/<int:history_id>` | `system.tenants_backup_history_download` | GET |
| `/tenants/backup_history/download/<int:history_id>` | `tenants_backup_history_download` | GET |
| `/tenants/backup_history/restore/<int:history_id>` | `system.tenants_backup_history_restore` | POST |
| `/tenants/backup_history/restore/<int:history_id>` | `tenants_backup_history_restore` | POST |
| `/tenants/create` | `system.tenants_create` | POST |
| `/tenants/create` | `tenants_create` | POST |
| `/toggle_user_status/<int:id>` | `misc.toggle_user_status` | POST |
| `/toggle_user_status/<int:id>` | `toggle_user_status` | POST |
| `/transfer_client/<int:id>` | `masters.transfer_client` | POST |
| `/transfer_client/<int:id>` | `transfer_client` | POST |
| `/transfer_supplier/<int:id>` | `masters.transfer_supplier` | POST |
| `/transfer_supplier/<int:id>` | `transfer_supplier` | POST |
| `/unpaid_transactions` | `reports.unpaid_transactions_page` | GET |
| `/unvoid_transaction/<string:type>/<int:id>` | `sales.unvoid_transaction` | POST |
| `/unvoid_transaction/<string:type>/<int:id>` | `unvoid_transaction` | POST |
| `/update_settings` | `misc.update_settings` | POST |
| `/update_settings` | `update_settings` | POST |
| `/uploads/<path:filename>` | `misc.uploaded_file` | GET |
| `/uploads/<path:filename>` | `uploaded_file` | GET |
| `/view_bill_detail/<string:type>/<int:id>` | `sales.view_bill_detail` | GET |
| `/view_bill_detail/<string:type>/<int:id>` | `view_bill_detail` | GET |
| `/void_audit/restore/<string:entity>/<int:record_id>` | `restore_audit_record` | POST |
| `/void_audit/restore/<string:entity>/<int:record_id>` | `system.restore_audit_record` | POST |
| `/void_transaction/<string:type>/<int:id>` | `sales.void_transaction` | POST |
| `/void_transaction/<string:type>/<int:id>` | `void_transaction` | POST |
