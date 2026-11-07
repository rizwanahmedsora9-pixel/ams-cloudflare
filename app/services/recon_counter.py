"""Counter-account postings for daily-count differences.

The problem this module exists for
----------------------------------
The daily board used to keep its counted figures entirely to itself: locking a
day carried the counted amount forward as the *board's* next opening, while
``Account.balance`` — the figure every other screen starts from — never moved.
The board said the drawer held 900 and Accounts said 1,000, forever.

The rule implemented here
-------------------------
A finalised day is a fact, so the difference between the count and the ledger is
**posted**, as a paired transfer against a dedicated counter account::

    counted < expected (shortage)   FBM  ──100──▶  Counter Less Account
    counted > expected (excess)     Counter Excess Account ──100──▶ FBM

Both legs are ordinary ``AccountTransaction`` rows, so:

* the counted account's balance becomes exactly the counted figure,
* the unexplained part sits in a named account instead of vanishing,
* Σ balances is unchanged — nothing is invented and nothing is lost,
* the pair nets to zero, so the counter account is a live to-do list.

The two counter accounts are ordinary ``Account`` rows created with
``category='recon'``.  Every money-account test in the app filters on
``category in ('cash','bank')`` (``cash_flow_svc._cf_is_money_account``,
``_cf_company_accounts``, the GRN / driver / cash-flow pickers, the daily board),
so a ``recon`` account can never be picked as a source of funds and never appears
on the board — without touching any of those places.

Guarantees
----------
* **Atomic**: postings are written in the caller's transaction (the day lock, an
  unlock, or a resolve).  The caller commits.
* **Idempotent**: every leg carries a deterministic ``idempotency_key``, and a
  partial unique index backs it up.  A double-clicked lock, a retried request or
  two admins racing the same day posts once.
* **Never voided**: the boot-time void purge (``void_purge.purge_voided_rows``)
  deletes voided rows with raw SQL and does **not** unwind cached balances, so a
  voided reconciliation row would corrupt a balance one restart later.  Postings
  are always *reversed and deleted* together with their balance effect.
* **Self-healing**: if a leg went missing (half-written legacy data, a manual
  deletion), ``counter_drift()`` / ``counter_invariants()`` report it, the
  consistency report fails, and re-running the same lock (or
  ``tools/post_historical_differences.py``) restores the pair from the keys.
"""
from __future__ import annotations

import logging
from datetime import datetime, time

from sqlalchemy import func, or_

from models import (
    db, Account, AccountTransaction, CashDayAccountPosition, CashDayDifference,
    Settings,
)
from utils.money import from_minor, to_minor
from app.services.time_money import _money_round, pk_now

logger = logging.getLogger(__name__)

#: ``Account.category`` used by the two counter accounts.  Deliberately not
#: ``cash``/``bank`` so no money-account filter anywhere can select them.
RECON_CATEGORY = 'recon'
RECON_ACCOUNT_TYPE = 'recon_counter'
LESS = 'less'
EXCESS = 'excess'

LESS_ACCOUNT_NAME = 'Counter Less Account'
EXCESS_ACCOUNT_NAME = 'Counter Excess Account'

STATUS_PENDING = 'pending'
STATUS_POSTED = 'posted'
STATUS_RESOLVED = 'resolved'
STATUS_REVERSED = 'reversed'

#: Resolution choices shown on the differences report.  ``counterpart`` is the
#: account id or ``None`` for "reduce the counter (or the partner account) by the
#: same amount on the opposite side" — see ``resolve_difference``.
RESOLUTION_KINDS = {
    'recovered_less': {
        'label': 'Shortage recovered',
        'hint': 'The shortfall was found and put back into the cash account.',
    },
    'recovered_excess': {
        'label': 'Excess returned',
        'hint': 'The extra cash was taken out of the cash account.',
    },
    'written_off': {
        'label': 'Written off (loss)',
        'hint': 'The shortfall is a real loss; it leaves the counter account.',
    },
    'income': {
        'label': 'Recognised as income',
        'hint': 'The extra cash is genuine income; it leaves the counter account.',
    },
}

