"""Public, read-only client ledger QR links and their staff print controls."""
from __future__ import annotations

import hashlib
import secrets

from flask import abort, current_app, make_response, render_template, request, session, url_for
from flask_login import current_user, login_required
from markupsafe import Markup
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.services.client_qr import (
    TOKEN_BYTES as _TOKEN_BYTES,
    TOKEN_LENGTH as _TOKEN_LENGTH,
    derive_client_qr_token,
    ensure_client_ledger_qr,
    is_qr_eligible_client,
    token_hash as _token_hash,
)
from app.services.public_url import request_origin, resolve_public_base_url

from ._common import *  # noqa: F401,F403


_FORM_MAX_AGE = 30 * 60


def _form_signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="client-ledger-qr-form")


def _form_context(client):
    """Bind a form to its browser, staff member, client and current QR state."""
    return {
        "client": client.id,
        "user": str(current_user.get_id()),
        "session": hashlib.sha256(session["_csrf_token"].encode()).hexdigest(),
        "state": client.client_ledger_qr_token_hash,
    }


def _form_nonce(client):
    # Do not write a single shared nonce into Flask's cookie session here.
    # Another tab/dialog (or an overlapping response) could overwrite it.
    # Signing the current state also rejects stale forms after a QR rotation.
    return _form_signer().dumps(_form_context(client))


