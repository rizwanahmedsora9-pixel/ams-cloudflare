# "500 Internal Server Error" appears by itself after some time

This note explains what causes it, how to read the exact cause in a minute, and
what was changed in the code to stop it.

---

## 1. Read the exact cause first (1 minute)

Before guessing, open one of these on the server:

| Where | What it holds |
|---|---|
| `instance/logs/500-errors.jsonl` | **New.** One JSON line per unhandled failure: time, reference (`E-xxxxxx`), endpoint, logged-in user, database file, full traceback. Newest last. |
| `instance/logs/errorlog.txt` | The general rotating error log (warnings + errors). |
| `/debug/recent_errors` | **New.** The same last-20 failures as JSON — sign in as **admin** and open it in the browser. |
| The error page itself | Now shows a reference like `E-1a2b3c`. Search that string in `500-errors.jsonl` to find its traceback. |

On **PythonAnywhere** also open the *Web* tab → *Error log*: that is where the
server's own tracebacks and worker restarts appear.

Commands on a yard PC (Windows) / server:

```bash
tail -n 40 instance/logs/500-errors.jsonl
grep -i "error\|locked\|disk" instance/logs/errorlog.txt | tail -n 40
```

The three most common tracebacks and what they mean:

| Traceback text | Meaning |
|---|---|
| `sqlite3.OperationalError: database is locked` | Something else held SQLite's write lock longer than the wait limit: a backup/export, a big import, another PC saving at the same moment, or a second copy of the app started on the same file. |
| `sqlite3.OperationalError: disk I/O error` / `unable to open database file` | The database file is on a network drive, was moved/deleted, or the disk/quota is full. |
| `sqlite3.DatabaseError: database disk image is malformed` | The file was corrupted (usually SQLite over a network filesystem, or a power cut). Restore the newest backup in `backups/db/`. |

---

## 2. What was actually wrong (findings)

The app itself is not leaking: a 10-minute run with three browser tabs polling
(every 6 s), several thousand page loads, 20 concurrent users and 12 mixed
read/write clients stayed flat on memory (145 MB), threads (3) and file handles
(22), with no 500s. So the "automatic" 500 is a **database lock / I/O fault**
that only shows up when a long job overlaps normal work — not a slow leak.

The concrete defects found while tracing that:

1. **A long database lock was turned into a permanent error for the user.**
   `wsgi.py` forces SQLite into rollback-journal (`DELETE`) mode on
   PythonAnywhere because WAL needs shared memory that `/home` (network storage)
   does not provide. In that mode **one writer blocks every reader**. A backup,
   an import, a big report, or a second app instance therefore makes every other
   request wait; when the wait expires SQLite raises `database is locked`, the
   route does not catch it and the browser shows the bare
   `500 Internal Server Error`. Reproduced end-to-end: holding SQLite's exclusive
   lock for 15.4 s made every page fail.
2. **The same lock silently logged users out.** `load_user()` treated any
   database error as "not logged in", so a busy database bounced every page to
   `/login` (a request that took 45 s and then landed on the login screen).
3. **Two background workers were dead code.** `app/services/backup.py` handed
   Flask's `current_app` *proxy* to a thread. Inside a thread the proxy raises
   `Working outside of application context`, so the hourly-backup loop and the
   auto-reconcile loop both failed forever, silently. Verified:
   `RuntimeError: Working outside of application context`.
4. **The auto-reconcile copy was unsafe and unbounded.** It used
   `shutil.copy2` on a live database (a torn copy when the journal mode is WAL)
   and kept 10 copies inside `instance/`.
5. **Nothing recorded which request failed.** The helper
   `_log_unhandled_exception` existed but was never connected to Flask's
   `got_request_exception` signal, and the error page carried no reference, so a
   report like "it showed 500 again" could not be traced.
6. **Pooled connections were never validated.** If the database file was
   replaced (backup/restore) or a laptop/PC resumed, the stale pooled connection
   failed, and it kept failing until the process restarted.

---

## 3. What changed

| File | Change |
|---|---|
| `app/services/errors.py` | **New.** Reference codes, bounded `500-errors.jsonl`, friendly error page, JSON errors for `/api/*`, session rollback on failure, QR token redaction, and a retry layer for transient SQLite locks. |
| `app/__init__.py` | Installs the error handling before bootstrap; `pool_pre_ping` + `pool_recycle` (default 1800 s, `DB_POOL_RECYCLE_SECONDS`); `busy_timeout` raised 8 s → 15 s. |
| `app/services/permissions.py` | `load_user()` retries a transient lock (0.5 s, 1.5 s) instead of logging the user out. |
| `app/services/backup.py` | Workers receive the real app object; the hourly loop resolves it inside the request, logs a failure once, and no longer spins silently. |
| `utils/reconciliation.py` | Resolves the real app; copies the database with SQLite's online-backup API instead of `shutil.copy2`; keeps 3 copies by default; logs the first failure of a streak. |
| `app/blueprints/system/extra.py` | `GET /debug/recent_errors` — admin/root only, last 20 failures with tracebacks. |
| `tests/test_error_handling.py` | **New.** 16 regression tests for all of the above. |

### Behaviour you will notice

* A request that hits a **transient** SQLite problem is retried once for
  `GET`/`HEAD`/`OPTIONS` (0.25 s, then 1 s) instead of showing a 500.
  Writes (`POST`/`PUT`/`PATCH`/`DELETE`) are **never** retried automatically —
  a second submit could duplicate a bill — so on a write you get the friendly
  page with a reference and a "please retry" hint.
* Real faults (corrupt file, read-only database, full disk) are never retried.
* Every failure is written once, with its reference, to
  `instance/logs/500-errors.jsonl` (bounded to 200 records).

### Environment switches

| Variable | Default | Purpose |
|---|---|---|
| `AMS_DB_RETRY` | on (off under tests) | `0` disables the transient-lock retry, `1` forces it. |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | How long a pooled database connection may live. |
| `ERROR_LOG_MAX_BYTES`, `ERROR_LOG_BACKUP_COUNT` | `2 MB`, `3` | Rotation of `errorlog.txt`. |

---

## 4. If a 500 still happens

1. Open the reference from the page in `instance/logs/500-errors.jsonl`
   (or `/debug/recent_errors`).
2. Match the traceback in the table in section 1.
3. For a persistent `database is locked`:
   * Make sure only **one** copy of the app runs against
     `instance/ahmed_cement_v44_fresh.db` (a second `python main.py`, a cron
     import, or a backup script are the usual culprits).
   * Keep large exports/imports out of peak hours.
   * On a **local disk** (a yard PC, not PythonAnywhere) WAL is used and readers
     no longer block: `SQLITE_JOURNAL_MODE=WAL`.
   * On **PythonAnywhere** the file lives on network storage, so WAL is not
     available; keep the database small, and let the built-in backup run at a
     quiet time.
4. For `disk I/O error` / `unable to open database file`, check free space and
   that `instance/` still contains the database:
   ```bash
   df -h .
   ls -l instance/
   ```
5. For `disk image is malformed`, stop the app, keep the original file, and
   restore the newest valid copy from `backups/db/`.
