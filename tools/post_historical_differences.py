#!/usr/bin/env python3
"""Post (or reverse) the counter-account postings of already-finalised days.

Before daily reconciliation posted anything, a locked day carried its counted
figure forward on the *board* only: ``Account.balance`` never moved.  This tool
lets an operator bring historical days into the new model deliberately, after
reviewing exactly what would happen.

It never touches a count.  It only writes the paired transfer
``account → Counter Less`` (shortage) or ``Counter Excess → account`` (excess)
for a difference that a finalised day already froze, and links it to the
difference row (``posted_status='posted'``).

Usage
-----
    # 1. Look first — nothing is written.
    python tools/post_historical_differences.py --from 2026-01-01 --dry-run

    # 2. Post, and say who is responsible.
    python tools/post_historical_differences.py --from 2026-01-01 --actor admin

    # 3. Undo everything this tool posted.
    python tools/post_historical_differences.py --from 2026-01-01 --reverse

Always take a database backup first (``tools/backup`` / the admin backup page).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_day(value):
    if not value:
        return None
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--from', dest='from_day', default=None,
                        help='only consider days on or after this date (YYYY-MM-DD)')
    parser.add_argument('--to', dest='to_day', default=None,
                        help='only consider days on or before this date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true',
                        help='print what would happen and write nothing')
    parser.add_argument('--reverse', action='store_true',
                        help='remove the postings this tool (or a lock) created')
    parser.add_argument('--actor', default=os.environ.get('USER') or 'system',
                        help='username recorded on every ledger row')
    parser.add_argument('--reason', default='Historical daily reconciliation close',
                        help='reason stored on the postings')
    parser.add_argument('--db', default=None, help='database path (defaults to APP_DB_PATH)')
    args = parser.parse_args(argv)

    if args.db:
        os.environ['APP_DB_PATH'] = args.db

    from app import create_app
    from models import db, Account, CashDayDifference, CashDayLock
    from app.services import recon_counter

    app = create_app()
    with app.app_context():
        start = _parse_day(args.from_day)
        end = _parse_day(args.to_day)

        query = CashDayDifference.query.join(
            CashDayLock, CashDayLock.lock_date == CashDayDifference.position_date
        ).filter(CashDayDifference.difference != 0)
        if start:
            query = query.filter(CashDayDifference.position_date >= start)
        if end:
            query = query.filter(CashDayDifference.position_date <= end)
        rows = query.order_by(CashDayDifference.position_date.asc(),
                              CashDayDifference.id.asc()).all()

        if not rows:
            print('Nothing to do: no finalised day carries a difference in that range.')
            return 0

        print(f'{"day":12} {"account":24} {"expected":>12} {"counted":>12} {"difference":>12}  state')
        posted = skipped = 0
        for row in rows:
            account = db.session.get(Account, row.account_id)
            name = (account.name if account else row.account_name or '?')[:24]
            print(f'{row.position_date!s:12} {name:24} {row.counted - row.difference:12,.2f} '
                  f'{row.counted:12,.2f} {row.difference:12,.2f}  {row.posted_status or "pending"}')

            if args.reverse:
                if row.posted_status in (recon_counter.STATUS_POSTED, recon_counter.STATUS_REVERSED):
                    if args.dry_run:
                        print('    would reverse the posting pair')
                    else:
                        removed = recon_counter.reverse_posting(
                            row, actor=args.actor, reason='Historical postings reversed')
                        print(f'    reversed {removed} leg(s)')
                        posted += 1
                continue

            if row.status != 'open':
                print('    skipped: the difference is already closed')
                skipped += 1
                continue
            if row.posted_status == recon_counter.STATUS_POSTED:
                print('    skipped: already posted')
                skipped += 1
                continue
            if args.dry_run:
                ok, message = True, 'would post'
            else:
                ok, message = recon_counter.post_difference(
                    row, actor=args.actor, reason=args.reason)
            if ok:
                posted += 1
                print(f'    {message}')
            else:
                skipped += 1
                print(f'    skipped: {message}')

        if args.dry_run:
            db.session.rollback()
            print(f'\nDRY RUN — nothing written. {posted} would be posted, {skipped} skipped.')
            problems = recon_counter.counter_invariants()
            if problems:
                print(f'{len(problems)} invariant problem(s) found; '
                      f'the consistency report lists them.')
            return 0

        if args.reverse:
            db.session.commit()
            print(f'\nReversed {posted} posting pair(s).')
            return 0

        db.session.commit()
        less, excess = recon_counter.counter_accounts()
        print(f'\nPosted {posted} pair(s), skipped {skipped}.')
        print(f'Counter Less   : Rs. {float(less.balance or 0):,.2f}' if less else 'Counter Less: n/a')
        print(f'Counter Excess : Rs. {float(excess.balance or 0):,.2f}' if excess else 'Counter Excess: n/a')
        print(f'Unresolved (posted differences still holding money): '
              f'Rs. {recon_counter.open_difference_total():,.2f}')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
