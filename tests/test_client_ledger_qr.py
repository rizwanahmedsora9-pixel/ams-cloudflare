from __future__ import annotations

import hashlib
import re
import secrets

from app import db
from app.blueprints.ledgers import _client_ledger_qr as qr_routes
from models import Client, User


def test_public_client_qr_shows_live_html_only_and_can_be_revoked(app, client, monkeypatch):
    """The bearer QR returns a no-store HTML statement, never a PDF or app UI."""
    monkeypatch.setattr(qr_routes, "_build_client_ledger_rows",
                        lambda _client: ([], [], 0, 0, 0, {}))
    monkeypatch.setattr(qr_routes, "client_material_summary", lambda _client: ({}, 0))
    monkeypatch.setattr(qr_routes, "client_movement_rows", lambda _client: [])

    token = secrets.token_urlsafe(32)
    with app.app_context():
        row = Client(code="QR-TEST", name="QR Test Client", is_active=True)
        row.client_ledger_qr_token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        assert len(row.client_ledger_qr_token_hash) == 64
        assert token not in row.client_ledger_qr_token_hash

    response = client.get(f"/c/{token}")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert response.headers["Content-Security-Policy"].find("script-src") == -1
    assert b"QR Test Client" in response.data
    assert b"Live statement" in response.data
    assert b"download_client_ledger" not in response.data
    assert b"Download PDF" not in response.data

    assert client.get(f"/c/{secrets.token_urlsafe(32)}").status_code == 404
    assert client.get("/c/not-a-valid-token").status_code == 404

    with app.app_context():
        row = db.session.get(Client, client_id)
        row.client_ledger_qr_token_hash = None
        db.session.commit()
    assert client.get(f"/c/{token}").status_code == 404


def test_client_qr_generation_uses_worker_origin_and_revoke_invalidates_it(app, client):
    app.config["PUBLIC_BASE_URL"] = "https://qr.example.workers.dev"
    with app.app_context():
        row = Client(code="QR-ADMIN", name="Printable QR Client", is_active=True)
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    page = client.get(f"/client_ledger_qr/{client_id}")
    assert page.status_code == 200
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    printed = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "generate", "qr_nonce": nonce,
    })
    assert printed.status_code == 200
    assert b"Client Ledger QR" in printed.data
    assert b"window.print()" in printed.data
    assert b"href=\"https://qr.example.workers.dev" not in printed.data

    with app.app_context():
        row = db.session.get(Client, client_id)
        assert row.client_ledger_qr_token_hash

    page = client.get(f"/client_ledger_qr/{client_id}")
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    revoked = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "revoke", "qr_nonce": nonce,
    })
    assert revoked.status_code == 302
    with app.app_context():
        assert db.session.get(Client, client_id).client_ledger_qr_token_hash is None


def test_client_qr_dialog_fragment_generates_qr_with_download_and_print(app, client):
    """More -> QR Code: the in-ledger dialog auto-generates and shows the big QR."""
    app.config["PUBLIC_BASE_URL"] = "https://qr.example.workers.dev"
    with app.app_context():
        row = Client(code="QR-DIALOG", name="Dialog QR Client", is_active=True)
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    # The ledger's "More" menu opens this dialog; an existing active client
    # without a QR yet gets one automatically and renders the SVG immediately.
    dialog = client.get(f"/client_ledger_qr/{client_id}/dialog")
    assert dialog.status_code == 200
    body = dialog.get_data(as_text=True)
    assert "clientLedgerQrCode" in body and "<svg" in body
    assert "clientLedgerQrDownload" in body
    assert "clientLedgerQrPrint" in body
    assert body.index("clientLedgerQrCode") < body.index("clientLedgerQrDownload")
    assert 'name="dialog" value="1"' in body
    with app.app_context():
        first_hash = db.session.get(Client, client_id).client_ledger_qr_token_hash
        assert first_hash
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', body).group(1)

    # Replacing inside the dialog returns the rotated QR fragment (not a new page),
    # with Download / Print directly below the code.
    generated = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "generate", "qr_nonce": nonce, "dialog": "1",
    })
    assert generated.status_code == 200
    body = generated.get_data(as_text=True)
    assert "clientLedgerQrCode" in body and "<svg" in body
    assert "clientLedgerQrDownload" in body
    assert "clientLedgerQrPrint" in body
    assert body.index("clientLedgerQrCode") < body.index("clientLedgerQrDownload")
    with app.app_context():
        rotated_hash = db.session.get(Client, client_id).client_ledger_qr_token_hash
        assert rotated_hash and rotated_hash != first_hash

    # The dialog needs staff permission.
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get(f"/client_ledger_qr/{client_id}/dialog").status_code in (302, 401, 403)


