"""Daily database backup — saved outside instance/, one file per day, emailed.

Contract under test:

* the backup is a valid SQLite copy of the live database (same tables, same
  rows) written OUTSIDE ``instance/``;
* exactly one run per Pakistan calendar day unless forced, and retention = 1
  means the newest file replaces the old one;
* a failed copy never leaves a partial file behind and never deletes the last
  good backup;
* the file can be emailed through SMTP, and a mail failure is reported without
  losing the saved backup;
* the admin page guards, saves and lists without ever exposing the password.
"""
from __future__ import annotations

import os
import socketserver
import sqlite3
import threading
from email import policy
from email.parser import Parser
from pathlib import Path

import pytest

from tests.conftest import make_csrf_client


# ---------------------------------------------------------------------------
# A tiny SMTP server: records messages, always accepts them.
# ---------------------------------------------------------------------------
class _Mailbox(socketserver.StreamRequestHandler):
    def handle(self):
        self.server.messages = getattr(self.server, "messages", [])
        self.wfile.write(b"220 fake smtp\r\n")
        in_data = False
        body: list[str] = []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if in_data:
                if text == ".":
                    in_data = False
                    self.server.messages.append("\n".join(body))
                    self.wfile.write(b"250 queued\r\n")
                else:
                    body.append(text)
                continue
            upper = text.upper()
            if upper.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-fake\r\n250 AUTH LOGIN PLAIN\r\n")
            elif upper.startswith("AUTH"):
                if "PLAIN" in upper:
                    self.wfile.write(b"235 ok\r\n")
                else:
                    self.wfile.write(b"334 VXNlcm5hbWU6\r\n")
            elif upper.startswith(("MAIL FROM", "RCPT TO")):
                self.wfile.write(b"250 ok\r\n")
            elif upper == "DATA":
                in_data = True
                self.wfile.write(b"354 go ahead\r\n")
            elif upper == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


@pytest.fixture()
def smtp_server():
    server = socketserver.TCPServer(("127.0.0.1", 0), _Mailbox)
    server.messages = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def backup_app(app_factory, tmp_path):
    return app_factory(
        BACKUP_DIR=str(tmp_path / "outside_instance" / "db"),
        MAINTENANCE_TEMP_DIR=str(tmp_path / "maintenance_tmp"),
        MIN_FREE_DISK_BYTES="0",
    )


def _configure(app, **values):
    from app.services import daily_backup
    from models import db

    with app.app_context():
        row = daily_backup.get_settings()
        for key, value in values.items():
            setattr(row, key, value)
        db.session.commit()
        return row


def _backdate(app, days: int) -> None:
    """Push every existing backup file back *days* days (simulates a real day)."""
    from app.services import daily_backup

    for path in daily_backup.list_backups(app):
        stamp = path.stat().st_mtime - days * 86400
        os.utime(path, (stamp, stamp))


# ---------------------------------------------------------------------------
# Backup creation
# ---------------------------------------------------------------------------
def test_backup_written_outside_instance_with_live_data(backup_app, app_factory):
    from app.services import daily_backup

    app = backup_app
    assert Path(app.config["BACKUP_DIR"]).resolve() != Path(app.instance_path).resolve()
    assert Path(app.instance_path).resolve() not in Path(app.config["BACKUP_DIR"]).resolve().parents

    with app.app_context():
        result = daily_backup.run_daily_backup(app, force=False, send_email=False)
        assert result["ok"] and result["created"]
        path = Path(result["path"])
        assert path.is_file()
        assert path.name.startswith("ams_db_")
        assert path.parent == Path(app.config["BACKUP_DIR"]).resolve()

        live = sqlite3.connect(app.config["APP_DB_PATH"])
        live_users = live.execute("SELECT username FROM user ORDER BY username").fetchall()
        live_tables = live.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        live.close()

        copy = sqlite3.connect(path)
        assert copy.execute("SELECT username FROM user ORDER BY username").fetchall() == live_users
        assert copy.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0] == live_tables
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert copy.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        copy.close()


