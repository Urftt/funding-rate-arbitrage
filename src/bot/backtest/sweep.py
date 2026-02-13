"""Parameter sweep engine for grid search over backtest configurations.

Generates all combinations of parameter values via itertools.product,
runs a backtest for each, and returns a SweepResult with metrics.

Memory management: Only the best result (highest net P&L) retains its
full equity curve and trades list. All other results have their equity
curves and trades lists discarded after metrics extraction. Compact
trade_stats are retained for all results.

BKTS-03: Parameter sweep over entry/exit thresholds and signal weights.

CRITICAL: All monetary values use Decimal. Never use float for prices, quantities, or fees.
"""

import logging
from collections.abc import Callable
from decimal import Decimal
from itertools import product

from bot.backtest.models import BacktestConfig, BacktestResult, SweepResult
from bot.backtest.runner import run_backtest
from bot.config import BacktestSettings, FeeSettings
from bot.logging import get_logger

logger = get_logger(__name__)


class ParameterSweep:
    """Grid search engine for parameter optimization.

    Iterates over all parameter combinations, runs a backtest for each,
    and returns the results sorted by net P&L. Manages memory by only
    retaining the full equity curve for the best result.

    Args:
        db_path: Path to the SQLite historical database.
        fee_settings: Fee rates. Defaults to standard Bybit Non-VIP rates.
        backtest_settings: Backtest-specific settings (slippage, etc.).
    """

    def __init__(
        self,
        db_path: str = "data/historical.db",
        fee_settings: FeeSettings | None = None,
        backtest_settings: BacktestSettings | None = None,
    ) -> None:
        self._db_path = db_path
        self._fee_settings = fee_settings
        self._backtest_settings = backtest_settings

    async def run(
        self,
        base_config: BacktestConfig,
        param_grid: dict[str, list],
        progress_callback: Callable | None = None,
    ) -> SweepResult:
        """Run backtests for all parameter combinations in the grid.

        Validates that all param_grid keys are valid BacktestConfig fields,
        generates all combinations via itertools.product, runs a backtest
        for each, and returns a SweepResult.

        Memory management: After extracting metrics from each BacktestResult,
        the full equity curve is discarded (replaced with empty list) to
        prevent memory growth. Only the best result (highest net P&L) retains
        its full equity curve.

        Args:
            base_config: Base configuration to override with each combination.
            param_grid: Dict mapping parameter names to lists of values.
            progress_callback: Optional callback(current_index, total, params, result).

        Returns:
            SweepResult with all parameter combinations and their results.

        Raises:
            ValueError: If a param_grid key is not a valid BacktestConfig field.
        """
        # Validate param_grid keys
        for key in param_grid:
            if not hasattr(base_config, key):
                raise ValueError(
                    f"Invalid parameter '{key}': not a BacktestConfig field"
                )

        # Generate all combinations
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combinations = list(product(*values))
        total = len(combinations)

        logger.info(
            "sweep_starting",
            parameters=keys,
            total_combinations=total,
        )

        results: list[tuple[dict, BacktestResult]] = []
        best_pnl = Decimal("-999999999")
        best_index = -1

        for idx, combo in enumerate(combinations):
            # Build params dict
            params = dict(zip(keys, combo))

            # Convert string values to Decimal where needed
            converted_params: dict[str, object] = {}
            for k, v in params.items():
                base_field_value = getattr(base_config, k)
                if isinstance(base_field_value, Decimal) and not isinstance(v, Decimal):
                    converted_params[k] = Decimal(str(v))
                else:
                    converted_params[k] = v

            # Create override config
            config = base_config.with_overrides(**converted_params)

            # Run backtest
            result = await run_backtest(
                config,
                self._db_path,
                self._fee_settings,
                self._backtest_settings,
            )

            # Track best result
            if result.metrics.net_pnl > best_pnl:
                # Discard equity curve and trades from previous best
                if best_index >= 0:
                    prev = results[best_index][1]
                    results[best_index] = (
                        results[best_index][0],
                        BacktestResult(
                            config=prev.config,
                            equity_curve=[],
                            trades=[],
                            trade_stats=prev.trade_stats,
                            metrics=prev.metrics,
                        ),
                    )
                best_pnl = result.metrics.net_pnl
                best_index = len(results)
                # Keep full equity curve and trades for new best
                results.append((params, result))
            else:
                # Discard equity curve and trades to save memory
                results.append((
                    params,
                    BacktestResult(
                        config=result.config,
                        equity_curve=[],
                        trades=[],
                        trade_stats=result.trade_stats,
                        metrics=result.metrics,
                    ),
                ))

            # Call progress callback if provided
            if progress_callback is not None:
                progress_callback(idx + 1, total, params, result)

            logger.debug(
                "sweep_run_complete",
                index=idx + 1,
                total=total,
                params={k: str(v) for k, v in params.items()},
                net_pnl=str(result.metrics.net_pnl),
            )

        logger.info(
            "sweep_complete",
            total_combinations=total,
            best_pnl=str(best_pnl),
        )

        return SweepResult(param_grid=param_grid, results=results)

    @staticmethod
    def generate_default_grid(strategy_mode: str = "simple") -> dict[str, list]:
        """Generate a default parameter grid for the given strategy mode.

        For "simple" mode: sweeps over min_funding_rate and exit_funding_rate.
        For "composite" mode: sweeps over entry_threshold, exit_threshold,
        and weight_rate_level.

        Args:
            strategy_mode: "simple" or "composite".

        Returns:
            Dict mapping parameter names to lists of Decimal values.
        """
        if strategy_mode == "composite":
            return {
                "entry_threshold": [
                    Decimal("0.3"),
                    Decimal("0.4"),
                    Decimal("0.5"),
                    Decimal("0.6"),
                    Decimal("0.7"),
                ],
                "exit_threshold": [
                    Decimal("0.2"),
                    Decimal("0.3"),
                    Decimal("0.4"),
                ],
                "weight_rate_level": [
                    Decimal("0.25"),
                    Decimal("0.35"),
                    Decimal("0.45"),
                ],
            }
        # Default: simple mode
        return {
            "min_funding_rate": [
                Decimal("0.0001"),
                Decimal("0.0002"),
                Decimal("0.0003"),
                Decimal("0.0005"),
                Decimal("0.0008"),
            ],
            "exit_funding_rate": [
                Decimal("0.00005"),
                Decimal("0.0001"),
                Decimal("0.0002"),
            ],
        }


