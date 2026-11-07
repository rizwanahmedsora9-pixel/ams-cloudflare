from datetime import date, datetime, timedelta

from models import Account, AccountTransaction, CashDayDifference, db
from app.services import cash_day_recon as recon


def _account(name='Drawer', balance=1400):
    account = Account(name=name, type='CASH', account_type='company', category='cash',
                      opening_balance=balance, balance=balance,
                      opening_balance_date=datetime(2020, 1, 1), is_active=True)
    db.session.add(account)
    db.session.commit()
    return account


def _login(client):
    client.post('/login', data={'username': 'Admin', 'password': 'Admin@fbm12345'})


def _post(client, day, account_id, count):
    return client.post('/daily_reconciliation', data={
        'action': 'save_count', 'day': day.isoformat(), 'account_id': account_id, 'counted': count,
    }, headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'})


def test_difference_is_reporting_only_and_settles_on_correction(app, client):
    with app.app_context():
        account = _account()
        aid = account.id
        tx_count = AccountTransaction.query.count()
    _login(client)
    day = date.today()
    assert _post(client, day, aid, '1500').status_code == 200
    # Saving the identical count again must not create a duplicate.
    assert _post(client, day, aid, '1500').status_code == 200
    with app.app_context():
        row = CashDayDifference.query.one()
        assert (row.kind, row.difference, row.expected, row.counted, row.status) == ('excess', 100, 1400, 1500, 'open')
        assert row.recorded_by == 'Admin'
        assert db.session.get(Account, aid).balance == 1400
        assert AccountTransaction.query.count() == tx_count
        assert Account.query.count() == 1  # no financial accounts for these reports
    client.post('/daily_reconciliation', data={'action': 'lock', 'day': day.isoformat()})
    with app.app_context():
        assert recon.account_positions_for_date(day + timedelta(days=1))[0]['opening'] == 1500
        assert CashDayDifference.query.count() == 1
    # Locked counts are read-only until the existing unlock action is used.
    assert _post(client, day, aid, '1400').status_code == 400
    client.post('/daily_reconciliation', data={'action': 'unlock', 'day': day.isoformat()})
    assert _post(client, day, aid, '1400').status_code == 200
    with app.app_context():
        row = CashDayDifference.query.one()
        assert row.status == 'settled'
        assert row.closed_by == 'Admin' and row.closed_at is not None
        assert (row.expected, row.counted, row.difference) == (1400, 1500, 100)
        assert (row.closed_expected, row.closed_counted) == (1400, 1400)
        assert AccountTransaction.query.count() == tx_count
    html = client.get('/daily_reconciliation/differences').get_data(as_text=True)
    assert 'Less Counted Transactions' in html and 'Excess Counted Transactions' in html
    assert 'SETTLED' in html and 'diff-settled' in html and 'Admin' in html


def test_changing_or_clearing_is_not_falsely_called_settled(app, client):
    with app.app_context():
        aid = _account().id
    _login(client)
    day = date.today()
    _post(client, day, aid, '1300')
    _post(client, day, aid, '1350')
    _post(client, day, aid, '1450')
    with app.app_context():
        rows = CashDayDifference.query.order_by(CashDayDifference.id).all()
        assert [(r.kind, r.difference, r.status) for r in rows] == [
            ('less', -100, 'superseded'), ('less', -50, 'superseded'), ('excess', 50, 'open')]
    client.post('/daily_reconciliation', data={'action': 'clear_count', 'day': day.isoformat(), 'account_id': aid})
    with app.app_context():
        row = CashDayDifference.query.order_by(CashDayDifference.id.desc()).first()
        assert row.status == 'cleared' and row.closed_by == 'Admin'
        assert row.closed_counted is None


def test_refresh_after_ledger_correction_and_legacy_counts(app, client):
    from models import CashDayAccountPosition
    with app.app_context():
        account = _account()
        aid = account.id
        day = date.today() - timedelta(days=1)
        # Existing count from before this feature is adopted when explicitly checked.
        db.session.add(CashDayAccountPosition(position_date=day, account_id=aid,
            account_name='Drawer', counted=1500, updated_by='Old user'))
        db.session.commit()
    _login(client)
    client.post('/daily_reconciliation', data={'action': 'refresh_differences', 'day': day.isoformat()})
    with app.app_context():
        assert CashDayDifference.query.one().status == 'open'
        db.session.add(AccountTransaction(to_account_id=aid, amount=100, amount_minor=10000,
            transaction_type='Receipt', date_posted=datetime.combine(day, datetime.min.time()).replace(hour=12), is_void=False))
        db.session.commit()
    client.post('/daily_reconciliation', data={'action': 'refresh_differences', 'day': day.isoformat()})
    with app.app_context():
        row = CashDayDifference.query.one()
        assert row.status == 'settled'
        assert row.closed_by == 'Admin'
        assert row.closed_expected == row.closed_counted == 1500


def test_report_pagination_and_date_filter(app, client):
    with app.app_context():
        account = _account()
        day = date.today()
        for i in range(12):
            db.session.add(CashDayDifference(position_date=day, account_id=account.id,
                account_name='Drawer', kind='less', expected=1400, counted=1300,
                difference=-100, status='open', recorded_by=f'User {i}',
                recorded_at=datetime(2026, 1, 1) + timedelta(minutes=i)))
        db.session.commit()
    _login(client)
    page1 = client.get('/daily_reconciliation/differences').get_data(as_text=True)
    assert 'User 11' in page1 and 'User 0' not in page1 and 'Page 1 of 2' in page1
    page2 = client.get('/daily_reconciliation/differences?less_page=2').get_data(as_text=True)
    assert 'User 0' in page2 and 'User 11' not in page2
    filtered = client.get('/daily_reconciliation/differences?from_date=2000-01-01&to_date=2000-01-02').get_data(as_text=True)
    assert 'User 11' not in filtered


def test_import_older_counts_is_explicit_idempotent_and_labeled(app, client):
    from models import CashDayAccountPosition
    with app.app_context():
        account = _account()
        db.session.add(CashDayAccountPosition(position_date=date.today(), account_id=account.id,
            account_name=account.name, counted=1300, updated_by='Old user'))
        db.session.commit()
    _login(client)
    client.post('/daily_reconciliation/differences')
    client.post('/daily_reconciliation/differences')
    with app.app_context():
        row = CashDayDifference.query.one()
        assert (row.source, row.recorded_by, row.difference) == ('imported', 'Admin', -100)
    html = client.get('/daily_reconciliation/differences').get_data(as_text=True)
    assert 'IMPORTED SNAPSHOT' in html


def _seed_difference(account, *, kind, difference, counted, status='open',
                       recorded_by='Admin', source='live', day=None, minutes=0):
    difference = float(difference)
    db.session.add(CashDayDifference(
        position_date=day or date.today(), account_id=account.id,
        account_name=account.name, kind=kind, expected=float(counted) - difference,
        counted=float(counted), difference=difference, status=status, source=source,
        recorded_by=recorded_by,
        recorded_at=datetime(2026, 1, 1) + timedelta(minutes=minutes)))
    db.session.commit()


def test_report_filters_less_excess_status_account_and_user(app, client):
    with app.app_context():
        drawer = _account()
        till = _account(name='Till', balance=2000)
        # Counted amounts are unique per row so a row can be spotted in HTML
        # without matching a dropdown, total or summary figure.
        _seed_difference(drawer, kind='less', difference=-100, counted=1111, recorded_by='Ali')
        _seed_difference(drawer, kind='less', difference=-50, counted=1222,
                         status='settled', recorded_by='Ali')
        _seed_difference(drawer, kind='excess', difference=200, counted=1333, recorded_by='Sara')
        _seed_difference(till, kind='excess', difference=500, counted=1444, recorded_by='Ali')
        drawer_id, till_id = drawer.id, till.id
    _login(client)
    base = '/daily_reconciliation/differences'

    less_only = client.get(f'{base}?kind=less').get_data(as_text=True)
    assert 'Less Counted Transactions' in less_only
    assert 'Excess Counted Transactions' not in less_only
    assert 'Rs. 1,111.00' in less_only and 'Rs. 1,333.00' not in less_only
    # Filtered totals cover every matching page: 100 + 50 shortage.
    assert 'Rs. 150.00' in less_only

    excess_open = client.get(f'{base}?kind=excess&status=open').get_data(as_text=True)
    assert 'Excess Counted Transactions' in excess_open
    assert 'Less Counted Transactions' not in excess_open
    assert 'Rs. 1,333.00' in excess_open and 'Rs. 1,444.00' in excess_open

    settled = client.get(f'{base}?status=settled').get_data(as_text=True)
    assert 'Rs. 1,222.00' in settled and 'Rs. 1,111.00' not in settled

    by_account = client.get(f'{base}?account_id={till_id}').get_data(as_text=True)
    assert 'Rs. 1,444.00' in by_account and 'Rs. 1,111.00' not in by_account
    assert drawer_id != till_id

    by_user = client.get(f'{base}?recorded_by=Sar').get_data(as_text=True)
    assert 'Rs. 1,333.00' in by_user and 'Rs. 1,444.00' not in by_user

    imported = client.get(f'{base}?source=imported').get_data(as_text=True)
    assert 'Rs. 1,111.00' not in imported and 'No less counted' in imported


def test_report_date_presets_amount_range_sort_and_search(app, client):
    with app.app_context():
        drawer = _account()
        today = date.today()
        _seed_difference(drawer, kind='less', difference=-100, counted=2111, day=today, minutes=1)
        _seed_difference(drawer, kind='excess', difference=900, counted=2222, day=today, minutes=2)
        _seed_difference(drawer, kind='less', difference=-40, counted=2333,
                         day=today - timedelta(days=40), minutes=3)
    _login(client)
    base = '/daily_reconciliation/differences'

    today_html = client.get(f'{base}?preset=today').get_data(as_text=True)
    assert 'Rs. 2,111.00' in today_html and 'Rs. 2,333.00' not in today_html
    last_30 = client.get(f'{base}?preset=last_30').get_data(as_text=True)
    assert 'Rs. 2,111.00' in last_30 and 'Rs. 2,333.00' not in last_30
    everything = client.get(f'{base}?preset=all').get_data(as_text=True)
    assert 'Rs. 2,333.00' in everything

    big_only = client.get(f'{base}?amount_min=150').get_data(as_text=True)
    assert 'Rs. 2,222.00' in big_only and 'Rs. 2,111.00' not in big_only
    small_only = client.get(f'{base}?amount_max=100').get_data(as_text=True)
    assert 'Rs. 2,111.00' in small_only and 'Rs. 2,222.00' not in small_only
    assert client.get(f'{base}?amount_min=abc').status_code == 400
    assert client.get(f'{base}?amount_min=500&amount_max=100').status_code == 400
    assert client.get(f'{base}?account_id=abc').status_code == 400

    # Sorting applies inside each card: the Rs. 100 shortage precedes Rs. 40.
    largest = client.get(f'{base}?sort=largest').get_data(as_text=True)
    assert largest.index('Rs. 2,111.00') < largest.index('Rs. 2,333.00')
    smallest = client.get(f'{base}?sort=smallest').get_data(as_text=True)
    assert smallest.index('Rs. 2,333.00') < smallest.index('Rs. 2,111.00')

    searched = client.get(f'{base}?q=Drawer').get_data(as_text=True)
    assert 'Rs. 2,111.00' in searched
    no_match = client.get(f'{base}?q=No+Such+Place').get_data(as_text=True)
    assert 'Rs. 2,111.00' not in no_match


def test_report_account_summary_and_csv_export(app, client):
    with app.app_context():
        drawer = _account()
        till = _account(name='Till', balance=2000)
        _seed_difference(drawer, kind='less', difference=-100, counted=3111)
        _seed_difference(drawer, kind='excess', difference=300, counted=3222)
        _seed_difference(till, kind='less', difference=-700, counted=3333, status='settled')
    _login(client)
    html = client.get('/daily_reconciliation/differences').get_data(as_text=True)
    assert 'Summary by Account' in html
    # Drawer nets +200, Till nets -700; the filtered grand net is -500.
    assert 'Rs. 200.00' in html and 'Rs. -700.00' in html and 'Rs. -500.00' in html

    response = client.get('/daily_reconciliation/differences?kind=less&export_csv=1')
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('text/csv')
    body = response.get_data(as_text=True)
    assert 'Day,Account,Type' in body
    assert '-100.00' in body and '-700.00' in body
    assert '300.00' not in body  # excess row is filtered out of the download


def test_report_pagination_keeps_filters(app, client):
    with app.app_context():
        account = _account()
        for i in range(12):
            _seed_difference(account, kind='less', difference=-100, counted=1300,
                             recorded_by=f'User {i}', minutes=i)
    _login(client)
    page1 = client.get('/daily_reconciliation/differences?kind=less&status=open').get_data(as_text=True)
    assert 'User 11' in page1 and 'User 0' not in page1
    assert 'kind=less' in page1 and 'status=open' in page1 and 'less_page=2' in page1
    page2 = client.get('/daily_reconciliation/differences?kind=less&status=open&less_page=2').get_data(as_text=True)
    assert 'User 0' in page2 and 'User 11' not in page2


def test_report_obeys_cash_flow_permission(app, client):
    from werkzeug.security import generate_password_hash
    from models import User
    with app.app_context():
        db.session.add(User(username='limited', password_hash=generate_password_hash('Clerk@12345'),
                            role='user', status='active', can_view_cash_flow=False))
        db.session.commit()
    client.post('/login', data={'username': 'limited', 'password': 'Clerk@12345'})
    response = client.get('/daily_reconciliation/differences')
    assert response.status_code in (302, 303, 403)
    response = client.post('/daily_reconciliation/differences')
    assert response.status_code in (302, 303, 403)


def test_spreadsheet_replace_cannot_forge_or_erase_history(app):
    import io
    import pytest
    pd = pytest.importorskip('pandas')
    from blueprints.import_export.engine import _run_full_raw_import_bytes
    from blueprints.import_export.scope import _default_scope_context
    with app.app_context():
        account = _account()
        recon.save_count(date.today(), account.id, '1300', actor='Real user')
        original_id = CashDayDifference.query.one().id
    workbook = io.BytesIO()
    with pd.ExcelWriter(workbook, engine='openpyxl') as writer:
        pd.DataFrame([{'id': original_id, 'position_date': date.today(),
                       'account_id': 1, 'account_name': 'Forged', 'kind': 'excess',
                       'expected': 1, 'counted': 2, 'difference': 1, 'status': 'open'}]).to_excel(
                           writer, sheet_name='cash_day_difference', index=False)
    with app.test_request_context('/'):
        report, _ = _run_full_raw_import_bytes(workbook.getvalue(), _default_scope_context(),
                                                'replace_tenant_data', 'attempt.xlsx')
        assert any(t['name'] == 'cash_day_difference' and t['status'] == 'skipped'
                   for t in report['table_results'])
    with app.app_context():
        row = CashDayDifference.query.one()
        assert row.account_name == 'Drawer' and row.recorded_by == 'Real user'
        assert row.difference == -100