def test_client_qr_can_be_reprinted_without_rotating(app, client, monkeypatch):
    """Re-opening or printing the active QR never rotates it; replacing does."""
    monkeypatch.setattr(qr_routes, "_build_client_ledger_rows",
                        lambda _client: ([], [], 0, 0, 0, {}))
    monkeypatch.setattr(qr_routes, "client_material_summary", lambda _client: ({}, 0))
    monkeypatch.setattr(qr_routes, "client_movement_rows", lambda _client: [])
    app.config["PUBLIC_BASE_URL"] = "https://qr.example.workers.dev"
    with app.app_context():
        row = Client(code="QR-REPRINT", name="Reprint QR Client", is_active=True)
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    # Opening the QR page auto-generates and renders the QR immediately.
    page = client.get(f"/client_ledger_qr/{client_id}")
    assert page.status_code == 200
    assert b"<svg" in page.data

    with app.app_context():
        row = db.session.get(Client, client_id)
        hash_after_generate = row.client_ledger_qr_token_hash
        salt = row.client_ledger_qr_token_salt
        assert salt
        token = qr_routes._derive_token(row, salt)
        assert len(token) == 43
        assert hashlib.sha256(token.encode("ascii")).hexdigest() == hash_after_generate
    assert client.get(f"/c/{token}").status_code == 200

    # Re-opening the page renders the exact same active QR without rotating it.
    page = client.get(f"/client_ledger_qr/{client_id}")
    body = page.get_data(as_text=True)
    assert "<svg" in body
    assert "current active QR" in body
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', body).group(1)
    reprint = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "print", "qr_nonce": nonce,
    })
    assert reprint.status_code == 200
    assert b"<svg" in reprint.data
    assert "current active QR" in reprint.get_data(as_text=True)

    # Reprinting did NOT rotate the code: hash and salt are unchanged and
    # the same token still serves the public ledger.
    with app.app_context():
        row = db.session.get(Client, client_id)
        assert row.client_ledger_qr_token_hash == hash_after_generate
        assert row.client_ledger_qr_token_salt == salt
    assert client.get(f"/c/{token}").status_code == 200

    # Opening the dialog also shows the active QR directly, without rotating.
    dialog = client.get(f"/client_ledger_qr/{client_id}/dialog")
    body = dialog.get_data(as_text=True)
    assert "clientLedgerQrCode" in body and "<svg" in body
    assert "clientLedgerQrPrint" in body
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', body).group(1)
    reprint_dialog = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "print", "qr_nonce": nonce, "dialog": "1",
    })
    assert reprint_dialog.status_code == 200
    body = reprint_dialog.get_data(as_text=True)
    assert "clientLedgerQrCode" in body and "<svg" in body
    assert "clientLedgerQrPrint" in body
    with app.app_context():
        row = db.session.get(Client, client_id)
        assert row.client_ledger_qr_token_hash == hash_after_generate
        assert row.client_ledger_qr_token_salt == salt

    # A replacement still rotates the code: new token, new hash, old link dead.
    page = client.get(f"/client_ledger_qr/{client_id}")
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"',
                      page.get_data(as_text=True)).group(1)
    replaced = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "generate", "qr_nonce": nonce,
    })
    assert replaced.status_code == 200
    with app.app_context():
        row = db.session.get(Client, client_id)
        assert row.client_ledger_qr_token_hash != hash_after_generate
        assert row.client_ledger_qr_token_salt != salt
    assert client.get(f"/c/{token}").status_code == 404


