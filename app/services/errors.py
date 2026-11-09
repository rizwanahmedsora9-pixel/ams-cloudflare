"""Unhandled-error capture, reference codes and transient-SQLite recovery.

Why this module exists
----------------------
The deployed app answered a failed request with the bare Werkzeug page
``500 Internal Server Error``: no reference, no hint, and — for a *transient*
SQLite problem — a page that stayed broken until the process was restarted.
Two things are needed to stop that:

1.  **A reference code on the page and a bounded, readable log.**  Every
    unhandled exception is written to ``instance/logs/500-errors.jsonl`` (and
    to the normal rotating error log) together with the method, endpoint,
    user, database file and full traceback.  The short code shown on the page
    (``E-1a2b3c``) is the same code stored in the log, so a report from a yard
    PC can be matched to the traceback without guessing.

2.  **Release the database lock and retry once.**  A failed request must never
    leave a half-open SQLite transaction behind: that lock is what turns one
    failure into "every page is a 500 now".  The session is rolled back as
    soon as the failure is recorded, and idempotent requests (GET/HEAD) are
    retried by :class:`DatabaseBusyRetryMiddleware` when SQLite reported a
    *transient* condition (``database is locked``, ``disk I/O error``, …).

The retry middleware is disabled while ``TESTING`` unless ``AMS_DB_RETRY=1``
is set, and can always be switched off with ``AMS_DB_RETRY=0``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import current_app, g, has_request_context, jsonify, request
from werkzeug.exceptions import HTTPException

LOG = logging.getLogger("errors")

# Appended to instance/logs/ and bounded so it can never fill the disk.
ERROR_LOG_NAME = "500-errors.jsonl"
MAX_STORED_ERRORS = 200
_ERROR_FLAG = "ams.transient_db_error"
_LOCK = threading.Lock()

# Wording SQLite/pysqlite uses for conditions that clear up on their own.
# Anything else (corruption, missing file, read-only disk, full disk) is a real
# fault and must not be retried silently.
_TRANSIENT_SIGNATURES = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
    "database is busy",
    "disk i/o error",
    "busy timeout",
    "unable to open database file",
)

_TOKEN_IN_PATH = re.compile(r"^/c/[^/]+")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def _iter_exception_chain(exc):
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        for linked in (
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
            getattr(current, "orig", None),
            getattr(current, "original_exception", None),
        ):
            if linked is not None:
                current = linked
                break
        else:
            current = None


def error_text(exc) -> str:
    """Every message/argument in the exception chain, lower-cased."""
    parts = []
    for item in _iter_exception_chain(exc):
        parts.append(type(item).__name__)
        parts.append(str(item))
        for arg in getattr(item, "args", ()) or ():
            parts.append(str(arg))
    return " | ".join(parts).lower()


def is_transient_db_error(exc) -> bool:
    """True for a SQLite/driver error that is likely to clear up on retry."""
    text = error_text(exc)
    if not any(sig in text for sig in _TRANSIENT_SIGNATURES):
        return False
    # A database that cannot be opened at all is a broken path, not contention.
    if "unable to open database file" in text and "locked" not in text:
        return bool(os.path.exists(str(_db_path())))
    return True


def is_database_error(exc) -> bool:
    for item in _iter_exception_chain(exc):
        if isinstance(item, sqlite3.Error):
            return True
        module = type(item).__module__ or ""
        if module.startswith("sqlalchemy") and type(item).__name__.endswith("Error"):
            return True
    return False


def _db_path() -> str:
    try:
        return str(current_app.config.get("APP_DB_PATH") or "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def error_log_path(app=None) -> Path:
    app = app or current_app
    folder = Path(app.instance_path) / "logs"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return folder / ERROR_LOG_NAME


def _new_reference() -> str:
    return "E-" + secrets.token_hex(3)


def _safe_path(raw: str) -> str:
    """Client-ledger QR paths carry a bearer token; never store it."""
    if not raw:
        return raw
    return _TOKEN_IN_PATH.sub("/c/[client-ledger-token]", str(raw))


def _trim_log(path: Path) -> None:
    """Keep only the newest MAX_STORED_ERRORS records."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            lines = stream.readlines()
        if len(lines) <= MAX_STORED_ERRORS * 2:
            return
        keep = lines[-MAX_STORED_ERRORS:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("".join(keep), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _write_record(app, record: dict) -> None:
    path = error_log_path(app)
    try:
        with _LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            _trim_log(path)
    except OSError:
        # A read-only or full instance directory must not make the error page
        # fail as well; the normal error log still has the traceback.
        LOG.warning("Could not append to %s", path, exc_info=True)


def _request_context() -> dict:
    if not has_request_context():
        return {}
    info = {
        "method": request.method,
        "path": _safe_path(request.path),
        "endpoint": request.endpoint,
        "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr or "-"),
        "user_agent": (request.headers.get("User-Agent") or "")[:200],
    }
    try:
        from flask_login import current_user

        if current_user and current_user.is_authenticated:
            info["user"] = current_user.username
            info["role"] = current_user.role
    except Exception:
        pass
    return info


def record_exception(exc, *, app=None, reference: str | None = None) -> str:
    """Log *exc* once per request and return its reference code."""
    try:
        app = app or current_app._get_current_object()
    except Exception:
        app = None

    if has_request_context():
        existing = getattr(g, "ams_error_ref", None)
        if existing:
            return existing

    reference = reference or _new_reference()
    transient = False
    try:
        transient = is_transient_db_error(exc)
    except Exception:
        transient = False

    # Release the write lock immediately: an open transaction on a pooled
    # SQLite connection is what makes the *next* request fail too.
    if is_database_error(exc):
        try:
            from models import db

            db.session.rollback()
        except Exception:
            pass

    record = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reference": reference,
        "exception": type(exc).__name__,
        "message": str(exc)[:2000],
        "transient_db": transient,
        "db_path": _db_path(),
    }
    record.update(_request_context())
    import traceback

    record["traceback"] = traceback.format_exc()[-8000:]

    if app is not None:
        _write_record(app, record)
    if has_request_context():
        try:
            g.ams_error_ref = reference
        except Exception:
            pass
        try:
            request.environ[_ERROR_FLAG] = transient
        except Exception:
            pass

    LOG.exception(
        "Unhandled %s on %s %s [%s]%s",
        record["exception"],
        record.get("method", "-"),
        record.get("path", "-"),
        reference,
        " (transient database error)" if transient else "",
        exc_info=exc,
    )
    return reference


def recent_errors(limit: int = 20, app=None) -> list[dict]:
    """Newest stored error records (most recent first)."""
    path = error_log_path(app)
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return list(reversed(out[-max(1, int(limit)):]))


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
_ERROR_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Something went wrong</title>
<style>
 body{{margin:0;padding:2rem;background:#0f172a;color:#e2e8f0;
      font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
 .card{{max-width:640px;margin:6vh auto;background:#1e293b;border:1px solid #334155;
        border-radius:14px;padding:1.75rem 2rem}}
 h1{{font-size:1.35rem;margin:0 0 .75rem;color:#fbbf24}}
 p{{line-height:1.6;margin:.5rem 0;color:#cbd5e1}}
 code{{background:#0f172a;border:1px solid #334155;border-radius:6px;
       padding:.15rem .4rem;color:#fbbf24}}
 .hint{{font-size:.92rem;color:#94a3b8}}
</style></head><body>
<div class="card">
  <h1>Something went wrong</h1>
  <p>This page could not be completed. Nothing was changed by this request.</p>
  <p>Reference: <code>{reference}</code></p>
  <p class="hint">{hint}</p>
  <p class="hint">Please try again. If it keeps happening, give the reference
  above to the administrator &mdash; it is stored with the technical details in
  <code>instance/logs/{log_name}</code>.</p>
</div></body></html>
"""

_TRANSIENT_HINT = (
    "The database was busy for a moment (another save, backup or report was "
    "running). Retry in a few seconds."
)


def _wants_json() -> bool:
    if not has_request_context():
        return False
    if str(request.path or "").startswith("/api/"):
        return True
    if (request.headers.get("X-Requested-With") or "").lower() in ("fetch", "xmlhttprequest"):
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept and "text/html" not in accept


def _error_response(exc):
    try:
        reference = getattr(g, "ams_error_ref", None) or record_exception(exc)
    except Exception:
        reference = "E-unknown"
    transient = False
    try:
        transient = is_transient_db_error(exc)
    except Exception:
        transient = False
    hint = _TRANSIENT_HINT if transient else (
        "The failure was written to the technical error log. Reloading the page "
        "is safe."
    )
    if _wants_json():
        response = jsonify(
            {
                "ok": False,
                "error": "The request could not be completed."
                if not transient
                else "The database was busy — please retry.",
                "error_reference": reference,
                "retryable": bool(transient),
            }
        )
        response.status_code = 500
        return response
    body = _ERROR_PAGE.format(reference=reference, hint=hint, log_name=ERROR_LOG_NAME)
    return body, 500, {"Content-Type": "text/html; charset=utf-8"}


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
def _handle_unhandled(exc):
    """Catch programming/DB errors; leave 404/403/413 alone."""
    if isinstance(exc, HTTPException):
        return exc
    if current_app.config.get("TESTING") and not current_app.config.get("AMS_ERROR_PAGES"):
        # Let pytest see the real exception unless a test opts in.
        raise exc
    return _error_response(exc)


def _handle_http_500(exc):
    original = getattr(exc, "original_exception", None)
    if current_app.config.get("TESTING") and not current_app.config.get("AMS_ERROR_PAGES"):
        raise (original or exc)
    return _error_response(original or exc)


def _on_request_exception(sender, exception, **_extra):
    # In tests the exception is re-raised for pytest to inspect; recording it
    # would only fill the real instance/logs directory with expected noise.
    if sender.config.get("TESTING") and not sender.config.get("AMS_ERROR_PAGES"):
        return
    try:
        record_exception(exception, app=sender)
    except Exception:  # pragma: no cover - logging must never mask the error
        LOG.warning("Could not record an unhandled exception", exc_info=True)


class DatabaseBusyRetryMiddleware:
    """Re-run an idempotent request once when SQLite was only temporarily busy.

    The error handler marks the WSGI environ when it classified the failure as
    transient, so the middleware never retries real faults (corruption, full
    disk, read-only database) or mutating requests.
    """

    DELAYS = (0.25, 1.0)
    RETRYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        attempts = len(self.DELAYS) if method in self.RETRYABLE_METHODS else 0
        attempt = 0
        while True:
            captured: dict = {}

            def _start(status, headers, exc_info=None, _c=captured):
                _c["status"] = status
                _c["headers"] = headers
                _c["exc_info"] = exc_info
                return lambda _data: None  # body is produced by the app itself

            try:
                result = self.wsgi_app(environ, _start)
            except Exception:
                if attempt < attempts and environ.pop(_ERROR_FLAG, False):
                    time.sleep(self.DELAYS[attempt])
                    attempt += 1
                    continue
                raise

            status = str(captured.get("status") or "")
            transient = bool(environ.pop(_ERROR_FLAG, False))
            if transient and status.startswith("500") and attempt < attempts:
                try:
                    result.close()
                except Exception:
                    pass
                time.sleep(self.DELAYS[attempt])
                attempt += 1
                continue

            start_response(
                captured.get("status") or "500 INTERNAL SERVER ERROR",
                captured.get("headers") or [],
                captured.get("exc_info"),
            )
            return result


def install_error_handling(app) -> None:
    """Register the 500 handlers, exception log and (optional) retry layer."""
    if getattr(app, "_ams_error_handling", False):
        return
    app._ams_error_handling = True

    from flask import got_request_exception

    got_request_exception.connect(_on_request_exception, app)
    app.register_error_handler(Exception, _handle_unhandled)
    app.register_error_handler(500, _handle_http_500)

    override = (os.environ.get("AMS_DB_RETRY") or "").strip().lower()
    if override in ("0", "false", "no", "off"):
        retry = False
    elif override in ("1", "true", "yes", "on"):
        retry = True
    else:
        retry = not app.config.get("TESTING")
    if retry:
        app.wsgi_app = DatabaseBusyRetryMiddleware(app.wsgi_app)
