"""Shared helpers for the standalone Bybit Postgres sync scripts.

Used by backfill.py and update.py. Provides:

- ``connect_db()`` -- psycopg2 connection from ``POSTGRES_*`` env vars.
- ``ensure_schema(conn)`` -- idempotent ``CREATE TABLE IF NOT EXISTS`` for the
  five bybit_* tables. NEVER drops, truncates, or alters anything -- the
  ``crypto`` database is shared with another project (statistical-arbitrage-v3)
  and the existing ``ohlcv`` table must not be touched.
- ``bybit_get(path, params)`` -- HTTP GET wrapper with retries on 5xx/429.
- ``fetch_linear_perps()`` / ``fetch_spot_instruments()`` -- instrument discovery.
- ``fetch_funding_page(...)`` / ``fetch_kline_page(...)`` -- one page each.
- ``insert_funding_rates(...)`` / ``insert_klines(...)`` -- batch upserts.
- Sync-state read/write helpers.
- Symbol conversion helpers (raw Bybit <-> ccxt unified).

Intentionally standalone: uses ``requests`` + ``psycopg2`` directly and does
NOT import from ``src/bot/`` or any other project code. Designed to run inside
a vanilla ``python:3.12-slim`` docker image on Unraid with just
``pip install psycopg2-binary requests python-dotenv``.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

# Load .env files before any env var lookups.
# Search order (first hit wins; real shell env always beats all of them):
#   1. <scripts_dir>/.env   -- standalone deployments (e.g. Unraid appdata)
#   2. <repo>/.env          -- dev setup, user's personal/local overrides
#   3. <repo>/config/.env   -- dev setup, project-standard shared secrets
_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent.parent
load_dotenv(_SCRIPTS_DIR / ".env")
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT / "config" / ".env")

logger = logging.getLogger(__name__)

BYBIT_BASE_URL = "https://api.bybit.com"
REQUEST_SLEEP_SEC = 0.04  # ~25 req/sec (Bybit public limit is 120/5s = 24/s sustained)
HTTP_TIMEOUT_SEC = 30
MAX_RETRIES = 5
RETRY_BACKOFF_SEC = 1.0  # doubled each retry

FUNDING_PAGE_LIMIT = 200  # Bybit max
KLINE_PAGE_LIMIT = 1000   # Bybit max


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


def connect_db() -> psycopg2.extensions.connection:
    """Open a psycopg2 connection using POSTGRES_* env vars.

    Defaults match the user's Unraid instance. ``POSTGRES_PASSWORD`` is
    required and has no default -- raises ``RuntimeError`` if unset.

    Returns:
        An open psycopg2 connection. The caller owns closing it.
    """
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(
            "POSTGRES_PASSWORD env var is required. "
            "Set it in .env or export it before invoking the script."
        )
    host = os.environ.get("POSTGRES_HOST", "192.168.1.53")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    dbname = os.environ.get("POSTGRES_DB", "crypto")
    user = os.environ.get("POSTGRES_USER", "luc")
    logger.info("connecting to postgres %s@%s:%s/%s", user, host, port, dbname)
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
    )


# NOTE: all statements use IF NOT EXISTS so the script never drops or alters
# existing objects. The ``crypto`` DB is shared with statistical-arbitrage-v3.
CREATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bybit_funding_rates (
    symbol           TEXT        NOT NULL,
    funding_time     TIMESTAMPTZ NOT NULL,
    funding_rate     NUMERIC(20,12) NOT NULL,
    interval_hours   SMALLINT    NOT NULL,
    mark_price       NUMERIC(24,12),
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, funding_time)
);

CREATE INDEX IF NOT EXISTS idx_bybit_funding_time
    ON bybit_funding_rates (funding_time);
CREATE INDEX IF NOT EXISTS idx_bybit_funding_symbol_time_desc
    ON bybit_funding_rates (symbol, funding_time DESC);

CREATE TABLE IF NOT EXISTS bybit_funding_sync_state (
    symbol              TEXT PRIMARY KEY,
    earliest_time       TIMESTAMPTZ,
    latest_time         TIMESTAMPTZ,
    backfill_complete   BOOLEAN NOT NULL DEFAULT false,
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    listing_time        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bybit_perp_instruments (
    symbol                  TEXT PRIMARY KEY,
    bybit_symbol            TEXT NOT NULL,
    base                    TEXT NOT NULL,
    quote                   TEXT NOT NULL,
    settle                  TEXT NOT NULL,
    funding_interval_hours  SMALLINT NOT NULL,
    launch_time             TIMESTAMPTZ,
    status                  TEXT NOT NULL,
    last_refreshed          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bybit_perp_klines (
    symbol      TEXT NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    turnover    DOUBLE PRECISION,
    PRIMARY KEY (symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_bybit_perp_klines_time
    ON bybit_perp_klines (timestamp);

CREATE TABLE IF NOT EXISTS bybit_spot_klines (
    symbol      TEXT NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    turnover    DOUBLE PRECISION,
    PRIMARY KEY (symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_bybit_spot_klines_time
    ON bybit_spot_klines (timestamp);

CREATE TABLE IF NOT EXISTS bybit_kline_sync_state (
    symbol              TEXT NOT NULL,
    market_type         TEXT NOT NULL,
    interval            TEXT NOT NULL,
    earliest_time       TIMESTAMPTZ,
    latest_time         TIMESTAMPTZ,
    backfill_complete   BOOLEAN NOT NULL DEFAULT false,
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, market_type, interval)
);

CREATE TABLE IF NOT EXISTS bybit_predicted_funding (
    symbol             TEXT NOT NULL,
    observed_at        TIMESTAMPTZ NOT NULL,
    predicted_rate     NUMERIC(20,12) NOT NULL,
    next_funding_time  TIMESTAMPTZ NOT NULL,
    mark_price         NUMERIC(24,12),
    index_price        NUMERIC(24,12),
    PRIMARY KEY (symbol, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_bybit_predicted_funding_time
    ON bybit_predicted_funding (observed_at);
CREATE INDEX IF NOT EXISTS idx_bybit_predicted_funding_next
    ON bybit_predicted_funding (symbol, next_funding_time);
"""


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    """Create all bybit_* tables and indexes if they don't exist (idempotent).

    NEVER drops, truncates, or alters. If a table already exists with a
    different schema, Postgres silently keeps the existing definition -- the
    mismatch will surface on the first INSERT that doesn't fit, which is the
    intended "fail safely" behavior per the project's safety constraint.
    """
    with conn.cursor() as cur:
        cur.execute(CREATE_SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Symbol conversion
# ---------------------------------------------------------------------------


def bybit_perp_to_ccxt(bybit_symbol: str, quote: str = "USDT", settle: str = "USDT") -> str:
    """Convert raw Bybit perp symbol to ccxt unified form.

    Examples:
        >>> bybit_perp_to_ccxt("BTCUSDT")
        'BTC/USDT:USDT'
        >>> bybit_perp_to_ccxt("1000PEPEUSDT")
        '1000PEPE/USDT:USDT'

    Args:
        bybit_symbol: Raw Bybit symbol, e.g. ``"BTCUSDT"``.
        quote: Quote coin as reported by Bybit (default ``"USDT"``).
        settle: Settle coin (default ``"USDT"``; for linear USDT perps
            settle == quote).

    Returns:
        ccxt unified symbol, e.g. ``"BTC/USDT:USDT"``.
    """
    if not bybit_symbol.endswith(quote):
        raise ValueError(f"symbol {bybit_symbol!r} does not end with quote {quote!r}")
    base = bybit_symbol[: -len(quote)]
    return f"{base}/{quote}:{settle}"


def bybit_spot_to_ccxt(base: str, quote: str) -> str:
    """Convert base/quote pair to ccxt unified spot symbol.

    Examples:
        >>> bybit_spot_to_ccxt("BTC", "USDT")
        'BTC/USDT'
    """
    return f"{base}/{quote}"


# ---------------------------------------------------------------------------
# Bybit REST
# ---------------------------------------------------------------------------


def bybit_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET ``{BYBIT_BASE_URL}{path}`` with retries on 5xx/429 and rate-limit floor.

    Retries up to ``MAX_RETRIES`` times with exponential backoff on:
      - HTTP 429 (rate limited) or 5xx server errors
      - ``requests.ConnectionError`` / ``requests.Timeout``
      - Bybit API-level ``retCode != 0`` for transient codes (10006, 10016)

    Always sleeps ``REQUEST_SLEEP_SEC`` between successful calls.

    Args:
        path: Path component, e.g. ``"/v5/market/funding/history"``.
        params: Query-string dict.

    Returns:
        The ``result`` dict from Bybit's envelope (or whatever ``result`` is
        -- typically ``{"list": [...], "nextPageCursor": "..."}``).

    Raises:
        RuntimeError: if all retries fail or API returns a non-transient
            ``retCode``.
    """
    url = f"{BYBIT_BASE_URL}{path}"
    delay = RETRY_BACKOFF_SEC
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params or {}, timeout=HTTP_TIMEOUT_SEC)
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    "bybit %s status=%d attempt=%d -- backing off %.1fs",
                    path,
                    resp.status_code,
                    attempt,
                    delay,
                )
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            body = resp.json()
            ret_code = body.get("retCode")
            if ret_code != 0:
                # 10006 = too many visits (rate limit at API layer)
                # 10016 = server busy
                if ret_code in (10006, 10016):
                    logger.warning(
                        "bybit %s retCode=%s retMsg=%s attempt=%d -- backing off",
                        path,
                        ret_code,
                        body.get("retMsg"),
                        attempt,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError(
                    f"bybit {path} retCode={ret_code} retMsg={body.get('retMsg')!r}"
                )
            time.sleep(REQUEST_SLEEP_SEC)
            return body.get("result", {})
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            logger.warning(
                "bybit %s connection error attempt=%d: %s -- backing off %.1fs",
                path,
                attempt,
                exc,
                delay,
            )
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"bybit {path} failed after {MAX_RETRIES} attempts: {last_exc}")


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------


def _parse_launch_time(ms_str: str | None) -> datetime | None:
    """Parse Bybit's epoch-ms string into a UTC datetime, or None if invalid/0."""
    if not ms_str:
        return None
    try:
        ms = int(ms_str)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def fetch_linear_perps() -> list[dict[str, Any]]:
    """Fetch all Bybit linear USDT-settled perpetual instruments.

    Filters for ``contractType == 'LinearPerpetual'`` and
    ``quoteCoin == 'USDT'``. Paginates via ``nextPageCursor``.

    Returns:
        List of dicts with keys: ``ccxt_symbol``, ``bybit_symbol``, ``base``,
        ``quote``, ``settle``, ``funding_interval_hours``, ``launch_time``
        (datetime or None), ``status``.
    """
    out: list[dict[str, Any]] = []
    cursor = ""
    while True:
        params: dict[str, Any] = {"category": "linear", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        result = bybit_get("/v5/market/instruments-info", params)
        items = result.get("list") or []
        for it in items:
            if it.get("contractType") != "LinearPerpetual":
                continue
            if it.get("quoteCoin") != "USDT":
                continue
            bybit_symbol = it["symbol"]
            base = it["baseCoin"]
            quote = it["quoteCoin"]
            settle = it.get("settleCoin", quote)
            funding_min = it.get("fundingInterval")
            if funding_min is None:
                continue
            funding_hours = int(funding_min) // 60
            out.append(
                {
                    "ccxt_symbol": bybit_perp_to_ccxt(bybit_symbol, quote, settle),
                    "bybit_symbol": bybit_symbol,
                    "base": base,
                    "quote": quote,
                    "settle": settle,
                    "funding_interval_hours": funding_hours,
                    "launch_time": _parse_launch_time(it.get("launchTime")),
                    "status": it.get("status", "Unknown"),
                }
            )
        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            break
    out.sort(key=lambda r: r["ccxt_symbol"])
    return out


def fetch_spot_instruments() -> list[dict[str, Any]]:
    """Fetch all Bybit spot instruments. Paginates via ``nextPageCursor``.

    Returns:
        List of dicts with keys: ``ccxt_symbol``, ``bybit_symbol``, ``base``,
        ``quote``, ``status``.
    """
    out: list[dict[str, Any]] = []
    cursor = ""
    while True:
        params: dict[str, Any] = {"category": "spot", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        result = bybit_get("/v5/market/instruments-info", params)
        items = result.get("list") or []
        for it in items:
            bybit_symbol = it["symbol"]
            base = it["baseCoin"]
            quote = it["quoteCoin"]
            out.append(
                {
                    "ccxt_symbol": bybit_spot_to_ccxt(base, quote),
                    "bybit_symbol": bybit_symbol,
                    "base": base,
                    "quote": quote,
                    "status": it.get("status", "Unknown"),
                }
            )
        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            break
    return out


INSTRUMENTS_UPSERT_SQL = """
INSERT INTO bybit_perp_instruments
    (symbol, bybit_symbol, base, quote, settle, funding_interval_hours,
     launch_time, status, last_refreshed)
VALUES %s
ON CONFLICT (symbol) DO UPDATE SET
    bybit_symbol = EXCLUDED.bybit_symbol,
    base = EXCLUDED.base,
    quote = EXCLUDED.quote,
    settle = EXCLUDED.settle,
    funding_interval_hours = EXCLUDED.funding_interval_hours,
    launch_time = EXCLUDED.launch_time,
    status = EXCLUDED.status,
    last_refreshed = EXCLUDED.last_refreshed
"""


def upsert_instruments(
    conn: psycopg2.extensions.connection,
    instruments: list[dict[str, Any]],
) -> int:
    """Upsert perp instruments; returns number of rows affected."""
    if not instruments:
        return 0
    now = datetime.now(tz=timezone.utc)
    rows = [
        (
            i["ccxt_symbol"],
            i["bybit_symbol"],
            i["base"],
            i["quote"],
            i["settle"],
            i["funding_interval_hours"],
            i["launch_time"],
            i["status"],
            now,
        )
        for i in instruments
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, INSTRUMENTS_UPSERT_SQL, rows, page_size=max(len(rows), 2000)
        )
        affected = cur.rowcount
    conn.commit()
    return affected


# ---------------------------------------------------------------------------
# Funding rates
# ---------------------------------------------------------------------------


def fetch_funding_page(
    bybit_symbol: str,
    end_ms: int | None = None,
    limit: int = FUNDING_PAGE_LIMIT,
) -> list[dict[str, Any]]:
    """Fetch one page of funding rate history for ``bybit_symbol``.

    Returned list is newest-first (Bybit's native order). Each item is a
    dict with ``symbol``, ``fundingRate``, ``fundingRateTimestamp``.

    CRITICAL: ``end_ms`` is always passed (the repo's prior code had issues
    when omitting it). For the very first call, pass ``None`` and Bybit
    defaults to the current timestamp.
    """
    params: dict[str, Any] = {
        "category": "linear",
        "symbol": bybit_symbol,
        "limit": limit,
    }
    if end_ms is not None:
        params["endTime"] = end_ms
    result = bybit_get("/v5/market/funding/history", params)
    return result.get("list") or []


FUNDING_INSERT_SQL = (
    "INSERT INTO bybit_funding_rates "
    "(symbol, funding_time, funding_rate, interval_hours, mark_price) "
    "VALUES %s ON CONFLICT (symbol, funding_time) DO NOTHING"
)


def insert_funding_rates(
    conn: psycopg2.extensions.connection,
    ccxt_symbol: str,
    interval_hours: int,
    rows: list[dict[str, Any]],
) -> int:
    """Batch-upsert funding rates for ``ccxt_symbol``.

    Args:
        conn: Open psycopg2 connection.
        ccxt_symbol: ccxt-unified symbol to store (e.g. ``"BTC/USDT:USDT"``).
        interval_hours: Funding interval (from ``bybit_perp_instruments``).
        rows: Raw Bybit funding entries.

    Returns:
        Number of rows inserted (duplicates skipped via ON CONFLICT).
    """
    if not rows:
        return 0
    tuples: list[tuple] = []
    for r in rows:
        ts_ms = int(r["fundingRateTimestamp"])
        if ts_ms <= 0:
            # Bybit occasionally returns bogus records with timestamp 0; skip.
            logger.warning("skipping funding record with invalid timestamp for %s", ccxt_symbol)
            continue
        ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        # Pass funding_rate as Decimal to preserve precision (stored as NUMERIC).
        rate = Decimal(str(r["fundingRate"]))
        tuples.append((ccxt_symbol, ts, rate, interval_hours, None))
    if not tuples:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, FUNDING_INSERT_SQL, tuples, page_size=max(len(tuples), 1000)
        )
        inserted = cur.rowcount
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Predicted funding (live forecast)
# ---------------------------------------------------------------------------


PREDICTED_FUNDING_INSERT_SQL = (
    "INSERT INTO bybit_predicted_funding "
    "(symbol, observed_at, predicted_rate, next_funding_time, mark_price, index_price) "
    "VALUES %s ON CONFLICT (symbol, observed_at) DO NOTHING"
)


def fetch_and_insert_predicted_funding(
    conn: psycopg2.extensions.connection,
) -> int:
    """Capture the current predicted funding rate for all linear perps.

    Calls Bybit's ``/v5/market/tickers?category=linear`` once (returns all
    linear perp tickers in a single response, no pagination needed) and
    inserts one row per known perp into ``bybit_predicted_funding``. All
    rows in a single call share the same ``observed_at`` timestamp (now UTC),
    so a double invocation within the same second is a no-op thanks to the
    primary-key conflict.

    Only symbols present in ``bybit_perp_instruments`` are accepted -- the
    tickers endpoint occasionally includes non-perp contracts that cannot
    be safely converted with ``bybit_perp_to_ccxt``.

    Returns:
        Number of rows inserted (duplicates skipped via ON CONFLICT).
    """
    # Build the raw -> ccxt symbol map and per-symbol quote/settle from the
    # DB so bybit_perp_to_ccxt gets the correct coins for odd contracts.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT bybit_symbol, symbol, quote, settle "
            "FROM bybit_perp_instruments"
        )
        instrument_rows = cur.fetchall()
    known: dict[str, tuple[str, str, str]] = {
        r[0]: (r[1], r[2], r[3]) for r in instrument_rows
    }

    result = bybit_get("/v5/market/tickers", {"category": "linear"})
    items = result.get("list") or []

    # Truncate to whole seconds so two invocations within the same second
    # collide on the PK and no-op via ON CONFLICT DO NOTHING.
    observed_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
    tuples: list[tuple] = []
    skipped_unknown = 0
    skipped_invalid = 0
    for it in items:
        bybit_sym = it.get("symbol")
        if not bybit_sym or bybit_sym not in known:
            skipped_unknown += 1
            continue
        ccxt_sym, _quote, _settle = known[bybit_sym]

        next_ft_raw = it.get("nextFundingTime")
        rate_raw = it.get("fundingRate")
        if not next_ft_raw or rate_raw in (None, "", "null"):
            skipped_invalid += 1
            continue
        try:
            next_ft_ms = int(next_ft_raw)
        except (TypeError, ValueError):
            skipped_invalid += 1
            continue
        if next_ft_ms <= 0:
            # Bybit occasionally returns bogus records with timestamp 0; skip.
            logger.warning(
                "skipping predicted funding with invalid nextFundingTime for %s",
                ccxt_sym,
            )
            skipped_invalid += 1
            continue
        try:
            predicted_rate = Decimal(str(rate_raw))
        except Exception:  # noqa: BLE001
            skipped_invalid += 1
            continue

        next_funding_time = datetime.fromtimestamp(
            next_ft_ms / 1000.0, tz=timezone.utc
        )

        mark_raw = it.get("markPrice")
        index_raw = it.get("indexPrice")
        mark_price = Decimal(str(mark_raw)) if mark_raw not in (None, "", "null") else None
        index_price = (
            Decimal(str(index_raw)) if index_raw not in (None, "", "null") else None
        )

        tuples.append(
            (
                ccxt_sym,
                observed_at,
                predicted_rate,
                next_funding_time,
                mark_price,
                index_price,
            )
        )

    if not tuples:
        logger.info(
            "predicted_funding: tickers=%d inserted=0 skipped_unknown=%d skipped_invalid=%d",
            len(items),
            skipped_unknown,
            skipped_invalid,
        )
        return 0

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            PREDICTED_FUNDING_INSERT_SQL,
            tuples,
            page_size=max(len(tuples), 2000),
        )
        inserted = cur.rowcount
    conn.commit()
    logger.info(
        "predicted_funding: tickers=%d candidates=%d inserted=%d "
        "skipped_unknown=%d skipped_invalid=%d",
        len(items),
        len(tuples),
        inserted,
        skipped_unknown,
        skipped_invalid,
    )
    return inserted


