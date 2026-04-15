"""Historical funding-profit analysis for delta-neutral arbitrage.

Reusable computation module for simulating a continuously-held delta-neutral
position (long spot + short perp) across the full Postgres history. Runs
entirely in Polars on top of connectorx-read DataFrames.

Sign convention (drilled in because it is a classic source of 2x errors):

    positive funding_rate  => longs pay shorts
    delta-neutral book     => long spot + SHORT perp
    therefore              => our book RECEIVES funding when rate > 0
                              our book PAYS funding when rate < 0
    funding_payment_usd    = +short_notional * funding_rate   (USD, signed)

Entry/exit fees are applied once each (single-entry, single-exit model).
Price P&L captures basis risk between spot and perp legs and should be
small if the venue behaves well.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import connectorx as cx
import polars as pl
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


# ---------------------------------------------------------------------------
# Configuration / results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundingProfitConfig:
    """Configuration for a historical P&L simulation."""

    symbols: list[str]
    start: str | None = None
    end: str | None = None
    initial_capital_usd: Decimal = Decimal("10000")
    spot_taker_fee: Decimal = Decimal("0.001")
    perp_taker_fee: Decimal = Decimal("0.00055")
    use_mark_fallback: bool = True


@dataclass
class FundingProfitResult:
    """Per-symbol (or basket) P&L result."""

    config: FundingProfitConfig
    symbol: str
    funding_df: pl.DataFrame
    equity_curve: pl.DataFrame
    summary: dict
    has_spot_data: bool = True
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Postgres access
# ---------------------------------------------------------------------------


def _dsn() -> str:
    user = os.environ["POSTGRES_USER"]
    pw = quote(os.environ["POSTGRES_PASSWORD"])
    host = os.environ.get("POSTGRES_HOST", "192.168.1.53")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "crypto")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


def _sql_escape_list(items: list[str]) -> str:
    return ",".join("'" + s.replace("'", "''") + "'" for s in items)


def _perp_to_spot(symbol: str) -> str:
    """'BTC/USDT:USDT' -> 'BTC/USDT'."""
    return symbol.split(":")[0]


def load_funding_history(
    symbols: list[str],
    start: str | None = None,
    end: str | None = None,
) -> pl.DataFrame:
    """Load funding rates joined with perp-kline close prices.

    Returns columns:
        symbol, funding_time, funding_rate, interval_hours, mark_price,
        perp_close, spot_close, kline_hour
    """
    if not symbols:
        return pl.DataFrame()

    sym_list = _sql_escape_list(symbols)
    spot_symbols = [_perp_to_spot(s) for s in symbols]
    spot_list = _sql_escape_list(spot_symbols)

    where = [f"f.symbol IN ({sym_list})"]
    if start:
        where.append(f"f.funding_time >= '{start}'")
    if end:
        where.append(f"f.funding_time <= '{end}'")
    where_sql = " AND ".join(where)

    # Funding table has 8h-aligned funding_time — match perp kline on the
    # hour of funding_time directly. date_trunc('hour', ...) guarantees a match
    # against the hourly kline index.
    sql = f"""
        SELECT
            f.symbol,
            f.funding_time,
            f.funding_rate::double precision AS funding_rate,
            f.interval_hours,
            f.mark_price::double precision AS mark_price,
            pk.close AS perp_close,
            date_trunc('hour', f.funding_time) AS kline_hour
        FROM bybit_funding_rates f
        LEFT JOIN bybit_perp_klines pk
            ON pk.symbol = f.symbol
           AND pk.timestamp = date_trunc('hour', f.funding_time)
        WHERE {where_sql}
        ORDER BY f.symbol, f.funding_time
    """
    df = cx.read_sql(_dsn(), sql, return_type="polars")

    # Now pull the matching spot klines for ALL spot symbols we care about,
    # limited to the covered time range, and join in Polars (cheaper than
    # a doubled server-side join against a large table).
    if df.is_empty():
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias("spot_close"))

    tmin = df["funding_time"].min()
    tmax = df["funding_time"].max()
    spot_sql = f"""
        SELECT
            symbol AS spot_symbol,
            timestamp AS kline_hour,
            close AS spot_close
        FROM bybit_spot_klines
        WHERE symbol IN ({spot_list})
          AND timestamp >= '{tmin}'
          AND timestamp <= '{tmax}'
    """
    spot_df = cx.read_sql(_dsn(), spot_sql, return_type="polars")

    # Build perp->spot mapping column so we can join on (spot_symbol, kline_hour).
    df = df.with_columns(
        pl.col("symbol").map_elements(_perp_to_spot, return_dtype=pl.String).alias("spot_symbol")
    )

    if not spot_df.is_empty():
        df = df.join(
            spot_df,
            on=["spot_symbol", "kline_hour"],
            how="left",
        )
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("spot_close"))

    return df


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def _simulate_one(
    symbol: str,
    df: pl.DataFrame,
    config: FundingProfitConfig,
) -> FundingProfitResult:
    """Simulate delta-neutral P&L for a single symbol."""
    initial_capital = float(config.initial_capital_usd)
    spot_fee = float(config.spot_taker_fee)
    perp_fee = float(config.perp_taker_fee)

    warns: list[str] = []

    if df.is_empty():
        warns.append("no_funding_rows")
        return FundingProfitResult(
            config=config,
            symbol=symbol,
            funding_df=pl.DataFrame(),
            equity_curve=pl.DataFrame(),
            summary={
                "symbol": symbol,
                "funding_events": 0,
                "total_funding": 0.0,
                "total_fees": 0.0,
                "price_pnl": 0.0,
                "net_pnl": 0.0,
                "max_drawdown_pct": 0.0,
                "max_drawdown_duration_days": 0.0,
                "mean_funding_rate": 0.0,
                "median_funding_rate": 0.0,
                "pct_positive_events": 0.0,
                "is_monotonically_profitable": False,
                "sharpe_like": 0.0,
                "start": None,
                "end": None,
                "has_spot_data": False,
            },
            has_spot_data=False,
            warnings=warns,
        )

    # Determine whether we have spot data for the simulation window.
    has_spot = df["spot_close"].drop_nulls().len() > 0
    if not has_spot:
        warns.append("no_spot_leg_approximation: using perp mark/close for both legs")

    # Fill perp_close-and-mark_price.  mark_price is NULL for this dataset, so
    # we use perp kline close as notional basis.
    df = df.with_columns(
        pl.coalesce(pl.col("mark_price"), pl.col("perp_close")).alias("mark_effective"),
    )

    # Drop rows where we cannot establish notional at all (no perp price).
    before = df.height
    df = df.filter(pl.col("mark_effective").is_not_null())
    after = df.height
    if before != after:
        warns.append(f"dropped_{before - after}_rows_missing_perp_price")

    if df.is_empty():
        warns.append("all_rows_missing_perp_price")
        return FundingProfitResult(
            config=config,
            symbol=symbol,
            funding_df=pl.DataFrame(),
            equity_curve=pl.DataFrame(),
            summary={
                "symbol": symbol,
                "funding_events": 0,
                "total_funding": 0.0,
                "total_fees": 0.0,
                "price_pnl": 0.0,
                "net_pnl": 0.0,
                "max_drawdown_pct": 0.0,
                "max_drawdown_duration_days": 0.0,
                "mean_funding_rate": 0.0,
                "median_funding_rate": 0.0,
                "pct_positive_events": 0.0,
                "is_monotonically_profitable": False,
                "sharpe_like": 0.0,
                "start": None,
                "end": None,
                "has_spot_data": False,
            },
            has_spot_data=False,
            warnings=warns,
        )

    df = df.sort("funding_time")

    # Entry: first row. Exit: last row.
    entry_row = df.row(0, named=True)
    exit_row = df.row(-1, named=True)

    # Establish position sizing.
    # If spot data is missing, use perp entry price as spot proxy (synthetic).
    entry_spot = entry_row["spot_close"] if has_spot and entry_row["spot_close"] is not None else entry_row["mark_effective"]
    exit_spot = exit_row["spot_close"] if has_spot and exit_row["spot_close"] is not None else exit_row["mark_effective"]
    entry_perp = entry_row["mark_effective"]
    exit_perp = exit_row["mark_effective"]

    # Fixed dollar size. Long spot at entry_spot; short perp at entry_perp.
    # We split capital equally between legs -> same base qty on each side so
    # they're delta neutral in base units. position_size_base = notional / 2 /
    # entry_price (approximately — we keep it simple: the notional used for
    # funding is mark_effective * size_base).
    #
    # Simpler and most common in arb practice: deploy full capital on EACH leg
    # (so total deployed is 2x initial_capital). But the ask said "fixed dollar
    # position", so we use initial_capital as the gross notional on each leg
    # (i.e. short perp notional == long spot notional == initial_capital).
    # size_base is chosen so long-spot notional == initial_capital at entry.
    size_base = initial_capital / entry_spot

    # Per-event funding payment (signed; our book RECEIVES when rate > 0).
    df = df.with_columns(
        (pl.col("mark_effective") * size_base).alias("notional"),
    )
    df = df.with_columns(
        (pl.col("notional") * pl.col("funding_rate")).alias("funding_payment"),
    )
    df = df.with_columns(
        pl.col("funding_payment").cum_sum().alias("cumulative_funding"),
    )

    # Fees: pay spot + perp taker on each leg, twice (entry + exit).
    entry_notional_spot = initial_capital
    entry_notional_perp = size_base * entry_perp
    exit_notional_spot = size_base * exit_spot
    exit_notional_perp = size_base * exit_perp

    entry_fee = entry_notional_spot * spot_fee + entry_notional_perp * perp_fee
    exit_fee = exit_notional_spot * spot_fee + exit_notional_perp * perp_fee
    total_fees = entry_fee + exit_fee

    # Price P&L (basis): long spot gains (exit_spot - entry_spot) * size;
    # short perp gains (entry_perp - exit_perp) * size. Sum = basis drift.
    spot_pnl = (exit_spot - entry_spot) * size_base
    perp_pnl = (entry_perp - exit_perp) * size_base
    price_pnl = spot_pnl + perp_pnl

    total_funding = float(df["funding_payment"].sum())
    net_pnl = total_funding + price_pnl - total_fees

    # Equity curve = initial_capital + cumulative_funding (gross) or
    # initial_capital + cumulative_funding - entry_fee + mtm_price - exit_fee_final.
    # We keep it simple: funding_pnl = running; price_pnl gets attributed
    # linearly in time (not strictly realized until exit, but visually useful);
    # net = funding - entry_fee - (linear price drift) - (linear exit fee).
    n = df.height
    linear_weights = pl.int_range(1, n + 1, dtype=pl.Int64).cast(pl.Float64) / n  # 1/n .. 1

    df = df.with_columns(
        (pl.col("cumulative_funding")).alias("funding_pnl"),
    ).with_columns(
        (linear_weights * price_pnl).alias("price_pnl"),
    ).with_columns(
        (
            pl.col("funding_pnl")
            + pl.col("price_pnl")
            - entry_fee
            - linear_weights * exit_fee
        ).alias("net_pnl")
    ).with_columns(
        (initial_capital + pl.col("net_pnl")).alias("equity"),
    )

    equity_curve = df.select(
        pl.col("funding_time").alias("time"),
        "funding_pnl",
        "price_pnl",
        "net_pnl",
        "equity",
    )

    # Drawdown (on equity curve).
    eq = equity_curve["equity"]
    running_max = eq.cum_max()
    dd = (eq - running_max) / running_max  # negative or zero
    equity_curve = equity_curve.with_columns(dd.alias("drawdown"))

    max_dd_pct = float(dd.min()) * 100.0 if dd.len() > 0 else 0.0

    # Longest drawdown duration (days): longest consecutive run where equity <
    # running max.
    under_water = (eq < running_max).to_list()
    times = equity_curve["time"].to_list()
    longest_days = 0.0
    run_start_idx: int | None = None
    for i, uw in enumerate(under_water):
        if uw and run_start_idx is None:
            run_start_idx = i
        elif not uw and run_start_idx is not None:
            delta = (times[i] - times[run_start_idx]).total_seconds() / 86400.0
            longest_days = max(longest_days, delta)
            run_start_idx = None
    if run_start_idx is not None:
        delta = (times[-1] - times[run_start_idx]).total_seconds() / 86400.0
        longest_days = max(longest_days, delta)

    # Monotonicity: equity never dips below previous peak by > 0.5% and total is
    # positive.
    is_monotonic = float(dd.min() if dd.len() > 0 else 0.0) > -0.005 and net_pnl > 0

    # Summary.
    funding_events = df.height
    funding_std = float(df["funding_payment"].std() or 0.0)
    mean_rate = float(df["funding_rate"].mean() or 0.0)
    median_rate = float(df["funding_rate"].median() or 0.0)
    pct_positive = float((df["funding_payment"] > 0).mean() or 0.0) * 100.0

    # Sharpe-like: net_pnl / std(funding_payment) * sqrt(events/year).
    start_time = df["funding_time"].min()
    end_time = df["funding_time"].max()
    years = max((end_time - start_time).total_seconds() / (365.25 * 86400.0), 1e-9)
    events_per_year = funding_events / years if years > 0 else 0
    sharpe_like = (
        (net_pnl / funding_std) * (events_per_year**0.5)
        if funding_std > 0
        else 0.0
    )

    summary = {
        "symbol": symbol,
        "funding_events": funding_events,
        "total_funding": total_funding,
        "total_fees": total_fees,
        "price_pnl": price_pnl,
        "net_pnl": net_pnl,
        "max_drawdown_pct": max_dd_pct,
        "max_drawdown_duration_days": longest_days,
        "mean_funding_rate": mean_rate,
        "median_funding_rate": median_rate,
        "pct_positive_events": pct_positive,
        "is_monotonically_profitable": bool(is_monotonic),
        "sharpe_like": sharpe_like,
        "start": str(start_time),
        "end": str(end_time),
        "has_spot_data": has_spot,
    }

    # Build the final funding_df view with the columns promised in the API.
    funding_df_out = df.select(
        "funding_time",
        "funding_rate",
        "notional",
        "funding_payment",
        "cumulative_funding",
    )

    return FundingProfitResult(
        config=config,
        symbol=symbol,
        funding_df=funding_df_out,
        equity_curve=equity_curve,
        summary=summary,
        has_spot_data=has_spot,
        warnings=warns,
    )


def simulate_delta_neutral(config: FundingProfitConfig) -> list[FundingProfitResult]:
    """Run delta-neutral P&L simulation for each symbol in the config."""
    history = load_funding_history(config.symbols, config.start, config.end)
    results: list[FundingProfitResult] = []
    for sym in config.symbols:
        sub = history.filter(pl.col("symbol") == sym) if not history.is_empty() else history
        res = _simulate_one(sym, sub, config)
        if res.warnings:
            for w in res.warnings:
                warnings.warn(f"[{sym}] {w}", stacklevel=2)
        results.append(res)
    return results


def compute_basket(
    results: list[FundingProfitResult],
    weights: dict[str, Decimal] | None = None,
) -> FundingProfitResult:
    """Aggregate per-symbol results into a basket.

    Default is equal-weighted across symbols that have data. Weights apply
    to each symbol's dollar P&L stream before summation.
    """
    valid = [r for r in results if not r.equity_curve.is_empty()]
    if not valid:
        # Empty basket
        cfg = results[0].config if results else FundingProfitConfig(symbols=[])
        return FundingProfitResult(
            config=cfg,
            symbol="BASKET",
            funding_df=pl.DataFrame(),
            equity_curve=pl.DataFrame(),
            summary={
                "symbol": "BASKET",
                "funding_events": 0,
                "total_funding": 0.0,
                "total_fees": 0.0,
                "price_pnl": 0.0,
                "net_pnl": 0.0,
                "max_drawdown_pct": 0.0,
                "max_drawdown_duration_days": 0.0,
                "mean_funding_rate": 0.0,
                "median_funding_rate": 0.0,
                "pct_positive_events": 0.0,
                "is_monotonically_profitable": False,
                "sharpe_like": 0.0,
                "start": None,
                "end": None,
                "has_spot_data": False,
            },
        )

    cfg = valid[0].config

    if weights is None:
        weights = {r.symbol: Decimal(1) / Decimal(len(valid)) for r in valid}
    # Normalize weights
    w_total = sum(weights.values(), Decimal(0))
    w_norm = {k: float(v / w_total) for k, v in weights.items()}

    # Build a common time axis across all symbols using union-then-forward-fill.
    curves = []
    for r in valid:
        w = w_norm.get(r.symbol, 0.0)
        if w == 0:
            continue
        c = r.equity_curve.select(
            pl.col("time"),
            (pl.col("funding_pnl") * w).alias(f"funding_{r.symbol}"),
            (pl.col("price_pnl") * w).alias(f"price_{r.symbol}"),
            (pl.col("net_pnl") * w).alias(f"net_{r.symbol}"),
        )
        curves.append(c)

    # Outer-join everything on time, then forward-fill.
    merged = curves[0]
    for c in curves[1:]:
        merged = merged.join(c, on="time", how="full", coalesce=True)
    merged = merged.sort("time").fill_null(strategy="forward").fill_null(0.0)

    f_cols = [c for c in merged.columns if c.startswith("funding_")]
    p_cols = [c for c in merged.columns if c.startswith("price_")]
    n_cols = [c for c in merged.columns if c.startswith("net_")]

    basket_eq = merged.select(
        pl.col("time"),
        pl.sum_horizontal(*f_cols).alias("funding_pnl"),
        pl.sum_horizontal(*p_cols).alias("price_pnl"),
        pl.sum_horizontal(*n_cols).alias("net_pnl"),
    )
    initial_capital = float(cfg.initial_capital_usd)
    basket_eq = basket_eq.with_columns(
        (initial_capital + pl.col("net_pnl")).alias("equity"),
    )

    eq = basket_eq["equity"]
    running_max = eq.cum_max()
    dd = (eq - running_max) / running_max
    basket_eq = basket_eq.with_columns(dd.alias("drawdown"))

    max_dd_pct = float(dd.min()) * 100.0 if dd.len() > 0 else 0.0

    under_water = (eq < running_max).to_list()
    times = basket_eq["time"].to_list()
    longest_days = 0.0
    run_start_idx: int | None = None
    for i, uw in enumerate(under_water):
        if uw and run_start_idx is None:
            run_start_idx = i
        elif not uw and run_start_idx is not None:
            delta = (times[i] - times[run_start_idx]).total_seconds() / 86400.0
            longest_days = max(longest_days, delta)
            run_start_idx = None
    if run_start_idx is not None:
        delta = (times[-1] - times[run_start_idx]).total_seconds() / 86400.0
        longest_days = max(longest_days, delta)

    # Aggregate summary (weighted sum).
    total_funding = sum(r.summary["total_funding"] * w_norm.get(r.symbol, 0) for r in valid)
    total_fees = sum(r.summary["total_fees"] * w_norm.get(r.symbol, 0) for r in valid)
    price_pnl = sum(r.summary["price_pnl"] * w_norm.get(r.symbol, 0) for r in valid)
    net_pnl = total_funding + price_pnl - total_fees
    funding_events = sum(r.summary["funding_events"] for r in valid)
    is_monotonic = max_dd_pct > -0.5 and net_pnl > 0

    # Concatenate per-event funding_df's with a weighted payment column — this
    # lets downstream distribution analysis operate on a single frame.
    per_event_frames = []
    for r in valid:
        w = w_norm.get(r.symbol, 0.0)
        if w == 0 or r.funding_df.is_empty():
            continue
        per_event_frames.append(
            r.funding_df.with_columns(
                pl.lit(r.symbol).alias("symbol"),
                (pl.col("funding_payment") * w).alias("funding_payment_weighted"),
            )
        )
    if per_event_frames:
        basket_funding = pl.concat(per_event_frames, how="diagonal_relaxed").sort("funding_time")
    else:
        basket_funding = pl.DataFrame()

    start_time = basket_eq["time"].min()
    end_time = basket_eq["time"].max()
    years = max((end_time - start_time).total_seconds() / (365.25 * 86400.0), 1e-9)
    events_per_year = funding_events / years if years > 0 else 0
    # Basket funding-payment std uses the weighted per-event series.
    if not basket_funding.is_empty():
        f_std = float(basket_funding["funding_payment_weighted"].std() or 0.0)
    else:
        f_std = 0.0
    sharpe_like = (net_pnl / f_std) * (events_per_year**0.5) if f_std > 0 else 0.0

    mean_rate = (
        sum(r.summary["mean_funding_rate"] * w_norm.get(r.symbol, 0) for r in valid)
    )
    median_rate = (
        sum(r.summary["median_funding_rate"] * w_norm.get(r.symbol, 0) for r in valid)
    )
    pct_positive = (
        sum(r.summary["pct_positive_events"] * w_norm.get(r.symbol, 0) for r in valid)
    )

    summary = {
        "symbol": "BASKET",
        "funding_events": funding_events,
        "total_funding": total_funding,
        "total_fees": total_fees,
        "price_pnl": price_pnl,
        "net_pnl": net_pnl,
        "max_drawdown_pct": max_dd_pct,
        "max_drawdown_duration_days": longest_days,
        "mean_funding_rate": mean_rate,
        "median_funding_rate": median_rate,
        "pct_positive_events": pct_positive,
        "is_monotonically_profitable": bool(is_monotonic),
        "sharpe_like": sharpe_like,
        "start": str(start_time),
        "end": str(end_time),
        "has_spot_data": all(r.has_spot_data for r in valid),
        "components": [r.symbol for r in valid],
        "weights": w_norm,
    }

    return FundingProfitResult(
        config=cfg,
        symbol="BASKET",
        funding_df=basket_funding,
        equity_curve=basket_eq,
        summary=summary,
        has_spot_data=all(r.has_spot_data for r in valid),
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Helpers for notebook exploration
# ---------------------------------------------------------------------------


def list_symbols_with_history(min_days: int = 365) -> pl.DataFrame:
    """Return symbols that have at least `min_days` of funding history, sorted by coverage."""
    sql = """
        SELECT
            symbol,
            COUNT(*) AS events,
            MIN(funding_time) AS first_event,
            MAX(funding_time) AS last_event,
            EXTRACT(EPOCH FROM (MAX(funding_time) - MIN(funding_time))) / 86400.0 AS days_covered
        FROM bybit_funding_rates
        GROUP BY symbol
        ORDER BY days_covered DESC
    """
    df = cx.read_sql(_dsn(), sql, return_type="polars")
    return df.filter(pl.col("days_covered") >= min_days)


def list_symbols_without_spot(limit: int = 5) -> list[str]:
    """Return perp symbols that have no matching Bybit spot pair."""
    sql = f"""
        SELECT DISTINCT b.symbol
        FROM bybit_perp_instruments b
        LEFT JOIN bybit_spot_klines s
            ON (b.base || '/' || b.quote) = s.symbol
        WHERE s.symbol IS NULL
          AND b.status = 'Trading'
        LIMIT {limit}
    """
    df = cx.read_sql(_dsn(), sql, return_type="polars")
    return df["symbol"].to_list()
