#!/usr/bin/env bash
# run_backfill.sh -- Unraid docker one-liner for the Bybit historical backfill.
#
# Assumes scripts have been copied to /mnt/user/appdata/bybit-funding-updater/
# and that POSTGRES_PASSWORD is readable from a .env file in that same dir.
#
# Usage:
#   /mnt/user/appdata/bybit-funding-updater/run_backfill.sh
#   /mnt/user/appdata/bybit-funding-updater/run_backfill.sh --dry-run
#   /mnt/user/appdata/bybit-funding-updater/run_backfill.sh --symbol BTC/USDT:USDT --limit-pages 3

set -euo pipefail

SCRIPTS_HOST_DIR="${SCRIPTS_HOST_DIR:-/mnt/user/appdata/bybit-funding-updater}"

# Load POSTGRES_PASSWORD from the .env next to the scripts so it can be
# passed into the container without being hard-coded here.
if [[ -f "${SCRIPTS_HOST_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  . "${SCRIPTS_HOST_DIR}/.env"
  set +a
fi

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set (check ${SCRIPTS_HOST_DIR}/.env)}"

docker run --rm \
  -v "${SCRIPTS_HOST_DIR}:/scripts" \
  -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  -e POSTGRES_HOST="${POSTGRES_HOST:-192.168.1.53}" \
  -e POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
  -e POSTGRES_DB="${POSTGRES_DB:-crypto}" \
  -e POSTGRES_USER="${POSTGRES_USER:-luc}" \
  --network=host \
  python:3.12-slim \
  bash -lc "pip install --quiet psycopg2-binary requests python-dotenv && python /scripts/backfill.py $*"
