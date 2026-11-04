#!/usr/bin/env python3
"""Probe: does the mechanism ever call ``seed.mutate()``?

Context: ``checks.py`` W-06 asserts a reconciliation difference of 17,000, but
the row it reads is only written by ``seed.mutate()``.  In a normal run the
table is empty, so W-06 reports ``observed=None``.  This probe measures both
halves of that story:

1. a normal run does **not** touch the phase-2 tables (they stay empty);
2. running ``mutate()`` by hand *does* write them — and changes four canonical
   figures, which is why it cannot simply be switched on.

    python "1.all files/shared/../run-005-.../scripts/probe_mutate_gap.py"

Nothing is written to the repository: the database is a temp file.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.abspath(os.path.join(HERE, "..", "..", "shared"))
sys.path.insert(0, SHARED)

from harness import Db, boot  # noqa: E402

import seed  # noqa: E402

PHASE2_TABLES = ["material_return", "material_return_item", "pending_bill",
                 "cash_flow_difference_adjustment", "cash_flow_reconciliation_audit",
                 "cash_flow_entry_audit", "account_reconciliation"]


def stock(db: Db) -> dict:
    return {r["name"]: r["total"] for r in db.rows("select name,total from material")}


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="mutate-gap-")
    db_path = os.path.join(tmp, "probe.db")
    session = boot(db_path)
    db = Db(db_path)

    seed.STAGES.clear()
    ctx = seed.seed(session, db)
    phase1_stages = len(seed.STAGES)
    before = db.counts()
    stock_before = stock(db)
    pnl_before = session.page("/profit_reports?start_date=2026-10-01&end_date=2026-10-31")[1]
    clients_before = session.page("/clients")[1]

    # ---- would a normal run ever reach phase 2? -------------------------
    import inspect
    source = inspect.getsource(seed.seed)
    called = "mutate(" in source

    # ---- now run phase 2 by hand ---------------------------------------
    seed.mutate(session, db, ctx)
    mutate_stages = seed.STAGES[phase1_stages:]
    after = db.counts()
    stock_after = stock(db)
    pnl_after = session.page("/profit_reports?start_date=2026-10-01&end_date=2026-10-31")[1]
    clients_after = session.page("/clients")[1]

    diff = {t: (before.get(t, 0), after.get(t, 0))
            for t in sorted(after) if before.get(t, 0) != after.get(t, 0)}

    print(f"seed() calls mutate()?        {called}")
    print(f"phase-1 stages                {phase1_stages}")
    print(f"phase-2 stages (unreachable)  {len(mutate_stages)}")
    for stage in mutate_stages:
        print(f"   [{'ok ' if stage['ok'] else 'FAIL'}] {stage['stage']}")
    print(f"\nrows created by phase 2       {json.dumps(diff, indent=1)}")
    print(f"phase-2 tables before         "
          f"{ {t: before.get(t, 0) for t in PHASE2_TABLES} }")
    print(f"stock DG before/after         {stock_before.get('DG Cement')} -> "
          f"{stock_after.get('DG Cement')}")
    print(f"clients page payable before   "
          f"{'18,500' if '18,500' in clients_before else '?'} / after "
          f"{'20,500' if '20,500' in clients_after else '?'}")
    print(f"P&L profit same?              "
          f"{('11,600' in pnl_before) == ('11,600' in pnl_after)}")

    payload = {
        "seed_calls_mutate": called,
        "phase1_stages": phase1_stages,
        "phase2_stages": len(mutate_stages),
        "phase2_stage_log": mutate_stages,
        "count_deltas": diff,
        "phase2_tables_before": {t: before.get(t, 0) for t in PHASE2_TABLES},
        "stock_dg": [stock_before.get("DG Cement"), stock_after.get("DG Cement")],
    }
    out = os.path.join(HERE, "probe-mutate-gap.json")
    with open(out, "w") as fh:
        json.dump(payload, fh, indent=1)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