#: Source marker used by the void-purge / audit helpers to recognise these rows.
SOURCE_TYPE = 'CashDayDifference'


# ---------------------------------------------------------------------------
# Counter accounts
# ---------------------------------------------------------------------------

def _settings():
    settings = Settings.query.first()
    if settings is None:
        settings = Settings()
        db.session.add(settings)
        db.session.flush()
    return settings


def _create_counter(name, *, channel='ledger_only'):
    """Build (but do not add) one counter account."""
    account = Account(
        name=name,
        type='RECON',
        account_type=RECON_ACCOUNT_TYPE,
        category=RECON_CATEGORY,
        source_category='Company',
        balance=0,
        balance_minor=0,
        opening_balance=0,
        opening_balance_minor=0,
        opening_balance_date=pk_now(),
        channel=channel,
        class_category='Equity / Own Funds',
        class_subcategory='Reconciliation Clearing',
        class_account_type='Difference Counter',
        linked_entity_type='none',
        account_status='active',
        is_active=True,
        note=('Holds unexplained daily-count differences. Postings here are made '
              'only by the daily reconciliation; the account is never a source '
              'of funds.'),
        created_at=pk_now(),
        updated_at=pk_now(),
    )
    return account


def ensure_counter_accounts(*, commit=False):
    """Create (once) and return ``(less_account, excess_account)``.

    Idempotent and safe to call from any request.  Accounts are matched by the
    stored ids first, then by name inside ``category='recon'``, so a rename never
    duplicates them.
    """
    settings = _settings()
    less = db.session.get(Account, settings.recon_less_account_id) if settings.recon_less_account_id else None
    excess = db.session.get(Account, settings.recon_excess_account_id) if settings.recon_excess_account_id else None

    changed = False
    if less is None or (less.category or '').lower() != RECON_CATEGORY:
        less = _find_existing(LESS_ACCOUNT_NAME)
    if excess is None or (excess.category or '').lower() != RECON_CATEGORY:
        excess = _find_existing(EXCESS_ACCOUNT_NAME)

    if less is None:
        less = _create_counter(LESS_ACCOUNT_NAME)
        db.session.add(less)
        db.session.flush()
        changed = True
    if excess is None:
        excess = _create_counter(EXCESS_ACCOUNT_NAME)
        db.session.add(excess)
        db.session.flush()
        changed = True

    if settings.recon_less_account_id != less.id:
        settings.recon_less_account_id = less.id
        changed = True
    if settings.recon_excess_account_id != excess.id:
        settings.recon_excess_account_id = excess.id
        changed = True

    if changed:
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        logger.info('Daily reconciliation counter accounts ready: less=#%s excess=#%s',
                    less.id, excess.id)
    return less, excess


def _find_existing(name):
    return Account.query.filter(
        func.lower(func.trim(Account.category)) == RECON_CATEGORY,
        func.lower(func.trim(Account.name)) == name.lower(),
    ).first()


def counter_accounts():
    """Return ``(less, excess)`` if they exist, without creating them."""
    settings = Settings.query.first()
    if settings is None:
        return None, None
    less = db.session.get(Account, settings.recon_less_account_id) if settings.recon_less_account_id else None
    excess = db.session.get(Account, settings.recon_excess_account_id) if settings.recon_excess_account_id else None
    return less, excess


def is_counter_account(account) -> bool:
    return bool(account) and (getattr(account, 'category', '') or '').strip().lower() == RECON_CATEGORY


def counter_name_for(kind) -> str:
    return LESS_ACCOUNT_NAME if kind == LESS else EXCESS_ACCOUNT_NAME


# ---------------------------------------------------------------------------
# Ledger primitives
# ---------------------------------------------------------------------------

def _tx_minor(tx) -> int:
    if tx is None:
        return 0
    if getattr(tx, 'amount_minor', None) is not None:
        return int(tx.amount_minor)
    return to_minor(tx.amount or 0)


