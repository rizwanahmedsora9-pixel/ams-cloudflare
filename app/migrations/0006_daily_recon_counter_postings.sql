-- Daily reconciliation: post each counted difference to a counter account.
--
-- A finalised day's difference used to live only on the board, so the real
-- account balance never moved.  It is now posted as a paired transfer against
-- one of two counter accounts (category 'recon'), and the posting is linked back
-- to the difference row it came from.
--
-- NOTE ON COLUMNS: every new column of this feature is declared on the ORM
-- models and added by app/services/schema.py::_ensure_model_columns(), which runs
-- *before* this file on every boot (it tolerates columns that already exist,
-- while SQLite's ALTER TABLE does not).  This migration therefore only adds what
-- neither `db.create_all()` nor the column helper can express: the partial unique
-- index that makes a duplicated posting impossible.

CREATE UNIQUE INDEX IF NOT EXISTS uq_account_tx_daydiff_key
  ON account_transaction (idempotency_key)
  WHERE idempotency_key LIKE 'daydiff:%';

CREATE INDEX IF NOT EXISTS ix_cash_day_difference_posted_status
  ON cash_day_difference (posted_status);

-- Existing history is deliberately NOT back-filled here: posting a past day
-- moves real money, so it is a reviewed, explicit operation
-- (tools/post_historical_differences.py --dry-run first).
