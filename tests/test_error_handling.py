"""Regression tests for unhandled-error capture and transient SQLite retries.

These cover the "500 Internal Server Error appears by itself after a while"
failure mode: the page must carry a reference the log can be searched for, the
failed transaction must be rolled back, and a *transient* SQLite lock must be
retried instead of surfacing as a 500 for the user.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services import errors as errors_service


def _boom_route(app, path, func_name, view):
    app.add_url_rule(path, func_name, view)


def test_unhandled_exception_shows_reference_and_writes_traceback(app, client):
    calls = {"n": 0}

    def _explode():
        calls["n"] += 1
        return 1 / 0

    _boom_route(app, "/__test/boom", "test_boom", _explode)
    response = client.get("/__test/boom")

    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "E-" in body
    reference = body.split("E-")[1][:6]
    assert len(reference) == 6

    log_path = errors_service.error_log_path(app)
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    record = records[-1]
    assert record["exception"] == "ZeroDivisionError"
    assert record["reference"] == "E-" + reference
    assert record["path"] == "/__test/boom"
    assert "ZeroDivisionError" in record["traceback"]
    assert record["transient_db"] is False
    assert calls["n"] == 1, "a programming error must never be retried"


def test_api_paths_get_json_errors_with_the_same_reference(app, client):
    _boom_route(app, "/api/__test/boom", "test_api_boom", lambda: {}["missing"])

    response = client.get("/api/__test/boom")

    assert response.status_code == 500
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_reference"].startswith("E-")
    assert payload["retryable"] is False
    assert "[client-ledger-token]" not in json.dumps(payload)


def test_http_404_and_redirects_are_not_converted_to_500(app, client):
    assert client.get("/definitely-not-a-route").status_code == 404


def test_client_ledger_token_is_not_written_to_the_error_log(app):
    # /c/<token> links are bearer credentials: the token must never be stored.
    assert errors_service._safe_path("/c/supersecretbearertoken") == "/c/[client-ledger-token]"
    with app.test_request_context("/c/supersecretbearertoken"):
        errors_service.record_exception(RuntimeError("token route failed"), app=app)

    log_text = errors_service.error_log_path(app).read_text(encoding="utf-8")
    assert "supersecretbearertoken" not in log_text
    assert "[client-ledger-token]" in log_text


def test_transient_sqlite_lock_is_retried_once(app_factory, monkeypatch):
    monkeypatch.setenv("AMS_DB_RETRY", "1")
    app = app_factory()
    attempts = {"n": 0}

    def _busy_then_ok():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return "recovered"

    app.add_url_rule("/__test/busy", "test_busy", _busy_then_ok)
    response = app.test_client().get("/__test/busy")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "recovered"
    assert attempts["n"] == 2


def test_permanent_fault_is_not_retried(app_factory, monkeypatch):
    monkeypatch.setenv("AMS_DB_RETRY", "1")
    app = app_factory()
    attempts = {"n": 0}

    def _always_broken():
        attempts["n"] += 1
        raise RuntimeError("not a lock problem")

    app.add_url_rule("/__test/broken", "test_broken", _always_broken)
    response = app.test_client().get("/__test/broken")

    assert response.status_code == 500
    assert attempts["n"] == 1


def test_retry_is_disabled_by_environment(app_factory, monkeypatch):
    monkeypatch.setenv("AMS_DB_RETRY", "0")
    app = app_factory()

    assert not isinstance(app.wsgi_app, errors_service.DatabaseBusyRetryMiddleware)


def test_database_locked_is_classified_as_transient(app):
    with app.app_context():
        assert errors_service.is_transient_db_error(sqlite3.OperationalError("database is locked"))
        assert errors_service.is_transient_db_error(sqlite3.OperationalError("disk I/O error"))
        assert not errors_service.is_transient_db_error(
            sqlite3.DatabaseError("database disk image is malformed")
        )
        assert not errors_service.is_transient_db_error(RuntimeError("nope"))


def test_failed_request_rolls_the_session_back(app):
    from models import db

    def _fail():
        raise sqlite3.OperationalError("database is locked")

    with app.test_request_context("/__test/rollback"):
        db.session.execute(db.text("SELECT 1"))
        with pytest.raises(sqlite3.OperationalError):
            _fail()
        errors_service.record_exception(sqlite3.OperationalError("database is locked"), app=app)
        assert not db.session().in_transaction()


def test_reconcile_worker_resolves_the_real_app(app):
    from flask import current_app

    from utils.reconciliation import real_app

    with app.app_context():
        assert real_app(current_app) is app
    # Outside a context a proxy cannot be resolved — the caller must not crash.
    outside = real_app(current_app)
    assert outside is None or hasattr(outside, "app_context")


def test_reconcile_backup_copy_is_a_valid_database(app):
    from models import db

    from utils.reconciliation import _safe_copy_db

    target_dir = Path(app.instance_path) / "reconcile_backups"
    with app.app_context():
        db.session.execute(db.text("SELECT 1"))
        db_path = app.config["APP_DB_PATH"]

    copied = _safe_copy_db(db_path, str(target_dir))

    assert copied and Path(copied).is_file()
    connection = sqlite3.connect(copied)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()
    assert "user" in tables


def test_load_user_retries_a_transient_database_lock(monkeypatch):
    """A busy database must not silently log the user out."""
    from types import SimpleNamespace

    from app.services import permissions

    class _Session:
        calls = 0

        def get(self, _model, uid):
            _Session.calls += 1
            if _Session.calls == 1:
                raise sqlite3.OperationalError("database is locked")
            return SimpleNamespace(id=uid, username="Admin")

        def rollback(self):
            pass

    monkeypatch.setattr(permissions, "db", SimpleNamespace(session=_Session()))
    monkeypatch.setattr(permissions.time, "sleep", lambda *_args: None)

    user = permissions.load_user("1")

    assert user is not None and user.username == "Admin"
    assert _Session.calls == 2


def test_load_user_gives_up_quietly_on_a_real_fault(monkeypatch):
    from types import SimpleNamespace

    from app.services import permissions

    class _Session:
        calls = 0

        def get(self, _model, _uid):
            _Session.calls += 1
            raise sqlite3.DatabaseError("database disk image is malformed")

        def rollback(self):
            pass

    monkeypatch.setattr(permissions, "db", SimpleNamespace(session=_Session()))
    monkeypatch.setattr(permissions.time, "sleep", lambda *_args: None)

    assert permissions.load_user("1") is None
    assert _Session.calls == 1
    assert permissions.load_user("not-a-number") is None


def _login(client, username="Admin", password="Admin@fbm12345"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_recent_errors_feed_requires_a_session(app, client):
    assert client.get("/debug/recent_errors").status_code == 302


def test_recent_errors_feed_lists_the_last_failure(app, client):
    _boom_route(app, "/__test/feed_boom", "test_feed_boom", lambda: 1 / 0)
    assert _login(client).status_code == 302
    assert client.get("/__test/feed_boom").status_code == 500

    response = client.get("/debug/recent_errors")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["count"] >= 1
    newest = payload["errors"][0]
    assert newest["reference"].startswith("E-")
    assert newest["path"] == "/__test/feed_boom"
    assert "ZeroDivisionError" in newest["traceback_tail"]
    assert "traceback" not in newest


def test_recent_errors_feed_is_closed_to_regular_users(app, client):
    from werkzeug.security import generate_password_hash

    from models import User, db

    with app.app_context():
        db.session.add(User(username="clerk", password_hash=generate_password_hash("clerk-pass-1"), role="staff"))
        db.session.commit()

    assert _login(client, "clerk", "clerk-pass-1").status_code == 302
    assert client.get("/debug/recent_errors").status_code == 403