def test_wal_source_produces_single_self_contained_file(backup_app, app_factory, tmp_path):
    """A WAL database must not become a .db plus a sidecar holding the data.

    SQLite's backup API keeps the source journal mode.  Without sealing, the
    published copy is ``x.db`` + ``x.db-wal`` where committed rows still live
    in the WAL — a lone emailed ``.db`` would then look empty.  The copy must be
    one rollback-journal file that contains every row.
    """
    from app.services import daily_backup
    from models import Client, db

    app = app_factory(
        db_file=tmp_path / "wal_live.db",
        BACKUP_DIR=str(Path(backup_app.config["BACKUP_DIR"])),
        MAINTENANCE_TEMP_DIR=str(backup_app.config["MAINTENANCE_TEMP_DIR"]),
        MIN_FREE_DISK_BYTES="0",
        SQLITE_JOURNAL_MODE="WAL",
    )
    assert app.config["SQLITE_JOURNAL_MODE"] == "WAL"
    live = sqlite3.connect(app.config["APP_DB_PATH"])
    assert live.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    live.close()
    with app.app_context():
        # A row committed just before the copy: in WAL mode it may still be in
        # the -wal file rather than the main database file.
        db.session.add(Client(code="WAL-TEST", name="Wal Test Client", is_active=True))
        db.session.commit()

        result = daily_backup.run_daily_backup(app, force=True, send_email=False)
        path = Path(result["path"])
        assert path.is_file()

        backup_dir = path.parent
        published_names = sorted(p.name for p in backup_dir.iterdir())
        assert published_names == [path.name], (
            "the backup folder must contain only the database file, "
            f"found sidecars: {published_names}"
        )

        copy = sqlite3.connect(path)
        try:
            assert copy.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
            names = [r[0] for r in copy.execute("SELECT code FROM client")]
            assert "WAL-TEST" in names, "rows committed in the WAL must be inside the copy"
        finally:
            copy.close()


def test_once_per_day_and_retention_replaces_old_file(backup_app):
    from app.services import daily_backup

    app = backup_app
    with app.app_context():
        first = daily_backup.run_daily_backup(app, force=False, send_email=False)
        assert first["created"] is True
        second = daily_backup.run_daily_backup(app, force=False, send_email=False)
        assert second["created"] is False, "a second automatic run the same day must be a no-op"
        assert daily_backup.backup_due(app) is False

        # The next calendar day replaces yesterday's file (keep_days = 1).
        _backdate(app, 1)
        assert daily_backup.backup_due(app) is True
        third = daily_backup.run_daily_backup(app, force=False, send_email=False)
        assert third["created"] is True
        files = daily_backup.list_backups(app)
        assert len(files) == 1, "keep_days=1 keeps exactly one file"
        assert files[0].name == Path(third["path"]).name
        assert Path(third["path"]).is_file()
        assert first["path"] not in [str(f) for f in files] or files[0].name != first["name"]
        assert not Path(first["path"]).exists()


def test_keep_days_retains_history(backup_app):
    from app.services import daily_backup

    app = backup_app
    _configure(app, keep_days=3)
    with app.app_context():
        for _ in range(3):
            daily_backup.run_daily_backup(app, force=True, send_email=False)
            _backdate(app, 1)
        assert len(daily_backup.list_backups(app)) == 3
        daily_backup.run_daily_backup(app, force=True, send_email=False)
        assert len(daily_backup.list_backups(app)) == 3


def test_same_second_force_runs_get_distinct_never_partial_files(backup_app):
    from app.services import daily_backup

    app = backup_app
    with app.app_context():
        first = daily_backup.run_daily_backup(app, force=True, send_email=False)
        second = daily_backup.run_daily_backup(app, force=True, send_email=False)
        # A distinct file per run — the old one is never overwritten mid-write.
        assert Path(first["path"]).name != Path(second["path"]).name
        assert "removed" in second
        # Retention (keep_days = 1) then keeps only the newest valid copy.
        files = daily_backup.list_backups(app)
        assert len(files) == 1
        assert files[0].name == Path(second["path"]).name
        assert files[0].is_file()
        daily_backup._validate_database(files[0])
        assert not list(Path(app.config["BACKUP_DIR"]).glob(".partial-*"))


