"""Orchestrates the two-cycle end-to-end smoke run.

Cycle A: fresh database -> full journey -> wipe -> verify empty -> restart ->
         verify the wipe persisted -> re-create data (proves the app is usable).
Cycle B: the same journey again from the wiped database -> wipe again ->
         empty-database UI sweep -> restart -> verify again.

Every server is a separate real process listening on its own port against its
own throw-away SQLite file, so nothing here touches instance/ or production.

    python run_smoke.py --out out
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PYTHON = sys.executable


def wait_for_port(port: int, timeout: float = 180.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def wait_for_login(port: int, timeout: float = 240.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/login"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


class Server:
    def __init__(self, port: int, db: str, log: str, uploads: str):
        self.port = port
        self.db = db
        self.log_path = log
        self.uploads = uploads
        self.proc = None
        self.log = None

    def start(self):
        env = dict(os.environ)
        env.update({
            "APP_DB_PATH": self.db,
            "UPLOAD_DIR": self.uploads,
            "ALLOW_EMPTY_DB": "1",
            "BACKUP_EMBEDDED_SCHEDULER": "0",
            "AMS_DAILY_BACKUP_SCHEDULER": "0",
            "SQLITE_JOURNAL_MODE": "DELETE",
            "PORT": str(self.port),
            "PYTHONUNBUFFERED": "1",
            # The health check remembers the last DB it opened; three servers
            # in a row share one throw-away file, so switching is intended here.
            "ALLOW_DB_DROP": "1",
        })
        self.log = open(self.log_path, "ab")
        self.proc = subprocess.Popen(
            [PYTHON, "main.py"], cwd=REPO, env=env,
            stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        return wait_for_port(self.port) and wait_for_login(self.port)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except Exception:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except Exception:
                    self.proc.kill()
        if self.log:
            self.log.close()


def run_journey(port, db, label, out_json, phases, timeout=2400):
    cmd = [PYTHON, os.path.join(HERE, "journey.py"), "--port", str(port),
           "--db", db, "--label", label, "--json", out_json, "--phases", phases]
    print(f"\n$ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write("\n--- journey stderr ---\n" + proc.stderr[-4000:])
    return proc.returncode


def server_errors(log_path):
    try:
        text = open(log_path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return []
    hits = []
    for line in text.splitlines():
        low = line.lower()
        if ('" 500 ' in line or ' 500 -' in line or "traceback" in low
                or "internal server error" in low):
            hits.append(line[:400])
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--cycles", type=int, default=2)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)

    summary = {"started": datetime.now(timezone.utc).isoformat(), "cycles": []}
    port = 5100
    rc_total = 0
    for cycle in range(1, args.cycles + 1):
        letter = "AB"[cycle - 1] if cycle <= 2 else str(cycle)
        db = os.path.join(work, f"cycle{letter}.db")
        uploads = os.path.join(work, f"uploads{letter}")
        os.makedirs(uploads, exist_ok=True)
        for stale in (db, db + "-wal", db + "-shm", db + ".health.json"):
            if os.path.exists(stale):
                os.remove(stale)
        log1 = os.path.join(out, f"cycle{letter}-server-1.log")
        log2 = os.path.join(out, f"cycle{letter}-server-2.log")
        log3 = os.path.join(out, f"cycle{letter}-server-3.log")
        print(f"\n############ CYCLE {letter}  db={db}  port={port} ############", flush=True)

        srv = Server(port, db, log1, uploads)
        booted = srv.start()
        print(f"server started: {booted}", flush=True)
        cycle_info = {"cycle": letter, "db": db, "port": port, "booted": booted}

        j1 = os.path.join(out, f"cycle{letter}-1-full.json")
        rc1 = run_journey(port, db, f"cycle{letter}-1", j1, ",".join([
            "boot", "masters", "purchasing", "stock", "sales", "collections",
            "returns", "deliveries", "accounts", "cash_flow", "reconciliation",
            "reports", "deep", "manage", "system", "readback", "wipe"]))
        srv.stop()
        time.sleep(2)

        # Restart against the wiped file: the wipe must have persisted,, the app
        # must boot on an empty database without repairing anything back, and a
        # second identical end-to-end pass must run on it.
        srv2 = Server(port + 1, db, log2, uploads)
        booted2 = srv2.start()
        print(f"restarted after wipe: {booted2}", flush=True)
        j2 = os.path.join(out, f"cycle{letter}-2-pass2.json")
        rc2 = run_journey(port + 1, db, f"cycle{letter}-2", j2, ",".join([
            "boot", "verify_empty", "empty_ui", "masters", "purchasing", "stock",
            "sales", "collections", "returns", "deliveries", "accounts", "cash_flow",
            "reconciliation", "reports", "deep", "manage", "system", "readback",
            "wipe"]))
        srv2.stop()
        time.sleep(2)

        # Third boot proves the closing wipe persisted across a restart.
        srv3 = Server(port + 2, db, log3, uploads)
        booted3 = srv3.start()
        print(f"restarted after the closing wipe: {booted3}", flush=True)
        j3 = os.path.join(out, f"cycle{letter}-3-empty.json")
        rc3 = run_journey(port + 2, db, f"cycle{letter}-3", j3,
                          "boot,verify_empty")
        srv3.stop()

        errs1 = server_errors(log1)
        errs2 = server_errors(log2)
        errs3 = server_errors(log3)
        cycle_info.update({
            "journey1_rc": rc1, "journey2_rc": rc2, "journey3_rc": rc3,
            "json1": j1, "json2": j2, "json3": j3, "booted2": booted2,
            "booted3": booted3,
            "server_errors_1": errs1, "server_errors_2": errs2,
            "server_errors_3": errs3,
        })
        summary["cycles"].append(cycle_info)
        rc_total += (rc1 != 0) + (rc2 != 0) + (rc3 != 0)
        port += 10
        if not args.keep:
            pass  # databases are kept for the report; they are small and in out/

    summary["finished"] = datetime.now(timezone.utc).isoformat()
    summary["failed_journeys"] = rc_total
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print("\n" + "#" * 72)
    print(json.dumps(summary, indent=2)[:4000])
    print("#" * 72, flush=True)
    return 1 if rc_total else 0


if __name__ == "__main__":
    sys.exit(main())
