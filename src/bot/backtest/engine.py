"""Core backtest engine with event-driven historical replay.

Replays historical funding rate timestamps in chronological order, constructing
data snapshots at each step and feeding them through the strategy pipeline.
Reuses production FeeCalculator, PnLTracker, and PositionManager for all
fee/P&L computations (BKTS-02).

BKTS-01: No look-ahead bias -- only data with timestamp_ms <= current_time is visible.
BKTS-02: Reuses production code via Executor ABC swap pattern.
BKTS-05: Supports both simple and composite strategy modes.

CRITICAL: All monetary values use Decimal. Never use float for prices, quantities, or fees.
CRITICAL: Never use time.time() -- always use simulated timestamps.
"""

from bisect import bisect_right
from decimal import Decimal

from bot.backtest.data_wrapper import BacktestDataStoreWrapper
from bot.backtest.executor import BacktestExecutor
from bot.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    EquityPoint,
    TradeStats,
)
from bot.analytics.metrics import max_drawdown, sharpe_ratio, win_rate
from bot.config import BacktestSettings, FeeSettings, TradingSettings
from bot.data.store import HistoricalDataStore
from bot.exchange.types import InstrumentInfo
from bot.logging import get_logger
from bot.market_data.ticker_service import TickerService
from bot.models import FundingRateData
from bot.pnl.fee_calculator import FeeCalculator
from bot.pnl.tracker import PnLTracker
from bot.position.delta_validator import DeltaValidator
from bot.position.manager import PositionManager
from bot.position.dynamic_sizer import DynamicSizer
from bot.position.sizing import PositionSizer
from bot.signals.engine import SignalEngine

logger = get_logger(__name__)


