"""Shared helpers for resolving the public base URL / origin used in QR codes.

Production deployments behind the Cloudflare Worker default to
``https://still-base-ac7a.rizwanahmedsora9.workers.dev`` (configured via
``PUBLIC_BASE_URL`` in ``wsgi.py`` and editable in Settings).  When blank
(e.g. cleared in Settings or running locally without Worker config), callers
can fall back to the active request origin instead of failing.
"""
from __future__ import annotations

from urllib.parse import urlsplit

DEFAULT_PUBLIC_BASE_URL = "https://still-base-ac7a.rizwanahmedsora9.workers.dev"


def normalize_public_origin(raw: str | None, *, allow_http: bool = True) -> str:
    """Validate and normalize an ``http(s)://host[:port]`` origin without a path.

    Returns ``""`` for empty or invalid values.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    scheme = (parsed.scheme or "").lower()
    allowed_schemes = ("https", "http") if allow_http else ("https",)
    if (
        scheme not in allowed_schemes
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return f"{scheme}://{parsed.netloc}"


def resolve_public_base_url(*, allow_http: bool = True) -> str:
    """Return the configured public QR origin, or ``""`` if intentionally blank.

    Precedence:
    1. Explicit runtime ``app.config["PUBLIC_BASE_URL"]`` overrides (tests or
       live Settings saves that changed it from startup ``_ENV_PUBLIC_BASE_URL``).
    2. ``Settings.public_base_url`` in the database when present (``None`` means
       never configured there yet; ``""`` means intentionally cleared).
    3. Startup ``app.config["PUBLIC_BASE_URL"]`` (from env / ``wsgi.py``).
    """
    try:
        from flask import current_app, has_app_context
        if not has_app_context():
            return ""
        has_cfg = "PUBLIC_BASE_URL" in current_app.config
        cfg_raw = current_app.config.get("PUBLIC_BASE_URL")
        cfg_val = (cfg_raw or "").strip() if isinstance(cfg_raw, str) else ""

        if "_ENV_PUBLIC_BASE_URL" not in current_app.config:
            if has_cfg:
                return normalize_public_origin(cfg_val, allow_http=allow_http)
        else:
            env_val = (current_app.config.get("_ENV_PUBLIC_BASE_URL") or "").strip()
            if has_cfg and cfg_val != env_val:
                return normalize_public_origin(cfg_val, allow_http=allow_http)

        # Check database Settings safely (some isolated unit tests use a bare
        # Flask app with no SQLAlchemy instance bound).
        try:
            from models import Settings
            settings = Settings.query.first()
        except Exception:
            settings = None
        if settings is not None and getattr(settings, "public_base_url", None) is not None:
            return normalize_public_origin(settings.public_base_url, allow_http=allow_http)

        return normalize_public_origin(cfg_val, allow_http=allow_http)
    except Exception:
        return ""


def request_origin() -> str:
    """Return ``scheme://host`` for the active HTTP request, or ``""``."""
    try:
        from flask import has_request_context, request
        if not has_request_context() or not request:
            return ""
        host = (
            request.headers.get("X-Forwarded-Host")
            or request.host
            or ""
        ).split(",")[0].strip()
        scheme = (
            request.headers.get("X-Forwarded-Proto")
            or request.scheme
            or "http"
        ).split(",")[0].strip().lower()
        if scheme not in ("http", "https") or not host:
            return ""
        return normalize_public_origin(f"{scheme}://{host}", allow_http=True)
    except Exception:
        return ""