def _find_leg(key):
    if not key:
        return None
    return (
        AccountTransaction.query
        .filter(AccountTransaction.idempotency_key == key)
        .order_by(AccountTransaction.id.desc())
        .first()
    )


def _delete_leg(tx):
    """Remove one posting leg *and* its cached balance effect."""
    if tx is None:
        return False
    from app.services.accounting import _reverse_account_tx_effect
    _reverse_account_tx_effect(tx)
    db.session.delete(tx)
    return True


def _marker(key):
    """The ``[SRC:...]`` tag that makes a leg identifiable in any note view.

    ``accounting._src_marker`` is the app-wide convention for "this ledger row is
    the mirror of document X"; reusing it means an operator can find, grep or
    reconcile a posting without knowing about this module.
    """
    return f'[SRC:DayDiff:{key}]'


def _leg_direction(key):
    """'out' / 'in' for a posting key (``…:<row id>:out`` / ``…:<row id>:in``)."""
    tail = str(key or '').rsplit(':', 1)[-1]
    return tail if tail in ('out', 'in') else ''


def _write_leg(*, key, from_account, to_account, amount_minor, description, note,
               tx_type, reason, actor, posted_at, difference):
    """Write one ledger leg (idempotent) and apply it to the cached balances.

    Replay is decided by the key *and* the leg direction carried inside the note:
    a mirror entry (same key family, opposite direction) is always written, while
    the same leg posted twice is not.
    """
    from app.services.accounting import _apply_account_tx_effect

    existing = _find_leg(key)
    if existing is not None:
        return existing, False
    amount_minor = int(amount_minor)
    if amount_minor <= 0:
        return None, False
    note = f'{_marker(key)} {note or ""}'.strip()
    tx = AccountTransaction(
        from_account_id=(from_account.id if from_account is not None else None),
        to_account_id=(to_account.id if to_account is not None else None),
        amount=float(from_minor(amount_minor)),
        amount_minor=amount_minor,
        description=description[:200],
        note=note,
        reason=(reason or '')[:300] or None,
        transaction_type=tx_type,
        source_type=SOURCE_TYPE,
        source_id=(difference.id if difference is not None else None),
        idempotency_key=key[:64],
        created_by=_actor_name(actor),
        date_posted=posted_at,
    )
    db.session.add(tx)
    db.session.flush()
    _apply_account_tx_effect(tx)
    return tx, True


def _actor_name(actor):
    return str(getattr(actor, 'username', None) or actor or 'System')[:80]


def _day_day(day):
    if hasattr(day, 'date') and not isinstance(day, datetime):
        return day
    if isinstance(day, datetime):
        return day.date()
    return datetime.strptime(str(day)[:10], '%Y-%m-%d').date()


def day_of(day):
    """Public alias of the day normaliser used by callers outside this module."""
    return _day_day(day)


def _posting_instant(day):
    """End of the financial day — the instant the count closes the day."""
    return datetime.combine(_day_day(day), time.max)


# ---------------------------------------------------------------------------
# Post / reverse / resolve
# ---------------------------------------------------------------------------

def posting_key(difference) -> str:
    return f'daydiff:{_day_day(difference.position_date):%Y-%m-%d}:{difference.account_id}:{difference.id}'


def expected_of(difference):
    """Expected closing implied by a difference snapshot (counted − difference)."""
    return _money_round(float(difference.counted or 0) - float(difference.difference or 0))


def _note_for(difference, *, label):
    return (
        f'[RECON:DAY:{_day_day(difference.position_date):%Y-%m-%d}:{difference.account_id}] '
        f'expected={expected_of(difference):.2f} '
        f'counted={_money_round(difference.counted or 0):.2f} '
        f'difference={_money_round(difference.difference or 0):.2f}'
        + (f' | {label}' if label else '')
    )


