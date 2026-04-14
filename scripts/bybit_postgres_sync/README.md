# Bybit Postgres sync (standalone)

Self-contained scripts that sync Bybit v5 public-REST data into a Postgres
database. Deployable on Unraid via a vanilla `python:3.12-slim` docker image
-- no repo imports, no project dependencies beyond `psycopg2-binary`,
`requests`, and `python-dotenv`.

## What gets synced

| Bybit endpoint | Postgres table |
|---|---|
| `/v5/market/instruments-info?category=linear` | `bybit_perp_instruments` |
| `/v5/market/funding/history` (per perp) | `bybit_funding_rates` |
| `/v5/market/kline?category=linear` | `bybit_perp_klines` |
| `/v5/market/kline?category=spot` | `bybit_spot_klines` |

Sync progress is tracked in `bybit_funding_sync_state` and
`bybit_kline_sync_state`.

Universe: **linear USDT-settled perpetuals only** (category=linear,
quote=USDT, contract=LinearPerpetual). Matching spot pairs are synced as
1h klines when a Bybit spot listing exists (e.g. `BTC/USDT` spot for
`BTC/USDT:USDT` perp).

## Files

- `_common.py` -- shared helpers (DB, HTTP, schema, upserts, symbol conv).
- `backfill.py` -- one-time full historical backfill (idempotent, resumable).
- `update.py` -- hourly refresh (last 200 funding + last 168 klines).
- `run_backfill.sh` / `run_update.sh` -- Unraid docker one-liners.
- `.env.example` -- Postgres credential template.

## Safety

The `crypto` Postgres database is shared with another project. The scripts
**only** use `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` --
no `DROP`, `TRUNCATE`, or `ALTER`. The existing `ohlcv` table is never
touched.

## Unraid deployment

1. Create the host directory and copy the scripts into it:

   ```bash
   mkdir -p /mnt/user/appdata/bybit-funding-updater
   cp scripts/bybit_postgres_sync/*.py /mnt/user/appdata/bybit-funding-updater/
   cp scripts/bybit_postgres_sync/run_*.sh /mnt/user/appdata/bybit-funding-updater/
   chmod +x /mnt/user/appdata/bybit-funding-updater/run_*.sh
   ```

2. Create `/mnt/user/appdata/bybit-funding-updater/.env` from the template:

   ```
   POSTGRES_HOST=192.168.1.53
   POSTGRES_PORT=5432
   POSTGRES_DB=crypto
   POSTGRES_USER=luc
   POSTGRES_PASSWORD=<your password>
   ```

3. Verify schema + instruments fetch with a dry-run:

   ```bash
   /mnt/user/appdata/bybit-funding-updater/run_backfill.sh --dry-run
   ```

4. Smoke-test a single symbol with 3 pages:

   ```bash
   /mnt/user/appdata/bybit-funding-updater/run_backfill.sh \
       --symbol BTC/USDT:USDT --limit-pages 3
   ```

5. Run the full backfill (will take several hours for ~500 perps):

   ```bash
   /mnt/user/appdata/bybit-funding-updater/run_backfill.sh
   ```

6. Register the hourly cron (Unraid's User Scripts plugin, or root crontab):

   ```cron
   5 * * * * /mnt/user/appdata/bybit-funding-updater/run_update.sh \
       >> /var/log/bybit-update.log 2>&1
   ```

## Dev invocation (local uv)

```bash
uv run --with psycopg2-binary --with requests --with python-dotenv \
    python scripts/bybit_postgres_sync/backfill.py --dry-run

uv run --with psycopg2-binary --with requests --with python-dotenv \
    python scripts/bybit_postgres_sync/backfill.py \
    --symbol BTC/USDT:USDT --limit-pages 3

uv run --with psycopg2-binary --with requests --with python-dotenv \
    python scripts/bybit_postgres_sync/update.py
```

`.env` is read from (first hit wins):
1. `scripts/bybit_postgres_sync/.env`
2. `<repo>/.env`
3. `<repo>/config/.env`

## Idempotency

All inserts use `ON CONFLICT DO NOTHING`, all table creates use
`IF NOT EXISTS`, and sync-state upserts merge bounds with `LEAST` / `GREATEST`
so re-running `backfill.py` never re-fetches pages that are already marked
`backfill_complete=true` for that symbol.
