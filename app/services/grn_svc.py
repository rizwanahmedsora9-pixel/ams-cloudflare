"""Domain service module — extracted from legacy ERP core."""
from __future__ import annotations

import os
import io
import secrets
import json
import calendar
import threading
import time
import smtplib
import shutil
import sqlite3
import zipfile
import urllib.request
import urllib.error
import re
import logging
import importlib
from itertools import zip_longest
from urllib.parse import unquote
from contextlib import redirect_stderr
from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from sqlalchemy import func, case, text, or_, and_, exists, not_
from sqlalchemy.orm import selectinload
from types import SimpleNamespace
from flask import (
    current_app as app,
    render_template, request, redirect, url_for, flash, jsonify,
    send_file, Response, make_response, send_from_directory,
    got_request_exception, abort, session, g, has_request_context,
)
from flask_login import login_user, login_required, logout_user, current_user

from models import *
from utils.audit import audit_log
from utils.reconciliation import run_auto_reconcile
from cash_flow_reconciliation_helpers import (
    create_reconciliation, update_reconciliation, delete_reconciliation,
    get_reconciliation_history, migrate_legacy_record,
)
from app.services import constants as C
from app.services import state

# === explicit service imports ===
from app.services.accounting import (
    _sync_supplier_payment_accounting,
)
from app.services.time_money import (
    pk_now,
    pk_today,
)


# Rebind constants used as bare names
OPEN_KHATA_CODE = C.OPEN_KHATA_CODE
OPEN_KHATA_NAME = C.OPEN_KHATA_NAME
PK_TZ = C.PK_TZ
SALE_CATEGORY_CHOICES = C.SALE_CATEGORY_CHOICES
_SALE_CATEGORY_ALIASES = C._SALE_CATEGORY_ALIASES
DOMAIN_WIPE_REGISTRY = C.DOMAIN_WIPE_REGISTRY
USER_PERMISSION_DEFAULTS = C.USER_PERMISSION_DEFAULTS
PERMISSION_LEGACY_FALLBACKS = C.PERMISSION_LEGACY_FALLBACKS
ENDPOINT_PERMISSION_MAP = C.ENDPOINT_PERMISSION_MAP
AUTO_BILL_NS_DEFAULT = C.AUTO_BILL_NS_DEFAULT
AUTO_BILL_NAMESPACES = C.AUTO_BILL_NAMESPACES
EDITABLE_USER_PERMISSION_FIELDS = C.EDITABLE_USER_PERMISSION_FIELDS
basedir = C.basedir
legacy_instance_dir = C.legacy_instance_dir
legacy_db_path = C.legacy_db_path
db_path = C.db_path
_DB_HEALTH_SNAPSHOT_PATH = C._DB_HEALTH_SNAPSHOT_PATH
_max_upload_mb = C._max_upload_mb
_AUTO_BACKUP_ENABLED = C._AUTO_BACKUP_ENABLED
_WIPE_BACKUP_ENABLED = C._WIPE_BACKUP_ENABLED
_AUTO_RECONCILE_ENABLED = C._AUTO_RECONCILE_ENABLED
_AUTO_RECONCILE_FIX = C._AUTO_RECONCILE_FIX
_AUTO_RECONCILE_INTERVAL_SEC = C._AUTO_RECONCILE_INTERVAL_SEC
_AUTO_RECONCILE_TOL = C._AUTO_RECONCILE_TOL
_ALLOW_EMPTY_DB = C._ALLOW_EMPTY_DB
_ALLOW_DB_DROP = C._ALLOW_DB_DROP
_DB_HEALTH_DROP_RATIO = C._DB_HEALTH_DROP_RATIO
_DB_HEALTH_DROP_MIN = C._DB_HEALTH_DROP_MIN
_DB_HEALTH_MIN_BYTES = C._DB_HEALTH_MIN_BYTES

def calculate_grn_total(grn):
    """Compatibility wrapper — the authoritative implementation now lives in
    :mod:`app.services.grn_costing` (single arithmetic source).

    LANDED GRNs return the landed cost; LEGACY GRNs keep the historical
    formula so old prints/reports never change.  This is a *document total*;
    it must never be used as a supplier payable (owner rule A2).
    """
    from app.services.grn_costing import calculate_grn_total as _authoritative
    return _authoritative(grn)


def _grn_bill_ref(grn):
    return (getattr(grn, 'manual_bill_no', None) or getattr(grn, 'auto_bill_no', None) or f"GRN-{getattr(grn, 'id', '')}").strip()


def _grn_auto_payment_note(grn):
    return f"[AUTO_GRN_PAY:{grn.id}] Auto-payment for GRN #{_grn_bill_ref(grn)}"