# ---------------------------------------------------------------------------
# Klines
# ---------------------------------------------------------------------------


def fetch_kline_page(
    category: str,
    bybit_symbol: str,
    end_ms: int | None = None,
    interval: str = "60",
    limit: int = KLINE_PAGE_LIMIT,
) -> list[list[str]]:
    """Fetch one page of klines, reversed to chronological (ascending) order.

    Bybit returns klines newest-first; we reverse so callers can treat
    ``page[0]`` as oldest and ``page[-1]`` as newest for easier reasoning.

    Args:
        category: ``"linear"`` or ``"spot"``.
        bybit_symbol: Raw Bybit symbol (e.g. ``"BTCUSDT"``).
        end_ms: Exclusive upper bound epoch ms, or None for newest.
        interval: Bybit kline interval string (default ``"60"`` = 1h).
        limit: Page size (Bybit max 1000).

    Returns:
        List of raw entries ``[timestamp_ms, open, high, low, close, volume,
        turnover]`` (all strings), ordered ascending by timestamp.
    """
    params: dict[str, Any] = {
        "category": category,
        "symbol": bybit_symbol,
        "interval": interval,
        "limit": limit,
    }
    if end_ms is not None:
        params["end"] = end_ms
    result = bybit_get("/v5/market/kline", params)
    items = result.get("list") or []
    # Bybit returns newest-first; reverse to ascending for easier reasoning.
    items.reverse()
    return items


