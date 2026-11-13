"""Cloudflare Workers entry point for the AMS ERP Flask application.

The minimal Flask-on-Workers sketch is::

    from workers import wsgi
    from app import create_app

    app = create_app()
    Default = wsgi.entrypoint(app)

This module keeps that shape but makes it survive the Workers runtime, where
three things differ from a normal server:

* **Modules are imported once, at deploy time, and memory-snapshotted.**  The
  filesystem is *not* part of that snapshot: ``/session/metadata`` (the bundle)
  is re-mounted for every isolate and everything else is a fresh in-memory
  filesystem.  An app built during import would come back holding a SQLite file
  that no longer exists.  The app is therefore created on the *first request*
  (``wsgi.entrypoint`` is replaced by an equivalent ``WorkerEntrypoint`` class
  so the creation can happen inside ``fetch``).
* **Worker vars and secrets live on ``self.env``**, while the Flask factory
  reads ``os.environ`` (database path, secret key, upload folders, ...), so
  they are copied across before the app is built.
* **``threading`` cannot start threads and the bundle directory is read-only**,
  so background schedulers are disabled and writable paths are redirected to
  the per-isolate in-memory filesystem.

Everything Cloudflare-specific is expressed through environment variables that
plain WSGI hosts (PythonAnywhere, gunicorn, ``python main.py``) simply ignore,
so importing this file elsewhere has no side effects.

Deploy with ``cloudflare/deploy.sh`` (or ``cd cloudflare && uv run pywrangler
deploy``).  See ``cloudflare/README.md`` for the full procedure and limits.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from workers import WorkerEntrypoint, wsgi

# Cloudflare snapshots module initialization. SQLAlchemy's import is expensive
# in Pyodide; importing it on the first request can exceed the Free CPU budget.
# Only preload the library here: app creation needs request-time bindings and
# must not snapshot a SQLite connection or a writable filesystem.
import sqlalchemy  # noqa: F401

LOG = logging.getLogger("ams.worker")

#: Worker vars/secrets forwarded into ``os.environ`` before the app is built.
_ENV_KEYS = (
    "SECRET_KEY",
    "APP_DB_PATH",
    "AMS_INSTANCE_DIR",
    "AMS_SCHEMA_VERSION",
    "ALLOW_EMPTY_DB",
    "SQLITE_JOURNAL_MODE",
    "PUBLIC_BASE_URL",
    "AMS_HTTPS",
    "SESSION_COOKIE_SECURE",
    "SESSION_COOKIE_SAMESITE",
    "DEFAULT_ADMIN_USER",
    "DEFAULT_ADMIN_PASSWORD",
    "MAX_UPLOAD_MB",
    "UPLOAD_DIR",
    "BACKUP_DIR",
    "TZ",
)

#: Defaults that make the app runnable on Workers.  Anything the Worker
#: configures explicitly (``vars`` or secrets) takes precedence.
_WORKERS_DEFAULTS = {
    "AMS_SCHEMA_VERSION": "v44",
    "ALLOW_EMPTY_DB": "1",
    # The emulated filesystem has no POSIX shared memory for SQLite WAL files.
    "SQLITE_JOURNAL_MODE": "DELETE",
    # HTTPS-only deployment: secure cookies (the factory derives SameSite).
    "AMS_HTTPS": "1",
    # `threading` is importable but cannot start threads under Pyodide.
    "AMS_DAILY_BACKUP_SCHEDULER": "0",
    "BACKUP_EMBEDDED_SCHEDULER": "0",
    "AUTO_RECONCILE_ENABLED": "0",
    # Compiling every Jinja template on a cold isolate is wasted CPU.
    "AMS_SKIP_TEMPLATE_WARMUP": "1",
    # Static files are served by Cloudflare Assets, not from the bundle.
    "AMS_STATIC_FROM_ASSETS": "1",
}

_APP = None


def _writable_root() -> Path:
    """Writable directory for SQLite, logs and uploads.

    ``/session/metadata`` (the bundle) is mounted read-only, so everything the
    running app writes goes to the per-isolate in-memory filesystem.
    """
    configured = (os.environ.get("AMS_INSTANCE_DIR") or "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "ams-erp"


def _env_value(env, key: str) -> str | None:
    """Return one Worker var/secret as a string, or ``None`` when unset."""
    if env is None:
        return None
    try:
        value = getattr(env, key)
    except Exception:  # unset binding
        return None
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text or None


def _prepare_environment(env) -> None:
    """Copy Worker vars into ``os.environ`` and fill in Workers-safe defaults."""
    for key in _ENV_KEYS:
        value = _env_value(env, key)
        if value is not None:
            os.environ[key] = value

    for key, value in _WORKERS_DEFAULTS.items():
        os.environ.setdefault(key, value)

    instance_dir = _writable_root()
    instance_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("AMS_INSTANCE_DIR", str(instance_dir))
    os.environ.setdefault("APP_DB_PATH", str(instance_dir / "ahmed_cement_v44_fresh.db"))
    os.environ.setdefault(
        "DB_HEALTH_SNAPSHOT_PATH", str(instance_dir / "health_snapshot.json")
    )
    os.environ.setdefault("BACKUP_DIR", str(instance_dir / "storage" / "backups"))
    os.environ.setdefault("UPLOAD_DIR", str(instance_dir / "storage" / "uploads"))
    os.environ.setdefault("MAINTENANCE_TEMP_DIR", str(instance_dir / "storage" / "temp"))


def _install_static_assets(app) -> None:
    """Serve ``/static/...`` from the ``ASSETS`` binding when it is present.

    The 14 MB ``static/`` tree (mostly Urdu fonts) is published as Cloudflare
    static assets instead of being bundled into the Worker, which keeps the
    upload inside the Workers script-size limits.  Asset keys are relative to
    the assets directory, so ``/static/css/app.css`` maps to ``css/app.css``.
    Flask's own ``static`` view remains the fallback for local runs.
    """
    from flask import Response, abort, request

    original = app.view_functions.get("static")

    def _asset_static(filename: str):
        env = request.environ.get("workers.env")
        assets = None
        if env is not None:
            try:
                assets = env.ASSETS
            except Exception:
                assets = None
        if assets is None or ".." in filename.replace("\\", "/").split("/"):
            if original is not None:
                return original(filename)
            abort(404)
        from pyodide.ffi import run_sync

        try:
            asset = run_sync(assets.fetch(f"https://assets.local/{filename}"))
            status = int(getattr(asset, "status", 200))
            if status == 404 and original is not None:
                return original(filename)
            body = run_sync(asset.bytes())
            headers = {}
            try:
                content_type = asset.headers.get("content-type")
            except Exception:
                content_type = None
            if content_type:
                headers["Content-Type"] = str(content_type)
            try:
                cache_control = asset.headers.get("cache-control")
            except Exception:
                cache_control = None
            if cache_control:
                headers["Cache-Control"] = str(cache_control)
        except Exception:
            LOG.warning("Serving /static/%s from the bundle fallback", filename,
                        exc_info=True)
            if original is not None:
                return original(filename)
            abort(404)
        return Response(body, status=status, headers=headers)

    app.view_functions["static"] = _asset_static


def _get_app():
    """Build the Flask application once per isolate, on the first request."""
    global _APP
    if _APP is None:
        # Imported lazily: an import error must not fail the Worker's module
        # evaluation (which happens at deploy time, with no request context).
        from app import create_app

        LOG.info("AMS on Cloudflare Workers: writable root %s", _writable_root())
        app = create_app()
        if os.environ.get("AMS_STATIC_FROM_ASSETS", "1") == "1":
            _install_static_assets(app)
        _APP = app
    return _APP


class Default(WorkerEntrypoint):
    """Worker entrypoint — the ``wsgi.entrypoint(app)`` equivalent, lazily."""

    async def fetch(self, request):
        env = getattr(self, "env", None)
        _prepare_environment(env)
        return await wsgi.fetch(_get_app(), request, env)
