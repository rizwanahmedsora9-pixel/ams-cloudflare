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
    got_request_exception, abort, session, g,
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
from app.services.time_money import (
    pk_now,
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

def _safe_download_name(name, default='document.pdf'):
    raw = (name or '').strip()
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', raw).strip('._')
    if not safe:
        safe = default
    if '.' not in safe:
        safe = f"{safe}.pdf"
    return safe


def _download_stamp(dt=None):
    dt = dt or pk_now()
    return dt.strftime('%d-%m-%Y_%I-%M%p')


def _download_filename(section, ext='pdf', dt=None):
    sec = re.sub(r'[^A-Za-z0-9]+', '', (section or 'DOWNLOAD')).upper() or 'DOWNLOAD'
    ext = (ext or '').lstrip('.').lower() or 'dat'
    return f"{sec}-{_download_stamp(dt)}.{ext}"


def _ext_from_name(name, fallback='dat'):
    ext = os.path.splitext(str(name or ''))[1].lstrip('.').lower()
    return ext or fallback


def resolve_export_lang(default='en'):
    """Read the requested document language off the query string.

    Every export accepts ``?lang=en`` (the default) or ``?lang=ur``.  Urdu is
    always a *separate* document — see :func:`_language_layer` for why the two
    languages are never mixed in one export any more.
    """
    try:
        raw = (request.args.get('lang') or '').strip().lower()
    except Exception:      # outside a request context (tests, CLI)
        return default
    if raw in ('ur', 'urdu', 'اردو'):
        return 'ur'
    if raw in ('en', 'eng', 'english'):
        return 'en'
    return default


def _language_layer(rendered_html, lang, urdu_labels=False):
    """Apply the language layer for one export.

    A document is now **either** English **or** Urdu — never both at once.

    The old mixed layer appended a Nastaleeq translation beside every Latin
    label.  That reads acceptably in a browser, but the pure-Python ReportLab
    fallback used on hosts without WeasyPrint draws the two scripts on one
    baseline inside one paragraph, so every header and summary line turned into
    overlapping, unreadable text.  Splitting the languages fixes the exported
    PDF *and* gives bilingual staff a clean Urdu copy on demand.

    ``urdu_labels=True`` selects the label-replacing Urdu layer (ledgers,
    statements and reports, whose templates have no Urdu branch of their own).
    Bills keep ``False``: they render their own Urdu labels through
    ``bill_lang`` and only need the font plus the RTL direction.
    """
    if not rendered_html:
        return rendered_html
    if lang == 'ur':
        try:
            from app.services.bilingual import apply_urdu, apply_urdu_labels
            return (apply_urdu_labels(rendered_html) if urdu_labels
                    else apply_urdu(rendered_html))
        except Exception:
            logging.getLogger(__name__).exception(
                'Urdu PDF layer failed; rendering English-only.')
            return rendered_html
    return rendered_html      # English: the template is already English.


def _try_render_weasy_pdf(rendered_html, download_name, disposition='attachment',
                          lang=None, urdu_labels=False, doc_title=None):
    """
    Render PDF with WeasyPrint only when available.
    On first failure, disable future attempts to avoid repeated noisy warnings.

    When WeasyPrint cannot be used (missing module, or missing system libraries
    such as pango on shared hosts) the request is NOT downgraded to HTML: a
    genuine PDF is produced by the ReportLab fallback instead, so a download
    that asked for a PDF always receives one.

    ``lang`` selects the document language:
      * ``'en'`` (or ``None``) — English only, no Urdu layer is injected;
      * ``'ur'`` — a single-language Urdu document (labels replaced, RTL).

    ``doc_title`` is the human-readable title used for the PDF metadata and the
    running page footer.  It defaults to the download name with the timestamp
    stripped, so the footer never prints ``CLIENTLEDGER-06-11-2026_08-21PM.pdf``.
    """

    safe_name = _safe_download_name(download_name, default='document.pdf')
    rendered_html = _language_layer(rendered_html, lang, urdu_labels=urdu_labels)
    html_for_pdf = _with_pdf_page_css(rendered_html)
    try:
        if state.WEASYPRINT_MODULE is None:
            # WeasyPrint prints dependency warnings to stderr on import; silence them here.
            with redirect_stderr(io.StringIO()):
                state.WEASYPRINT_MODULE = importlib.import_module('flask_weasyprint')
        # If a previous attempt already confirmed WeasyPrint is unavailable, bail early.
        if state.WEASYPRINT_MODULE is False:
            return _render_reportlab_pdf(rendered_html, safe_name, disposition,
                                         doc_title=doc_title, html=html_for_pdf)
        # Render with the *print* media type so the app's own ``@media print``
        # rules apply.  Those rules hide the sidebar, modals, loading overlay
        # and anything marked ``d-print-none``; without this the exported
        # document carries the whole application chrome.
        try:
            html_doc = state.WEASYPRINT_MODULE.HTML(
                string=html_for_pdf, media_type='print'
            )
        except TypeError:
            # Older flask_weasyprint builds without media_type support.
            html_doc = state.WEASYPRINT_MODULE.HTML(string=html_for_pdf)
        response = state.WEASYPRINT_MODULE.render_pdf(
            html_doc,
            download_name=safe_name
        )
        response.headers['Content-Disposition'] = f'{disposition}; filename={safe_name}'
        _disable_response_cache(response)
        return response
    except ModuleNotFoundError:
        state.WEASYPRINT_MODULE = False
        logging.getLogger(__name__).warning(
            'flask_weasyprint is not installed; using the ReportLab PDF fallback.'
        )
    except Exception as exc:
        state.WEASYPRINT_MODULE = False
        # A missing native library (pango/cairo) is an expected condition on
        # shared hosts, not an application fault - report it once, briefly, and
        # carry on with the ReportLab path instead of dumping a traceback.
        message = str(exc).lower()
        if 'cannot load library' in message or 'shared object' in message:
            logging.getLogger(__name__).warning(
                'WeasyPrint native libraries unavailable (%s); '
                'using the ReportLab PDF fallback.', type(exc).__name__
            )
        else:
            logging.getLogger(__name__).exception(
                'WeasyPrint PDF generation failed; using the ReportLab PDF fallback.'
            )
    return _render_reportlab_pdf(rendered_html, safe_name, disposition,
                                 doc_title=doc_title,
                                 html=_with_pdf_page_css(rendered_html))


# ---------------------------------------------------------------------------
# One paper geometry for every export path
# ---------------------------------------------------------------------------
# A browser printing the sheet, WeasyPrint and the pure-Python ReportLab
# fallback must all end up on the same page, otherwise "print" and "download
# PDF" visibly disagree.  A5 portrait (14.8cm x 21cm) with 10mm top/bottom and
# 8mm left/right margins is that single geometry; :mod:`app.services.pdf_fallback`
# uses the same numbers.
PDF_PAGE_WIDTH_CM = 14.8
PDF_PAGE_HEIGHT_CM = 21.0
PDF_MARGIN_X_CM = 0.8
PDF_MARGIN_Y_CM = 1.0

# Only a fallback for templates that declare no ``@page`` of their own.
PDF_PAGE_CSS = (
    "<style id=\"ams-pdf-page\">"
    "@page { size: A5 portrait; margin: 10mm 8mm; }"
    "</style>"
)

_PAGE_RULE_RE = re.compile(r'@page[^{]*\{([^}]*)\}', re.I)
_MARGIN_RE = re.compile(r'(?:^|;)\s*margin\s*:\s*([^;}]+)', re.I)
_LENGTH_RE = re.compile(r'(-?[\d.]+)\s*(cm|mm|in|pt|px)?')

_UNITS_TO_CM = {
    'cm': 1.0,
    'mm': 0.1,
    'in': 2.54,
    'pt': 2.54 / 72.0,
    'px': 2.54 / 96.0,
    '': 2.54 / 96.0,          # bare numbers are treated as px
}


def _lengths_to_cm(value):
    """``"10mm 8mm"`` / ``"1cm"`` / ``"0"`` -> list of centimetres."""
    out = []
    for number, unit in _LENGTH_RE.findall(value or ''):
        try:
            out.append(float(number) * _UNITS_TO_CM[(unit or '').lower()])
        except (TypeError, ValueError, KeyError):
            continue
    return out


def page_margins_cm(html):
    """The page margins the *template* asks the browser printer to use.

    Bills and receipts print edge to edge (``@page { margin: 0 }``) and put
    their own padding inside the wrapper, while statements ask for ``10mm 8mm``.
    Forcing one geometry on every PDF is what made the download look unlike the
    sheet the browser prints, so the export now reads the template's own rule
    and reproduces it.
    """
    html = html or ''
    declared = None
    for body in _PAGE_RULE_RE.findall(html):
        match = _MARGIN_RE.search(body)
        if match:
            declared = match.group(1)
    if declared is None:
        return PDF_MARGIN_X_CM, PDF_MARGIN_Y_CM
    values = _lengths_to_cm(declared)
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0]
    if len(values) == 2:                       # vertical horizontal
        return values[1], values[0]
    if len(values) == 3:                       # top horizontal bottom
        return values[1], (values[0] + values[2]) / 2.0
    return values[1], (values[0] + values[2]) / 2.0   # top right bottom left