def test_failed_backup_keeps_previous_good_file(backup_app, monkeypatch):
    from app.services import daily_backup

    app = backup_app
    with app.app_context():
        from pathlib import Path as _Path

        good = daily_backup.run_daily_backup(app, force=True, send_email=False)
        assert good["created"]

        # Break the SQLite copy step inside create_daily_backup (not the test's
        # own clock helper, which also touches files).
        import sqlite3 as real_sqlite3

        def boom(*_args, **_kwargs):
            raise real_sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(daily_backup, "sqlite3", type("X", (), {"connect": staticmethod(boom)}))
        bad = daily_backup.run_daily_backup(app, force=True, send_email=False)
        monkeypatch.undo()

        assert bad["ok"] is False
        assert "disk I/O error" in bad["message"]
        files = daily_backup.list_backups(app)
        assert [f.name for f in files] == [_Path(good["path"]).name]
        assert not list(Path(app.config["BACKUP_DIR"]).glob(".partial-*"))
        assert daily_backup.latest_backup(app).is_file()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def test_backup_emailed_with_attachment(backup_app, smtp_server, monkeypatch):
    from app.services import daily_backup

    monkeypatch.setenv("AMS_BACKUP_SMTP_PASSWORD", "app-password")
    app = backup_app
    _configure(
        app,
        enabled=True,
        recipient_emails="owner@example.com, accounts@example.com",
        mail_host="127.0.0.1",
        mail_port=smtp_server.server_address[1],
        mail_security="none",
        mail_username="bot@example.com",
        mail_from="backups@example.com",
        email_db_attachment=True,
    )
    with app.app_context():
        result = daily_backup.run_daily_backup(app, force=True, send_email=True)
        assert result["ok"] and result["emailed"] is True
        assert "emailed" in result["message"]

    assert len(smtp_server.messages) == 1
    message = Parser(policy=policy.default).parsestr(smtp_server.messages[0])
    assert message["To"] == "owner@example.com, accounts@example.com"
    assert "backups@example.com" in message["From"]
    attachments = [
        part for part in message.walk() if part.get_content_disposition() == "attachment"
    ]
    assert len(attachments) == 1
    assert attachments[0].get_filename().startswith("ams_db_")
    payload = attachments[0].get_payload(decode=True)
    assert payload[:16] == b"SQLite format 3\x00"
    assert len(payload) == result["size_bytes"]


def test_email_failure_keeps_backup_and_reports(backup_app):
    from app.services import daily_backup

    app = backup_app
    _configure(
        app,
        enabled=True,
        recipient_emails="owner@example.com",
        mail_host="127.0.0.1",
        mail_port=1,  # nothing listens here
        mail_security="none",
        mail_username="bot@example.com",
        mail_from="bot@example.com",
        smtp_timeout_seconds=5,
    )
    with app.app_context():
        result = daily_backup.run_daily_backup(app, force=True, send_email=True)
        assert result["created"] is True
        assert result["emailed"] is False
        assert result["email_status"] == "failed"
        assert Path(result["path"]).is_file()
        assert daily_backup.latest_backup(app).is_file()


def test_email_settings_required(backup_app):
    from app.services import daily_backup

    app = backup_app
    _configure(app, enabled=True, recipient_emails="", mail_host="smtp.example.com")
    with app.app_context():
        result = daily_backup.run_daily_backup(app, force=True, send_email=True)
        assert result["emailed"] is False
        assert result["created"] is True


def test_missing_password_reports_actionable_error(backup_app, smtp_server, monkeypatch):
    from app.services import daily_backup

    monkeypatch.delenv("AMS_BACKUP_SMTP_PASSWORD", raising=False)
    app = backup_app
    _configure(
        app,
        enabled=True,
        recipient_emails="owner@example.com",
        mail_host="127.0.0.1",
        mail_port=smtp_server.server_address[1],
        mail_security="none",
        mail_username="bot@example.com",
        mail_from="bot@example.com",
    )
    with app.app_context():
        result = daily_backup.run_daily_backup(app, force=True, send_email=True)
        assert result["created"] is True
        assert result["emailed"] is False
        assert "AMS_BACKUP_SMTP_PASSWORD" in result["email_error"]