def _kline_to_row(ccxt_symbol: str, entry: list[str]) -> tuple:
    ts_ms = int(entry[0])
    ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return (
        ccxt_symbol,
        ts,
        float(entry[1]),
        float(entry[2]),
        float(entry[3]),
        float(entry[4]),
        float(entry[5]),
        float(entry[6]) if len(entry) > 6 else None,
    )


def insert_klines(
    conn: psycopg2.extensions.connection,
    table_name: str,
    ccxt_symbol: str,
    rows: list[list[str]],
) -> int:
    """Batch-upsert klines into ``table_name`` (``bybit_perp_klines`` or ``bybit_spot_klines``).

    Returns:
        Number of rows inserted (duplicates skipped via ON CONFLICT).
    """
    if not rows:
        return 0
    if table_name not in ("bybit_perp_klines", "bybit_spot_klines"):
        raise ValueError(f"unexpected kline table: {table_name!r}")
    tuples = [_kline_to_row(ccxt_symbol, r) for r in rows]
    sql = (
        f"INSERT INTO {table_name} "
        f"(symbol, timestamp, open, high, low, close, volume, turnover) "
        f"VALUES %s ON CONFLICT (symbol, timestamp) DO NOTHING"
    )
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, sql, tuples, page_size=max(len(tuples), 2000)
        )
        inserted = cur.rowcount
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Sync state
# ---------------------------------------------------------------------------