def test_client_qr_reprint_rejects_stale_forms(app, client):
    """A print form bound to an earlier QR state must not render the code."""
    app.config["PUBLIC_BASE_URL"] = "https://qr.example.workers.dev"
    with app.app_context():
        row = Client(code="QR-STALE", name="Stale QR", is_active=True)
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True
    page = client.get(f"/client_ledger_qr/{client_id}")
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"',
                      page.get_data(as_text=True)).group(1)
    generated = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "generate", "qr_nonce": nonce,
    })
    assert generated.status_code == 200
    # The old form was bound to the pre-rotation state.
    rejected = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "print", "qr_nonce": nonce,
    })
    assert rejected.status_code == 400
    assert b"<svg" not in rejected.data


def test_legacy_qr_without_salt_cannot_be_reprinted_but_offers_replacement(
        app, client, monkeypatch):
    """QRs created before reprint support stay usable but can only be replaced."""
    monkeypatch.setattr(qr_routes, "_build_client_ledger_rows",
                        lambda _client: ([], [], 0, 0, 0, {}))
    monkeypatch.setattr(qr_routes, "client_material_summary", lambda _client: ({}, 0))
    monkeypatch.setattr(qr_routes, "client_movement_rows", lambda _client: [])
    app.config["PUBLIC_BASE_URL"] = "https://qr.example.workers.dev"
    token = secrets.token_urlsafe(32)
    with app.app_context():
        row = Client(code="QR-LEGACY", name="Legacy QR", is_active=True)
        row.client_ledger_qr_token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True
    page = client.get(f"/client_ledger_qr/{client_id}")
    body = page.get_data(as_text=True)
    assert "Print current QR" not in body
    assert "before reprint support" in body
    # The legacy state must not claim reprint is possible, and must point to
    # the replacement flow instead.
    assert "again any time" not in body
    assert "Generate replacement and show QR" in body
    dialog = client.get(f"/client_ledger_qr/{client_id}/dialog")
    frag = dialog.get_data(as_text=True)
    assert "Print current QR" not in frag
    assert "before reprint support" in frag
    assert "again any time" not in frag
    assert "Generate replacement and show QR" in frag
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', body).group(1)
    rejected = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "print", "qr_nonce": nonce,
    })
    assert rejected.status_code == 409
    assert b"before reprint support" in rejected.data
    # The existing public link still works.
    assert client.get(f"/c/{token}").status_code == 200


def test_material_ledger_page_opens_qr_dialog_and_generates_in_it(app, client):
    """The Client Ledger page opens the QR dialog and shows the QR automatically."""
    app.config["PUBLIC_BASE_URL"] = "https://qr.example.workers.dev"
    with app.app_context():
        row = Client(code="QR-MAT", name="Material QR Client", is_active=True)
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    ledger = client.get(f"/client_ledger/{client_id}")
    assert ledger.status_code == 200
    body = ledger.get_data(as_text=True)
    # The Client QR button opens the in-ledger dialog (no settings page needed).
    assert 'id="clientLedgerQrModal"' in body
    assert 'data-bs-target="#clientLedgerQrModal"' in body
    assert 'id="clientLedgerQrModalBody"' in body
    assert "Loading QR" in body

    dialog = client.get(f"/client_ledger_qr/{client_id}/dialog")
    assert dialog.status_code == 200
    frag = dialog.get_data(as_text=True)
    assert "clientLedgerQrCode" in frag and "<svg" in frag
    assert "clientLedgerQrDownload" in frag and "clientLedgerQrPrint" in frag
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', frag).group(1)
    generated = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "generate", "qr_nonce": nonce, "dialog": "1",
    })
    assert generated.status_code == 200
    body = generated.get_data(as_text=True)
    assert "clientLedgerQrCode" in body and "<svg" in body
    assert "clientLedgerQrDownload" in body and "clientLedgerQrPrint" in body


