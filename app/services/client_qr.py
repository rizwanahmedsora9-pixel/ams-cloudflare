"""Client ledger QR token generation and derivation helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from flask import current_app, has_app_context

from app.services.constants import OPEN_KHATA_CODE

TOKEN_BYTES = 32
TOKEN_LENGTH = 43  # secrets.token_urlsafe(32), 256 bits of entropy


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _resolve_secret(secret_key=None):
    if secret_key:
        return secret_key
    if has_app_context():
        return current_app.secret_key
    return None


def derive_client_qr_token(client, salt: str, *, secret_key=None) -> str:
    """Re-derive the client's current bearer token from the stored salt.

    The raw token is never written to the database — only its SHA-256 digest
    and the random per-rotation salt are.  Re-running this with the same salt
    reproduces the exact token so the active QR can be displayed or printed
    without rotating it.
    """
    secret = _resolve_secret(secret_key)
    if not secret:
        raise RuntimeError("SECRET_KEY is required to derive a client ledger QR token.")
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    message = f"client-ledger-qr-v1:{client.id}:{salt}".encode("utf-8")
    digest = hmac.new(secret_bytes, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def is_qr_eligible_client(client) -> bool:
    if client is None or not getattr(client, "is_active", False):
        return False
    if getattr(client, "transferred_to_id", None):
        return False
    code = str(getattr(client, "code", "") or "").strip().upper()
    open_code = str(OPEN_KHATA_CODE or "OPEN-KHATA").strip().upper()
    if code and code == open_code:
        return False
    return True


def ensure_client_ledger_qr(client, *, force_rotate: bool = False, secret_key=None) -> tuple[str | None, bool]:
    """Ensure an eligible client has a derivable ledger QR salt and digest.

    Flushes ``db.session`` if ``client.id`` or ORM column defaults such as
    ``is_active`` are not assigned yet so the eligibility check sees real
    defaults and the derived HMAC always binds to the persistent primary key.
    Never replaces an already-active (including legacy hash-only) token unless
    ``force_rotate`` is explicitly requested.
    """
    if client is None:
        return None, False
    secret = _resolve_secret(secret_key)
    if not secret:
        return None, False
    if not force_rotate and getattr(client, "client_ledger_qr_token_hash", None):
        return None, False
    if getattr(client, "is_active", None) is False or getattr(client, "transferred_to_id", None):
        return None, False
    code = str(getattr(client, "code", "") or "").strip().upper()
    open_code = str(OPEN_KHATA_CODE or "OPEN-KHATA").strip().upper()
    if code and code == open_code:
        return None, False

    from models import db

    if getattr(client, "id", None) is None or getattr(client, "is_active", None) is None:
        if db.session.object_session(client) is not None or client in db.session:
            db.session.flush()

    if not is_qr_eligible_client(client) or getattr(client, "id", None) is None:
        return None, False

    salt = secrets.token_urlsafe(TOKEN_BYTES)
    token = derive_client_qr_token(client, salt, secret_key=secret)
    client.client_ledger_qr_token_salt = salt
    client.client_ledger_qr_token_hash = token_hash(token)
    return token, True