class BacktestEngine:
    """Event-driven historical replay engine for funding rate backtesting.

    Walks through funding rate timestamps chronologically, constructs data
    snapshots visible at each moment, feeds them through the strategy decision
    logic, simulates funding settlements, and tracks P&L using production
    components.

    Args:
        config: Backtest configuration (symbol, dates, strategy, thresholds).
        data_store: The real HistoricalDataStore (not wrapped). Engine creates
            the BacktestDataStoreWrapper internally.
        fee_settings: Fee rates for spot and perp taker fees.
        backtest_settings: Backtest-specific settings (slippage, etc.).
    """

    def __init__(
        self,
        config: BacktestConfig,
        data_store: HistoricalDataStore,
        fee_settings: FeeSettings,
        backtest_settings: BacktestSettings,
    ) -> None:
        self._config = config
        self._data_store = data_store

        # Simulated time state
        self._current_time_ms: int = 0
        self._current_time_s: float = 0.0

        # Derive spot symbol and build static markets dict
        base = config.symbol.split("/")[0]
        quote = config.symbol.split("/")[1].split(":")[0]
        self._spot_symbol = f"{base}/{quote}"
        self._markets = {
            config.symbol: {
                "base": base,
                "quote": quote,
                "spot": False,
                "active": True,
                "type": "swap",
            },
            self._spot_symbol: {
                "base": base,
                "quote": quote,
                "spot": True,
                "active": True,
                "type": "spot",
            },
        }

        # Create internal components
        self._executor = BacktestExecutor(
            fee_settings=fee_settings,
            slippage_bps=backtest_settings.slippage_bps,
        )
        self._data_wrapper = BacktestDataStoreWrapper(data_store)
        self._fee_calculator = FeeCalculator(fee_settings)
        self._ticker_service = TickerService()
        self._pnl_tracker = PnLTracker(
            fee_calculator=self._fee_calculator,
            ticker_service=self._ticker_service,
            fee_settings=fee_settings,
            time_fn=lambda: self._current_time_s,
        )

        # Position management (reusing production classes per BKTS-02)
        trading_settings = TradingSettings(
            max_position_size_usd=config.initial_capital,
        )
        self._position_sizer = PositionSizer(settings=trading_settings)
        self._delta_validator = DeltaValidator(settings=trading_settings)
        self._position_manager = PositionManager(
            executor=self._executor,
            position_sizer=self._position_sizer,
            fee_calculator=self._fee_calculator,
            delta_validator=self._delta_validator,
            ticker_service=self._ticker_service,
            settings=trading_settings,
        )

        # Signal engine for composite mode
        self._signal_engine: SignalEngine | None = None
        if config.strategy_mode == "composite":
            self._signal_engine = SignalEngine(
                signal_settings=config.to_signal_settings(),
                data_store=self._data_wrapper,
                ticker_service=self._ticker_service,
            )

        # Dynamic sizer for composite mode with sizing enabled (Phase 7)
        self._dynamic_sizer: DynamicSizer | None = None
        if config.strategy_mode == "composite" and config.sizing_enabled:
            self._dynamic_sizer = DynamicSizer(
                position_sizer=self._position_sizer,
                settings=config.to_sizing_settings(),
                max_position_size_usd=config.initial_capital,
            )

        # Last signal score from composite decision (used by dynamic sizer)
        self._last_signal_score: Decimal | None = None

        # Generous instrument info for backtest (no exchange constraint validation)
        self._spot_instrument = InstrumentInfo(
            symbol=self._spot_symbol,
            min_qty=Decimal("0.00001"),
            max_qty=Decimal("1000000"),
            qty_step=Decimal("0.00001"),
            min_notional=Decimal("1"),
        )
        self._perp_instrument = InstrumentInfo(
            symbol=config.symbol,
            min_qty=Decimal("0.00001"),
            max_qty=Decimal("1000000"),
            qty_step=Decimal("0.00001"),
            min_notional=Decimal("1"),
        )

    async def run(self) -> BacktestResult:
        """Execute the backtest: replay historical data and return results.

        Loads all funding rates and OHLCV candles for the configured symbol
        and date range, then walks through each funding rate timestamp
        chronologically, making strategy decisions and tracking P&L.

        Returns:
            BacktestResult with equity curve and computed metrics.
        """
        symbol = self._config.symbol

        # 1. Load funding rates
        all_rates = await self._data_store.get_funding_rates(
            symbol=symbol,
            since_ms=self._config.start_ms,
            until_ms=self._config.end_ms,
        )

        if not all_rates:
            logger.warning(
                "no_funding_rates_for_backtest",
                symbol=symbol,
                start_ms=self._config.start_ms,
                end_ms=self._config.end_ms,
            )
            return self._empty_result()

        # 2. Load OHLCV candles and build lookup structures
        all_candles = await self._data_store.get_ohlcv_candles(
            symbol=symbol,
            since_ms=self._config.start_ms,
            until_ms=self._config.end_ms,
        )

        candle_by_ts: dict[int, Decimal] = {}
        sorted_candle_timestamps: list[int] = []
        for candle in all_candles:
            candle_by_ts[candle.timestamp_ms] = candle.close
            sorted_candle_timestamps.append(candle.timestamp_ms)
        sorted_candle_timestamps.sort()

        if not sorted_candle_timestamps:
            logger.warning(
                "no_candles_for_backtest",
                symbol=symbol,
                start_ms=self._config.start_ms,
                end_ms=self._config.end_ms,
            )
            return self._empty_result()

        # 3. Helper: get price at a timestamp (most recent candle close)
        def _get_price_at(timestamp_ms: int) -> Decimal | None:
            idx = bisect_right(sorted_candle_timestamps, timestamp_ms)
            if idx == 0:
                return None  # No candle available at or before this time
            return candle_by_ts[sorted_candle_timestamps[idx - 1]]

        # 4. Track state
        equity_curve: list[EquityPoint] = []
        total_trades = 0
        has_open_position = False

        logger.info(
            "backtest_starting",
            symbol=symbol,
            strategy_mode=self._config.strategy_mode,
            funding_rate_count=len(all_rates),
            candle_count=len(all_candles),
            start_ms=self._config.start_ms,
            end_ms=self._config.end_ms,
        )

        # 5. Walk through each funding interval chronologically.
        #
        # Stopgap timing fix (2026-04-15): the live bot decides at the START of
        # a funding interval using the predicted rate for the upcoming
        # settlement, and -- if it opens -- collects that settlement. The
        # previous backtester decided AT the settlement moment using the rate
        # that just settled, missing the concurrent settlement and instead
        # earning the next-next interval's rate. This mismatch systematically
        # underestimated strategy performance.
        #
        # The stopgap shifts each decision tick to `decide_ms = settle_ms -
        # interval_ms` and uses the upcoming settled rate as a proxy for what
        # the live bot would have seen as the predicted rate. Settlement itself
        # still happens at `settle_ms` with the settled rate. This is still
        # optimistic vs reality because real predicted rates fluctuate within
        # the interval, but it fixes the timing-granularity bug. Part 3 of the
        # plan will replace the proxy with actual captured predicted-rate
        # history.
        for fr in all_rates:
            settle_ms = fr.timestamp_ms
            interval_ms = fr.interval_hours * 3600 * 1000
            decide_ms = settle_ms - interval_ms

            # ---- Decision phase at decide_ms ----
            decide_price = _get_price_at(decide_ms)

            if decide_price is None:
                # Edge case: first interval may start before earliest candle.
                # Skip the decision but still fall through to settlement.
                logger.debug(
                    "backtest_skip_decision_no_price",
                    decide_ms=decide_ms,
                    settle_ms=settle_ms,
                )
            else:
                self._current_time_ms = decide_ms
                self._current_time_s = decide_ms / 1000.0

                self._executor.set_prices({
                    self._config.symbol: decide_price,
                    self._spot_symbol: decide_price,
                })
                self._executor.set_current_time(self._current_time_s)

                self._data_wrapper.set_current_time(decide_ms)

                await self._ticker_service.update_price(
                    self._spot_symbol, decide_price, self._current_time_s
                )
                await self._ticker_service.update_price(
                    self._config.symbol, decide_price, self._current_time_s
                )

                # Snapshot for the strategy decision. `rate` carries the
                # upcoming settled rate (fr.funding_rate) as a proxy for the
                # predicted rate visible to the live bot at decide_ms.
                decide_snapshot = FundingRateData(
                    symbol=self._config.symbol,
                    rate=fr.funding_rate,
                    next_funding_time=settle_ms,
                    interval_hours=fr.interval_hours,
                    mark_price=decide_price,
                    volume_24h=Decimal("1000000"),
                )

                open_positions = self._position_manager.get_open_positions()
                has_open_position = len(open_positions) > 0

                should_open = False
                should_close = False

                if self._config.strategy_mode == "simple":
                    should_open, should_close = self._simple_decision(
                        fr.funding_rate, has_open_position
                    )
                else:
                    should_open, should_close = await self._composite_decision(
                        decide_snapshot, has_open_position
                    )

                # Close (at decide_ms price; position will miss the upcoming
                # settlement).
                if should_close and open_positions:
                    for pos in open_positions:
                        try:
                            spot_result, perp_result = (
                                await self._position_manager.close_position(pos.id)
                            )
                            exit_fee = spot_result.fee + perp_result.fee
                            self._pnl_tracker.record_close(
                                position_id=pos.id,
                                spot_exit_price=spot_result.filled_price,
                                perp_exit_price=perp_result.filled_price,
                                exit_fee=exit_fee,
                            )
                            total_trades += 1
                            has_open_position = False
                            logger.debug(
                                "backtest_position_closed",
                                position_id=pos.id,
                                timestamp_ms=decide_ms,
                            )
                        except Exception as e:
                            logger.debug(
                                "backtest_close_error",
                                position_id=pos.id,
                                error=str(e),
                            )

                # Open (at decide_ms price; position will collect the upcoming
                # settlement at settle_ms).
                if should_open and not has_open_position:
                    available_balance = self._config.initial_capital

                    if (
                        self._dynamic_sizer is not None
                        and self._last_signal_score is not None
                    ):
                        current_exposure = self._compute_current_exposure()
                        budget = self._dynamic_sizer.compute_signal_budget(
                            self._last_signal_score, current_exposure
                        )
                        if budget is None:
                            logger.debug(
                                "backtest_portfolio_cap_reached",
                                timestamp_ms=decide_ms,
                                current_exposure=str(current_exposure),
                            )
                            should_open = False
                        else:
                            available_balance = min(
                                self._config.initial_capital, budget
                            )

                    if should_open:
                        try:
                            position = await self._position_manager.open_position(
                                spot_symbol=self._spot_symbol,
                                perp_symbol=self._config.symbol,
                                available_balance=available_balance,
                                spot_instrument=self._spot_instrument,
                                perp_instrument=self._perp_instrument,
                            )
                            self._pnl_tracker.record_open(
                                position, position.entry_fee_total
                            )
                            total_trades += 1
                            has_open_position = True
                            logger.debug(
                                "backtest_position_opened",
                                position_id=position.id,
                                timestamp_ms=decide_ms,
                            )
                        except Exception as e:
                            logger.debug(
                                "backtest_open_error",
                                error=str(e),
                            )

            # ---- Settlement phase at settle_ms ----
            settle_price = _get_price_at(settle_ms)
            if settle_price is None:
                # No price at settlement either -- nothing we can do. This
                # should be rare; skip the equity record.
                continue

            self._current_time_ms = settle_ms
            self._current_time_s = settle_ms / 1000.0

            self._executor.set_prices({
                self._config.symbol: settle_price,
                self._spot_symbol: settle_price,
            })
            self._executor.set_current_time(self._current_time_s)

            self._data_wrapper.set_current_time(settle_ms)

            await self._ticker_service.update_price(
                self._spot_symbol, settle_price, self._current_time_s
            )
            await self._ticker_service.update_price(
                self._config.symbol, settle_price, self._current_time_s
            )

            # Settle funding for any still-open positions against the mark
            # price at settle_ms. Positions opened at decide_ms participate
            # here; positions closed at decide_ms do not.
            for pos in self._position_manager.get_open_positions():
                try:
                    self._pnl_tracker.record_funding_payment(
                        position_id=pos.id,
                        funding_rate=fr.funding_rate,
                        mark_price=settle_price,
                        quantity=pos.quantity,
                    )
                except Exception as e:
                    logger.debug(
                        "funding_settlement_error",
                        position_id=pos.id,
                        error=str(e),
                    )

            # Record equity point at settlement time (unchanged: curve is
            # still indexed by settled funding events).
            portfolio = self._pnl_tracker.get_portfolio_summary()
            equity = self._config.initial_capital + portfolio["net_portfolio_pnl"]
            equity_curve.append(
                EquityPoint(
                    timestamp_ms=settle_ms,
                    equity=equity,
                )
            )

        # 6. Close any remaining open positions at last available price
        remaining_positions = self._position_manager.get_open_positions()
        for pos in remaining_positions:
            try:
                spot_result, perp_result = (
                    await self._position_manager.close_position(pos.id)
                )
                exit_fee = spot_result.fee + perp_result.fee
                self._pnl_tracker.record_close(
                    position_id=pos.id,
                    spot_exit_price=spot_result.filled_price,
                    perp_exit_price=perp_result.filled_price,
                    exit_fee=exit_fee,
                )
                total_trades += 1
                logger.debug(
                    "backtest_final_close",
                    position_id=pos.id,
                )
            except Exception as e:
                logger.debug(
                    "backtest_final_close_error",
                    position_id=pos.id,
                    error=str(e),
                )

        # 7. Compute metrics and extract trades
        metrics, trades, trade_stats = self._compute_metrics()

        logger.info(
            "backtest_complete",
            symbol=symbol,
            strategy_mode=self._config.strategy_mode,
            total_trades=metrics.total_trades,
            net_pnl=str(metrics.net_pnl),
            equity_points=len(equity_curve),
        )

        return BacktestResult(
            config=self._config,
            equity_curve=equity_curve,
            metrics=metrics,
            trades=trades,
            trade_stats=trade_stats,
        )

    def _compute_current_exposure(self) -> Decimal:
        """Compute total portfolio exposure as sum of open position notional values.

        Returns:
            Sum of (quantity * perp_entry_price) for all open positions.
        """
        total = Decimal("0")
        for pos in self._position_manager.get_open_positions():
            total += pos.quantity * pos.perp_entry_price
        return total

    def _simple_decision(
        self,
        funding_rate: Decimal,
        has_open_position: bool,
    ) -> tuple[bool, bool]:
        """Make entry/exit decision using simple threshold strategy.

        Args:
            funding_rate: Current funding rate at this timestamp.
            has_open_position: Whether a position is currently open.

        Returns:
            Tuple of (should_open, should_close).
        """
        should_open = False
        should_close = False

        if has_open_position:
            if funding_rate < self._config.exit_funding_rate:
                should_close = True
        else:
            if funding_rate >= self._config.min_funding_rate:
                should_open = True

        return should_open, should_close

    async def _composite_decision(
        self,
        funding_snapshot: FundingRateData,
        has_open_position: bool,
    ) -> tuple[bool, bool]:
        """Make entry/exit decision using composite signal strategy.

        Also stores the last signal score for use by dynamic sizer.

        Args:
            funding_snapshot: Current funding rate data snapshot.
            has_open_position: Whether a position is currently open.

        Returns:
            Tuple of (should_open, should_close).
        """
        should_open = False
        should_close = False
        self._last_signal_score = None  # Reset each decision

        if self._signal_engine is None:
            # Fallback to simple if signal engine not available
            return self._simple_decision(
                funding_snapshot.rate,
                has_open_position,
            )

        try:
            scores = await self._signal_engine.score_opportunities(
                [funding_snapshot], self._markets
            )
            if scores:
                signal = scores[0].signal
                if has_open_position:
                    if signal.score < self._config.exit_threshold:
                        should_close = True
                else:
                    if signal.passes_entry:
                        should_open = True
                        self._last_signal_score = signal.score
            elif has_open_position:
                # No score available (e.g., rate <= 0), close position
                should_close = True
        except Exception as e:
            logger.debug(
                "composite_decision_error",
                error=str(e),
            )
            # Fallback to simple on error
            return self._simple_decision(
                funding_snapshot.rate,
                has_open_position,
            )

        return should_open, should_close

    def _compute_metrics(
        self,
    ) -> tuple[BacktestMetrics, list[BacktestTrade], TradeStats | None]:
        """Compute backtest metrics and extract per-trade detail.

        Extracts trades from PnLTracker closed positions, computes
        TradeStats, and builds BacktestMetrics using correct round-trip
        trade counts.

        Returns:
            Tuple of (BacktestMetrics, trades list, TradeStats or None).
        """
        portfolio = self._pnl_tracker.get_portfolio_summary()
        closed_positions = self._pnl_tracker.get_closed_positions()

        # Build trades list from closed positions (oldest first)
        trades = [
            BacktestTrade.from_position_pnl(p, i + 1)
            for i, p in enumerate(reversed(closed_positions))
        ]
        trade_stats = TradeStats.from_trades(trades) if trades else None

        # Compute analytics metrics from closed positions
        sharpe = sharpe_ratio(closed_positions) if closed_positions else None
        max_dd = max_drawdown(closed_positions) if closed_positions else None
        wr = win_rate(closed_positions) if closed_positions else None

        # Duration in days
        duration_ms = self._config.end_ms - self._config.start_ms
        duration_days = max(1, duration_ms // (86400 * 1000))

        # Use round-trip trade count (closed positions) instead of
        # open+close event count (per research Pitfall 1)
        metrics = BacktestMetrics(
            total_trades=len(closed_positions),
            winning_trades=(
                trade_stats.winning_trades if trade_stats else 0
            ),
            net_pnl=portfolio["net_portfolio_pnl"],
            total_fees=portfolio["total_fees_paid"],
            total_funding=portfolio["total_funding_collected"],
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=wr,
            duration_days=duration_days,
        )

        return metrics, trades, trade_stats

    def _empty_result(self) -> BacktestResult:
        """Return an empty BacktestResult for when no data is available."""
        return BacktestResult(
            config=self._config,
            equity_curve=[],
            metrics=BacktestMetrics(
                total_trades=0,
                winning_trades=0,
                net_pnl=Decimal("0"),
                total_fees=Decimal("0"),
                total_funding=Decimal("0"),
                sharpe_ratio=None,
                max_drawdown=None,
                win_rate=None,
                duration_days=max(
                    1,
                    (self._config.end_ms - self._config.start_ms) // (86400 * 1000),
                ),
            ),
            trades=[],
            trade_stats=None,
        )