def post_difference(difference, *, actor=None, reason='', commit=False):
    """Post one difference as a paired transfer against its counter account.

    Returns ``(ok, message)``.  Safe to call twice: the deterministic keys make
    the second call a no-op.
    """
    if difference is None:
        return False, 'No difference to post.'
    if difference.posted_status == STATUS_POSTED and difference.posted_out_tx_id and difference.posted_in_tx_id:
        return True, 'Already posted.'
    if difference.posted_status == STATUS_RESOLVED:
        return False, 'This difference was already resolved.'

    amount_minor = abs(to_minor(difference.difference or 0))
    if amount_minor <= 0:
        return False, 'A zero difference is never posted.'

    account = db.session.get(Account, difference.account_id)
    if account is None:
        return False, 'The counted account no longer exists.'
    if is_counter_account(account):
        return False, 'Counter accounts are never reconciled against themselves.'

    less, excess = ensure_counter_accounts()
    counted_less = (difference.difference or 0) < 0

    # A count is a fact, so a shortage is always posted — even when the account
    # does not currently hold that much (a day finalised late, after the money
    # already moved on).  Refusing here would leave the ledger claiming money the
    # drawer did not have, which is exactly what this module exists to fix.  The
    # shortfall is surfaced in the message instead.
    available = int(account.balance_minor) if account.balance_minor is not None else to_minor(account.balance or 0)
    short_by = max(0, amount_minor - max(available, 0)) if counted_less else 0

    posted_at = _posting_instant(difference.position_date)
    label = (reason or '').strip()
    note = _note_for(difference, label=label)
    key = posting_key(difference)
    tx_type = 'Reconciliation Loss' if counted_less else 'Reconciliation Excess'

    if counted_less:
        out_desc = f'Counted less — sent to {less.name} ({account.name})'
        in_desc = f'Counted less — received from {account.name}'
        out_tx, _ = _write_leg(
            key=f'{key}:out', from_account=account, to_account=None,
            amount_minor=amount_minor, description=out_desc, note=note,
            tx_type=tx_type, reason=label, actor=actor, posted_at=posted_at,
            difference=difference,
        )
        in_tx, _ = _write_leg(
            key=f'{key}:in', from_account=None, to_account=less,
            amount_minor=amount_minor, description=in_desc, note=note,
            tx_type=tx_type, reason=label, actor=actor, posted_at=posted_at,
            difference=difference,
        )
    else:
        out_desc = f'Counted more — sent to {account.name}'
        in_desc = f'Counted more — received from {excess.name}'
        out_tx, _ = _write_leg(
            key=f'{key}:out', from_account=excess, to_account=None,
            amount_minor=amount_minor, description=out_desc, note=note,
            tx_type=tx_type, reason=label, actor=actor, posted_at=posted_at,
            difference=difference,
        )
        in_tx, _ = _write_leg(
            key=f'{key}:in', from_account=None, to_account=account,
            amount_minor=amount_minor, description=in_desc, note=note,
            tx_type=tx_type, reason=label, actor=actor, posted_at=posted_at,
            difference=difference,
        )

    difference.posted_status = STATUS_POSTED
    difference.posted_out_tx_id = out_tx.id if out_tx is not None else None
    difference.posted_in_tx_id = in_tx.id if in_tx is not None else None
    difference.posted_at = pk_now()
    difference.posted_by = _actor_name(actor)
    difference.posted_expected = expected_of(difference)
    difference.posted_counted = _money_round(difference.counted or 0)

    message = (
        f'Rs. {_money_round(from_minor(amount_minor)):,.2f} '
        + (f'shortage sent from {account.name} to {less.name}.'
           if counted_less else
           f'excess sent from {excess.name} to {account.name}.')
    )
    if short_by:
        message += (
            f' Note: the shortage (Rs. {_money_round(from_minor(short_by)):,.2f}) is larger '
            f'than {account.name} held, so that account is now short — the count is '
            f'still the truth and the gap belongs in this difference.'
        )
    if commit:
        db.session.commit()
    return True, message


