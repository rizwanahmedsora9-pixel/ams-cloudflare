"""Harness — boot the AMS app against a throw-away SQLite file and drive it.

Every run of the full-cycle mechanism imports this module.  Nothing here is
specific to one run: run-specific *data* lives in ``data.py`` and run-specific
*assertions* live in the run script.

Design rules
------------
* The database is always a scratch file under a run directory.  The mechanism
  never touches ``instance/`` or any production file.
* Every write POST goes through ``post()`` which follows redirects and captures
  the flash messages, so a check can assert on what a human would have seen.
* Every read helper returns *text*, never raw HTML, so assertions do not depend
  on markup details that a CSS change can break.
"""
from __future__ import annotations

import io
import os
import re
import sqlite3
import sys

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if os.path.join(REPO_ROOT, "tests") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

FLASH_RE = re.compile(
    r'<div class="alert alert-(\w+) alert-dismissible[^"]*"\s*role="alert">\s*(.*?)\s*<button',
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")


def text_of(html: str) -> str:
    """Rendered page -> one long line of human-readable text."""
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    return " ".join(TAG_RE.sub(" ", html).split())


def strip_tags(fragment: str) -> str:
    return " ".join(TAG_RE.sub(" ", fragment).split())


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------
def prepare_env(db_path: str, health_path: str = None, fresh: bool = True) -> None:
    """Point the app at a scratch DB and make boot non-interactive.

    ``fresh=True`` deletes the file first (a normal run).  ``fresh=False``
    re-opens an existing run's DB, which is how a failed run is debugged
    without re-seeding — and how you avoid accidentally wiping evidence.
    """
    if fresh:
        for suffix in ("", "-wal", "-shm"):
            target = db_path + suffix
            if os.path.exists(target):
                os.remove(target)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    os.environ["APP_DB_PATH"] = db_path
    os.environ["DB_HEALTH_SNAPSHOT_PATH"] = health_path or (db_path + ".health.json")
    os.environ["BACKUP_EMBEDDED_SCHEDULER"] = "0"
    os.environ["ALLOW_EMPTY_DB"] = "1"
    os.environ.setdefault("ALLOW_DB_DROP", "1")


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
class Session:
    """A logged-in CSRF-aware test client plus all the read helpers."""

    def __init__(self, app, client):
        self.app = app
        self.client = client

    # -- raw ------------------------------------------------------------
    def get(self, path, **kw):
        return self.client.get(path, **kw)

    def post(self, path, data=None, **kw):
        kw.setdefault("follow_redirects", True)
        return self.client.post(path, data=data or {}, **kw)

    # -- read helpers ---------------------------------------------------
    def page(self, path) -> tuple[int, str]:
        """GET -> (status, text)."""
        r = self.get(path)
        return r.status_code, text_of(r.get_data(as_text=True))

    def html(self, path) -> tuple[int, str]:
        r = self.get(path)
        return r.status_code, r.get_data(as_text=True)

    def json(self, path):
        r = self.get(path)
        try:
            return r.status_code, r.get_json()
        except Exception:
            return r.status_code, None

    def bytes(self, path) -> tuple[int, bytes, str]:
        r = self.get(path)
        return r.status_code, r.data, r.headers.get("Content-Type", "")

    def pdf_text(self, path) -> tuple[int, int, str]:
        """GET a PDF -> (status, bytes_len, extracted_text)."""
        status, data, _ctype = self.bytes(path)
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            body = " ".join((p.extract_text() or "") for p in reader.pages)
            return status, len(data), " ".join(body.split())
        except Exception as exc:  # not a PDF, or unreadable
            return status, len(data), f"<<pdf read failed: {exc}>>"

    # -- write helper ---------------------------------------------------
    def flashes(self, response) -> list[tuple[str, str]]:
        body = response.get_data(as_text=True) if not isinstance(response, str) else response
        return [(cat, strip_tags(msg)) for cat, msg in FLASH_RE.findall(body)]

    def flash_text(self, response) -> str:
        return " | ".join(f"{c}: {m}" for c, m in self.flashes(response))


# --------------------------------------------------------------------------
# Boot
# --------------------------------------------------------------------------
def boot(db_path: str, health_path: str = None, username: str = "Admin",
         password: str = "Admin@fbm12345", fresh: bool = True) -> Session:
    """Create the app on ``db_path``, log in, return a :class:`Session`."""
    prepare_env(db_path, health_path, fresh=fresh)

    from app import create_app  # noqa: E402  (import after env is set)
    from tests.conftest import make_csrf_client  # noqa: E402

    app = create_app()
    app.config["TESTING"] = True
    client = make_csrf_client(app)
    client.post("/login", data={"username": username, "password": password},
                follow_redirects=True)
    return Session(app, client)


# --------------------------------------------------------------------------
# Database inspection
# --------------------------------------------------------------------------
class Db:
    """Read-only view on the scratch SQLite file, for row-level assertions."""

    def __init__(self, path: str):
        self.path = path

    def rows(self, sql: str, args: tuple = ()) -> list[dict]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        found = self.rows(sql, args)
        return found[0] if found else None

    def scalar(self, sql: str, args: tuple = ()):
        row = self.one(sql, args)
        return next(iter(row.values())) if row else None

    def tables(self) -> list[str]:
        return [r["name"] for r in self.rows(
            "select name from sqlite_master where type='table' order by name")]

    def counts(self) -> dict[str, int]:
        out = {}
        for table in self.tables():
            if table.startswith("sqlite_"):
                continue
            try:
                out[table] = int(self.scalar(f'select count(*) from "{table}"') or 0)
            except Exception:
                out[table] = -1
        return out


# --------------------------------------------------------------------------
# Small formatting utilities used by the checks
# --------------------------------------------------------------------------
def money(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def contains_any(haystack: str, needles) -> bool:
    return any(n in haystack for n in needles)


def first_after(text: str, label: str, width: int = 120) -> str:
    """Text right after ``label`` — handy for 'KPI label -> value' checks."""
    index = text.find(label)
    return text[index:index + width] if index >= 0 else ""