def format_sweep_summary(sweep_result: SweepResult) -> str:
    """Format a text summary table of sweep results.

    Sorts results by net P&L descending and displays each parameter
    combination with its key metrics. The best result is highlighted.

    Args:
        sweep_result: The completed sweep result.

    Returns:
        Formatted string suitable for console output.
    """
    if not sweep_result.results:
        return "No sweep results to display."

    # Sort by net P&L descending
    sorted_results = sorted(
        sweep_result.results,
        key=lambda x: x[1].metrics.net_pnl,
        reverse=True,
    )

    # Determine parameter column names
    param_names = list(sweep_result.param_grid.keys())

    # Build header
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("PARAMETER SWEEP RESULTS")
    lines.append("=" * 80)
    lines.append(f"Total combinations: {len(sorted_results)}")
    lines.append("")

    # Column headers
    header_parts = []
    for name in param_names:
        header_parts.append(f"{name:>15s}")
    header_parts.append(f"{'Net P&L':>12s}")
    header_parts.append(f"{'Sharpe':>8s}")
    header_parts.append(f"{'Win Rate':>10s}")
    header_parts.append(f"{'Trades':>8s}")
    header = " | ".join(header_parts)
    lines.append(header)
    lines.append("-" * len(header))

    # Data rows
    for rank, (params, result) in enumerate(sorted_results):
        m = result.metrics
        row_parts = []
        for name in param_names:
            val = params.get(name, "")
            row_parts.append(f"{str(val):>15s}")
        row_parts.append(f"${m.net_pnl:>10.2f}")
        sharpe_str = f"{m.sharpe_ratio:.2f}" if m.sharpe_ratio is not None else "N/A"
        row_parts.append(f"{sharpe_str:>8s}")
        win_str = (
            f"{m.win_rate * 100:.1f}%" if m.win_rate is not None else "N/A"
        )
        row_parts.append(f"{win_str:>10s}")
        row_parts.append(f"{m.total_trades:>8d}")
        row = " | ".join(row_parts)
        if rank == 0:
            row = row + "  <-- BEST"
        lines.append(row)

    lines.append("")
    lines.append("=" * 80)

    # Highlight best result
    best_params, best_result = sorted_results[0]
    lines.append("BEST PARAMETERS:")
    for name in param_names:
        lines.append(f"  {name}: {best_params.get(name, 'N/A')}")
    bm = best_result.metrics
    lines.append(f"  Net P&L: ${bm.net_pnl:.2f}")
    sharpe_display = f"{bm.sharpe_ratio:.2f}" if bm.sharpe_ratio is not None else "N/A"
    lines.append(f"  Sharpe Ratio: {sharpe_display}")
    win_display = (
        f"{bm.win_rate * 100:.1f}%" if bm.win_rate is not None else "N/A"
    )
    lines.append(f"  Win Rate: {win_display}")
    lines.append(f"  Total Trades: {bm.total_trades}")
    lines.append("=" * 80)

    return "\n".join(lines)
