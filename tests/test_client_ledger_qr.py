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
    """More -> QR Code: the in-ledger dialog generates and shows the big QR."""
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

    # The ledger's "More" menu opens this dialog.
    dialog = client.get(f"/client_ledger_qr/{client_id}/dialog")
    assert dialog.status_code == 200
    body = dialog.get_data(as_text=True)
    assert "Generate QR Code" in body
    assert 'name="dialog" value="1"' in body
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', body).group(1)

    # Generating inside the dialog returns the QR fragment (not a new page),
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
        assert db.session.get(Client, client_id).client_ledger_qr_token_hash

    # The dialog needs staff permission.
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get(f"/client_ledger_qr/{client_id}/dialog").status_code in (302, 401, 403)


def test_client_qr_can_be_reprinted_without_rotating(app, client, monkeypatch):
    """The active QR can be printed again — the same code stays valid."""
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

    # Generate the first QR.
    page = client.get(f"/client_ledger_qr/{client_id}")
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"',
                      page.get_data(as_text=True)).group(1)
    first = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "generate", "qr_nonce": nonce,
    })
    assert first.status_code == 200
    assert b"<svg" in first.data

    with app.app_context():
        row = db.session.get(Client, client_id)
        hash_after_generate = row.client_ledger_qr_token_hash
        salt = row.client_ledger_qr_token_salt
        assert salt
        token = qr_routes._derive_token(row, salt)
        assert len(token) == 43
        assert hashlib.sha256(token.encode("ascii")).hexdigest() == hash_after_generate
    assert client.get(f"/c/{token}").status_code == 200

    # The settings page now offers reprinting the active QR.
    page = client.get(f"/client_ledger_qr/{client_id}")
    body = page.get_data(as_text=True)
    assert "Print current QR" in body
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

    # The dialog also offers reprinting, without rotating.
    dialog = client.get(f"/client_ledger_qr/{client_id}/dialog")
    body = dialog.get_data(as_text=True)
    assert "Print current QR" in body
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
    nonce = re.search(r'name="qr_nonce" value="([^"]+)"', body).group(1)
    rejected = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "print", "qr_nonce": nonce,
    })
    assert rejected.status_code == 409
    assert b"before reprint support" in rejected.data
    # The existing public link still works.
    assert client.get(f"/c/{token}").status_code == 200


def test_material_ledger_page_opens_qr_dialog_and_generates_in_it(app, client):
    """The Client Ledger page opens the QR dialog without the settings page."""
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
    assert "Generate QR Code" in frag
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
    rejected = client.post(f"/client_ledger_qr/{client_id}", data={
        "action": "generate", "dialog": "1", "qr_nonce": form_nonce,
        "_csrf_token": "invalid",
    })
    assert rejected.status_code == 400
    assert "Reload the page" in rejected.get_json()["error"]
    with app.app_context():
        assert db.session.get(Client, client_id).client_ledger_qr_token_hash is None