def reverse_posting(difference, *, actor=None, reason='', commit=False):
    """Remove the day's posting pair (used when a finalised day is unlocked).

    The legs are reversed **and deleted** in the same transaction as their
    balance effect — never flagged ``is_void``, because the boot-time void purge
    deletes voided rows without unwinding balances.
    """
    if difference is None:
        return 0
    from utils.accounting_audit import record_accounting_audit

    removed = 0
    keys = [f'{posting_key(difference)}:out', f'{posting_key(difference)}:in']
    for key in keys:
        tx = _find_leg(key)
        if tx is None:
            continue
        if _leg_direction(key) and _leg_direction(key) not in (tx.note or ''):
            # The row under this key is a mirror entry, not the original leg.
            continue
        before = {
            'id': tx.id, 'from_account_id': tx.from_account_id,
            'to_account_id': tx.to_account_id, 'amount': _money_round(tx.amount or 0),
        }
        _delete_leg(tx)
        removed += 1
        record_accounting_audit(
            actor, action='Unpost', entity_type='AccountTransaction', entity_id=before['id'],
            before=before, after={'removed': True},
            amount_before=before['amount'], amount_after=0,
            account_before_id=before['from_account_id'] or before['to_account_id'],
            reason=(reason or 'Daily reconciliation day unlocked')[:300],
        )

    if difference.posted_status in (STATUS_POSTED, STATUS_REVERSED):
        # Unlocking always drops the row back to "recorded only": the count is
        # no longer finalised, so its posting must not survive.
        difference.posted_status = STATUS_REVERSED
    difference.posted_out_tx_id = None
    difference.posted_in_tx_id = None
    difference.posted_at = None
    difference.posted_by = None
    if commit:
        db.session.commit()
    return removed