def test_qr_forms_survive_other_tabs_and_reject_stale_or_invalid_forms(app, client, monkeypatch):
    """Opening QR settings must not invalidate a form in another dialog/tab."""
    app.config["PUBLIC_BASE_URL"] = "https://qr.example.workers.dev"
    app.config["AMS_CSRF_ALWAYS"] = True
    with app.app_context():
        rows = [Client(code=f"QR-TAB-{i}", name=f"QR Tab {i}", is_active=True)
                for i in range(2)]
        db.session.add_all(rows)
        db.session.commit()
        first_id, second_id = [row.id for row in rows]
        admin_id = User.query.filter_by(username="Admin").first().id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    def nonce(response):
        assert response.status_code == 200
        return re.search(r'name="qr_nonce" value="([^"]+)"',
                         response.get_data(as_text=True)).group(1)

    def generate(client_id, form_nonce):
        return client.post(f"/client_ledger_qr/{client_id}", data={
            "action": "generate", "dialog": "1", "qr_nonce": form_nonce,
        })

    first_nonce = nonce(client.get(f"/client_ledger_qr/{first_id}/dialog"))
    # Both a second client and standalone settings used to overwrite the
    # first dialog's session nonce, causing the generic HTTP 400 failure.
    second_nonce = nonce(client.get(f"/client_ledger_qr/{second_id}/dialog"))
    nonce(client.get(f"/client_ledger_qr/{first_id}"))
    # GETs no longer add/change a shared session nonce.
    with client.session_transaction() as sess:
        assert "client_ledger_qr_nonce" not in sess

    # Forms are bound to the client, browser session, and signature.
    for invalid in (second_nonce, first_nonce + "tampered", ""):
        rejected = generate(first_id, invalid)
        assert rejected.status_code == 400
        assert b"cl-qr-dialog" in rejected.data
        assert b"Review the current status" in rejected.data
        assert b"<svg" not in rejected.data

    # A signed form from an earlier browser session must not be accepted.
    with client.session_transaction() as sess:
        csrf_token = sess["_csrf_token"]
        sess["_csrf_token"] = "another-session-token"
    assert generate(first_id, first_nonce).status_code == 400
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token

    # Expired signatures return a fresh, actionable form, not an abort page.
    with monkeypatch.context() as patch:
        patch.setattr(qr_routes, "_FORM_MAX_AGE", -1)
        expired = generate(first_id, first_nonce)
        assert expired.status_code == 400
        assert b"expired" in expired.data

    generated = generate(first_id, first_nonce)
    assert generated.status_code == 200
    assert b"<svg" in generated.data
    with app.app_context():
        original_hash = db.session.get(Client, first_id).client_ledger_qr_token_hash
        assert original_hash
    # An accidental double submit cannot rotate a just-generated QR.
    assert generate(first_id, first_nonce).status_code == 400
    with app.app_context():
        assert db.session.get(Client, first_id).client_ledger_qr_token_hash == original_hash
    assert generate(second_id, second_nonce).status_code == 200

    # The newly generated form still supports revocation without navigation.
    revoke = client.post(f"/client_ledger_qr/{first_id}", data={
        "action": "revoke", "dialog": "1", "qr_nonce": nonce(generated),
    })
    assert revoke.status_code == 200
    with app.app_context():
        assert db.session.get(Client, first_id).client_ledger_qr_token_hash is None


def test_qr_dialog_csrf_errors_are_explicit_and_do_not_generate(app, client):
    app.config["AMS_CSRF_ALWAYS"] = True
    with app.app_context():
        row = Client(code="QR-CSRF", name="QR CSRF", is_active=True)
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True
    dialog = client.get(f"/client_ledger_qr/{client_id}/dialog")
    form_nonce = re.search(r'name="qr_nonce" value="([^"]+)"',
                           dialog.get_data(as_text=True)).group(1)
    with app.app_context():
        initial_hash = db.session.get(Client, client_id).client_ledger_qr_token_hash
        assert initial_hash
    rejected = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "generate", "dialog": "1", "qr_nonce": form_nonce,
        "_csrf_token": "invalid",
    })
    assert rejected.status_code == 400
    assert "Reload the page" in rejected.get_json()["error"]
    with app.app_context():
        assert db.session.get(Client, client_id).client_ledger_qr_token_hash == initial_hash


