# P6 — Unsafe file uploads

**Status:** Upload validation added locally; not deployed.

`save_photo` now allows only JPG/JPEG, PNG, GIF, or WebP extensions whose initial bytes match the corresponding image signature. It enforces the configured `MAX_CONTENT_LENGTH` (or 10 MiB default), saves only validated bytes, and safely rejects unsupported/spoofed uploads with a flash message. This prevents HTML/script files disguised as images from being written into the publicly served upload folder. All existing upload callers continue to receive `None` when no file or an invalid file is submitted.

**Impact:** Reduces risk from uploaded active content and oversized files. Uploaded valid images remain under the existing public static upload path; this change does not introduce per-user attachment privacy.

**Validation:** Tests cover fake PNG/HTML rejection and signature-checked PNG saving. Focused suite: 31 passed. Full suite: 250 passed, 5 skipped. `git diff --check` and compile checks passed. No schema/data changes.