def _with_pdf_page_css(html):
    """Return *html* with a ``@page`` size rule, honouring the template's margins.

    Every print template already declares ``@page`` inside ``@media print``;
    the browser applies it and so does WeasyPrint under ``media_type='print'``.
    Only the paper *size* is pinned here (A5 portrait) and only when the
    template declares no rule at all, so the PDF never overrides margins the
    on-screen print preview would have used.
    """
    html = html or ''
    if _PAGE_RULE_RE.search(html):
        return html
    lowered = html.lower()
    cut = lowered.rfind('</head>')
    if cut != -1:
        return html[:cut] + PDF_PAGE_CSS + html[cut:]
    return PDF_PAGE_CSS + html


def _human_doc_title(doc_title, safe_name):
    """A title worth printing in the page footer.

    Download names carry a timestamp (``CLIENTLEDGER-06-11-2026_08-21PM.pdf``)
    which is useful as a filename and useless — and noisy — as a document
    footer.  Prefer the caller's title and tidy a fallback from the filename.
    """
    title = (doc_title or '').strip()
    if title:
        return title
    stem = re.sub(r'\.pdf$', '', safe_name or '', flags=re.I)
    # Drop the trailing "_DD-MM-YYYY_HH-MMPM" stamp and turn it into words.
    stem = re.sub(r'[_-]?\d{2}-\d{2}-\d{4}[_-]?\d{2}-\d{2}(?:[ap]m)?$', '',
                  stem, flags=re.I)
    stem = re.sub(r'[._-]+', ' ', stem).strip()
    # "CLIENTLEDGER" -> "Client Ledger" for the known all-caps section codes.
    words, out = stem.split(' '), []
    for word in words:
        if word.isupper() and len(word) > 4 and ' ' not in word:
            out.append(word.title())
        else:
            out.append(word)
    return ' '.join(out) or 'AMS Document'


