"""CRUD flexibility policy: no accidental blockers, no silent data loss.

These tests pin the behaviour the shop asked for — "editing a sale, a GRN or any
transaction must go through, not stop me half-way" — while keeping the one hard
stop that protects closed books (a deliberately restricted user touching data
older than the licensed window).
"""
import datetime
from types import SimpleNamespace

import pytest

from app.services import edit_policy as policy


def _user(role="user", restricted=False):
    return SimpleNamespace(
        is_authenticated=True,
        role=role,
        id=7,
        username="tester",
        restrict_backdated_edit=restricted,
    )


TODAY = datetime.date(2026, 11, 11)


@pytest.mark.parametrize(
    "label,user,offset,expected",
    [
        ("admin, ancient record", _user("admin"), 400, True),
        ("root, ancient record", _user("root"), 3000, True),
        ("normal user, ancient record", _user(), 400, True),
        ("restricted user, today", _user(restricted=True), 0, True),
        ("restricted user, inside window", _user(restricted=True), 10, True),
        ("restricted user, outside window", _user(restricted=True), 200, False),
    ],
)
def test_authorise_edit_matches_policy(label, user, offset, expected):
    record_date = TODAY - datetime.timedelta(days=offset)
    try:
        allowed = policy.authorise_edit(
            user, record_date, action_label="Edit test", today=TODAY
        )
    except policy.EditBlocked as blocked:
        assert blocked.message, "a refusal must explain itself to the operator"
        allowed = False
    assert allowed is expected, label


def test_normal_profile_is_never_blocked_by_a_date():
    """The default user profile has no date-based stop at all."""
    for offset in (0, 1, 45, 500, 5000):
        assert policy.authorise_edit(
            _user(), TODAY - datetime.timedelta(days=offset), today=TODAY
        ) is True


def test_window_can_be_disabled_entirely(monkeypatch):
    monkeypatch.setenv("AMS_BACKDATE_LIMIT", "0")
    assert policy.authorise_edit(
        _user(restricted=True), TODAY - datetime.timedelta(days=3650), today=TODAY
    ) is True


def test_window_length_is_configurable(monkeypatch):
    monkeypatch.setenv("AMS_BACKDATE_DAYS", "400")
    assert policy.authorise_edit(
        _user(restricted=True), TODAY - datetime.timedelta(days=300), today=TODAY
    ) is True
    with pytest.raises(policy.EditBlocked):
        policy.authorise_edit(
            _user(restricted=True), TODAY - datetime.timedelta(days=500), today=TODAY
        )


def test_reason_is_never_required_to_save():
    """Flexibility: an inside-window edit passes without any reason text."""
    assert policy.authorise_edit(
        _user(restricted=True),
        TODAY - datetime.timedelta(days=3),
        action_label="Edit GRN",
        reason=None,
        today=TODAY,
    ) is True


def test_record_date_of_reads_datetime_and_string():
    obj = SimpleNamespace(date_posted=datetime.datetime(2026, 1, 5, 9, 30))
    assert policy.record_date_of(obj) == datetime.date(2026, 1, 5)
    assert policy.record_date_of(SimpleNamespace(date="2026-02-03")) == datetime.date(2026, 2, 3)
    assert policy.record_date_of(SimpleNamespace(date=None)) is None


def test_form_reason_accepts_the_field_names_used_across_modules():
    form = {"edit_reason": "  wrong client  "}
    assert policy.form_reason(form) == "wrong client"
    assert policy.form_reason({"reason": "typo"}) == "typo"
    assert policy.form_reason({}) == ""


def test_resolve_payment_account_prefers_the_selected_account(app):
    from models import Account, db

    with app.app_context():
        cash = Account(name="Counter Cash", type="cash", category="cash",
                       account_type="company", balance=0, is_active=True)
        bank = Account(name="HBL Main", type="bank", category="bank",
                       account_type="company", balance=0, is_active=True)
        db.session.add_all([cash, bank])
        db.session.commit()

        picked_id, picked = policy.resolve_payment_account(bank.id, "Bank")
        assert picked_id == bank.id and picked.name == "HBL Main"

        auto_id, auto = policy.resolve_payment_account(None, "Cash")
        assert auto is not None and auto.category == "cash"
        # deterministic: repeated saves keep posting to the same account
        assert policy.resolve_payment_account(None, "Cash")[0] == auto_id


def test_resolve_payment_account_returns_none_when_nothing_exists(app):
    with app.app_context():
        assert policy.resolve_payment_account(None, "Cash") == (None, None)