def _find_grn_auto_supplier_payment(grn):
    if not grn:
        return None
    marker = f"[auto_grn_pay:{grn.id}]"
    q = SupplierPayment.query.filter_by(is_void=False)
    if getattr(grn, 'supplier_id', None):
        q = q.filter(SupplierPayment.supplier_id == grn.supplier_id)
    marker_row = q.filter(
        func.lower(func.coalesce(SupplierPayment.note, '')).like(f"{marker}%")
    ).order_by(SupplierPayment.id.desc()).first()
    if marker_row:
        return marker_row

    # Legacy fallback for rows created before marker support.
    bill_ref = _grn_bill_ref(grn).lower()
    if not bill_ref:
        return None
    legacy_row = q.filter(
        func.lower(func.coalesce(SupplierPayment.note, '')).like(f"auto-payment for grn #{bill_ref}%")
    ).order_by(SupplierPayment.id.desc()).first()
    return legacy_row


def _sync_grn_auto_supplier_payment(grn, old_supplier_id=None):
    if not grn:
        return
    # Owner rule A1: a LANDED GRN never pays anybody.  Only pre-existing
    # LEGACY GRNs keep their historical auto-payment row in sync when edited
    # (so old data stays valid without creating new payments at GRN entry).
    if (getattr(grn, 'costing_mode', 'LEGACY') or 'LEGACY').upper() == 'LANDED':
        return
    # If supplier changed, void old supplier's auto row (if any).
    if old_supplier_id and old_supplier_id != getattr(grn, 'supplier_id', None):
        old_marker = f"[auto_grn_pay:{grn.id}]"
        old_row = SupplierPayment.query.filter(
            SupplierPayment.is_void == False,
            SupplierPayment.supplier_id == old_supplier_id,
            func.lower(func.coalesce(SupplierPayment.note, '')).like(f"{old_marker}%")
        ).order_by(SupplierPayment.id.desc()).first()
        if old_row:
            old_row.is_void = True

    row = _find_grn_auto_supplier_payment(grn)
    paid = max(0.0, float(getattr(grn, 'paid_amount', 0) or 0))

    if not getattr(grn, 'supplier_id', None) or paid <= 0:
        if row:
            row.is_void = True
            _sync_supplier_payment_accounting(row)
        return

    is_new_row = row is None
    financial_changed = bool(row) and any((
        float(getattr(row, 'amount', 0) or 0) != paid,
        getattr(row, 'payment_account_id', None) != getattr(grn, 'payment_account_id', None),
        getattr(row, 'date_posted', None) != (grn.date_posted or pk_now()),
        bool(getattr(row, 'is_void', False)),
    ))
    if (is_new_row or financial_changed) and paid > 0:
        # Finalised reconciliation periods are immutable: creating (or
        # financially changing) a supplier payment inside a closed period
        # must be rejected, exactly like the manual payment paths.
        from app.services.payments_crud import _assert_period_open
        _assert_period_open(
            getattr(grn, 'payment_account_id', None),
            grn.date_posted or pk_now(),
            operation='posted',
        )

    if not row:
        row = SupplierPayment(
            supplier_id=grn.supplier_id,
            is_void=False
        )
        db.session.add(row)
        db.session.flush()
    row.is_void = False
    row.supplier_id = grn.supplier_id
    row.payment_type = 'Payment'
    row.source_type = 'GRN'
    row.source_id = grn.id
    row.amount = paid
    row.method = (grn.payment_type or row.method or 'Cash')
    row.date_posted = grn.date_posted or pk_now()
    row.note = _grn_auto_payment_note(grn)
    row.bank_name = grn.bank_name or ''
    row.account_name = grn.account_name or ''
    row.account_no = grn.account_no or ''
    row.payment_account_id = getattr(grn, 'payment_account_id', None)

    _sync_supplier_payment_accounting(row)


# --- GRN manual date / time override --------------------------------------
#
# The GRN wizard lets the operator type any date and time ("override") so a
# receipt can be stamped with the moment the goods were actually received
# instead of the moment the record was entered.  Adding and editing both run
# through the helpers below, so both accept exactly the same input:
#
#   * '' / None .......... server clock (PK timezone)
#   * date only, today ... current server clock time
#   * date only, other ... 00:00:00 (same rule as resolve_posted_datetime)
#   * time only .......... server clock date + the typed time
#   * 24-hour 'HH:MM' / 'HH:MM:SS' / 'H:MM'
#   * 12-hour 'h:mm AM' / 'h:mm:ss PM' (case-insensitive)
#   * 'YYYY-MM-DD' / 'YYYY/MM/DD' / 'DD/MM/YYYY' / 'DD-MM-YYYY'
#   * a full 'YYYY-MM-DDTHH:MM[:SS]' value arriving in the date box
#
# Anything that cannot be understood raises ValueError with a readable
# message so the route flashes it and refuses the save: a bookkeeping record
# must never be silently stamped with a different time than the operator
# typed (the old behaviour fell back to the server clock without a word).

_GRN_DATE_FORMATS = ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%d-%m-%Y')
_GRN_TIME_FORMATS = (
    '%H:%M',
    '%H:%M:%S',
    '%H:%M:%S.%f',
    '%I:%M %p',
    '%I:%M:%S %p',
    '%I:%M%p',
    '%I:%M:%S%p',
)