def _render_reportlab_pdf(rendered_html, safe_name, disposition, doc_title=None,
                          html=None):
    """Build a real PDF with ReportLab; return a response, or None if impossible."""
    try:
        from app.services.pdf_fallback import render_html_to_pdf
    except Exception:
        logging.getLogger(__name__).exception('PDF fallback module is not importable.')
        return None

    title = _human_doc_title(doc_title, safe_name)
    margin_x, margin_y = page_margins_cm(html if html is not None else rendered_html)
    data = render_html_to_pdf(rendered_html, download_name=safe_name, title=title,
                              margin_x_cm=margin_x, margin_y_cm=margin_y)
    if not data:
        return None

    response = make_response(data)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Length'] = str(len(data))
    response.headers['Content-Disposition'] = f'{disposition}; filename={safe_name}'
    _disable_response_cache(response)
    return response



def _bilingual_print_html(rendered_html, lang=None, urdu_labels=False):
    """Return *rendered_html* with the right language layer for browser printing.

    ``action=print`` endpoints hand the page back to the browser instead of a
    generated PDF.  ``lang='ur'`` produces a single-language Urdu sheet and
    anything else leaves the English sheet untouched.

    This mirrors :func:`_language_layer` exactly, so the sheet the browser
    prints and the PDF the server downloads are the same document in the same
    language — previously the print view got the mixed layer and the PDF got a
    mangled version of it.
    """
    try:
        return _language_layer(rendered_html, lang, urdu_labels=urdu_labels)
    except Exception:
        logging.getLogger(__name__).exception(
            'Print language layer failed; serving English-only HTML.')
        return rendered_html


def _disable_response_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def save_photo(file):
    """Save a bounded, signature-checked raster image; ignore unsafe uploads gracefully."""
    if not file or not file.filename:
        return None

    allowed_signatures = {
        '.jpg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.jpeg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.png': lambda data: data.startswith(b'\x89PNG\r\n\x1a\n'),
        '.gif': lambda data: data.startswith((b'GIF87a', b'GIF89a')),
        '.webp': lambda data: len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP',
    }
    safe_name = secure_filename(file.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    validator = allowed_signatures.get(ext)
    max_bytes = int(app.config.get('MAX_CONTENT_LENGTH') or (10 * 1024 * 1024))
    data = file.stream.read(max_bytes + 1)
    file.stream.seek(0)
    if len(data) > max_bytes or not validator or not validator(data):
        flash('Photo upload rejected: use a valid JPG, PNG, GIF, or WebP image under the upload size limit.', 'danger')
        return None

    filename = secure_filename(f"{pk_now().strftime('%Y%m%d%H%M%S%f')}_{safe_name}")
    upload_folder = os.path.join(basedir, 'static', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(upload_folder, filename)
    with open(file_path, 'wb') as saved:
        saved.write(data)
    return filename