def test_add_client_auto_generates_qr_and_more_qr_displays_it(app, client, monkeypatch):
    """Creating a new client generates a valid ledger QR immediately."""
    monkeypatch.setattr(qr_routes, "_build_client_ledger_rows",
                        lambda _client: ([], [], 0, 0, 0, {}))
    monkeypatch.setattr(qr_routes, "client_material_summary", lambda _client: ({}, 0))
    monkeypatch.setattr(qr_routes, "client_movement_rows", lambda _client: [])
    with app.app_context():
        admin_id = User.query.filter_by(username="Admin").first().id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    resp = client.post("/add_client", data={
        "name": "Auto QR Customer",
        "code": "QR-AUTO-1",
        "category": "Contractor",
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)

    with app.app_context():
        row = Client.query.filter_by(code="QR-AUTO-1").one()
        assert row.client_ledger_qr_token_hash
        assert row.client_ledger_qr_token_salt
        token = qr_routes._derive_token(row, row.client_ledger_qr_token_salt)
        assert hashlib.sha256(token.encode("ascii")).hexdigest() == row.client_ledger_qr_token_hash
        client_id = row.id

    # The auto-generated bearer link immediately serves the public live ledger.
    pub = client.get(f"/c/{token}")
    assert pub.status_code == 200
    assert b"Auto QR Customer" in pub.data

    # Clicking More -> QR Code shows the exact active QR without rotating it.
    dialog = client.get(f"/client_ledger_qr/{client_id}/dialog")
    assert dialog.status_code == 200
    body = dialog.get_data(as_text=True)
    assert "clientLedgerQrCode" in body and "<svg" in body
    assert "current active QR" in body
    with app.app_context():
        row = db.session.get(Client, client_id)
        assert qr_routes._derive_token(row, row.client_ledger_qr_token_salt) == token


def test_blank_public_base_url_falls_back_to_app_origin_without_503(app, client):
    """When PUBLIC_BASE_URL and Settings are blank, QR uses the active request origin."""
    from models import Settings
    app.config["PUBLIC_BASE_URL"] = ""
    with app.app_context():
        s = Settings.query.first() or Settings()
        s.public_base_url = ""
        db.session.add(s)
        row = Client(code="QR-FALLBACK", name="Fallback QR Client", is_active=True)
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    dialog = client.get(
        f"/client_ledger_qr/{client_id}/dialog",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "preview-5000.e2b.app"},
    )
    assert dialog.status_code == 200
    body = dialog.get_data(as_text=True)
    assert "clientLedgerQrCode" in body and "<svg" in body
    assert "PUBLIC_BASE_URL" not in body

    with app.test_request_context(
        "/",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "preview-5000.e2b.app"},
    ):
        assert qr_routes._public_qr_origin() == "https://preview-5000.e2b.app"


def test_standalone_revoke_does_not_auto_regenerate_immediately(app, client):
    """Revoking on standalone page redirects with ?revoked=1 and keeps QR off."""
    app.config["PUBLIC_BASE_URL"] = "https://qr.example.workers.dev"
    with app.app_context():
        row = Client(code="QR-REV", name="Revoke Stay Off", is_active=True)
        db.session.add(row)
        db.session.commit()
        client_id = row.id
        admin_id = User.query.filter_by(username="Admin").first().id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    page = client.get(f"/client_ledger_qr/{client_id}")
    assert page.status_code == 200
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', page.get_data(as_text=True)).group(1)

    revoked = client.post(
        f"/client_ledger_qr/{client_id}",
        data={"action": "revoke", "qr_nonce": nonce},
        follow_redirects=True,
    )
    assert revoked.status_code == 200
    html = revoked.get_data(as_text=True)
    assert "No active public QR" in html
    assert "clientLedgerQrCode" not in html
    with app.app_context():
        assert db.session.get(Client, client_id).client_ledger_qr_token_hash is None


