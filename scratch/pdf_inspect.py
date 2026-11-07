#!/usr/bin/env python3
"""Dump every downloadable document three ways so screen/print/PDF can be diffed.

Outputs, under ``scratch/pdf_out/``:

* ``<name>.pdf.html``   - the print-view HTML exactly as the browser gets it
* ``<name>.pdf``        - the byte-for-byte download the user receives
* ``<name>.pdf.txt``    - text extracted from that PDF (what "messy" looks like)
* ``<name>.screen.html``- the on-screen page the user compares against
"""
from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
SHARED = os.path.join(REPO, "full cycle test mechanism", "1.all files", "shared")
sys.path.insert(0, REPO)
sys.path.insert(0, SHARED)

OUT = os.path.join(HERE, "pdf_out")
os.makedirs(OUT, exist_ok=True)

import seed                      # noqa: E402
from harness import Db, boot     # noqa: E402


def write(name, data):
    path = os.path.join(OUT, name)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as fh:
        fh.write(data)
    print(f"  wrote {name} ({len(data)} bytes)")


def pdf_text(data):
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for i, page in enumerate(reader.pages, 1):
            pages.append(f"----- page {i} -----\n" + (page.extract_text() or ""))
        return "\n".join(pages)
    except Exception as exc:
        return f"<<pdf read failed: {exc}>>"


def main():
    db_path = os.path.join(HERE, "pdf_out", "inspect.db")
    session = boot(db_path, health_path=db_path + ".health.json", fresh=os.environ.get("FRESH","1")=="1")
    db = Db(db_path)
    print("booted")
    if os.environ.get("SKIP_SEED") == "1":
        print("skipping seed")
    else:
        ctx = seed.seed(session, db, artifact_dir=os.path.join(OUT, "artifacts"))
    pass

    targets = []

    client_ids = [r["id"] for r in db.rows("select id from client order by id limit 3")]
    for cid in client_ids:
        targets.append(
            (f"client_ledger_{cid}", f"/download_client_ledger/{cid}",
             f"/client_ledger/{cid}"))
        targets.append(
            (f"client_clearance_{cid}", f"/download_client_clearance/{cid}",
             f"/client_ledger/{cid}"))
        targets.append(
            (f"client_full_history_{cid}", f"/download_full_client_history/{cid}",
             f"/client_ledger/{cid}"))

    supplier_ids = [r["id"] for r in db.rows("select id from supplier order by id limit 2")]
    for sid in supplier_ids:
        targets.append(
            (f"supplier_ledger_{sid}", f"/download_supplier_ledger/{sid}?scope=full",
             f"/supplier_ledger/{sid}"))

    bills = [r["b"] for r in db.rows(
        "select manual_bill_no as b from booking where manual_bill_no is not null limit 1")]
    for b in bills:
        targets.append((f"invoice_{b}", f"/download_invoice/{b}", f"/view_bill/{b}"))

    for name, pdf_path, screen_path in targets:
        print(f"\n=== {name} ===")
        try:
            status, data, ctype = session.bytes(pdf_path)
            print(f"  download {pdf_path} -> {status} {ctype} {len(data)}B")
            ext = "pdf" if data[:5] == b"%PDF-" else "html"
            write(f"{name}.{ext}", data)
            if ext == "pdf":
                write(f"{name}.txt", pdf_text(data))
            elif ext == "html":
                write(f"{name}.fallback.html", data)
        except Exception as exc:
            print(f"  download failed: {exc}")

        # the browser "print" view (same route, action=print)
        try:
            status, html = session.html(pdf_path + ("&" if "?" in pdf_path else "?") + "action=print")
            print(f"  print    -> {status} {len(html)}B")
            write(f"{name}.print.html", html)
        except Exception as exc:
            print(f"  print failed: {exc}")

        try:
            status, html = session.html(screen_path)
            print(f"  screen   {screen_path} -> {status} {len(html)}B")
            write(f"{name}.screen.html", html)
        except Exception as exc:
            print(f"  screen failed: {exc}")

    print("\noutput dir:", OUT)


if __name__ == "__main__":
    main()
