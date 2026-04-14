#!/usr/bin/env bash
# run_update.sh -- Unraid docker one-liner for the hourly Bybit update.
#
# Intended to be invoked from cron every hour (e.g. at :05) to keep the
# Postgres tables fresh. Safe to re-run -- idempotent.
#
# Usage:
#   /mnt/user/appdata/bybit-funding-updater/run_update.sh

set -euo pipefail

SCRIPTS_HOST_DIR="${SCRIPTS_HOST_DIR:-/mnt/user/appdata/bybit-funding-updater}"

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
  bash -lc "pip install --quiet psycopg2-binary requests python-dotenv && python /scripts/update.py $*"