def test_import_party_and_legacy_migration_auto_generate_qr(app):
    """Client creation helpers used by imports and legacy migration auto-assign QR."""
    from app.services.client_qr import ensure_client_ledger_qr
    with app.app_context():
        c1 = Client(code="QR-IMP-1", name="Imported Client", category="Contractor")
        db.session.add(c1)
        token1, created1 = ensure_client_ledger_qr(c1)
        assert created1 is True and token1
        assert c1.is_active is True
        assert c1.client_ledger_qr_token_hash
        # Inactive and OPEN-KHATA clients are skipped.
        c2 = Client(code="QR-INACT", name="Inactive", category="Contractor", is_active=False)
        db.session.add(c2)
        assert ensure_client_ledger_qr(c2) == (None, False)
        ok = Client(code="OPEN-KHATA", name="Walk-In", category="Cash")
        db.session.add(ok)
        assert ensure_client_ledger_qr(ok) == (None, False)
        db.session.commit()


def test_settings_and_wsgi_default_cloudflare_worker_url(app, client):
    """Cloudflare Worker is the default in wsgi.py & Settings, and editable in UI."""
    from pathlib import Path
    import sqlite3
    from models import Settings

    wsgi_text = (Path(__file__).resolve().parents[1] / "wsgi.py").read_text()
    assert "https://still-base-ac7a.rizwanahmedsora9.workers.dev" in wsgi_text

    # Migration 0012 backfills NULL without clobbering edited or blank settings.
    mig = (Path(__file__).resolve().parents[1] / "app" / "migrations" / "0012_public_base_url_setting.sql").read_text()
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, public_base_url VARCHAR(300))")
    con.executemany("INSERT INTO settings (id, public_base_url) VALUES (?, ?)", [
        (1, None),
        (2, "https://custom.example.workers.dev"),
        (3, ""),
    ])
    con.executescript(mig)
    con.executescript(mig)
    rows = dict(con.execute("SELECT id, public_base_url FROM settings").fetchall())
    assert rows[1] == "https://still-base-ac7a.rizwanahmedsora9.workers.dev"
    assert rows[2] == "https://custom.example.workers.dev"
    assert rows[3] == ""

    with app.app_context():
        admin_id = User.query.filter_by(username="Admin").first().id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    # Settings UI shows the default Worker URL and saves edits + blank resets.
    settings_page = client.get("/settings")
    assert settings_page.status_code == 200
    assert "https://still-base-ac7a.rizwanahmedsora9.workers.dev" in settings_page.get_data(as_text=True)

    saved = client.post("/update_settings", data={
        "company_name": "Test Shop",
        "public_base_url": "https://custom-qr.workers.dev/",
    }, follow_redirects=True)
    assert saved.status_code == 200
    with app.app_context():
        assert Settings.query.first().public_base_url == "https://custom-qr.workers.dev"
        from app.services.public_url import resolve_public_base_url
        assert resolve_public_base_url() == "https://custom-qr.workers.dev"

    # Reject invalid URLs cleanly without overwriting valid setting.
    bad = client.post("/update_settings", data={
        "company_name": "Test Shop",
        "public_base_url": "https://custom-qr.workers.dev/some/path",
    }, follow_redirects=True)
    assert bad.status_code == 200
    with app.app_context():
        assert Settings.query.first().public_base_url == "https://custom-qr.workers.dev"

    # Clearing to blank falls back cleanly without breaking.
    cleared = client.post("/update_settings", data={
        "company_name": "Test Shop",
        "public_base_url": "",
    }, follow_redirects=True)
    assert cleared.status_code == 200
    with app.app_context():
        assert Settings.query.first().public_base_url == ""
        from app.services.public_url import resolve_public_base_url
        assert resolve_public_base_url() == ""

