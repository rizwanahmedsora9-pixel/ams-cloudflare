import sqlite3
from pathlib import Path


def test_reference_terms_migration_preserves_custom_terms_and_is_retry_safe():
    con = sqlite3.connect(':memory:')
    root = Path(__file__).resolve().parents[1] / 'app' / 'migrations'
    con.executescript((root / '0007_terms_and_conditions.sql').read_text())
    con.execute("INSERT INTO terms_and_conditions (title, content_ur) VALUES ('Custom', 'custom clause')")
    migration = (root / '0008_reference_receipt_terms.sql').read_text()
    con.executescript(migration)
    con.executescript(migration)
    rows = con.execute('SELECT content_ur FROM terms_and_conditions WHERE is_active = 1 ORDER BY sort_order').fetchall()
    assert len(rows) == 8
    assert ('custom clause',) in rows
    assert sum('10 دن' in r[0] for r in rows) == 1
    assert con.execute('SELECT count(*) FROM terms_and_conditions WHERE is_active = 0').fetchone()[0] == 3
