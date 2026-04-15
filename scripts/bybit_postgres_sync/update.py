"""update.py -- hourly refresh for Bybit funding + 1h klines in Postgres.

For every perp in ``bybit_perp_instruments``:
  - fetch the latest page (200 rows) of funding history -- no endTime.
  - fetch the last ~168 bars (1 week cushion) of perp + matching spot klines.

All inserts use ``ON CONFLICT DO NOTHING`` so re-runs are safe and gaps
from downtime self-heal up to the cushion window.

Usage (from dev machine)::

    uv run --with psycopg2-binary --with requests --with python-dotenv \\
        python scripts/bybit_postgres_sync/update.py

Usage (Unraid docker one-liner; see run_update.sh).

Cron example (runs at 5m past every hour)::

    5 * * * * /mnt/user/appdata/bybit-funding-updater/run_update.sh \\
        >> /var/log/bybit-update.log 2>&1
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    connect_db,
    ensure_schema,
    fetch_and_insert_predicted_funding,
    fetch_funding_page,
    fetch_kline_page,
    fetch_linear_perps,
    fetch_spot_instruments,
    get_funding_sync_state,
    get_kline_sync_state,
    insert_funding_rates,
    insert_klines,
    load_perp_instruments,
    upsert_funding_sync_state,
    upsert_instruments,
    upsert_kline_sync_state,
)

logger = logging.getLogger("bybit_update")

# Fetch the last 168 bars (1 week of hourly data) per symbol. Generous
# cushion so a reboot, NAS maintenance, or misfiring cron self-heals on the
# next run with no manual intervention. Already-present rows hit ON CONFLICT
# and are skipped silently.
UPDATE_KLINE_LIMIT = 168
# Funding: Bybit's max per page is 200. One page is plenty since even a 1h
# funding schedule only produces 168 events/week.
UPDATE_FUNDING_LIMIT = 200


def update_funding(conn, p: dict) -> int:
    """Fetch the latest funding page for a perp and upsert. Returns new rows."""
    ccxt = p["ccxt_symbol"]
    bybit_sym = p["bybit_symbol"]
    status = p["status"]
    if status and status.lower() in ("delisted", "closed"):
        logger.info("  %s: status=%s, skipping funding", ccxt, status)
        return 0
    page = fetch_funding_page(bybit_sym, end_ms=None, limit=UPDATE_FUNDING_LIMIT)
    if not page:
        return 0
    inserted = insert_funding_rates(
        conn, ccxt, p["funding_interval_hours"], page
    )
    # Update sync state bounds (preserve any existing earliest_time).
    state = get_funding_sync_state(conn, ccxt)
    from datetime import datetime, timezone

    ms_list = [int(r["fundingRateTimestamp"]) for r in page]
    newest_dt = datetime.fromtimestamp(max(ms_list) / 1000.0, tz=timezone.utc)
    oldest_dt = datetime.fromtimestamp(min(ms_list) / 1000.0, tz=timezone.utc)
    earliest = state["earliest_time"] if state and state.get("earliest_time") else oldest_dt
    backfill_complete = bool(state and state.get("backfill_complete"))
    upsert_funding_sync_state(
        conn, ccxt, earliest, newest_dt, backfill_complete, p.get("launch_time")
    )
    logger.info("  %s: funding fetched=%d inserted=%d", ccxt, len(page), inserted)
    return inserted


def update_klines(
    conn,
    ccxt_symbol: str,
    bybit_symbol: str,
    category: str,
    table_name: str,
    market_type: str,
    interval: str = "60",
    interval_label: str = "1h",
) -> int:
    """Fetch the last UPDATE_KLINE_LIMIT bars for a symbol and upsert."""
    page = fetch_kline_page(
        category, bybit_symbol, end_ms=None, interval=interval, limit=UPDATE_KLINE_LIMIT
    )
    if not page:
        return 0
    inserted = insert_klines(conn, table_name, ccxt_symbol, page)

    from datetime import datetime, timezone

    oldest_ms = int(page[0][0])
    newest_ms = int(page[-1][0])
    newest_dt = datetime.fromtimestamp(newest_ms / 1000.0, tz=timezone.utc)
    oldest_dt = datetime.fromtimestamp(oldest_ms / 1000.0, tz=timezone.utc)
    state = get_kline_sync_state(conn, ccxt_symbol, market_type, interval_label)
    earliest = state["earliest_time"] if state and state.get("earliest_time") else oldest_dt
    backfill_complete = bool(state and state.get("backfill_complete"))
    upsert_kline_sync_state(
        conn, ccxt_symbol, market_type, interval_label, earliest, newest_dt, backfill_complete
    )
    logger.info(
        "  %s (%s): kline fetched=%d inserted=%d",
        ccxt_symbol,
        market_type,
        len(page),
        inserted,
    )
    return inserted


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hourly Bybit funding + kline update.")
    p.add_argument(
        "--symbol",
        help="Optional single ccxt symbol (debug/smoke-test).",
    )
    p.add_argument("--skip-funding", action="store_true")
    p.add_argument("--skip-perp", action="store_true")
    p.add_argument("--skip-spot", action="store_true")
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    conn = connect_db()
    try:
        ensure_schema(conn)

        # Refresh instruments -- cheap, catches new listings.
        perps = fetch_linear_perps()
        upsert_instruments(conn, perps)
        logger.info("refreshed %d linear perp instruments", len(perps))

        spots = fetch_spot_instruments()
        spot_lookup = {i["ccxt_symbol"]: i["bybit_symbol"] for i in spots}

        # Capture predicted funding BEFORE the per-symbol loop so the snapshot
        # reflects the forecast at start-of-run. instruments were upserted just
        # above, so any newly-launched perps are already known and eligible.
        try:
            predicted_inserted = fetch_and_insert_predicted_funding(conn)
        except Exception as exc:  # noqa: BLE001
            logger.exception("predicted funding capture failed: %s -- continuing", exc)
            predicted_inserted = 0

        db_perps = load_perp_instruments(conn)
        if args.symbol:
            db_perps = [p for p in db_perps if p["ccxt_symbol"] == args.symbol]
            if not db_perps:
                logger.error("symbol %s not found", args.symbol)
                return 1
        logger.info("updating %d perps", len(db_perps))

        total_funding = 0
        total_perp_k = 0
        total_spot_k = 0
        for p in db_perps:
            ccxt = p["ccxt_symbol"]
            try:
                if not args.skip_funding:
                    total_funding += update_funding(conn, p)
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s funding failed: %s -- continuing", ccxt, exc)

            try:
                if not args.skip_perp:
                    total_perp_k += update_klines(
                        conn,
                        ccxt,
                        p["bybit_symbol"],
                        category="linear",
                        table_name="bybit_perp_klines",
                        market_type="linear",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s perp kline failed: %s -- continuing", ccxt, exc)

            if not args.skip_spot:
                spot_ccxt = f"{p['base']}/{p['quote']}"
                spot_bybit = spot_lookup.get(spot_ccxt)
                if spot_bybit is not None:
                    try:
                        total_spot_k += update_klines(
                            conn,
                            spot_ccxt,
                            spot_bybit,
                            category="spot",
                            table_name="bybit_spot_klines",
                            market_type="spot",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.exception(
                            "%s spot kline failed: %s -- continuing", spot_ccxt, exc
                        )

        logger.info(
            "DONE. funding_inserted=%d perp_klines_inserted=%d "
            "spot_klines_inserted=%d predicted_funding_inserted=%d",
            total_funding,
            total_perp_k,
            total_spot_k,
            predicted_inserted,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