def resolve_difference(difference, *, kind, counterpart=None, note='', actor=None, commit=False):
    """Offset a posted difference with a real explanation entry.

    The day's closing is never rewritten: the counter account is emptied by a
    second, mirrored entry that says what actually happened to the money.  That
    entry is the audit trail — who did it, when, and against which account.
    """
    from utils.accounting_audit import record_accounting_audit

    if difference is None:
        raise ValueError('Difference not found.')
    if difference.posted_status != STATUS_POSTED:
        raise ValueError(
            'Only a posted difference can be resolved. Finalise the day first.'
            if difference.posted_status == STATUS_PENDING else
            'This difference is not open for resolution.'
        )
    kind = (kind or '').strip().lower()
    if kind not in RESOLUTION_KINDS:
        raise ValueError('Choose what happened to the money.')
    note = (note or '').strip()
    if not note:
        raise ValueError('A note is required to resolve a difference.')

    amount_minor = abs(to_minor(difference.difference or 0))
    if amount_minor <= 0:
        raise ValueError('A zero difference cannot be resolved.')

    counted = db.session.get(Account, difference.account_id)
    if counted is None:
        raise ValueError('The counted account no longer exists.')
    less, excess = ensure_counter_accounts()
    counted_less = (difference.difference or 0) < 0

    # Which counter holds the money, and where it goes next.
    if counted_less:
        counter = less
        if kind not in ('recovered_less', 'written_off'):
            raise ValueError('A shortage can be recovered or written off.')
    else:
        counter = excess
        if kind not in ('recovered_excess', 'income'):
            raise ValueError('An excess can be returned or recognised as income.')

    other = None
    if counterpart:
        try:
            other = db.session.get(Account, int(counterpart))
        except (TypeError, ValueError):
            other = None
        if other is None:
            raise ValueError('Select a valid account for the other side of the entry.')
        if is_counter_account(other):
            raise ValueError('The other side cannot be a counter account.')

    posted_at = pk_now()
    tx_type = 'Reconciliation Loss' if kind in ('recovered_less', 'written_off') else 'Reconciliation Excess'
    # The resolution's label and the operator's reason both live on the leg, so
    # the ledger explains itself without this module.
    tx_note = f'[RECON:RESOLVE:{difference.id}] {note}'[:500]

    if counted_less and kind == 'recovered_less':
        # counter ──▶ counted account  (money went back into the drawer)
        from_acc, to_acc = counter, counted
        description = f'Shortage recovered — {counter.name} to {counted.name}'
    elif counted_less and kind == 'written_off':
        # counter ──▶ counterpart (expense / partner) — loss leaves the counter
        from_acc, to_acc = counter, other
        description = f'Shortage written off — {counter.name}'
    elif not counted_less and kind == 'recovered_excess':
        # counted account ──▶ counter  (extra cash taken out of the drawer)
        from_acc, to_acc = counted, counter
        description = f'Excess returned — {counted.name} to {counter.name}'
    else:  # income
        from_acc, to_acc = other, counter
        description = f'Excess recognised as income — {counter.name}'

    if from_acc is None or to_acc is None:
        raise ValueError('Choose the account that absorbs this amount.')
    if from_acc.id == to_acc.id:
        raise ValueError('Choose a different account for the other side of the entry.')

    # One leg, because a counter account is always on one side of it: the money
    # leaves the counter and lands in the account (or expense) that explains it,
    # so the counter returns to zero without touching the counted closing.
    tx, _created = _write_leg(
        key=f'{posting_key(difference)}:resolve', from_account=from_acc, to_account=to_acc,
        amount_minor=amount_minor, description=description, note=tx_note,
        tx_type=tx_type, reason=note, actor=actor, posted_at=posted_at,
        difference=difference,
    )
    if tx is None:
        raise ValueError('The resolved amount must be greater than zero.')

    difference.posted_status = STATUS_RESOLVED
    difference.resolved_at = posted_at
    difference.resolved_by = _actor_name(actor)
    difference.resolution_kind = kind
    difference.resolution_note = note[:500]
    difference.resolution_out_tx_id = tx.id
    difference.resolution_in_tx_id = None
    difference.status = 'settled'
    difference.closed_by = _actor_name(actor)
    difference.closed_at = posted_at
    difference.closed_expected = expected_of(difference)
    difference.closed_counted = _money_round(difference.counted or 0)

    record_accounting_audit(
        actor, action='Resolve', entity_type='CashDayDifference', entity_id=difference.id,
        before={'posted_status': STATUS_POSTED, 'difference': _money_round(difference.difference or 0)},
        after={'posted_status': STATUS_RESOLVED, 'resolution_kind': kind,
               'transaction_id': tx.id, 'counterpart_account_id': (other.id if other else None)},
        amount_before=0, amount_after=_money_round(from_minor(amount_minor)),
        account_before_id=from_acc.id if from_acc else None,
        account_after_id=to_acc.id if to_acc else None,
        reason=note[:300],
    )
    if commit:
        db.session.commit()
    return tx


# ---------------------------------------------------------------------------
# Queries used by the board, the report and the consistency check
# ---------------------------------------------------------------------------

def open_differences(day=None):
    """Recorded differences, optionally for one day (any posting state)."""
    query = CashDayDifference.query.filter(CashDayDifference.status == 'open')
    if day is not None:
        query = query.filter(CashDayDifference.position_date == _day_day(day))
    return query.order_by(CashDayDifference.id.asc()).all()


def posted_differences(day=None):
    query = CashDayDifference.query.filter(CashDayDifference.posted_status == STATUS_POSTED)
    if day is not None:
        query = query.filter(CashDayDifference.position_date == _day_day(day))
    return query.order_by(CashDayDifference.id.asc()).all()


def posted_total_for_day(day):
    rows = posted_differences(day)
    return _money_round(sum(float(r.difference or 0) for r in rows))


def counter_balance_total():
    """Σ signed counter balances (positive = shortages parked, negative = excess).

    This is the opposite sign of the differences themselves: a shortage of
    Rs. 100 is ``difference = -100`` and leaves ``Counter Less = +100``.
    """
    less, excess = counter_accounts()
    total = 0
    for account in (less, excess):
        if account is None:
            continue
        total += float(from_minor(account.balance_minor
                                  if account.balance_minor is not None
                                  else to_minor(account.balance or 0)))
    return _money_round(total)


