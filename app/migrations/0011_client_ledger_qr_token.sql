-- Store a unique digest per client's public-ledger QR capability.
-- The ORM bootstrap adds the nullable token-hash column to existing databases;
-- this migration adds the partial uniqueness constraint without touching rows.
CREATE UNIQUE INDEX IF NOT EXISTS uq_client_ledger_qr_token_hash
    ON client (client_ledger_qr_token_hash)
    WHERE client_ledger_qr_token_hash IS NOT NULL;
