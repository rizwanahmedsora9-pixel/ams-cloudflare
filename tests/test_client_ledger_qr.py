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
