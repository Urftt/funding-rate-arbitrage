"""backfill.py -- one-shot historical backfill of Bybit data into Postgres.

Walks every Bybit linear USDT-settled perpetual backwards through:
  - funding rate history -> ``bybit_funding_rates``
  - 1h perp klines       -> ``bybit_perp_klines``
  - matching spot 1h klines (where a spot pair exists) -> ``bybit_spot_klines``

Idempotent: safe to re-run. Sync state is tracked in
``bybit_funding_sync_state`` and ``bybit_kline_sync_state`` so a second
invocation picks up where the first left off.

Usage (from dev machine with uv)::

    uv run --with psycopg2-binary --with requests --with python-dotenv \\
        python scripts/bybit_postgres_sync/backfill.py --dry-run

    uv run --with psycopg2-binary --with requests --with python-dotenv \\
        python scripts/bybit_postgres_sync/backfill.py \\
        --symbol BTC/USDT:USDT --limit-pages 3

Usage (Unraid docker one-liner; see run_backfill.sh).

Flags:

- ``--dry-run``       create schema + refresh instruments, but do NOT fetch
                      funding/kline history. Useful for validating Postgres
                      connectivity and that the schema didn't touch the
                      existing ``ohlcv`` table.
- ``--symbol SYM``    restrict to a single ccxt symbol (e.g.
                      ``BTC/USDT:USDT``). Default: all perps.
- ``--limit-pages N`` stop after N pages per category per symbol. Default:
                      unlimited (fetch all history).
- ``--skip-funding``  skip funding rate backfill.
- ``--skip-perp``     skip perp kline backfill.
- ``--skip-spot``     skip spot kline backfill.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make "from _common import ..." work when run from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    FUNDING_PAGE_LIMIT,
    KLINE_PAGE_LIMIT,
    connect_db,
    ensure_schema,
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

logger = logging.getLogger("bybit_backfill")


def _ts_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def backfill_funding(
    conn,
    ccxt_symbol: str,
    bybit_symbol: str,
    interval_hours: int,
    launch_time: datetime | None,
    limit_pages: int | None,
) -> tuple[int, int]:
    """Paginate backwards through all funding rate history for a symbol.

    Stops when: page is empty, OR the oldest page timestamp equals
    ``launch_time`` (no more history to fetch), OR ``limit_pages`` is reached.

    Returns:
        (total_fetched, total_inserted)
    """
    state = get_funding_sync_state(conn, ccxt_symbol)
    if state and state.get("backfill_complete"):
        logger.info("  funding: backfill already complete, skipping")
        return 0, 0

    total_fetched = 0
    total_inserted = 0
    end_ms: int | None = None
    earliest_seen: datetime | None = state.get("earliest_time") if state else None
    latest_seen: datetime | None = state.get("latest_time") if state else None
    page_count = 0
    complete = False

    while True:
        page = fetch_funding_page(bybit_symbol, end_ms=end_ms, limit=FUNDING_PAGE_LIMIT)
        if not page:
            complete = True
            break
        total_fetched += len(page)
        inserted = insert_funding_rates(conn, ccxt_symbol, interval_hours, page)
        total_inserted += inserted

        # Bybit returns newest-first. Oldest entry is page[-1].
        oldest_ms = min(int(r["fundingRateTimestamp"]) for r in page)
        newest_ms = max(int(r["fundingRateTimestamp"]) for r in page)
        oldest_dt = _ts_to_dt(oldest_ms)
        newest_dt = _ts_to_dt(newest_ms)
        if earliest_seen is None or oldest_dt < earliest_seen:
            earliest_seen = oldest_dt
        if latest_seen is None or newest_dt > latest_seen:
            latest_seen = newest_dt
        page_count += 1
        logger.info(
            "  funding page %d: %d rows (inserted=%d), oldest=%s",
            page_count,
            len(page),
            inserted,
            oldest_dt.isoformat(),
        )

        if launch_time is not None and oldest_dt <= launch_time:
            complete = True
            break
        if len(page) < FUNDING_PAGE_LIMIT:
            complete = True
            break
        if limit_pages is not None and page_count >= limit_pages:
            break
        end_ms = oldest_ms - 1

    upsert_funding_sync_state(
        conn,
        ccxt_symbol,
        earliest_seen,
        latest_seen,
        complete,
        launch_time,
    )
    return total_fetched, total_inserted


def backfill_klines(
    conn,
    ccxt_symbol: str,
    bybit_symbol: str,
    category: str,
    table_name: str,
    launch_time: datetime | None,
    limit_pages: int | None,
    interval: str = "60",
    market_type: str | None = None,
    interval_label: str = "1h",
) -> tuple[int, int]:
    """Paginate backwards through kline history.

    Stops when: page is empty, OR a page's oldest ts matches previously-seen
    earliest (treated as drained), OR ``limit_pages`` reached.

    Args:
        category: ``"linear"`` or ``"spot"`` (Bybit API category).
        table_name: destination table (``bybit_perp_klines`` or
            ``bybit_spot_klines``).
        market_type: sync-state market_type label (``"linear"`` or
            ``"spot"``). Defaults to ``category``.
        interval_label: sync-state interval label (default ``"1h"``).

    Returns:
        (total_fetched, total_inserted)
    """
    if market_type is None:
        market_type = category
    state = get_kline_sync_state(conn, ccxt_symbol, market_type, interval_label)
    if state and state.get("backfill_complete"):
        logger.info("  %s klines: backfill already complete, skipping", market_type)
        return 0, 0

    total_fetched = 0
    total_inserted = 0
    end_ms: int | None = None
    earliest_seen: datetime | None = state.get("earliest_time") if state else None
    latest_seen: datetime | None = state.get("latest_time") if state else None
    prev_oldest_ms: int | None = None
    page_count = 0
    complete = False

    while True:
        page = fetch_kline_page(category, bybit_symbol, end_ms=end_ms, interval=interval)
        if not page:
            complete = True
            break
        total_fetched += len(page)
        inserted = insert_klines(conn, table_name, ccxt_symbol, page)
        total_inserted += inserted

        # page is ascending (we reversed in _common.fetch_kline_page).
        oldest_ms = int(page[0][0])
        newest_ms = int(page[-1][0])
        oldest_dt = _ts_to_dt(oldest_ms)
        newest_dt = _ts_to_dt(newest_ms)
        if earliest_seen is None or oldest_dt < earliest_seen:
            earliest_seen = oldest_dt
        if latest_seen is None or newest_dt > latest_seen:
            latest_seen = newest_dt
        page_count += 1
        logger.info(
            "  %s kline page %d: %d bars (inserted=%d), oldest=%s",
            market_type,
            page_count,
            len(page),
            inserted,
            oldest_dt.isoformat(),
        )

        if launch_time is not None and oldest_dt <= launch_time:
            complete = True
            break
        if len(page) < KLINE_PAGE_LIMIT:
            complete = True
            break
        if prev_oldest_ms is not None and oldest_ms >= prev_oldest_ms:
            # No progress -- safety net against API repeating the same window.
            complete = True
            break
        if limit_pages is not None and page_count >= limit_pages:
            break
        prev_oldest_ms = oldest_ms
        end_ms = oldest_ms - 1

    upsert_kline_sync_state(
        conn,
        ccxt_symbol,
        market_type,
        interval_label,
        earliest_seen,
        latest_seen,
        complete,
    )
    return total_fetched, total_inserted


def build_spot_lookup(spot_instruments: list[dict[str, Any]]) -> dict[str, str]:
    """Map ccxt spot symbol -> raw Bybit spot symbol for lookup by perp base/quote."""
    return {i["ccxt_symbol"]: i["bybit_symbol"] for i in spot_instruments}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill Bybit funding rates + 1h klines into Postgres.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Create schema + refresh instruments only. No funding/kline fetch.",
    )
    p.add_argument(
        "--symbol",
        help="Restrict to a single ccxt symbol (e.g. BTC/USDT:USDT).",
    )
    p.add_argument(
        "--limit-pages",
        type=int,
        default=None,
        help="Cap pages per category per symbol (smoke-test helper).",
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

        logger.info("fetching linear perp instruments from Bybit")
        perps = fetch_linear_perps()
        logger.info("found %d linear USDT perps", len(perps))
        upserted = upsert_instruments(conn, perps)
        logger.info("upserted %d rows into bybit_perp_instruments", upserted)

        logger.info("fetching spot instruments from Bybit")
        spots = fetch_spot_instruments()
        spot_lookup = build_spot_lookup(spots)
        logger.info("found %d spot instruments", len(spots))

        if args.dry_run:
            logger.info("--dry-run: schema + instruments done, exiting.")
            return 0

        db_perps = load_perp_instruments(conn)
        if args.symbol:
            db_perps = [p for p in db_perps if p["ccxt_symbol"] == args.symbol]
            if not db_perps:
                logger.error("symbol %s not found in bybit_perp_instruments", args.symbol)
                return 1

        grand_funding_inserted = 0
        grand_perp_inserted = 0
        grand_spot_inserted = 0

        for i, p in enumerate(db_perps, start=1):
            ccxt = p["ccxt_symbol"]
            bybit_sym = p["bybit_symbol"]
            interval_h = p["funding_interval_hours"]
            launch = p["launch_time"]
            status = p["status"]
            logger.info(
                "[%d/%d] %s (bybit=%s, interval=%dh, status=%s)",
                i,
                len(db_perps),
                ccxt,
                bybit_sym,
                interval_h,
                status,
            )

            if not args.skip_funding:
                try:
                    _, inserted = backfill_funding(
                        conn, ccxt, bybit_sym, interval_h, launch, args.limit_pages
                    )
                    grand_funding_inserted += inserted
                except Exception as exc:  # noqa: BLE001
                    logger.exception("  funding failed for %s: %s", ccxt, exc)

            if not args.skip_perp:
                try:
                    _, inserted = backfill_klines(
                        conn,
                        ccxt,
                        bybit_sym,
                        category="linear",
                        table_name="bybit_perp_klines",
                        launch_time=launch,
                        limit_pages=args.limit_pages,
                    )
                    grand_perp_inserted += inserted
                except Exception as exc:  # noqa: BLE001
                    logger.exception("  perp kline failed for %s: %s", ccxt, exc)

            if not args.skip_spot:
                spot_ccxt = f"{p['base']}/{p['quote']}"
                spot_bybit = spot_lookup.get(spot_ccxt)
                if spot_bybit is None:
                    logger.info("  spot pair %s not listed on Bybit, skipping", spot_ccxt)
                else:
                    try:
                        _, inserted = backfill_klines(
                            conn,
                            spot_ccxt,
                            spot_bybit,
                            category="spot",
                            table_name="bybit_spot_klines",
                            launch_time=None,
                            limit_pages=args.limit_pages,
                            market_type="spot",
                        )
                        grand_spot_inserted += inserted
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("  spot kline failed for %s: %s", spot_ccxt, exc)

        logger.info(
            "DONE. funding_inserted=%d perp_klines_inserted=%d spot_klines_inserted=%d "
            "across %d symbols",
            grand_funding_inserted,
            grand_perp_inserted,
            grand_spot_inserted,
            len(db_perps),
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
