from __future__ import annotations

from datetime import date, datetime

from app.services import cash_day_recon as recon
from app.services import recon_counter
from app.services.accounting import _apply_account_tx_effect
from app.services.payments_crud import ledger_balance
from models import (
    Account, AccountTransaction, CashDayDifference, CashDayLock, Settings, db,
)
from utils.money import to_minor


def _login(client):
    resp = client.post(
        "/login",
        data={"username": "Admin", "password": "Admin@fbm12345"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def _make_cash_account(name="Main Cash Drawer", balance=1000.0):
    acc = Account(
        name=name,
        type="company",
        account_type="company",
        category="cash",
        source_category="Company",
        balance=float(balance),
        balance_minor=to_minor(balance),
        opening_balance=float(balance),
        opening_balance_minor=to_minor(balance),
        opening_balance_date=datetime(2026, 1, 1),
        is_active=True,
    )
    db.session.add(acc)
    db.session.flush()
    return acc


def test_save_count_shortage_and_excess_immediately_update_accounts(app, client):
    """Saving a counted difference immediately posts to the account and counters."""
    _login(client)
    day = date(2026, 11, 10)
    with app.app_context():
        db.session.add(Settings())
        cash = _make_cash_account("Drawer A", balance=1000)
        bank = _make_cash_account("Bank B", balance=5000)
        bank.category = "bank"
        db.session.commit()
        cash_id, bank_id = cash.id, bank.id

    # Shortage on Drawer A: expected 1,000, counted 900 -> -100 immediately updates Accounts.
    res = client.post(
        "/daily_reconciliation",
        data={
            "action": "save_count",
            "day": day.isoformat(),
            "account_id": str(cash_id),
            "counted": "900",
        },
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["posting"]["less_total"] == -100.0
    assert payload["counter_total"] == 100.0
    cash_pos = next(p for p in payload["positions"] if p["account_id"] == cash_id)
    assert cash_pos["expected_closing"] == 1000.0
    assert cash_pos["counted"] == 900.0
    assert cash_pos["difference"] == -100.0
    assert cash_pos["posting"]["status"] == "posted"

    with app.app_context():
        assert db.session.get(Account, cash_id).balance == 900.0
        assert ledger_balance(cash_id) == 900.0
        less, excess = recon_counter.counter_accounts()
        assert less is not None and less.balance == 100.0
        assert excess is not None and excess.balance == 0.0
        assert recon.get_day_lock(day) is None
        assert recon_counter.counter_invariants() == []

    # Excess on Bank B: expected 5,000, counted 5,250 -> +250 immediately updates Accounts.
    res2 = client.post(
        "/daily_reconciliation",
        data={
            "action": "save_count",
            "day": day.isoformat(),
            "account_id": str(bank_id),
            "counted": "5,250",
        },
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    assert res2.status_code == 200
    payload2 = res2.get_json()
    assert payload2["posting"]["excess_total"] == 250.0
    assert payload2["counter_total"] == -150.0  # +100 less, -250 excess

    with app.app_context():
        assert db.session.get(Account, bank_id).balance == 5250.0
        assert ledger_balance(bank_id) == 5250.0
        less, excess = recon_counter.counter_accounts()
        assert less.balance == 100.0
        assert excess.balance == -250.0
        assert recon_counter.counter_invariants() == []

    # Accounts page and Accounts dashboard immediately reflect the counted balances.
    accounts_html = client.get("/accounts/accounts").get_data(as_text=True)
    assert "900.00" in accounts_html
    assert "5250.00" in accounts_html
    assert "Counter Less Account" not in accounts_html
    assert "Counter Excess Account" not in accounts_html

    dash_html = client.get("/accounts/").get_data(as_text=True)
    assert "6150.00" in dash_html  # 900 + 5,250


def test_editing_and_clearing_counts_sync_and_reverse_cleanly(app, client):
    """Editing a saved count or clearing it cleanly updates Accounts and counters."""
    _login(client)
    day = date(2026, 11, 10)
    with app.app_context():
        db.session.add(Settings())
        cash = _make_cash_account("Editable Drawer", balance=1000)
        db.session.commit()
        cash_id = cash.id

    # 1. Shortage -100 (900)
    with app.app_context():
        recon.save_count(day, cash_id, "900", actor="Admin")
        assert db.session.get(Account, cash_id).balance == 900.0
        assert recon_counter.counter_balance_total() == 100.0

        # 2. Edit count to 950 (-50): old -100 reversed, new -50 posted.
        recon.save_count(day, cash_id, "950", actor="Admin")
        assert db.session.get(Account, cash_id).balance == 950.0
        assert ledger_balance(cash_id) == 950.0
        assert recon_counter.counter_balance_total() == 50.0
        assert recon_counter.counter_invariants() == []

        # 3. Flip from shortage (-50) to excess (+150 -> 1150)
        recon.save_count(day, cash_id, "1150", actor="Admin")
        assert db.session.get(Account, cash_id).balance == 1150.0
        less, excess = recon_counter.counter_accounts()
        assert less.balance == 0.0
        assert excess.balance == -150.0
        assert recon_counter.counter_invariants() == []

        # 4. Edit to exact match (1000 -> 0 diff): settles and reverses.
        recon.save_count(day, cash_id, "1000", actor="Admin")
        assert db.session.get(Account, cash_id).balance == 1000.0
        less, excess = recon_counter.counter_accounts()
        assert less.balance == 0.0 and excess.balance == 0.0
        assert recon_counter.counter_invariants() == []

        # 5. Re-enter shortage (-200 -> 800), then clear count completely.
        recon.save_count(day, cash_id, "800", actor="Admin")
        assert db.session.get(Account, cash_id).balance == 800.0
        assert recon_counter.counter_balance_total() == 200.0

        recon.delete_count(day, cash_id, actor="Admin")
        assert db.session.get(Account, cash_id).balance == 1000.0
        assert ledger_balance(cash_id) == 1000.0
        assert recon_counter.counter_balance_total() == 0.0
        assert recon_counter.counter_invariants() == []


def test_lock_unlock_refresh_and_resolve_with_live_save_count(app):
    """Locking after save_count never double-posts; refresh & resolve stay exact."""
    day = date(2026, 11, 10)
    with app.app_context():
        db.session.add(Settings())
        cash = _make_cash_account("Lock Flow Cash", balance=1000)
        db.session.commit()
        cash_id = cash.id

        # Save count 900 -> immediately posts -100.
        recon.save_count(day, cash_id, "900", actor="Admin")
        assert db.session.get(Account, cash_id).balance == 900.0

        # A late receipt (+100) enters the ledger on the same day -> balance 1000,
        # expected closing 1100, counted still 900 -> refresh_differences updates diff to -200!
        tx = AccountTransaction(
            to_account_id=cash_id,
            amount=100.0,
            amount_minor=to_minor(100.0),
            description="Cash sale receipt",
            transaction_type="Receipt",
            date_posted=datetime(2026, 11, 10, 14, 0, 0),
        )
        db.session.add(tx)
        db.session.flush()
        _apply_account_tx_effect(tx)
        db.session.commit()

        assert db.session.get(Account, cash_id).balance == 1000.0
        checked = recon.refresh_differences(day, actor="Admin")
        assert checked == 1
        assert db.session.get(Account, cash_id).balance == 900.0
        assert recon_counter.counter_balance_total() == 200.0
        assert recon_counter.counter_invariants() == []

        # Lock day: must NOT double-post; posted_total should equal 200.
        lock = recon.lock_day(day, actor="Admin", note="EOD")
        assert isinstance(lock, CashDayLock)
        assert lock.posted_total == 200.0
        assert db.session.get(Account, cash_id).balance == 900.0
        assert recon_counter.counter_balance_total() == 200.0
        assert recon_counter.counter_invariants() == []

        # Unlock day: day opens for editing while keeping Accounts at 900 (saved count).
        recon.unlock_day(day, actor="Admin")
        assert recon.get_day_lock(day) is None
        assert db.session.get(Account, cash_id).balance == 900.0
        assert recon_counter.counter_balance_total() == 200.0

        # Re-lock and resolve shortage as recovered -> Counter Less returns to 0.
        recon.lock_day(day, actor="Admin", note="Re-locked")
        diff_row = CashDayDifference.query.filter_by(
            position_date=day, account_id=cash_id, status="open"
        ).one()
        recon_counter.resolve_difference(
            diff_row, kind="recovered_less", note="Found in safe", actor="Admin"
        )
        db.session.commit()
        assert db.session.get(Account, cash_id).balance == 1100.0
        assert recon_counter.counter_balance_total() == 0.0
        assert recon_counter.counter_invariants() == []

        # P&L never includes any reconciliation posting or resolution.
        from app.services.profit_loss import _Projection
        proj = _Projection().build()
        recon_tx_ids = {
            r.id for r in AccountTransaction.query.filter(
                AccountTransaction.source_type == "CashDayDifference"
            ).all()
        }
        assert not any(
            row.get("document_type") == "AccountTransaction"
            and row.get("document_id") in recon_tx_ids
            for row in proj.rows
        )


def test_editing_earlier_open_day_resyncs_later_day_openings_and_balances(app):
    """Changing day 1's saved count keeps day 2's opening, difference, and Accounts exact."""
    day1 = date(2026, 11, 9)
    day2 = date(2026, 11, 10)
    with app.app_context():
        db.session.add(Settings())
        cash = _make_cash_account("Multi-Day Drawer", balance=1000)
        db.session.commit()
        cash_id = cash.id

        # Day 1 counted 900 (-100), Day 2 counted 850 (-50 against opening 900).
        recon.save_count(day1, cash_id, "900", actor="Admin")
        recon.save_count(day2, cash_id, "850", actor="Admin")
        assert db.session.get(Account, cash_id).balance == 850.0
        assert recon_counter.counter_balance_total() == 150.0
        assert recon_counter.counter_invariants() == []

        # Edit Day 1 to 950 (-50): Day 2 opening shifts to 950 -> Day 2 diff becomes -100 ->
        # total counter remains 150 and Cash remains 850 (matching Day 2's count!).
        recon.save_count(day1, cash_id, "950", actor="Admin")
        assert db.session.get(Account, cash_id).balance == 850.0
        assert recon_counter.counter_balance_total() == 150.0
        assert recon_counter.counter_invariants() == []
        d2_pos = next(
            p for p in recon.account_positions_for_date(day2)
            if p["account_id"] == cash_id
        )
        assert d2_pos["opening"] == 950.0
        assert d2_pos["difference"] == -100.0
