"""Tests for the Cloudflare Workers entry point (``cloudflare/src/worker.py``).

The real ``workers`` runtime only exists inside Cloudflare, so these tests
install a small stub package with the same public surface the entry point uses
(``WorkerEntrypoint`` / ``wsgi``) and then drive the Flask app through it with a
fake ``env`` binding object — the same contract the runtime provides.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "cloudflare" / "src" / "worker.py"


class _FakeEnv:
    """Minimal stand-in for a Worker's ``env`` (vars, secrets, bindings)."""

    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class _WsgiRecorder:
    """Captures the arguments the entry point hands to ``wsgi.fetch``."""

    def __init__(self):
        self.calls = []

    async def fetch(self, app, request, env):
        self.calls.append((app, request, env))
        return f"served:{request}"


def _load_worker(monkeypatch):
    """Import the entry point with a stubbed ``workers`` module."""
    recorder = _WsgiRecorder()

    workers_pkg = types.ModuleType("workers")
    workers_pkg.WorkerEntrypoint = type("WorkerEntrypoint", (), {})
    workers_pkg.wsgi = recorder
    monkeypatch.setitem(sys.modules, "workers", workers_pkg)

    module_name = "ams_cloudflare_worker_under_test"
    spec = importlib.util.spec_from_file_location(module_name, WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_APP", None, raising=False)
    return module, recorder


def _clear_worker_env(monkeypatch):
    for key in (
        "AMS_INSTANCE_DIR",
        "APP_DB_PATH",
        "DB_HEALTH_SNAPSHOT_PATH",
        "BACKUP_DIR",
        "UPLOAD_DIR",
        "MAINTENANCE_TEMP_DIR",
        "AMS_SCHEMA_VERSION",
        "ALLOW_EMPTY_DB",
        "SQLITE_JOURNAL_MODE",
        "AMS_HTTPS",
        "AMS_DAILY_BACKUP_SCHEDULER",
        "BACKUP_EMBEDDED_SCHEDULER",
        "AUTO_RECONCILE_ENABLED",
        "AMS_SKIP_TEMPLATE_WARMUP",
        "AMS_STATIC_FROM_ASSETS",
        "PUBLIC_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_entry_point_is_a_worker_entrypoint(monkeypatch):
    worker, _ = _load_worker(monkeypatch)
    assert issubclass(worker.Default, sys.modules["workers"].WorkerEntrypoint)
    # The runtime calls fetch() on the class; the Flask app is built lazily.
    assert hasattr(worker.Default, "fetch")
    assert worker._APP is None


@pytest.mark.asyncio
async def test_fetch_prepares_environment_and_delegates_to_wsgi(monkeypatch, tmp_path):
    _clear_worker_env(monkeypatch)
    worker, recorder = _load_worker(monkeypatch)

    sentinel_app = object()
    monkeypatch.setattr(worker, "_get_app", lambda: sentinel_app)

    instance_dir = tmp_path / "worker-instance"
    env = _FakeEnv(
        AMS_INSTANCE_DIR=str(instance_dir),
        SECRET_KEY="worker-secret",
        PUBLIC_BASE_URL="https://ams.example.workers.dev",
    )

    instance = worker.Default()
    instance.env = env
    result = await instance.fetch("request-object")

    assert result == "served:request-object"
    (app, request, forwarded_env) = recorder.calls[0]
    assert app is sentinel_app
    assert request == "request-object"
    assert forwarded_env is env

    # Worker secrets/vars must reach the app through os.environ, because the
    # Flask factory reads the environment, not the binding object.
    import os

    assert os.environ["SECRET_KEY"] == "worker-secret"
    assert os.environ["PUBLIC_BASE_URL"] == "https://ams.example.workers.dev"
    assert os.environ["AMS_INSTANCE_DIR"] == str(instance_dir)
    assert os.environ["APP_DB_PATH"].startswith(str(instance_dir))
    assert instance_dir.is_dir()


@pytest.mark.asyncio
async def test_fetch_applies_workers_safe_defaults(monkeypatch, tmp_path):
    _clear_worker_env(monkeypatch)
    worker, _ = _load_worker(monkeypatch)
    monkeypatch.setattr(worker, "_get_app", lambda: object())

    instance = worker.Default()
    instance.env = _FakeEnv(AMS_INSTANCE_DIR=str(tmp_path / "inst"))
    await instance.fetch(None)

    import os

    # No POSIX shared memory for WAL files, no threads, HTTPS-only cookies.
    assert os.environ["SQLITE_JOURNAL_MODE"] == "DELETE"
    assert os.environ["AMS_DAILY_BACKUP_SCHEDULER"] == "0"
    assert os.environ["BACKUP_EMBEDDED_SCHEDULER"] == "0"
    assert os.environ["AUTO_RECONCILE_ENABLED"] == "0"
    assert os.environ["AMS_HTTPS"] == "1"
    assert os.environ["AMS_SCHEMA_VERSION"] == "v44"


@pytest.mark.asyncio
async def test_explicit_worker_vars_win_over_defaults(monkeypatch, tmp_path):
    _clear_worker_env(monkeypatch)
    worker, _ = _load_worker(monkeypatch)
    monkeypatch.setattr(worker, "_get_app", lambda: object())

    instance = worker.Default()
    instance.env = _FakeEnv(
        AMS_INSTANCE_DIR=str(tmp_path / "inst"),
        SQLITE_JOURNAL_MODE="MEMORY",
        AMS_SCHEMA_VERSION="v44",
    )
    await instance.fetch(None)

    import os

    assert os.environ["SQLITE_JOURNAL_MODE"] == "MEMORY"


@pytest.mark.asyncio
async def test_missing_env_binding_does_not_break_the_request(monkeypatch, tmp_path):
    _clear_worker_env(monkeypatch)
    worker, recorder = _load_worker(monkeypatch)
    monkeypatch.setattr(worker, "_get_app", lambda: object())
    monkeypatch.setenv("AMS_INSTANCE_DIR", str(tmp_path / "inst"))

    instance = worker.Default()  # no .env attribute at all
    result = await instance.fetch("req")

    assert result == "served:req"
    assert recorder.calls[0][2] is None


def test_build_bundle_writes_the_module_root(monkeypatch):
    """``build_bundle.py`` must place the entry point's imports beside it."""
    spec = importlib.util.spec_from_file_location(
        "ams_cloudflare_build_bundle", ROOT / "cloudflare" / "build_bundle.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    written = module.build()
    assert "app/" in written
    assert "templates/" in written
    module_root = ROOT / "cloudflare" / "src"
    assert (module_root / "worker.py").is_file()
    assert (module_root / "app" / "__init__.py").is_file()
    assert (module_root / "templates").is_dir()

    # --tidy must put the tree back: the copies are generated, not tracked.
    module.main(["--tidy"])
    assert (module_root / "worker.py").is_file()
    assert not (module_root / "app").exists()


def test_wrangler_config_matches_the_documented_contract():
    """The config the README documents must stay valid JSON-with-comments."""
    text = (ROOT / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
    import json
    import re

    stripped = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    config = json.loads(stripped)

    assert config["name"] == "ams-cloudflare"
    assert config["main"] == "src/worker.py"
    assert config["compatibility_flags"] == ["python_workers"]
    assert config["compatibility_date"]
    assert config["find_additional_modules"] is True
    # Static assets (fonts, CSS, JS) are published separately from the script.
    assert config["assets"]["directory"] == "../static"
    assert config["assets"]["binding"] == "ASSETS"
    assert (ROOT / "cloudflare" / config["main"]).is_file()