def test_stale_lock_is_recovered_but_live_lock_is_honoured(backup_app):
    import json
    import time as _time

    from app.services import daily_backup

    app = backup_app
    root = Path(app.config["BACKUP_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    lock_dir = root / daily_backup._LOCK_DIR_NAME

    with app.app_context():
        # A lock owned by a pid that is not running AND older than the window
        # must not block backups forever.
        lock_dir.mkdir()
        (lock_dir / "owner.json").write_text(json.dumps({"pid": 999999}), encoding="utf-8")
        old = _time.time() - 3 * 3600
        os.utime(lock_dir, (old, old))
        result = daily_backup.run_daily_backup(app, force=True, send_email=False)
        assert result["created"] is True
        assert not lock_dir.exists(), "the stale lock must be released after the run"

        # A lock owned by this live process is honoured.
        lock_dir.mkdir()
        (lock_dir / "owner.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        blocked = daily_backup.run_daily_backup(app, force=True, send_email=False)
        assert blocked["created"] is False
        assert "already running" in blocked["message"]
        assert lock_dir.exists(), "a live owner's lock must be left alone"
        import shutil as _shutil

        _shutil.rmtree(lock_dir, ignore_errors=True)


def test_password_never_persisted(backup_app):
    from app.services import daily_backup
    from models import DailyDbBackupSettings, db

    app = backup_app
    with app.app_context():
        _configure(app, mail_host="smtp.example.com", mail_username="bot@example.com")
        columns = {c.name for c in DailyDbBackupSettings.__table__.columns}
        assert not any("password" in name or "secret" in name for name in columns)
        snapshot = daily_backup.status_snapshot(app)
        assert set(snapshot) >= {"dir", "count", "files", "latest", "password_configured"}
        assert "password" not in str(snapshot.get("files"))


# ---------------------------------------------------------------------------
# Admin page
# ---------------------------------------------------------------------------
def _login(client):
    return client.post(
        "/login", data={"username": "Admin", "password": "Admin@fbm12345"}, follow_redirects=True
    )


def test_admin_backup_page_guarded(client):
    anon = client.get("/settings/daily-backup")
    assert anon.status_code in (302, 401)


def test_admin_backup_page_saves_settings(backup_app):
    app = backup_app
    admin = make_csrf_client(app)
    _login(admin)

    page = admin.get("/settings/daily-backup")
    assert page.status_code == 200
    assert b"Daily Database Backup" in page.data

    saved = admin.post(
        "/settings/daily-backup/save",
        data={
            "_csrf_token": "test-csrf-token",
            "enabled": "on",
            "run_at": "23:30",
            "recipient_emails": "Owner@Example.com, not-an-email, second@example.com",
            "keep_days": "1",
            "mail_host": "smtp.example.com",
            "mail_port": "587",
            "mail_security": "starttls",
            "mail_username": "bot@example.com",
            "mail_from": "backups@example.com",
            "email_db_attachment": "on",
        },
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert b"settings updated" in saved.data

    with app.app_context():
        from models import DailyDbBackupSettings

        row = DailyDbBackupSettings.query.first()
        assert row.enabled is True
        assert row.run_at == "23:30"
        assert row.recipient_emails == "Owner@Example.com, second@example.com"
        assert row.keep_days == 1

    run = admin.post("/settings/daily-backup/run-now", follow_redirects=True)
    assert run.status_code == 200
    download = admin.get("/settings/daily-backup/download")
    assert download.status_code == 200
    assert download.data[:16] == b"SQLite format 3\x00"


def test_admin_backup_page_rejects_bad_time(backup_app):
    app = backup_app
    admin = make_csrf_client(app)
    _login(admin)
    response = admin.post(
        "/settings/daily-backup/save",
        data={"_csrf_token": "test-csrf-token", "run_at": "25:99"},
        follow_redirects=True,
    )
    assert b"Run time must be" in response.data
    with app.app_context():
        from models import DailyDbBackupSettings

        assert DailyDbBackupSettings.query.first().run_at == "auto"


def test_enabling_without_recipient_is_refused(backup_app):
    app = backup_app
    admin = make_csrf_client(app)
    _login(admin)
    response = admin.post(
        "/settings/daily-backup/save",
        data={"_csrf_token": "test-csrf-token", "enabled": "on", "mail_host": "smtp.example.com"},
        follow_redirects=True,
    )
    assert b"recipient email" in response.data
    with app.app_context():
        from models import DailyDbBackupSettings

        assert DailyDbBackupSettings.query.first().enabled is False
