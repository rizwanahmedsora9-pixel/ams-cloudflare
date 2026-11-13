#!/usr/bin/env python3
"""Assemble the Cloudflare Worker bundle for AMS ERP.

Wrangler only uploads the files below the Worker's module root (``src/`` by
convention — the directory that also holds the entry point), and Python Workers
import whatever sits next to the entry point.  The repository is a normal Flask
project laid out for a whole-server deployment (``app/``, ``blueprints/``,
``models/``, ``utils/``, ``templates/`` at the root), so this script copies the
runtime code into ``cloudflare/src/`` before ``pywrangler deploy``.

Layout produced (``main`` in ``wrangler.jsonc`` is ``src/worker.py``)::

    cloudflare/
      wrangler.jsonc  pyproject.toml
      src/
        worker.py          # the Worker entry point (kept in the repository)
        app/ blueprints/ models/ utils/     # application packages
        templates/         # Jinja templates (uploaded as text modules)
        cash_flow_reconciliation_helpers.py

``static/`` is *not* copied: it is published as Cloudflare static assets
(``assets.directory`` in ``cloudflare/wrangler.jsonc``) because the fonts alone
are far larger than a Worker script may be.

The script runs in two modes:

* ``python3 cloudflare/build_bundle.py`` — write the real copies (used by
  ``wrangler deploy`` through ``build.command`` and by ``deploy.sh``).
* ``python3 cloudflare/build_bundle.py --link`` — create relative symlinks
  instead, which is what ``wrangler dev`` wants: edits to the application show
  up on reload without re-running the build.  ``wrangler dev`` bundles symlinked
  files too, so the dry-run output stays identical.
* ``python3 cloudflare/build_bundle.py --tidy`` — delete the generated bundle
  again (the copies are git-ignored, so this is only local hygiene).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

CLOUDFLARE_DIR = Path(__file__).resolve().parent
ROOT = CLOUDFLARE_DIR.parent
MODULE_ROOT = CLOUDFLARE_DIR / "src"

#: Application packages copied verbatim into the module root.
PYTHON_PACKAGES = ("app", "blueprints", "models", "utils")

#: Single-file runtime modules copied to the module root.
PYTHON_MODULES = ("cash_flow_reconciliation_helpers.py",)

#: Non-Python trees the app reads at runtime (uploaded as Text modules).
DATA_DIRS = ("templates",)

#: Never copied into the bundle, on top of the repository's own .gitignore.
EXCLUDES = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    ".venv-workers",
    "python_modules",
}


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if name in EXCLUDES or name.endswith((".pyc", ".pyo"))}


def _link_or_copy(src: Path, dst: Path, *, link: bool) -> None:
    """Place *src* at *dst*: a relative symlink (dev) or a real copy (deploy)."""
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.is_dir():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if link:
        dst.symlink_to(os.path.relpath(src, dst.parent), target_is_directory=src.is_dir())
    elif src.is_dir():
        shutil.copytree(src, dst, ignore=_ignore)
    else:
        shutil.copy2(src, dst)


def build(*, link: bool = False) -> list[str]:
    """Populate ``src/`` and return the relative paths that were written."""
    if not (MODULE_ROOT / "worker.py").is_file():
        raise SystemExit(
            "cloudflare/src/worker.py is missing — the Worker entry point must stay in the repository."
        )

    MODULE_ROOT.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    for name in PYTHON_PACKAGES + DATA_DIRS:
        source = ROOT / name
        if not source.is_dir():
            continue
        _link_or_copy(source, MODULE_ROOT / name, link=link)
        written.append(name + "/")

    for name in PYTHON_MODULES:
        source = ROOT / name
        if source.is_file():
            _link_or_copy(source, MODULE_ROOT / name, link=link)
            written.append(name)

    # Stale bytecode in the bundle would shadow edited sources.
    for cache in MODULE_ROOT.rglob("__pycache__"):
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--link",
        action="store_true",
        help="symlink instead of copying (for `wrangler dev`)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the previous bundle before writing it again",
    )
    parser.add_argument(
        "--tidy",
        action="store_true",
        help="only remove the generated bundle (the sources are untouched)",
    )
    args = parser.parse_args(argv)

    if args.tidy:
        _remove_bundle()
        print(f"[ams] removed the generated bundle from {MODULE_ROOT.relative_to(ROOT)}/")
        return 0

    if args.clean:
        _remove_bundle()

    written = build(link=args.link)
    mode = "linked" if args.link else "copied"
    target = MODULE_ROOT.relative_to(ROOT)
    print(f"[ams] worker bundle {mode} into {target}/: " + ", ".join(written))
    if not (MODULE_ROOT / "app").exists():
        print("[ams] warning: app/ was not found — check the repository layout", file=sys.stderr)
        return 1

    if args.tidy:
        _remove_bundle()
        print(f"[ams] removed the generated bundle from {target}/")
    return 0


def _remove_bundle() -> None:
    """Delete the generated copies/links, leaving only ``worker.py``."""
    for name in PYTHON_PACKAGES + DATA_DIRS + PYTHON_MODULES:
        target = MODULE_ROOT / name
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)




if __name__ == "__main__":
    raise SystemExit(main())
