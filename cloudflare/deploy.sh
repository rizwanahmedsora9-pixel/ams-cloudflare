#!/usr/bin/env bash
# Deploy the AMS ERP Flask app as a Cloudflare Python Worker.
#
#   ./deploy.sh                 # bundle + deploy to the account in `wrangler login`
#   ./deploy.sh --dry-run       # bundle + show what would be uploaded
#   ./deploy.sh --dev           # local dev server on http://localhost:8787
#
# Requirements: Node.js (npx), uv (https://docs.astral.sh/uv/), and a Cloudflare
# account (`npx wrangler login`).  Pyodide-compatible wheels are resolved by
# pywrangler into ./python_modules on every run.
set -euo pipefail

cd "$(dirname "$0")"

# Remove the generated copies on exit, whatever the outcome (the bundle itself
# is git-ignored; this keeps the working tree tidy after a failed upload too).
trap 'python3 build_bundle.py --tidy >/dev/null 2>&1 || true' EXIT

echo "[ams] syncing the Worker bundle from the repository…"
# (wrangler's build.command repeats this step; running it first surfaces a
#  missing source tree before the upload starts)
python3 build_bundle.py --clean

if ! command -v uv >/dev/null 2>&1; then
  echo "[ams] uv is required (https://docs.astral.sh/uv/getting-started/installation/)" >&2
  exit 1
fi

if [ "${1:-}" = "--dev" ]; then
  # Symlinked bundle so edits reload without re-copying; uses the local
  # in-memory filesystem exactly like production.
  python3 build_bundle.py --clean --link
  trap - EXIT   # keep the links while the dev server is running
  uv run --quiet pywrangler dev --ip 0.0.0.0 --port "${PORT:-8787}"
  python3 build_bundle.py --tidy
  exit 0
fi

if [ "${1:-}" = "--dry-run" ]; then
  uv run --quiet pywrangler deploy --dry-run --outdir=dist
  exit 0
fi

uv run --quiet pywrangler deploy "$@"