def get_funding_sync_state(
    conn: psycopg2.extensions.connection,
    ccxt_symbol: str,
) -> dict[str, Any] | None:
    """Read the funding sync-state row for ``ccxt_symbol``, or None if absent."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, earliest_time, latest_time, backfill_complete, "
            "last_synced_at, listing_time FROM bybit_funding_sync_state "
            "WHERE symbol = %s",
            (ccxt_symbol,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "symbol": row[0],
        "earliest_time": row[1],
        "latest_time": row[2],
        "backfill_complete": row[3],
        "last_synced_at": row[4],
        "listing_time": row[5],
    }


def upsert_funding_sync_state(
    conn: psycopg2.extensions.connection,
    ccxt_symbol: str,
    earliest_time: datetime | None,
    latest_time: datetime | None,
    backfill_complete: bool,
    listing_time: datetime | None,
) -> None:
    """Upsert a funding_sync_state row, merging earliest/latest bounds."""
    now = datetime.now(tz=timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bybit_funding_sync_state
                (symbol, earliest_time, latest_time, backfill_complete,
                 last_synced_at, listing_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol) DO UPDATE SET
                earliest_time = LEAST(
                    bybit_funding_sync_state.earliest_time,
                    EXCLUDED.earliest_time
                ),
                latest_time = GREATEST(
                    bybit_funding_sync_state.latest_time,
                    EXCLUDED.latest_time
                ),
                backfill_complete = bybit_funding_sync_state.backfill_complete
                    OR EXCLUDED.backfill_complete,
                last_synced_at = EXCLUDED.last_synced_at,
                listing_time = COALESCE(
                    EXCLUDED.listing_time,
                    bybit_funding_sync_state.listing_time
                )
            """,
            (
                ccxt_symbol,
                earliest_time,
                latest_time,
                backfill_complete,
                now,
                listing_time,
            ),
        )
    conn.commit()


