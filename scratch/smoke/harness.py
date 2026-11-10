"""HTTP harness for the end-to-end smoke journey.

Nothing here fakes the application: it talks to a real Werkzeug server over a
real socket, authenticates with the real login form, carries the real session
cookie and submits the real forms that the real pages render (including the
CSRF token and every hidden field the page defines).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

ALERT_RE = re.compile(
    r'<div class="alert alert-(success|danger|warning|info)[^"]*"[^>]*>\s*(.*?)\s*<button',
    re.S,
)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


@dataclass
class Result:
    step: str
    ok: bool
    detail: str = ""
    page: str = ""
    kind: str = "check"          # check | page | write | wipe | read
    seconds: float = 0.0


class Journey:
    """Browser-like session with recording of every request."""

    def __init__(self, base_url: str = "http://127.0.0.1:5099",
                 user: str = "Admin", password: str = "Admin@fbm12345",
                 log: dict | None = None, db_path: str | None = None):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "AMS-Smoke-Journey/1.0"
        shared = log if log is not None else {}
        shared.setdefault("requests", [])
        shared.setdefault("results", [])
        self.user = user
        self.password = password
        self.csrf = ""
        self.last_path = "/"
        self.last_response = None
        self.client_code = ""
        self.client_name = ""
        self.supplier_name = ""
        self.driver_name = ""
        self.material = ""
        self.material_code = ""
        self.service = ""
        self.bill_refs: dict[str, str] = {}
        self.ids: dict[str, int] = {}
        # Shared with every other session (anonymous/limited users) so one
        # journey still produces one request log and one report.
        self.requests, self.results = shared["requests"], shared["results"]
        # A secondary session (anonymous / limited user) passes ``log=self.log``
        # so every request still lands in the one report for the whole journey.
        self.log = shared
        # Optional: lets a failed login report the stored account row.
        self.db_path = db_path

    # ------------------------------------------------------------------ core
    def record(self, step, ok, detail="", page="", kind="check", seconds=0.0):
        self.results.append(Result(step, bool(ok), str(detail)[:700], page, kind, seconds))
        return ok

    def _log(self, method, url, status, note=""):
        self.requests.append({"method": method, "url": url, "status": status, "note": note})

    def request(self, method, path, **kwargs):
        allow_redirects = kwargs.pop("allow_redirects", False)
        if not path.startswith("http"):
            self.last_path = path
        url = path if path.startswith("http") else self.base + path
        started = time.time()
        resp = self.session.request(method, url, timeout=180,
                                    allow_redirects=allow_redirects, **kwargs)
        elapsed = time.time() - started
        self.last_response = resp
        self._log(method, path.split("?")[0], resp.status_code)
        # Track the session CSRF token from the cookie-based session via forms.
        if resp.status_code >= 500:
            self.record(f"{method} {path} -> {resp.status_code}", False,
                        clean(resp.text)[:400], page=path, kind="page", seconds=elapsed)
        return resp, elapsed

    def follow(self, resp, limit=5):
        """Follow redirects the way a browser does, returning the final page."""
        chain = []
        while resp.status_code in (301, 302, 303, 307, 308) and limit > 0:
            target = resp.headers.get("Location", "")
            chain.append(target)
            resp, elapsed = self.request("GET", target)
            limit -= 1
        return resp, chain

    def get(self, path, expect=200, kind="page", allow=()):
        resp, elapsed = self.request("GET", path)
        ok = resp.status_code in ((expect,) + tuple(allow))
        if not ok:
            self.record(f"GET {path} -> {resp.status_code}", False,
                        clean(resp.text)[:400], page=path, kind=kind, seconds=elapsed)
        elif kind in ("json", "file"):
            # Downloads and JSON feeds are judged by their status and payload,
            # never by the HTML error-page heuristic (a diagnostics feed quotes
            # tracebacks on purpose, and a PDF is not HTML at all).
            self.record(f"GET {path}", True, f"{resp.status_code} {len(resp.content)}B",
                        page=path, kind=kind, seconds=elapsed)
        elif kind == "page":
            body = resp.text
            broken = self.detect_error_page(body)
            if broken:
                self.record(f"GET {path} rendered an error page", False, broken,
                            page=path, kind="page", seconds=elapsed)
            else:
                self.record(f"GET {path}", True, f"{resp.status_code} {len(body)}B",
                            page=path, kind="page", seconds=elapsed)
        return resp

    @staticmethod
    def detect_error_page(html: str) -> str:
        low = html.lower()
        markers = [
            "traceback (most recent call last)",
            "internal server error",
            "jinja2.exceptions",
            "sqlalchemy.exc.",
            "something went wrong while building this page",
        ]
        for m in markers:
            if m in low:
                return f"page contains '{m}'"
        return ""

    # ------------------------------------------------------------------ pages
    def page(self, path, allow=()):
        return self.get(path, kind="page", allow=allow)

    def flashes(self, html: str):
        out = []
        for m in ALERT_RE.finditer(html):
            out.append((m.group(1), clean(m.group(2))))
        return out

    def flash_text(self, resp):
        return " | ".join(f"{c}: {t}" for c, t in self.flashes(resp.text))

    def danger(self, resp):
        return [t for c, t in self.flashes(resp.text) if c == "danger"]

    def csrf_token(self, html: str) -> str:
        m = re.search(r'name="_csrf_token"\s+value="([^"]+)"', html)
        if m:
            self.csrf = m.group(1)
        if not self.csrf:
            m = re.search(r'"csrf_token"\s*:\s*"([^"]+)"', html)
            if m:
                self.csrf = m.group(1)
        return self.csrf

    # ------------------------------------------------------------------ forms
    def soup(self, resp):
        soup = BeautifulSoup(resp.text, "html.parser")
        self.csrf_token(resp.text)
        return soup

    @staticmethod
    def form_fields(form) -> dict:
        data: dict[str, list[str]] = {}
        for el in form.find_all(["input", "select", "textarea"]):
            name = el.get("name")
            if not name or name in ("_csrf_token",):
                continue
            if el.name == "select":
                chosen = [o for o in el.find_all("option") if o.has_attr("selected")] or []
                values = [o.get("value", o.get_text(strip=True)) for o in chosen]
                if not values and el.find("option") is not None:
                    first = el.find("option")
                    values = [first.get("value", first.get_text(strip=True))]
                data.setdefault(name, []).extend(values)
            elif el.name == "textarea":
                data.setdefault(name, []).append(el.get_text() or "")
            else:
                itype = (el.get("type") or "text").lower()
                if itype in ("checkbox", "radio"):
                    if el.has_attr("checked"):
                        data.setdefault(name, []).append(el.get("value", "on"))
                    continue
                if itype in ("submit", "button", "file", "reset", "image"):
                    continue
                data.setdefault(name, []).append(el.get("value", "") or "")
        return data

    def find_form(self, soup, action_contains: str, index: int = 0):
        """Find the form whose action contains *action_contains*.

        A form with ``action=""`` posts back to the current URL, so it matches
        when the current path contains the needle (that is how /login renders).
        """
        matches = []
        for form in soup.find_all("form"):
            action = form.get("action") or ""
            if action_contains in action:
                matches.append(form)
            elif action == "" and action_contains in (self.last_path or ""):
                matches.append(form)
        if not matches:
            return None
        return matches[index] if index < len(matches) else None

    def submit(self, soup, form, overrides=None, action_override=None, files=None,
               note=""):
        """POST exactly this form, with overrides applied, like a human clicking."""
        overrides = overrides or {}
        data = self.form_fields(form)
        # A form may be posted without any field of its own (pure buttons).
        for key, value in overrides.items():
            # Browsers post the field name verbatim, brackets included
            # ("mat_name[]"), so the key must not be normalised here.
            values = value if isinstance(value, (list, tuple)) else [value]
            data[key] = [str(v) for v in values]
        payload = []
        for key, values in data.items():
            for value in values:
                payload.append((key, value))
        payload.append(("_csrf_token", self.csrf))
        action = action_override or (form.get("action") if form is not None else None)
        if not action:
            action = self.last_path or "/"
        if action.startswith("http"):
            action = action.split(self.base, 1)[-1] or "/"
        started = time.time()
        resp = self.session.post(self.base + action, data=payload, files=files,
                                 timeout=180, allow_redirects=False)
        elapsed = time.time() - started
        self._log("POST", action, resp.status_code, note)
        if resp.status_code >= 500:
            self.record(f"POST {action} -> {resp.status_code}", False,
                        clean(resp.text)[:500], page=action, kind="write", seconds=elapsed)
        return resp, elapsed

    def submit_json(self, path, payload, note=""):
        headers = {"X-CSRF-Token": self.csrf, "Content-Type": "application/json"}
        started = time.time()
        resp = self.session.post(self.base + path, json=payload, headers=headers,
                                 timeout=120, allow_redirects=False)
        elapsed = time.time() - started
        self._log("POST", path, resp.status_code, note)
        return resp, elapsed

    # ------------------------------------------------------------------ login
    def login(self, expect_ok=True):
        """Log in through the real form.

        ``expect_ok=False`` is for the deliberate negative cases (a suspended or
        deactivated account): the app refusing the login is then the *passing*
        outcome, so the attempt is recorded as a successful check.
        """
        resp = self.get("/login", kind="page")
        soup = self.soup(resp)
        form = self.find_form(soup, "/login")
        resp, elapsed = self.submit(soup, form,
                                    {"username": self.user, "password": self.password},
                                    note="login")
        final, chain = self.follow(resp)
        authed = final.status_code == 200 and "logout" in final.text.lower()
        ok = authed == expect_ok
        flashes = [clean(" ".join(g) if isinstance(g, tuple) else g)
                   for g in ALERT_RE.findall(resp.text)]
        detail = f"{resp.status_code} -> {final.status_code} chain={chain}"
        if not ok:
            # Show *why* the app answered the way it did.
            detail += f" flash={flashes or clean(resp.text)[:160]!r}"
            if final is not resp:
                final_flashes = [clean(" ".join(g) if isinstance(g, tuple) else g)
                                 for g in ALERT_RE.findall(final.text)[:3]]
                detail += f" final_flash={final_flashes}"
            if self.db_path:
                try:
                    conn = sqlite3.connect(f"file:{os.path.abspath(self.db_path)}?mode=ro",
                                           uri=True, timeout=10)
                    row = conn.execute(
                        "SELECT username, role, status, access_mode FROM user "
                        "WHERE lower(trim(username))=lower(?)",
                        (self.user.strip(),)).fetchone()
                    conn.close()
                    detail += f" db_user={row}"
                except Exception:
                    pass
        label = (f"login as {self.user}" if expect_ok
                 else f"login refused for {self.user}")
        self.record(label, ok, detail, page="/login", kind="write", seconds=elapsed)
        if authed:
            self.soup(final)
        return authed

    def logout(self):
        resp, _ = self.request("GET", "/logout")
        final, _ = self.follow(resp)
        self.record("logout", final.status_code == 200, f"{final.status_code}", page="/logout")


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