def _grn_split_date_time(raw):
    """Split 'YYYY-MM-DDTHH:MM[:SS]' into ('YYYY-MM-DD', 'HH:MM:SS')."""
    text = (raw or '').strip()
    for sep in ('T', 't', ' '):
        if sep in text:
            head, _, tail = text.partition(sep)
            return head.strip(), tail.strip()
    return text, ''


def _grn_parse_date(text, raw_for_error=None):
    text = (text or '').strip()
    if not text:
        return None
    for fmt in _GRN_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"'{raw_for_error if raw_for_error is not None else text}' is not a valid date. "
        "Use the date picker or type YYYY-MM-DD (example: 2026-10-08)."
    )


def _grn_parse_time(text, raw_for_error=None):
    text = (text or '').strip().replace('\xa0', ' ')
    text = ' '.join(text.split())
    if not text:
        return None
    candidates = [text]
    if '.' in text:
        candidates.append(text.replace('.', ':', 1))
    for candidate in candidates:
        for fmt in _GRN_TIME_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).time()
            except ValueError:
                continue
    raise ValueError(
        f"'{raw_for_error if raw_for_error is not None else text}' is not a valid time. "
        "Use 24-hour HH:MM (e.g. 14:45) or 12-hour with AM/PM (e.g. 2:45 PM)."
    )


def parse_grn_datetime(date_raw, time_raw='', *, now=None):
    """Resolve the manual GRN date/time override into a naive PK datetime.

    Raises ValueError when the operator typed something unreadable; the
    calling route flashes the message and saves nothing.
    """
    now_dt = now or pk_now()
    date_text, embedded_time = _grn_split_date_time(date_raw)
    time_text = (time_raw or '').strip()
    if not time_text:
        time_text = embedded_time

    date_value = _grn_parse_date(date_text, raw_for_error=date_raw)
    time_value = _grn_parse_time(time_text, raw_for_error=time_text)

    if date_value is None and time_value is None:
        return now_dt
    if date_value is None:
        date_value = now_dt.date()
    if time_value is None:
        # Date typed without a time: today keeps the current clock time,
        # any other day starts at 00:00 (mirrors resolve_posted_datetime).
        time_value = now_dt.time() if date_value == now_dt.date() else datetime.min.time()

    return datetime.combine(date_value, time_value).replace(microsecond=0)


def sync_grn_entry_timestamps(grn, when=None):
    """Keep the GRN's stock-ledger Entry rows on the GRN's date/time.

    Header-only edits (a GRN whose lots are locked by sales) change the GRN
    stamp without rebuilding the lines, and the stock ledger used to keep the
    old timestamp.  Only date/time are touched here, never quantities, so the
    stock totals are unaffected.  Returns the number of rows updated.
    """
    if not grn or not getattr(grn, 'auto_bill_no', None):
        return 0
    stamp = when or getattr(grn, 'date_posted', None)
    if not stamp:
        return 0
    date_str = stamp.strftime('%Y-%m-%d')
    time_str = stamp.strftime('%H:%M:%S')
    rows = Entry.query.filter(
        Entry.auto_bill_no == grn.auto_bill_no,
        Entry.type == 'IN',
        Entry.is_void == False,  # noqa: E712 - SQLAlchemy column comparison
    ).all()
    updated = 0
    for row in rows:
        if row.date != date_str or row.time != time_str:
            row.date = date_str
            row.time = time_str
            updated += 1
    return updated


def _is_grn_backdate_restricted_user():
    """Kept for callers that only ask "is this profile restricted?".

    The rule itself now lives in ``app/services/edit_policy`` so GRN, dispatch
    and sales all answer the question the same way.
    """
    from app.services.edit_policy import is_backdate_restricted

    return is_backdate_restricted(current_user)


def _enforce_grn_backdate_policy(grn_dt, action_label, redirect_endpoint='grn',
                                 entity_id=None, **redirect_kwargs):
    """Shared back-date policy for GRN add/edit/cancel.

    Returns ``None`` when the action may proceed, or a redirect response when
    the policy refuses.  A restricted user may still edit a back-dated GRN
    inside the licensed window (``AMS_BACKDATE_DAYS``) as long as a reason is
    supplied with the form — the old rule refused every back-dated GRN edit
    outright, even one day old, which is what made GRN maintenance feel
    stuck.  Out-of-window records stay blocked for restricted users only.
    """
    from app.services.edit_policy import (
        EditBlocked, authorise_edit, audit_override, form_reason,
    )

    if not _is_grn_backdate_restricted_user():
        return None
    if not grn_dt:
        return None
    reason = form_reason(request.form) if has_request_context() else None
    try:
        authorise_edit(current_user, grn_dt, action_label=action_label, reason=reason)
    except EditBlocked as blocked:
        flash(blocked.message, 'danger')
        return redirect(url_for(redirect_endpoint, **redirect_kwargs))

    # Allowed: leave an audit row for the back-dated change.
    audit_override(
        current_user, action=action_label.lower(), entity='GRN',
        entity_id=entity_id, reason=reason,
    )
    return None