def get_kline_sync_state(
    conn: psycopg2.extensions.connection,
    ccxt_symbol: str,
    market_type: str,
    interval: str,
) -> dict[str, Any] | None:
    """Read the kline sync-state row, or None if absent."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, market_type, interval, earliest_time, latest_time, "
            "backfill_complete, last_synced_at FROM bybit_kline_sync_state "
            "WHERE symbol = %s AND market_type = %s AND interval = %s",
            (ccxt_symbol, market_type, interval),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "symbol": row[0],
        "market_type": row[1],
        "interval": row[2],
        "earliest_time": row[3],
        "latest_time": row[4],
        "backfill_complete": row[5],
        "last_synced_at": row[6],
    }


def upsert_kline_sync_state(
    conn: psycopg2.extensions.connection,
    ccxt_symbol: str,
    market_type: str,
    interval: str,
    earliest_time: datetime | None,
    latest_time: datetime | None,
    backfill_complete: bool,
) -> None:
    """Upsert a kline_sync_state row, merging earliest/latest bounds."""
    now = datetime.now(tz=timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bybit_kline_sync_state
                (symbol, market_type, interval, earliest_time, latest_time,
                 backfill_complete, last_synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, market_type, interval) DO UPDATE SET
                earliest_time = LEAST(
                    bybit_kline_sync_state.earliest_time,
                    EXCLUDED.earliest_time
                ),
                latest_time = GREATEST(
                    bybit_kline_sync_state.latest_time,
                    EXCLUDED.latest_time
                ),
                backfill_complete = bybit_kline_sync_state.backfill_complete
                    OR EXCLUDED.backfill_complete,
                last_synced_at = EXCLUDED.last_synced_at
            """,
            (
                ccxt_symbol,
                market_type,
                interval,
                earliest_time,
                latest_time,
                backfill_complete,
                now,
            ),
        )
    conn.commit()