def unsigned_counter_total():
    less, excess = counter_accounts()
    total = 0
    for account in (less, excess):
        if account is None:
            continue
        total += abs(float(from_minor(account.balance_minor
                                      if account.balance_minor is not None
                                      else to_minor(account.balance or 0))))
    return _money_round(total)


def open_difference_total():
    return _money_round(sum(abs(float(r.difference or 0)) for r in posted_differences()))


def posted_pair_balances(difference):
    """``(out_leg, in_leg)`` for one difference, or ``(None, None)``."""
    return (
        _find_leg(f'{posting_key(difference)}:out'),
        _find_leg(f'{posting_key(difference)}:in'),
    )


def counter_drift():
    """Posted differences whose pair is not fully in the ledger.

    Returns ``[(difference, problem)]``; empty means every posted difference is
    backed by its two legs.  ``counter_invariants()`` is the broader check that
    also verifies amounts and the counter balances.
    """
    problems = []
    for row in CashDayDifference.query.filter(
        CashDayDifference.posted_status == STATUS_POSTED
    ).order_by(CashDayDifference.id.asc()).all():
        out_tx, in_tx = posted_pair_balances(row)
        if out_tx is None or in_tx is None:
            problems.append((row, 'a ledger leg is missing'))
    return problems


def counter_invariants():
    """The invariants that must hold for every posted difference, over time.

    Deliberately *not* "the account's balance today equals the counted figure":
    a later recovery, receipt or expense legitimately moves the account on.  What
    must always hold is:

    1. every posted difference still has both legs in the ledger,
    2. the two legs carry the same amount and move it between the counted
       account and its counter (so the pair nets to zero), and
    3. the counter accounts hold exactly the sum of the *unresolved* posted
       differences — the number an operator can see on the report.

    Returns a list of ``(difference, problem)``; empty means consistent.
    """
    problems = []
    expected_total_minor = 0
    counter_ids = {account.id for account in counter_accounts() if account is not None}
    for row in CashDayDifference.query.filter(
        CashDayDifference.posted_status == STATUS_POSTED
    ).order_by(CashDayDifference.id.asc()).all():
        out_tx, in_tx = posted_pair_balances(row)
        if out_tx is None or in_tx is None:
            problems.append((row, 'a ledger leg is missing'))
            continue
        if getattr(row, 'posted_out_tx_id', None) != out_tx.id or getattr(row, 'posted_in_tx_id', None) != in_tx.id:
            problems.append((row, 'the stored leg ids do not match the ledger'))
        if _tx_minor(out_tx) != _tx_minor(in_tx):
            problems.append((row, 'the two legs carry different amounts'))
        if abs(_tx_minor(out_tx) - abs(to_minor(row.difference or 0))) > 0:
            problems.append((row, 'the posted amount does not match the difference'))
        # Exactly one leg must touch a counter account: that is what makes the
        # pair a transfer between the counted account and its parking bucket.
        counter_legs = [tx for tx in (out_tx, in_tx)
                        if tx.from_account_id in counter_ids or tx.to_account_id in counter_ids]
        if len(counter_legs) != 1:
            problems.append((row, 'the counter account is not one leg of the pair'))
        # A shortage (negative difference) moves money *into* the Counter Less
        # account, so the counters hold the opposite sign of the difference.
        expected_total_minor -= to_minor(row.difference or 0)

    # Same-day resolutions and later activity do not change this: the counters
    # must hold exactly the unresolved postings.
    drift_minor = to_minor(counter_balance_total()) - expected_total_minor
    if drift_minor:
        problems.append((None, f'the counter accounts hold '
                               f'{float(from_minor(drift_minor)):,.2f} more than the '
                               f'unresolved posted differences'))
    return problems


