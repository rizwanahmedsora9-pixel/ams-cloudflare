"""Process-wide mutable flags (workers, caches)."""
from __future__ import annotations

HOURLY_BACKUP_WORKER_STARTED = False
HOURLY_BACKUP_LAST_SLOT = None
RECON_WORKER_STARTED = False
DAILY_BACKUP_WORKER_STARTED = False
RESET_CONTEXT = None
WEASYPRINT_MODULE = None
# True while an admin wipe/reset is running. Background writers (auto-reconcile,
# hourly/daily backups) check this and skip their pass instead of competing for
# the SQLite write lock — that contention is what aborted wipes on busy PCs.
WIPE_IN_PROGRESS = False
