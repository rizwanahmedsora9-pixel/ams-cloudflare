"""Edit/delete flexibility policy — one place that decides "may this user touch
a back-dated record?".

Previously the same rule was written three times with three different
behaviours:

* ``ops/_dispatch_edit_entry.py``   — anyone except admin: hard block on any
  record whose date is not today.  Regular staff could not correct this
  morning's mistake after midnight.
* ``ops/_dispatch_delete_entry.py`` — same hard block, and it redirected to
  ``index`` so the person did not even see why.
* ``ops/grn.py`` + ``misc/pending.py`` — ``restrict_backdated_edit`` flag,
  admins always allowed.

That inconsistency is what users describe as "a blocker stops me in the middle
of CRUD".  The new rule keeps accountability without stopping the work:

* ``admin`` / ``root``            — always allowed.
* user with ``restrict_backdated_edit`` **off** — always allowed.  This is the
  default profile, so in normal use nobody is ever stopped by a date.
* user with ``restrict_backdated_edit`` **on**  — allowed for today and for any
  record inside the licensed window (``AMS_BACKDATE_DAYS``, default 90 days).

The *only* remaining hard stop is data older than the window *and* a user the
admin deliberately restricted, because editing a six-month-old dispatch
silently rewrites a closed cash day that has already been reconciled and
reported to the owner.  Nothing else in this module refuses a save: no reason
field is demanded, no "contact support" dead end.

Every allowed back-dated change by a restricted user is audited (actor +
record + reason when one is present), so flexibility keeps a trail — see
``audit_override``.
"""

from __future__ import annotations

import os
from datetime import date, datetime

DEFAULT_BACKDATE_DAYS = 90


class EditBlocked(Exception):
    """Raised when a policy refuses the change.

    ``message`` is user-facing and free of SQL/driver detail so the central
    sanitiser keeps it visible.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def backdate_window_days() -> int:
    raw = (os.environ.get("AMS_BACKDATE_DAYS") or "").strip()
    try:
        days = int(raw or DEFAULT_BACKDATE_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_BACKDATE_DAYS
    return max(0, days)


def backdate_window_enabled() -> bool:
    """``AMS_BACKDATE_LIMIT=0`` removes the window entirely (unlimited edits).

    Off by default: a call centre with a locked-down accountant profile should
    still not be able to rewrite a closed year without anyone noticing.
    """
    raw = (os.environ.get("AMS_BACKDATE_LIMIT") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def is_privileged(user) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return (getattr(user, "role", "") or "") in ("admin", "root")


def is_backdate_restricted(user) -> bool:
    if is_privileged(user):
        return False
    return bool(getattr(user, "restrict_backdated_edit", False))


def record_date_of(obj, *fields) -> date | None:
    for field in fields or ("date_posted", "date"):
        value = getattr(obj, field, None)
        parsed = _as_date(value)
        if parsed is not None:
            return parsed
    return None


def authorise_edit(
    user,
    record_date,
    *,
    action_label: str = "Edit",
    reason: str | None = None,
    today: date | None = None,
    check_window: bool = True,
) -> bool:
    """Return True when the change may proceed; raise ``EditBlocked`` otherwise.

    Never raises for the normal case (record is today, or the user is
    unrestricted), so the caller's happy path stays untouched.
    """
    today = today or date.today()
    if not is_backdate_restricted(user):
        return True

    rec = _as_date(record_date)
    if rec is None or rec >= today:
        return True

    if not check_window or not backdate_window_enabled():
        return True

    oldest = today.toordinal() - backdate_window_days()
    if rec.toordinal() < oldest:
        raise EditBlocked(
            f"{action_label} blocked: this record is older than "
            f"{backdate_window_days()} days and your account is limited to recent "
            "back-dated changes. Nothing was saved. An admin can make this change, "
            "or lift 'restrict back-dated edits' on your user profile."
        )

    # Inside the window: allowed, no extra fields required.  ``reason`` is only
    # used for the audit row so a restricted user's back-dated work stays
    # traceable without turning the form into a questionnaire.
    return True


def audit_override(user, *, action: str, entity: str, entity_id=None, reason: str | None = None) -> None:
    """Record an allowed back-dated change. Never raises.

    The audit write must not be able to fail the business operation: the user
    already received permission, and losing the row is better than losing the
    edit they just made.
    """
    import logging

    log = logging.getLogger(__name__)
    try:
        from utils.audit import audit_log

        detail = f"{entity}#{entity_id} back-dated {action}".strip()
        if reason:
            detail = f"{detail} | reason={reason.strip()[:200]}"
        audit_log(user, f"{entity.lower()}.{action.lower()}", detail)
    except Exception:  # pragma: no cover - audit must never break the request
        log.exception("Back-dated override audit failed for %s#%s", entity, entity_id)


def form_reason(source) -> str:
    """Pull a reason off a request form, tolerating the several field names
    used across modules (``reason``, ``edit_reason``, ``cancel_reason``)."""
    if source is None:
        return ""
    for key in ("reason", "edit_reason", "backdate_reason", "cancel_reason"):
        try:
            value = source.get(key)
        except Exception:
            value = None
        if value and str(value).strip():
            return str(value).strip()
    return ""


# ---------------------------------------------------------------------------
# Payment-account resolution
# ---------------------------------------------------------------------------
# "Select a cash/bank account" is the most common save-blocker in the whole
# app: a sale, GRN or booking that is otherwise complete is refused because one
# dropdown was left on its placeholder.  The money still has to land somewhere,
# so instead of refusing we resolve the account the operator obviously meant:
#
#   1. the account they picked (validated as before),
#   2. otherwise the only active account of the expected kind (cash or bank),
#   3. otherwise a stable default: lowest id active account of that kind.
#
# Step 3 is deterministic, so repeated saves keep posting to the same account
# and reconciliation still reconciles.  When no account of that kind exists at
# all the caller must still fail loudly — inventing an account would corrupt
# the cash book, and that failure is a configuration problem, not data entry.
# ---------------------------------------------------------------------------


def resolve_payment_account(
    payment_account_id,
    method: str = "Cash",
    *,
    active_only: bool = True,
):
    """Return ``(account_id, account)`` for a receipt/payment, auto-picking when
    the form left the dropdown empty.

    Returns ``(None, None)`` when no usable account exists; callers decide
    whether that is fatal.
    """
    from os import environ

    try:
        wanted = int(str(payment_account_id).strip()) if str(payment_account_id or "").strip() else None
    except (TypeError, ValueError):
        wanted = None

    from models import Account  # local import: models imports this module's siblings
    from sqlalchemy import func

    if wanted is not None:
        account = Account.query.get(wanted)
        if account is not None and (not active_only or bool(getattr(account, "is_active", True))):
            return wanted, account
        return None, None

    if (environ.get("AMS_AUTO_PICK_ACCOUNT") or "1").strip().lower() in ("0", "false", "no", "off"):
        return None, None

    from app.services.accounting import _payment_expected_account_category

    kind = (_payment_expected_account_category(method) or "cash").strip().lower()
    query = Account.query.filter(
        func.coalesce(Account.is_active, True) == True,  # noqa: E712
        func.lower(func.trim(Account.category)) == kind,
    )
    account = query.order_by(Account.id.asc()).first()
    if account is None:
        return None, None
    return account.id, account