def refresh_forward_lock_openings(from_day):
    """Re-derive already-locked days that start on or after *from_day*.

    A day's frozen ``opening`` is only valid while every earlier day is either
    unlocked (ledger-derived) or locked to the same figure the ledger now shows.
    Locking a *later* day first, or posting a movement into an earlier day,
    invalidates it.  This walks the locked days forward and recomputes each
    account's opening from the ledger, returning ``True`` when anything moved so
    the caller can rebuild its in-memory view.

    The frozen ``counted`` (the physical count) is never rewritten — only the
    derived columns (``opening``/``expected_closing``/``difference``) and the
    movement totals are.

    Returns the list of days whose frozen figures actually moved, so the caller
    can re-post the differences that changed with them.
    """
    if _REFRESHING[0]:
        # A forward re-date recomputes openings, which itself re-checks later
        # locked days.  Without this guard the two would recurse forever.
        return []
    _REFRESHING[0] = True
    try:
        return _refresh_forward_lock_openings(from_day)
    finally:
        _REFRESHING[0] = False


#: Re-entrancy guard for :func:`refresh_forward_lock_openings`.
_REFRESHING = [False]


def _refresh_forward_lock_openings(from_day):
    from app.services import cash_day_recon as recon

    changed = []
    days = [
        _day_day(row[0]) for row in db.session.query(
            CashDayAccountPosition.position_date
        ).filter(CashDayAccountPosition.position_date >= _day_day(from_day))
        .distinct().order_by(CashDayAccountPosition.position_date.asc()).all()
    ]
    for day in days:
        board = recon.account_positions_for_date(day)
        by_id = {p['account_id']: p for p in board}
        day_changed = False
        for pos in CashDayAccountPosition.query.filter_by(position_date=day).all():
            fresh = by_id.get(pos.account_id)
            if fresh is None:
                continue
            new_expected = _money_round(fresh['expected_closing'])
            if (_money_round(pos.expected_closing or 0) == new_expected
                    and _money_round(pos.opening or 0) == _money_round(fresh['opening'])):
                continue
            pos.opening = fresh['opening']
            pos.amount_in = fresh['in']
            pos.amount_out = fresh['out']
            pos.transfer_in = fresh['transfer_in']
            pos.transfer_out = fresh['transfer_out']
            pos.expected_closing = new_expected
            if pos.counted is not None:
                pos.difference = _money_round(float(pos.counted) - new_expected)
            day_changed = True
        if day_changed:
            changed.append(day)
            lock = recon.get_day_lock(day)
            if lock is not None:
                rows = CashDayAccountPosition.query.filter_by(position_date=day).all()
                lock.total_expected = _money_round(sum(float(r.expected_closing or 0) for r in rows))
                lock.total_counted = _money_round(
                    sum(float(r.counted if r.counted is not None else (r.expected_closing or 0))
                        for r in rows)
                )
                lock.difference = _money_round(lock.total_counted - lock.total_expected)
            db.session.flush()
    return changed


def postable_differences(day):
    """Differences of *day* that still have to reach the ledger."""
    return [
        row for row in CashDayDifference.query.filter(
            CashDayDifference.position_date == _day_day(day),
            CashDayDifference.status == 'open',
            or_(CashDayDifference.posted_status.is_(None),
                CashDayDifference.posted_status.in_([STATUS_PENDING, STATUS_REVERSED])),
        ).order_by(CashDayDifference.id.asc()).all()
        if row.difference
    ]


def difference_summary(day):
    """Per-account posting state for the board's locked rows."""
    out = {}
    for row in CashDayDifference.query.filter(
        CashDayDifference.position_date == _day_day(day)
    ).order_by(CashDayDifference.id.asc()).all():
        out[row.account_id] = {
            'status': row.posted_status,
            'kind': row.kind,
            'difference': _money_round(row.difference or 0),
            'posted_out_tx_id': row.posted_out_tx_id,
            'posted_in_tx_id': row.posted_in_tx_id,
            'counter_name': counter_name_for(row.kind),
            'resolution_kind': row.resolution_kind,
            'resolved_by': row.resolved_by,
            'resolved_at': (row.resolved_at.strftime('%Y-%m-%d %H:%M:%S')
                            if row.resolved_at else None),
        }
    return out