def _valid_form_nonce(client, nonce):
    try:
        payload = _form_signer().loads(nonce, max_age=_FORM_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return payload == _form_context(client)


def _derive_token(client, salt: str) -> str:
    """Re-derive the client's current bearer token from the stored salt."""
    return derive_client_qr_token(client, salt)


def _can_print(client) -> bool:
    """True when the active QR can be re-rendered (hash + salt stored)."""
    return bool(client.client_ledger_qr_token_hash
                and client.client_ledger_qr_token_salt)


def _public_qr_origin() -> str:
    """Resolve the origin for client ledger QR links.

    Uses the configured Cloudflare Worker / ``PUBLIC_BASE_URL`` (or Settings)
    first, and falls back to the active app request origin when blank so
    local and preview environments never fail with HTTP 503.
    """
    configured = resolve_public_base_url(allow_http=True)
    if configured:
        return configured
    return request_origin()


_worker_origin = _public_qr_origin


def _qr_svg_path(matrix) -> Markup:
    """Build a tiny self-contained SVG path; coordinates are encoder integers."""
    size = len(matrix)
    path = "".join(
        f"M{column},{row}h1v1h-1z"
        for row, values in enumerate(matrix)
        for column, dark in enumerate(values) if dark
    )
    # Only integer coordinates from our QR encoder enter this Markup value.
    return Markup(
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Client ledger QR code" viewBox="-4 -4 {size + 8} {size + 8}" '
        f'width="320" height="320" shape-rendering="crispEdges">'
        f'<rect x="-4" y="-4" width="{size + 8}" height="{size + 8}" fill="white"/>'
        f'<path d="{path}" transform="translate(0 0)" fill="black"/></svg>'
    )


def _staff_only():
    if not (current_user.role in ("admin", "root") or _user_can("can_manage_clients")):
        abort(403)


def _active_qr_view_state(client, *, auto_generate: bool = False) -> tuple[str, str, bool]:
    """Return ``(qr_url, error, replaced)`` for displaying a client's active QR.

    When ``auto_generate`` is true and an eligible client has no active QR yet,
    generates and persists a derivable QR immediately so opening More -> QR Code
    shows the scannable QR code without requiring a manual generate click.
    Legacy hash-only QRs (missing salt) are never rotated automatically.
    """
    if not is_qr_eligible_client(client):
        return "", "", False

    if not client.client_ledger_qr_token_hash and auto_generate:
        _token, created = ensure_client_ledger_qr(client)
        if created:
            db.session.commit()

    if not _can_print(client):
        return "", "", False

    origin = _public_qr_origin()
    if not origin:
        return (
            "",
            "Set Public QR / Cloudflare Worker URL in Settings before printing client ledger QR codes.",
            False,
        )

    token = _derive_token(client, client.client_ledger_qr_token_salt)
    if _token_hash(token) != client.client_ledger_qr_token_hash:
        return (
            "",
            "The current QR can no longer be reprinted because the server key changed. Generate a replacement to print another copy.",
            False,
        )

    qr_url = f"{origin}{url_for('ledgers.public_client_ledger', token=token)}"
    return qr_url, "", False


def _qr_dialog_fragment(client, *, qr_url="", error="", status=200,
                        replaced=True):
    """HTML fragment shown inside the ledger page's big QR dialog."""
    nonce = _form_nonce(client)
    svg = None
    if qr_url and not error:
        from app.services import qr_code
        matrix = qr_code.make_matrix(qr_url, error="m")
        if matrix:
            svg = _qr_svg_path(matrix)
    response = make_response(render_template(
        "client_ledger_qr_dialog_body.html",
        client=client,
        qr_url=qr_url,
        qr_svg=svg,
        error=error,
        is_active=bool(client.client_ledger_qr_token_hash),
        can_generate=bool(is_qr_eligible_client(client)),
        can_print=_can_print(client),
        replaced=replaced,
        qr_nonce=nonce,
    ), status)
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@bp.route("/client_ledger_qr/<int:client_id>/dialog")
@login_required
def client_ledger_qr_dialog(client_id):
    """Staff-only fragment loaded into the ledger page's QR dialog."""
    _staff_only()
    client = Client.query.get_or_404(client_id)
    auto_gen = (request.args.get("revoked") or "").strip() != "1"
    qr_url, error, replaced = _active_qr_view_state(client, auto_generate=auto_gen)
    return _qr_dialog_fragment(client, qr_url=qr_url, error=error, replaced=replaced)


def _qr_admin_page(client, *, qr_url="", error="", replaced=True):
    nonce = _form_nonce(client)
    svg = None
    if qr_url and not error:
        from app.services import qr_code
        matrix = qr_code.make_matrix(qr_url, error="m")
        if matrix:
            svg = _qr_svg_path(matrix)
    response = make_response(render_template(
        "client_ledger_qr.html",
        client=client,
        qr_url=qr_url,
        qr_svg=svg,
        error=error,
        is_active=bool(client.client_ledger_qr_token_hash),
        can_generate=bool(is_qr_eligible_client(client)),
        can_print=_can_print(client),
        replaced=replaced,
        qr_nonce=nonce,
    ))
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _qr_print_page(client, qr_url, matrix, *, replaced=True):
    """Full-page success response showing a printable QR sheet."""
    response = make_response(render_template(
        "client_ledger_qr.html",
        client=client,
        qr_url=qr_url,
        qr_svg=_qr_svg_path(matrix),
        error="",
        is_active=True,
        can_generate=bool(is_qr_eligible_client(client)),
        can_print=_can_print(client),
        replaced=replaced,
        qr_nonce=_form_nonce(client),
    ))
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@bp.route("/client_ledger_qr/<int:client_id>", methods=["GET", "POST"])
@login_required
def client_ledger_qr(client_id):
    """Staff-only QR generation/rotation and printing page."""
    _staff_only()
    client = Client.query.get_or_404(client_id)
    if request.method == "GET":
        auto_gen = (request.args.get("revoked") or "").strip() != "1"
        qr_url, error, replaced = _active_qr_view_state(client, auto_generate=auto_gen)
        return _qr_admin_page(client, qr_url=qr_url, error=error, replaced=replaced)

    submitted_nonce = request.form.get("qr_nonce") or ""
    in_dialog = (request.form.get("dialog") or "").strip() == "1"
    if not _valid_form_nonce(client, submitted_nonce):
        error = ("This QR form expired or the client's QR access changed. "
                 "Review the current status below and try again.")
        if in_dialog:
            return _qr_dialog_fragment(client, error=error, status=400)
        return _qr_admin_page(client, error=error), 400
    action = (request.form.get("action") or "").strip().lower()
    if action == "revoke":
        client.client_ledger_qr_token_hash = None
        client.client_ledger_qr_token_salt = None
        db.session.commit()
        if in_dialog:
            return _qr_dialog_fragment(client)
        flash("This client's public ledger QR has been revoked.", "success")
        return redirect(url_for("ledgers.client_ledger_qr", client_id=client.id, revoked="1"))
    if action == "print":
        if not is_qr_eligible_client(client):
            error = "An active, non-transferred client is required for a QR link."
            if in_dialog:
                return _qr_dialog_fragment(client, error=error, status=409)
            return _qr_admin_page(client, error=error), 409
        if not _can_print(client):
            error = ("This QR was created before reprint support and cannot be "
                     "shown again. Generate a replacement to print another copy.")
            if in_dialog:
                return _qr_dialog_fragment(client, error=error, status=409)
            return _qr_admin_page(client, error=error), 409
        origin = _public_qr_origin()
        if not origin:
            error = ("Set Public QR / Cloudflare Worker URL in Settings "
                     "before printing client ledger QR codes.")
            if in_dialog:
                return _qr_dialog_fragment(client, error=error, status=503)
            return _qr_admin_page(client, error=error), 503
        token = _derive_token(client, client.client_ledger_qr_token_salt)
        if _token_hash(token) != client.client_ledger_qr_token_hash:
            error = ("The current QR can no longer be reprinted because the "
                     "server key changed. Generate a replacement to print "
                     "another copy.")
            if in_dialog:
                return _qr_dialog_fragment(client, error=error, status=409)
            return _qr_admin_page(client, error=error), 409
        qr_url = f"{origin}{url_for('ledgers.public_client_ledger', token=token)}"
        from app.services import qr_code
        matrix = qr_code.make_matrix(qr_url, error="m")
        if not matrix:
            if in_dialog:
                return _qr_dialog_fragment(
                    client, error="Could not encode this QR link.", status=500)
            return _qr_admin_page(client, error="Could not encode this QR link."), 500
        if in_dialog:
            return _qr_dialog_fragment(client, qr_url=qr_url, replaced=False)
        return _qr_print_page(client, qr_url, matrix, replaced=False)
    if action != "generate":
        abort(400)
    if not is_qr_eligible_client(client):
        error = "An active, non-transferred client is required for a QR link."
        if in_dialog:
            return _qr_dialog_fragment(client, error=error, status=409)
        return _qr_admin_page(client, error=error), 409

    origin = _public_qr_origin()
    if not origin:
        error = ("Set Public QR / Cloudflare Worker URL in Settings "
                 "before printing client ledger QR codes.")
        if in_dialog:
            return _qr_dialog_fragment(client, error=error, status=503)
        return _qr_admin_page(client, error=error), 503

    salt = secrets.token_urlsafe(_TOKEN_BYTES)
    token = _derive_token(client, salt)
    path = url_for("ledgers.public_client_ledger", token=token)
    qr_url = f"{origin}{path}"
    from app.services import qr_code
    matrix = qr_code.make_matrix(qr_url, error="m")
    if not matrix:
        if in_dialog:
            return _qr_dialog_fragment(
                client, error="Could not encode this QR link.", status=500)
        return _qr_admin_page(client, error="Could not encode this QR link."), 500

    client.client_ledger_qr_token_salt = salt
    client.client_ledger_qr_token_hash = _token_hash(token)
    db.session.commit()
    if in_dialog:
        return _qr_dialog_fragment(client, qr_url=qr_url)
    return _qr_print_page(client, qr_url, matrix)


@bp.route("/c/<token>")
def public_client_ledger(token):
    """Capability-protected, read-only live client ledger rendered as HTML."""
    if len(token) != _TOKEN_LENGTH or not all(
            ch.isascii() and (ch.isalnum() or ch in "_-") for ch in token):
        abort(404)
    client = Client.query.filter_by(client_ledger_qr_token_hash=_token_hash(token)).first()
    if not client or not client.is_active or client.transferred_to_id:
        abort(404)

    (financial_history, pending_bills, total_debit, total_credit,
     total_balance, _material_history_grouped) = _build_client_ledger_rows(client)
    material_summary, material_total_qty = client_material_summary(client)
    context = {
        "client": client,
        "settings": Settings.query.first(),
        "financial_history": financial_history,
        "pending_bills": pending_bills,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "total_balance": total_balance,
        "movement_rows": client_movement_rows(client),
        "material_summary": material_summary,
        "material_total_qty": material_total_qty,
        "generated_at": pk_now(),
    }
    response = make_response(render_template("client_ledger_public.html", **context))
    response.headers.update({
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "private, no-store, max-age=0",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'; object-src 'none'; connect-src 'none'"
        ),
    })
    return response