def load_perp_instruments(
    conn: psycopg2.extensions.connection,
) -> list[dict[str, Any]]:
    """Load perp instruments from the DB (order: ccxt_symbol ASC)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, bybit_symbol, base, quote, settle, "
            "funding_interval_hours, launch_time, status "
            "FROM bybit_perp_instruments ORDER BY symbol"
        )
        rows = cur.fetchall()
    return [
        {
            "ccxt_symbol": r[0],
            "bybit_symbol": r[1],
            "base": r[2],
            "quote": r[3],
            "settle": r[4],
            "funding_interval_hours": r[5],
            "launch_time": r[6],
            "status": r[7],
        }
        for r in rows
    ]


def page_rows_min_max_ms(entries: Iterable[Any], key: str | int) -> tuple[int, int]:
    """Return ``(min_ms, max_ms)`` from an iterable of entries.

    Args:
        entries: Iterable of dicts (for funding rows) or lists (for kline rows).
        key: Dict key (e.g. ``"fundingRateTimestamp"``) or list index (e.g. ``0``).
    """
    mins = None
    maxs = None
    for e in entries:
        ts_ms = int(e[key])
        if mins is None or ts_ms < mins:
            mins = ts_ms
        if maxs is None or ts_ms > maxs:
            maxs = ts_ms
    assert mins is not None and maxs is not None
    return mins, maxs
