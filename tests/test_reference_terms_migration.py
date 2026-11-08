import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / 'app' / 'migrations'


def _run(con, name, times=1):
    sql = (MIGRATIONS / name).read_text()
    for _ in range(times):
        con.executescript(sql)


def test_reference_terms_migration_preserves_custom_terms_and_is_retry_safe():
    con = sqlite3.connect(':memory:')
    _run(con, '0007_terms_and_conditions.sql')
    con.execute("INSERT INTO terms_and_conditions (title, content_ur) VALUES ('Custom', 'custom clause')")
    _run(con, '0008_reference_receipt_terms.sql', times=2)
    rows = con.execute('SELECT content_ur FROM terms_and_conditions WHERE is_active = 1 ORDER BY sort_order').fetchall()
    assert len(rows) == 8
    assert ('custom clause',) in rows
    assert sum('10 دن' in r[0] for r in rows) == 1
    assert con.execute('SELECT count(*) FROM terms_and_conditions WHERE is_active = 0').fetchone()[0] == 3


def test_terms_speak_of_a_booking_never_a_bank():
    """The reference clauses are about a booking (بکنگ), not a bank (بینک)."""
    con = sqlite3.connect(':memory:')
    _run(con, '0007_terms_and_conditions.sql')
    _run(con, '0008_reference_receipt_terms.sql')
    _run(con, '0009_receipt_terms_booking.sql', times=2)  # idempotent

    rows = con.execute(
        'SELECT title, content_ur FROM terms_and_conditions WHERE is_active = 1 '
        'ORDER BY sort_order').fetchall()
    # nothing gained or lost: the same seven active reference clauses
    assert len(rows) == 7
    assert len({r[1] for r in rows}) == 7
    # not one printed word still says "bank"
    assert not [r for r in rows if 'بینک' in r[0] or 'بینک' in r[1]]
    # the three corrected clauses are present verbatim
    contents = [r[1] for r in rows]
    assert ('بکنگ پر خریدار کو دیا گیا ریٹ صرف اسی صورت میں لاگو ہوگا '
            'جب وہ اس بکنگ کی پوری رقم ادا کرے۔') in contents
    assert ('اگر بکنگ کی رقم جزوی ادا کی جائے تو بکنگ کا ریٹ صرف ادا شدہ '
            'رقم کے مطابق مال پر لاگو ہوگا۔') in contents
    assert 'بقیہ رقم/بکنگ کے بقیہ مال پر مارکیٹ کا نیا ریٹ لاگو ہوگا۔' in contents
    # a title corrected too
    assert 'بکنگ کی مکمل ادائیگی' in [r[0] for r in rows]


def test_booking_migration_keeps_admin_choices_and_custom_wording():
    """Only the seeded wording is rewritten; the admin's own terms are not."""
    con = sqlite3.connect(':memory:')
    _run(con, '0007_terms_and_conditions.sql')
    _run(con, '0008_reference_receipt_terms.sql')
    # An admin disables the second reference clause and writes a custom one.
    con.execute('UPDATE terms_and_conditions SET is_active = 0, sort_order = 9 '
                "WHERE title = 'جزوی ادائیگی'")
    con.execute("INSERT INTO terms_and_conditions (title, content_ur, sort_order) "
                "VALUES ('Custom', 'میرا اپنا بینک نوٹ', 20)")

    _run(con, '0009_receipt_terms_booking.sql')

    row = con.execute("SELECT is_active, sort_order, content_ur FROM "
                      "terms_and_conditions WHERE title = 'جزوی ادائیگی'").fetchone()
    assert row[0] == 0, 'the admin turned this clause off; it must stay off'
    assert row[1] == 9, 'the admin ordering must survive the wording fix'
    assert 'بکنگ' in row[2] and 'بینک' not in row[2]
    # A custom clause is untouched even though it mentions a bank.
    custom = con.execute("SELECT content_ur FROM terms_and_conditions "
                         "WHERE title = 'Custom'").fetchone()[0]
    assert custom == 'میرا اپنا بینک نوٹ'
    # No row was added or removed (10 seeded rows + the custom one).
    assert con.execute('SELECT count(*) FROM terms_and_conditions').fetchone()[0] == 11


def test_address_migration_completes_the_legacy_default_only():
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE settings (id INTEGER PRIMARY KEY, company_address VARCHAR(200))')
    con.executemany('INSERT INTO settings (id, company_address) VALUES (?, ?)', [
        (1, 'JALAL PUR SOBTIAN'),
        (2, '  jalal pur sobtian  '),
        (3, 'JALAL PUR SOBTIAN GUJRAT'),
        (4, 'Shop 4, GT Road, Kharian'),
        (5, ''),
        (6, None),
    ])

    _run(con, '0010_company_address_gujrat.sql', times=2)  # idempotent

    rows = dict(con.execute('SELECT id, company_address FROM settings').fetchall())
    assert rows[1] == 'JALAL PUR SOBTIAN GUJRAT'
    assert rows[2] == 'JALAL PUR SOBTIAN GUJRAT'
    assert rows[3] == 'JALAL PUR SOBTIAN GUJRAT'
    assert rows[4] == 'Shop 4, GT Road, Kharian', 'an edited address is never rewritten'
    assert rows[5] == ''
    assert rows[6] is None


def test_settings_default_address_names_the_district():
    """A brand-new database already carries the full address."""
    from models import Settings
    default = Settings.__table__.c.company_address.default.arg
    assert default == 'JALAL PUR SOBTIAN GUJRAT'
