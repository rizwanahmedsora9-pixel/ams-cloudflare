"""P1: suspension must stop existing sessions without logging out other users.

All cases use the real authentication/session hooks and disposable databases.
CSRF is deliberately enforced, including in tests, so a security fix cannot
pass only because the normal form-token gate was disabled.
"""
from __future__ import annotations

import sqlite3
from urllib.parse import urlsplit

import pytest
from werkzeug.security import generate_password_hash

from models import Client, User, db
from tests.conftest import make_csrf_client


PASSWORD = "p1-regression-password"


@pytest.fixture()
def p1_app(app_factory):
    return app_factory(
        AMS_CSRF_ALWAYS="1",
        AUTO_RECONCILE_ENABLED="0",
        AMS_DAILY_BACKUP_SCHEDULER="0",
    )


def _add_user(app, username, *, role="user", status="active", access_mode="read_write"):
    with app.app_context():
        user = User(
            username=username,
            password_hash=generate_password_hash(PASSWORD),
            role=role,
            status=status,
            access_mode=access_mode,
            can_manage_clients=True,
            can_view_dashboard=True,
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(browser, username="Admin", password="Admin@fbm12345"):
    response = browser.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.get_data(as_text=True)
    return response


def _assert_login_redirect(response):
    assert response.status_code == 302
    assert urlsplit(response.headers["Location"]).path == "/login"


def _client_form(code):
    return {
        "name": f"P1 customer {code}",
        "code": code,
        "category": "General",
        "opening_balance": "0",
        "opening_balance_date": "2026-11-01",
    }


def _client_count(app, code):
    with app.app_context():
        return Client.query.filter_by(code=code).count()


def _status(app, user_id):
    with app.app_context():
        return db.session.get(User, user_id).status


@pytest.mark.parametrize("role", ["user", "admin"])
def test_suspension_blocks_existing_session_get_and_write(p1_app, role):
    user_id = _add_user(p1_app, "target-manager", role=role)
    peer_id = _add_user(p1_app, "active-peer")
    browser = make_csrf_client(p1_app)
    peer = make_csrf_client(p1_app)
    admin = make_csrf_client(p1_app)
    _login(browser, "target-manager", PASSWORD)
    _login(peer, "active-peer", PASSWORD)
    _login(admin)
    assert browser.get("/clients").status_code == 200

    suspended = admin.post(f"/toggle_user_status/{user_id}")
    assert suspended.status_code == 302
    assert _status(p1_app, user_id) == "inactive"

    _assert_login_redirect(browser.get("/clients"))
    _assert_login_redirect(
        browser.post("/add_client", data=_client_form("P1-BLOCKED"))
    )
    assert _client_count(p1_app, "P1-BLOCKED") == 0

    # Status revocation is per account, not a global session/logout action.
    assert peer.get("/clients").status_code == 200
    assert peer.post("/add_client", data=_client_form("P1-PEER-OK")).status_code == 302
    assert _client_count(p1_app, "P1-PEER-OK") == 1
    assert admin.get("/settings").status_code == 200
    assert _status(p1_app, peer_id) == "active"


def test_remember_me_cookie_cannot_restore_a_suspended_user(p1_app):
    user_id = _add_user(p1_app, "remembered-clerk")
    original = make_csrf_client(p1_app)
    admin = make_csrf_client(p1_app)
    _login(original, "remembered-clerk", PASSWORD)
    _login(admin)
    remember = original.get_cookie("remember_token")
    assert remember is not None

    restored = make_csrf_client(p1_app)
    restored.set_cookie("remember_token", remember.value)
    assert restored.get("/clients").status_code == 200

    assert admin.post(f"/toggle_user_status/{user_id}").status_code == 302
    # Remove the ordinary session cookie so Flask-Login must use remember-me.
    restored.delete_cookie("ams_session")
    _assert_login_redirect(restored.get("/clients"))
    _assert_login_redirect(
        restored.post("/add_client", data=_client_form("P1-REMEMBER-BLOCKED"))
    )
    assert _client_count(p1_app, "P1-REMEMBER-BLOCKED") == 0


def test_suspension_from_another_connection_applies_without_restart(p1_app):
    user_id = _add_user(p1_app, "lan-clerk")
    browser = make_csrf_client(p1_app)
    _login(browser, "lan-clerk", PASSWORD)
    assert browser.get("/clients").status_code == 200

    # Simulate another worker/administrator committing the status change.
    connection = sqlite3.connect(p1_app.config["APP_DB_PATH"])
    try:
        connection.execute('UPDATE "user" SET status=? WHERE id=?', ("inactive", user_id))
        connection.commit()
    finally:
        connection.close()

    _assert_login_redirect(browser.get("/clients"))
    _assert_login_redirect(
        browser.post("/add_client", data=_client_form("P1-CROSS-WORKER"))
    )
    assert _client_count(p1_app, "P1-CROSS-WORKER") == 0


def test_all_existing_devices_for_the_suspended_account_are_blocked(p1_app):
    user_id = _add_user(p1_app, "two-device-clerk")
    first = make_csrf_client(p1_app)
    second = make_csrf_client(p1_app)
    admin = make_csrf_client(p1_app)
    _login(first, "two-device-clerk", PASSWORD)
    _login(second, "two-device-clerk", PASSWORD)
    _login(admin)
    assert first.get("/clients").status_code == 200
    assert second.get("/clients").status_code == 200

    assert admin.post(f"/toggle_user_status/{user_id}").status_code == 302
    _assert_login_redirect(first.get("/clients"))
    _assert_login_redirect(second.get("/clients"))


def test_deactivation_route_also_blocks_an_existing_session(p1_app):
    user_id = _add_user(p1_app, "deactivated-clerk", role="admin")
    browser = make_csrf_client(p1_app)
    admin = make_csrf_client(p1_app)
    _login(browser, "deactivated-clerk", PASSWORD)
    _login(admin)
    assert browser.get("/clients").status_code == 200

    assert admin.post(f"/delete_user/{user_id}").status_code == 302
    assert _status(p1_app, user_id) == "inactive"
    _assert_login_redirect(browser.get("/clients"))
    _assert_login_redirect(
        browser.post("/add_client", data=_client_form("P1-DEACTIVATED"))
    )
    assert _client_count(p1_app, "P1-DEACTIVATED") == 0
    with p1_app.app_context():
        # Deactivation remains orphan-safe: the historical User row is retained.
        assert db.session.get(User, user_id) is not None


def test_reactivation_allows_a_new_login_and_authorized_write(p1_app):
    user_id = _add_user(p1_app, "returning-clerk")
    old_browser = make_csrf_client(p1_app)
    admin = make_csrf_client(p1_app)
    _login(old_browser, "returning-clerk", PASSWORD)
    _login(admin)
    assert admin.post(f"/toggle_user_status/{user_id}").status_code == 302
    _assert_login_redirect(old_browser.get("/clients"))

    assert admin.post(f"/toggle_user_status/{user_id}").status_code == 302
    assert _status(p1_app, user_id) == "active"
    new_browser = make_csrf_client(p1_app)
    _login(new_browser, "returning-clerk", PASSWORD)
    assert new_browser.get("/clients").status_code == 200
    assert new_browser.post("/add_client", data=_client_form("P1-REACTIVATED")).status_code == 302
    assert _client_count(p1_app, "P1-REACTIVATED") == 1


def test_suspended_password_login_remains_blocked(p1_app):
    _add_user(p1_app, "suspended-clerk", status="inactive")
    browser = make_csrf_client(p1_app)
    response = browser.post(
        "/login", data={"username": "suspended-clerk", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert "Account suspended" in response.get_data(as_text=True)
    with browser.session_transaction() as sess:
        assert "_user_id" not in sess
    _assert_login_redirect(browser.get("/clients"))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("active", True),
        ("ACTIVE", True),
        (" active ", True),
        ("inactive", False),
        ("INACTIVE", False),
        ("suspended", False),
        ("", False),
        (None, False),
    ],
)
def test_user_active_flag_uses_the_existing_login_status_rule(status, expected):
    assert User(username="status-case", status=status).is_active is expected


def test_legacy_whitespace_active_status_keeps_working(p1_app):
    _add_user(p1_app, "legacy-active-clerk", status=" ACTIVE ")
    browser = make_csrf_client(p1_app)
    _login(browser, "legacy-active-clerk", PASSWORD)
    assert browser.get("/clients").status_code == 200


def test_active_read_only_user_keeps_view_access_but_cannot_write(p1_app):
    _add_user(p1_app, "read-only-clerk", access_mode="read_only")
    browser = make_csrf_client(p1_app)
    _login(browser, "read-only-clerk", PASSWORD)
    assert browser.get("/clients").status_code == 200
    response = browser.post("/add_client", data=_client_form("P1-READ-ONLY"))
    assert response.status_code == 302
    assert urlsplit(response.headers["Location"]).path != "/login"
    assert _client_count(p1_app, "P1-READ-ONLY") == 0


def test_suspended_write_still_requires_csrf_and_public_login_still_works(p1_app):
    user_id = _add_user(p1_app, "csrf-clerk")
    browser = make_csrf_client(p1_app)
    admin = make_csrf_client(p1_app)
    _login(browser, "csrf-clerk", PASSWORD)
    _login(admin)
    assert admin.post(f"/toggle_user_status/{user_id}").status_code == 302

    raw = p1_app.test_client()
    session_cookie = browser.get_cookie("ams_session")
    assert session_cookie is not None
    raw.set_cookie("ams_session", session_cookie.value)
    assert raw.post("/add_client", data=_client_form("P1-NO-CSRF")).status_code == 400
    assert _client_count(p1_app, "P1-NO-CSRF") == 0
    assert raw.get("/login").status_code == 200
    assert raw.get("/static/theme.css").status_code == 200
