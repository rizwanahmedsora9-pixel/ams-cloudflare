"""System-reserved accounts must never be treated as user-managed cash accounts."""
from __future__ import annotations

RECON_CATEGORY = 'recon'
RECON_ACCOUNT_TYPE = 'recon_counter'


def is_reserved_account(account) -> bool:
    if account is None:
        return False
    category = (getattr(account, 'category', '') or '').strip().lower()
    account_type = (getattr(account, 'account_type', '') or '').strip().lower()
    legacy_type = (getattr(account, 'type', '') or '').strip().lower()
    return category == RECON_CATEGORY or account_type == RECON_ACCOUNT_TYPE or legacy_type == RECON_ACCOUNT_TYPE


def is_legacy_loan_account(account) -> bool:
    if account is None:
        return False
    source_category = (getattr(account, 'source_category', '') or '').strip().lower()
    subcategory = (getattr(account, 'class_subcategory', '') or '').strip().lower()
    return source_category == 'loan' or subcategory == 'loans payable'


def account_is_reconciliation_source(tx) -> bool:
    """True for all count postings/resolutions, including historical source markers."""
    source_type = (getattr(tx, 'source_type', '') or '').strip().lower().replace('_', '')
    if source_type == 'cashdaydifference':
        return True
    note = (getattr(tx, 'note', '') or '').lower()
    return '[recon:day:' in note or '[recon:resolve:' in note
