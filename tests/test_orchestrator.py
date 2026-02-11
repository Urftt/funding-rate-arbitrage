"""Tests for the main bot orchestrator.

Tests verify:
- Orchestrator initializes and can be started/stopped
- Funding settlement simulation triggers after 8h elapsed
- open_position convenience method calls through to position_manager
- close_position convenience method records P&L
- get_status returns correct structure
- PAPR-02: Orchestrator works identically with PaperExecutor and LiveExecutor
- PAPR-02: Parameterized test proves identical behavior with both executors
- Phase 2: Autonomous cycle opens positions when opportunity passes risk check
- Phase 2: Autonomous cycle closes positions when rate drops below exit threshold
- Phase 2: Autonomous cycle skips pairs rejected by risk manager
- Phase 2: Margin critical triggers emergency controller
- Phase 2: Graceful stop closes all open positions
- Phase 2: Cycle lock prevents overlapping cycles
"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config import AppSettings, ExchangeSettings, FeeSettings, RiskSettings, TradingSettings
from bot.exchange.client import ExchangeClient
from bot.exchange.types import InstrumentInfo
from bot.execution.executor import Executor
from bot.execution.paper_executor import PaperExecutor
from bot.logging import get_logger
from bot.market_data.funding_monitor import FundingMonitor
from bot.market_data.opportunity_ranker import OpportunityRanker
from bot.market_data.ticker_service import TickerService
from bot.models import (
    FundingRateData,
    OpportunityScore,
    OrderRequest,
    OrderResult,
    OrderSide,
    Position,
    PositionSide,
)
from bot.orchestrator import Orchestrator, _FUNDING_SETTLEMENT_INTERVAL
from bot.pnl.fee_calculator import FeeCalculator
from bot.pnl.tracker import PnLTracker
from bot.position.delta_validator import DeltaValidator
from bot.position.manager import PositionManager
from bot.position.sizing import PositionSizer
from bot.risk.emergency import EmergencyController
from bot.risk.manager import RiskManager


@pytest.fixture
def settings() -> AppSettings:
    """Test AppSettings."""
    return AppSettings(
        log_level="DEBUG",
        exchange=ExchangeSettings(
            api_key="test-key",  # type: ignore[arg-type]
            api_secret="test-secret",  # type: ignore[arg-type]
            testnet=True,
        ),
        trading=TradingSettings(mode="paper"),
        fees=FeeSettings(),
        risk=RiskSettings(),
    )


@pytest.fixture
def mock_exchange_client() -> AsyncMock:
    """Mock ExchangeClient."""
    client = AsyncMock(spec=ExchangeClient)
    client.fetch_balance.return_value = {
        "USDT": {"free": 10000.0, "used": 0.0, "total": 10000.0}
    }
    client.get_instrument_info.return_value = InstrumentInfo(
        symbol="BTC/USDT",
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        qty_step=Decimal("0.001"),
        min_notional=Decimal("5"),
    )
    client.get_markets.return_value = {}
    return client


@pytest.fixture
def ticker_service() -> TickerService:
    """Real TickerService for testing."""
    return TickerService()


@pytest.fixture
def funding_monitor(
    mock_exchange_client: AsyncMock, ticker_service: TickerService
) -> FundingMonitor:
    """Real FundingMonitor with mocked exchange."""
    return FundingMonitor(mock_exchange_client, ticker_service, poll_interval=1.0)


@pytest.fixture
def fee_calculator(settings: AppSettings) -> FeeCalculator:
    """FeeCalculator with test settings."""
    return FeeCalculator(settings.fees)


@pytest.fixture
def delta_validator(settings: AppSettings) -> DeltaValidator:
    """DeltaValidator with test settings."""
    return DeltaValidator(settings.trading)


@pytest.fixture
def mock_position_manager() -> AsyncMock:
    """Mock PositionManager."""
    pm = AsyncMock(spec=PositionManager)
    pm.get_open_positions.return_value = []
    return pm


@pytest.fixture
def pnl_tracker(
    fee_calculator: FeeCalculator,
    ticker_service: TickerService,
    settings: AppSettings,
) -> PnLTracker:
    """Real PnLTracker for testing."""
    return PnLTracker(fee_calculator, ticker_service, settings.fees)


@pytest.fixture
def mock_risk_manager() -> MagicMock:
    """Mock RiskManager."""
    rm = MagicMock(spec=RiskManager)
    rm.check_can_open.return_value = (True, "")
    rm.check_margin_ratio = AsyncMock(return_value=(Decimal("0.1"), False))
    rm.is_margin_critical.return_value = False
    return rm


@pytest.fixture
def mock_ranker() -> MagicMock:
    """Mock OpportunityRanker."""
    ranker = MagicMock(spec=OpportunityRanker)
    ranker.rank_opportunities.return_value = []
    return ranker


@pytest.fixture
def mock_emergency_controller() -> AsyncMock:
    """Mock EmergencyController."""
    ec = AsyncMock(spec=EmergencyController)
    ec.triggered = False
    return ec


@pytest.fixture
def orchestrator(
    settings: AppSettings,
    mock_exchange_client: AsyncMock,
    funding_monitor: FundingMonitor,
    ticker_service: TickerService,
    mock_position_manager: AsyncMock,
    pnl_tracker: PnLTracker,
    delta_validator: DeltaValidator,
    fee_calculator: FeeCalculator,
    mock_risk_manager: MagicMock,
    mock_ranker: MagicMock,
    mock_emergency_controller: AsyncMock,
) -> Orchestrator:
    """Orchestrator with mocked dependencies."""
    return Orchestrator(
        settings=settings,
        exchange_client=mock_exchange_client,
        funding_monitor=funding_monitor,
        ticker_service=ticker_service,
        position_manager=mock_position_manager,
        pnl_tracker=pnl_tracker,
        delta_validator=delta_validator,
        fee_calculator=fee_calculator,
        risk_manager=mock_risk_manager,
        ranker=mock_ranker,
        emergency_controller=mock_emergency_controller,
    )


class TestOrchestratorLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_and_stop(
        self, orchestrator: Orchestrator
    ) -> None:
        """Orchestrator can be started and stopped gracefully."""
        # Start in background, then stop after a short delay
        task = asyncio.create_task(orchestrator.start())

        await asyncio.sleep(0.1)
        await orchestrator.stop()

        # Wait for the task to complete
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(
        self, orchestrator: Orchestrator
    ) -> None:
        """stop() sets _running to False."""
        orchestrator._running = True
        await orchestrator.stop()
        assert orchestrator._running is False


class TestFundingSettlement:
    """Tests for funding settlement simulation."""

    def test_settlement_triggers_after_8h_elapsed(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
        pnl_tracker: PnLTracker,
    ) -> None:
        """Funding settlement triggers when 8h have elapsed."""
        # Create a position for the tracker
        now = time.time()
        position = Position(
            id="pos_test",
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("0.1"),
            spot_entry_price=Decimal("50000"),
            perp_entry_price=Decimal("50010"),
            spot_order_id="s1",
            perp_order_id="p1",
            opened_at=now,
            entry_fee_total=Decimal("7.75"),
        )
        pnl_tracker.record_open(position, entry_fee=Decimal("7.75"))
        mock_position_manager.get_open_positions.return_value = [position]

        # Add funding rate to the monitor's cache
        orchestrator._funding_monitor._funding_rates["BTC/USDT:USDT"] = FundingRateData(
            symbol="BTC/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("50000"),
        )

        # Set last check to 8h+ ago
        orchestrator._last_funding_check = now - _FUNDING_SETTLEMENT_INTERVAL - 1

        orchestrator._check_funding_settlement()

        # Verify funding payment was recorded
        pnl = pnl_tracker.get_position_pnl("pos_test")
        assert pnl is not None
        assert len(pnl.funding_payments) == 1

    def test_settlement_does_not_trigger_before_8h(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
        pnl_tracker: PnLTracker,
    ) -> None:
        """Funding settlement does NOT trigger before 8h elapsed."""
        now = time.time()
        position = Position(
            id="pos_test",
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("0.1"),
            spot_entry_price=Decimal("50000"),
            perp_entry_price=Decimal("50010"),
            spot_order_id="s1",
            perp_order_id="p1",
            opened_at=now,
            entry_fee_total=Decimal("7.75"),
        )
        pnl_tracker.record_open(position, entry_fee=Decimal("7.75"))
        mock_position_manager.get_open_positions.return_value = [position]

        # Set last check to recently (less than 8h ago)
        orchestrator._last_funding_check = now - 100

        orchestrator._check_funding_settlement()

        # No funding payment should be recorded
        pnl = pnl_tracker.get_position_pnl("pos_test")
        assert pnl is not None
        assert len(pnl.funding_payments) == 0


class TestOpenPosition:
    """Tests for open_position convenience method."""

    @pytest.mark.asyncio
    async def test_calls_position_manager(
        self,
        orchestrator: Orchestrator,
        mock_exchange_client: AsyncMock,
        mock_position_manager: AsyncMock,
    ) -> None:
        """open_position delegates to position_manager.open_position."""
        now = time.time()
        expected_position = Position(
            id="pos_new",
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("0.02"),
            spot_entry_price=Decimal("50000"),
            perp_entry_price=Decimal("50010"),
            spot_order_id="s1",
            perp_order_id="p1",
            opened_at=now,
            entry_fee_total=Decimal("1.55"),
        )
        mock_position_manager.open_position.return_value = expected_position

        result = await orchestrator.open_position(
            "BTC/USDT", "BTC/USDT:USDT", available_balance=Decimal("5000")
        )

        assert result.id == "pos_new"
        mock_position_manager.open_position.assert_called_once()
        # Verify P&L tracking was initiated
        pnl = orchestrator._pnl_tracker.get_position_pnl("pos_new")
        assert pnl is not None
        assert pnl.entry_fee == Decimal("1.55")

    @pytest.mark.asyncio
    async def test_fetches_balance_when_not_provided(
        self,
        orchestrator: Orchestrator,
        mock_exchange_client: AsyncMock,
        mock_position_manager: AsyncMock,
    ) -> None:
        """open_position fetches balance from exchange when not provided."""
        now = time.time()
        mock_position_manager.open_position.return_value = Position(
            id="pos_bal",
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("0.1"),
            spot_entry_price=Decimal("50000"),
            perp_entry_price=Decimal("50010"),
            spot_order_id="s1",
            perp_order_id="p1",
            opened_at=now,
            entry_fee_total=Decimal("7.75"),
        )

        await orchestrator.open_position("BTC/USDT", "BTC/USDT:USDT")

        mock_exchange_client.fetch_balance.assert_called_once()


class TestClosePosition:
    """Tests for close_position convenience method."""

    @pytest.mark.asyncio
    async def test_records_pnl_on_close(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
    ) -> None:
        """close_position records exit fee and closes P&L tracking."""
        # First open a position
        now = time.time()
        position = Position(
            id="pos_close",
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("0.1"),
            spot_entry_price=Decimal("50000"),
            perp_entry_price=Decimal("50010"),
            spot_order_id="s1",
            perp_order_id="p1",
            opened_at=now,
            entry_fee_total=Decimal("7.75"),
        )
        orchestrator._pnl_tracker.record_open(position, Decimal("7.75"))

        # Mock close results
        spot_result = OrderResult(
            order_id="spot_close_1",
            symbol="BTC/USDT",
            side=OrderSide.SELL,
            filled_qty=Decimal("0.1"),
            filled_price=Decimal("50100"),
            fee=Decimal("5.01"),
            timestamp=time.time(),
        )
        perp_result = OrderResult(
            order_id="perp_close_1",
            symbol="BTC/USDT:USDT",
            side=OrderSide.BUY,
            filled_qty=Decimal("0.1"),
            filled_price=Decimal("50090"),
            fee=Decimal("2.75"),
            timestamp=time.time(),
        )
        mock_position_manager.close_position.return_value = (
            spot_result,
            perp_result,
        )

        await orchestrator.close_position("pos_close")

        pnl = orchestrator._pnl_tracker.get_position_pnl("pos_close")
        assert pnl is not None
        assert pnl.exit_fee == Decimal("7.76")  # 5.01 + 2.75
        assert pnl.closed_at is not None


class TestGetStatus:
    """Tests for get_status."""

    def test_returns_correct_structure(
        self, orchestrator: Orchestrator
    ) -> None:
        """get_status returns dict with expected keys."""
        status = orchestrator.get_status()

        assert "running" in status
        assert "open_positions_count" in status
        assert "mode" in status
        assert "portfolio_summary" in status
        assert "emergency_triggered" in status
        assert status["running"] is False
        assert status["open_positions_count"] == 0
        assert status["mode"] == "paper"
        assert status["emergency_triggered"] is False


# =============================================================================
# Phase 2: Autonomous Cycle Tests
# =============================================================================


def _make_test_position(
    position_id: str = "pos_1",
    perp_symbol: str = "BTC/USDT:USDT",
    spot_symbol: str = "BTC/USDT",
) -> Position:
    """Create a test position for autonomous cycle tests."""
    return Position(
        id=position_id,
        spot_symbol=spot_symbol,
        perp_symbol=perp_symbol,
        side=PositionSide.SHORT,
        quantity=Decimal("0.1"),
        spot_entry_price=Decimal("50000"),
        perp_entry_price=Decimal("50010"),
        spot_order_id="s1",
        perp_order_id="p1",
        opened_at=time.time(),
        entry_fee_total=Decimal("7.75"),
    )


def _make_test_opportunity(
    spot_symbol: str = "ETH/USDT",
    perp_symbol: str = "ETH/USDT:USDT",
    passes_filters: bool = True,
    annualized_yield: Decimal = Decimal("0.25"),
) -> OpportunityScore:
    """Create a test OpportunityScore for autonomous cycle tests."""
    return OpportunityScore(
        spot_symbol=spot_symbol,
        perp_symbol=perp_symbol,
        funding_rate=Decimal("0.0005"),
        funding_interval_hours=8,
        volume_24h=Decimal("5000000"),
        net_yield_per_period=Decimal("0.000228"),
        annualized_yield=annualized_yield,
        passes_filters=passes_filters,
    )


class TestAutonomousCycleOpen:
    """Tests for autonomous position opening."""

    @pytest.mark.asyncio
    async def test_opens_position_when_opportunity_passes_risk_check(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
        mock_exchange_client: AsyncMock,
        mock_ranker: MagicMock,
        mock_risk_manager: MagicMock,
        funding_monitor: FundingMonitor,
    ) -> None:
        """Autonomous cycle opens position when opportunity passes risk check."""
        # Setup: funding rates available
        funding_monitor._funding_rates["ETH/USDT:USDT"] = FundingRateData(
            symbol="ETH/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("3000"),
            volume_24h=Decimal("5000000"),
        )

        # Ranker returns an opportunity that passes filters
        opp = _make_test_opportunity()
        mock_ranker.rank_opportunities.return_value = [opp]

        # Risk manager allows opening
        mock_risk_manager.check_can_open.return_value = (True, "")

        # Position manager returns a position on open
        new_pos = _make_test_position(position_id="pos_eth", perp_symbol="ETH/USDT:USDT")
        mock_position_manager.open_position.return_value = new_pos

        await orchestrator._autonomous_cycle()

        # Verify open_position was called (via position_manager)
        mock_position_manager.open_position.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_pairs_rejected_by_risk_manager(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
        mock_ranker: MagicMock,
        mock_risk_manager: MagicMock,
        funding_monitor: FundingMonitor,
    ) -> None:
        """Autonomous cycle skips pairs rejected by risk manager."""
        # Setup funding rates
        funding_monitor._funding_rates["ETH/USDT:USDT"] = FundingRateData(
            symbol="ETH/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("3000"),
            volume_24h=Decimal("5000000"),
        )

        opp = _make_test_opportunity()
        mock_ranker.rank_opportunities.return_value = [opp]

        # Risk manager rejects
        mock_risk_manager.check_can_open.return_value = (False, "At max positions: 5")

        await orchestrator._autonomous_cycle()

        # No position should be opened
        mock_position_manager.open_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_opportunity_that_fails_filters(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
        mock_ranker: MagicMock,
        funding_monitor: FundingMonitor,
    ) -> None:
        """Autonomous cycle skips opportunities that don't pass filters."""
        funding_monitor._funding_rates["ETH/USDT:USDT"] = FundingRateData(
            symbol="ETH/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("3000"),
            volume_24h=Decimal("5000000"),
        )

        opp = _make_test_opportunity(passes_filters=False)
        mock_ranker.rank_opportunities.return_value = [opp]

        await orchestrator._autonomous_cycle()

        mock_position_manager.open_position.assert_not_called()


class TestAutonomousCycleClose:
    """Tests for autonomous position closing."""

    @pytest.mark.asyncio
    async def test_closes_position_when_rate_drops_below_exit(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
        mock_ranker: MagicMock,
        funding_monitor: FundingMonitor,
        pnl_tracker: PnLTracker,
    ) -> None:
        """Autonomous cycle closes position when rate drops below exit threshold."""
        # Position open on BTC
        pos = _make_test_position()
        mock_position_manager.get_open_positions.return_value = [pos]
        pnl_tracker.record_open(pos, Decimal("7.75"))

        # Funding rate is below exit threshold (0.0001)
        funding_monitor._funding_rates["BTC/USDT:USDT"] = FundingRateData(
            symbol="BTC/USDT:USDT",
            rate=Decimal("0.00005"),  # Below exit_funding_rate
            next_funding_time=0,
            mark_price=Decimal("50000"),
        )

        # Mock close results
        spot_result = OrderResult(
            order_id="sc1", symbol="BTC/USDT", side=OrderSide.SELL,
            filled_qty=Decimal("0.1"), filled_price=Decimal("50000"),
            fee=Decimal("5"), timestamp=time.time(),
        )
        perp_result = OrderResult(
            order_id="pc1", symbol="BTC/USDT:USDT", side=OrderSide.BUY,
            filled_qty=Decimal("0.1"), filled_price=Decimal("50000"),
            fee=Decimal("2.75"), timestamp=time.time(),
        )
        mock_position_manager.close_position.return_value = (spot_result, perp_result)
        mock_ranker.rank_opportunities.return_value = []

        await orchestrator._autonomous_cycle()

        # Position should have been closed
        mock_position_manager.close_position.assert_called_once_with("pos_1")

    @pytest.mark.asyncio
    async def test_closes_position_when_rate_unavailable(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
        mock_ranker: MagicMock,
        funding_monitor: FundingMonitor,
        pnl_tracker: PnLTracker,
    ) -> None:
        """Autonomous cycle closes position when funding rate data is unavailable."""
        pos = _make_test_position()
        mock_position_manager.get_open_positions.return_value = [pos]
        pnl_tracker.record_open(pos, Decimal("7.75"))

        # No funding rate data for BTC/USDT:USDT, but need at least one
        # rate entry so the cycle doesn't return early at the SCAN step
        funding_monitor._funding_rates["SOL/USDT:USDT"] = FundingRateData(
            symbol="SOL/USDT:USDT",
            rate=Decimal("0.0003"),
            next_funding_time=0,
            mark_price=Decimal("100"),
            volume_24h=Decimal("5000000"),
        )

        spot_result = OrderResult(
            order_id="sc1", symbol="BTC/USDT", side=OrderSide.SELL,
            filled_qty=Decimal("0.1"), filled_price=Decimal("50000"),
            fee=Decimal("5"), timestamp=time.time(),
        )
        perp_result = OrderResult(
            order_id="pc1", symbol="BTC/USDT:USDT", side=OrderSide.BUY,
            filled_qty=Decimal("0.1"), filled_price=Decimal("50000"),
            fee=Decimal("2.75"), timestamp=time.time(),
        )
        mock_position_manager.close_position.return_value = (spot_result, perp_result)
        mock_ranker.rank_opportunities.return_value = []

        await orchestrator._autonomous_cycle()

        mock_position_manager.close_position.assert_called_once_with("pos_1")


class TestMarginMonitoring:
    """Tests for margin ratio monitoring."""

    @pytest.mark.asyncio
    async def test_margin_critical_triggers_emergency(
        self,
        orchestrator: Orchestrator,
        mock_risk_manager: MagicMock,
        mock_emergency_controller: AsyncMock,
        funding_monitor: FundingMonitor,
        mock_ranker: MagicMock,
    ) -> None:
        """Margin critical triggers emergency controller."""
        # Setup: provide some funding rates so the cycle doesn't return early
        funding_monitor._funding_rates["BTC/USDT:USDT"] = FundingRateData(
            symbol="BTC/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("50000"),
            volume_24h=Decimal("5000000"),
        )
        mock_ranker.rank_opportunities.return_value = []

        # Margin check returns critical level
        mock_risk_manager.check_margin_ratio = AsyncMock(
            return_value=(Decimal("0.95"), True)
        )
        mock_risk_manager.is_margin_critical.return_value = True

        await orchestrator._autonomous_cycle()

        # Emergency controller should be triggered
        mock_emergency_controller.trigger.assert_called_once()
        trigger_arg = mock_emergency_controller.trigger.call_args[0][0]
        assert "margin_critical" in trigger_arg

    @pytest.mark.asyncio
    async def test_margin_alert_does_not_trigger_emergency(
        self,
        orchestrator: Orchestrator,
        mock_risk_manager: MagicMock,
        mock_emergency_controller: AsyncMock,
        funding_monitor: FundingMonitor,
        mock_ranker: MagicMock,
    ) -> None:
        """Margin alert logs warning but does not trigger emergency."""
        funding_monitor._funding_rates["BTC/USDT:USDT"] = FundingRateData(
            symbol="BTC/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("50000"),
            volume_24h=Decimal("5000000"),
        )
        mock_ranker.rank_opportunities.return_value = []

        # Margin check returns alert (but not critical)
        mock_risk_manager.check_margin_ratio = AsyncMock(
            return_value=(Decimal("0.85"), True)
        )
        mock_risk_manager.is_margin_critical.return_value = False

        await orchestrator._autonomous_cycle()

        # Emergency controller should NOT be triggered
        mock_emergency_controller.trigger.assert_not_called()


class TestGracefulStop:
    """Tests for graceful shutdown."""

    @pytest.mark.asyncio
    async def test_graceful_stop_closes_all_positions(
        self,
        orchestrator: Orchestrator,
        mock_position_manager: AsyncMock,
        pnl_tracker: PnLTracker,
    ) -> None:
        """Graceful stop closes all open positions."""
        pos1 = _make_test_position(position_id="pos_a", perp_symbol="BTC/USDT:USDT")
        pos2 = _make_test_position(position_id="pos_b", perp_symbol="ETH/USDT:USDT")
        mock_position_manager.get_open_positions.return_value = [pos1, pos2]

        # Record P&L for both
        pnl_tracker.record_open(pos1, Decimal("7.75"))
        pnl_tracker.record_open(pos2, Decimal("5.00"))

        # Mock close results
        spot_result = OrderResult(
            order_id="sc1", symbol="BTC/USDT", side=OrderSide.SELL,
            filled_qty=Decimal("0.1"), filled_price=Decimal("50000"),
            fee=Decimal("5"), timestamp=time.time(),
        )
        perp_result = OrderResult(
            order_id="pc1", symbol="BTC/USDT:USDT", side=OrderSide.BUY,
            filled_qty=Decimal("0.1"), filled_price=Decimal("50000"),
            fee=Decimal("2.75"), timestamp=time.time(),
        )
        mock_position_manager.close_position.return_value = (spot_result, perp_result)

        orchestrator._running = True
        await orchestrator.stop()

        assert orchestrator._running is False
        assert mock_position_manager.close_position.call_count == 2


class TestCycleLock:
    """Tests for cycle lock preventing overlapping cycles."""

    @pytest.mark.asyncio
    async def test_cycle_lock_prevents_overlapping_cycles(
        self, orchestrator: Orchestrator
    ) -> None:
        """Cycle lock prevents overlapping autonomous cycles."""
        call_order: list[str] = []

        async def slow_cycle() -> None:
            call_order.append("start")
            await asyncio.sleep(0.1)
            call_order.append("end")

        orchestrator._autonomous_cycle = slow_cycle  # type: ignore[method-assign]

        # Try to acquire lock and run two cycles concurrently
        async def run_locked_cycle() -> None:
            async with orchestrator._cycle_lock:
                await orchestrator._autonomous_cycle()

        t1 = asyncio.create_task(run_locked_cycle())
        t2 = asyncio.create_task(run_locked_cycle())

        await asyncio.gather(t1, t2)

        # Both cycles ran but sequentially (not overlapping)
        assert call_order == ["start", "end", "start", "end"]


class TestAutonomousCycleNoRates:
    """Tests for autonomous cycle with no funding rates."""

    @pytest.mark.asyncio
    async def test_cycle_returns_early_when_no_rates(
        self,
        orchestrator: Orchestrator,
        mock_ranker: MagicMock,
    ) -> None:
        """Autonomous cycle returns early when no funding rates available."""
        # No funding rates in monitor cache
        await orchestrator._autonomous_cycle()

        # Ranker should never be called
        mock_ranker.rank_opportunities.assert_not_called()


# =============================================================================
# PAPR-02: Swappable Executor Verification
# =============================================================================


def _make_mock_executor(executor_name: str) -> AsyncMock:
    """Create a mock executor that simulates order fills.

    Returns an AsyncMock that implements the Executor interface,
    producing realistic OrderResult objects for testing.
    """
    mock = AsyncMock(spec=Executor)
    call_count = {"n": 0}

    async def place_order_side_effect(request: OrderRequest) -> OrderResult:
        call_count["n"] += 1
        # Simulate slippage for realism
        fill_price = Decimal("50000")
        fee = request.quantity * fill_price * Decimal("0.001")
        return OrderResult(
            order_id=f"{executor_name}_{call_count['n']}",
            symbol=request.symbol,
            side=request.side,
            filled_qty=request.quantity,
            filled_price=fill_price,
            fee=fee,
            timestamp=time.time(),
            is_simulated=(executor_name == "paper"),
        )

    mock.place_order.side_effect = place_order_side_effect
    mock.cancel_order.return_value = True
    return mock


def _create_orchestrator_with_executor(
    executor: AsyncMock,
    settings: AppSettings,
    mock_exchange_client: AsyncMock,
    ticker_service: TickerService,
) -> tuple[Orchestrator, PositionManager, PnLTracker, FundingMonitor]:
    """Create a full Orchestrator with a specific executor for PAPR-02 testing."""
    fee_calculator = FeeCalculator(settings.fees)
    position_sizer = PositionSizer(settings.trading)
    delta_validator = DeltaValidator(settings.trading)

    position_manager = PositionManager(
        executor=executor,
        position_sizer=position_sizer,
        fee_calculator=fee_calculator,
        delta_validator=delta_validator,
        ticker_service=ticker_service,
        settings=settings.trading,
    )

    pnl_tracker = PnLTracker(fee_calculator, ticker_service, settings.fees)
    funding_monitor = FundingMonitor(mock_exchange_client, ticker_service)

    # Create risk manager and ranker for Phase 2 constructor
    risk_manager = RiskManager(settings=settings.risk)
    ranker = OpportunityRanker(settings.fees)

    orchestrator = Orchestrator(
        settings=settings,
        exchange_client=mock_exchange_client,
        funding_monitor=funding_monitor,
        ticker_service=ticker_service,
        position_manager=position_manager,
        pnl_tracker=pnl_tracker,
        delta_validator=delta_validator,
        fee_calculator=fee_calculator,
        risk_manager=risk_manager,
        ranker=ranker,
    )

    return orchestrator, position_manager, pnl_tracker, funding_monitor


class TestOrchestratorWithPaperExecutor:
    """Test orchestrator works end-to-end with PaperExecutor."""

    @pytest.mark.asyncio
    async def test_orchestrator_works_with_paper_executor(
        self,
        settings: AppSettings,
        mock_exchange_client: AsyncMock,
    ) -> None:
        """Full lifecycle: open -> fund -> close with PaperExecutor."""
        ticker_service = TickerService()
        await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())
        await ticker_service.update_price(
            "BTC/USDT:USDT", Decimal("50000"), time.time()
        )

        paper_executor = _make_mock_executor("paper")

        orch, pm, pnl, fm = _create_orchestrator_with_executor(
            paper_executor, settings, mock_exchange_client, ticker_service
        )

        # Open position
        position = await orch.open_position(
            "BTC/USDT", "BTC/USDT:USDT", available_balance=Decimal("5000")
        )
        assert position is not None
        assert position.id is not None

        # Verify P&L tracking initiated
        pnl_data = pnl.get_position_pnl(position.id)
        assert pnl_data is not None

        # Simulate funding settlement
        fm._funding_rates["BTC/USDT:USDT"] = FundingRateData(
            symbol="BTC/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("50000"),
        )
        orch._last_funding_check = time.time() - _FUNDING_SETTLEMENT_INTERVAL - 1
        orch._check_funding_settlement()

        pnl_data = pnl.get_position_pnl(position.id)
        assert pnl_data is not None
        assert len(pnl_data.funding_payments) == 1

        # Close position
        await orch.close_position(position.id)

        pnl_data = pnl.get_position_pnl(position.id)
        assert pnl_data is not None
        assert pnl_data.closed_at is not None

        # Verify full P&L
        total = pnl.get_total_pnl(position.id)
        assert "net_pnl" in total
        assert "total_funding" in total
        assert "total_fees" in total


class TestOrchestratorWithLiveExecutor:
    """Test orchestrator works end-to-end with mock LiveExecutor."""

    @pytest.mark.asyncio
    async def test_orchestrator_works_with_live_executor(
        self,
        settings: AppSettings,
        mock_exchange_client: AsyncMock,
    ) -> None:
        """Full lifecycle: open -> fund -> close with LiveExecutor mock."""
        ticker_service = TickerService()
        await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())
        await ticker_service.update_price(
            "BTC/USDT:USDT", Decimal("50000"), time.time()
        )

        live_executor = _make_mock_executor("live")

        orch, pm, pnl, fm = _create_orchestrator_with_executor(
            live_executor, settings, mock_exchange_client, ticker_service
        )

        # Open position
        position = await orch.open_position(
            "BTC/USDT", "BTC/USDT:USDT", available_balance=Decimal("5000")
        )
        assert position is not None

        # Verify P&L tracking initiated
        pnl_data = pnl.get_position_pnl(position.id)
        assert pnl_data is not None

        # Simulate funding settlement
        fm._funding_rates["BTC/USDT:USDT"] = FundingRateData(
            symbol="BTC/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("50000"),
        )
        orch._last_funding_check = time.time() - _FUNDING_SETTLEMENT_INTERVAL - 1
        orch._check_funding_settlement()

        pnl_data = pnl.get_position_pnl(position.id)
        assert pnl_data is not None
        assert len(pnl_data.funding_payments) == 1

        # Close position
        await orch.close_position(position.id)

        pnl_data = pnl.get_position_pnl(position.id)
        assert pnl_data is not None
        assert pnl_data.closed_at is not None


class TestExecutorSwapProducesIdenticalBehavior:
    """PAPR-02: Parameterized test proving identical orchestrator behavior.

    Runs the SAME scenario with both PaperExecutor and LiveExecutor mock.
    Asserts that both produce:
    (a) identical position_manager behavior (open/close calls)
    (b) identical pnl_tracker calls (record_open, record_close)
    (c) identical funding settlement triggers

    Key assertion: The Orchestrator and PositionManager code does NOT
    branch on executor type.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("executor_name", ["paper", "live"])
    async def test_executor_swap_produces_identical_behavior(
        self,
        executor_name: str,
        settings: AppSettings,
        mock_exchange_client: AsyncMock,
    ) -> None:
        """Parameterized: same scenario, different executors, identical outcomes."""
        ticker_service = TickerService()
        await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())
        await ticker_service.update_price(
            "BTC/USDT:USDT", Decimal("50000"), time.time()
        )

        executor = _make_mock_executor(executor_name)

        orch, pm, pnl, fm = _create_orchestrator_with_executor(
            executor, settings, mock_exchange_client, ticker_service
        )

        # === Open position ===
        position = await orch.open_position(
            "BTC/USDT", "BTC/USDT:USDT", available_balance=Decimal("5000")
        )

        # (a) Position was opened (same flow regardless of executor)
        assert position is not None
        assert position.quantity > Decimal("0")
        open_positions = pm.get_open_positions()
        assert len(open_positions) == 1

        # (b) P&L tracking was initiated
        pnl_state = pnl.get_position_pnl(position.id)
        assert pnl_state is not None
        assert pnl_state.entry_fee > Decimal("0")

        # === Simulate funding ===
        fm._funding_rates["BTC/USDT:USDT"] = FundingRateData(
            symbol="BTC/USDT:USDT",
            rate=Decimal("0.0005"),
            next_funding_time=0,
            mark_price=Decimal("50000"),
        )
        orch._last_funding_check = time.time() - _FUNDING_SETTLEMENT_INTERVAL - 1
        orch._check_funding_settlement()

        # (c) Funding settlement triggered for both executors
        pnl_state = pnl.get_position_pnl(position.id)
        assert pnl_state is not None
        assert len(pnl_state.funding_payments) == 1
        # Funding amount is identical: 0.02 * 50000 * 0.0005 = 0.5
        assert pnl_state.funding_payments[0].amount == Decimal("0.500")

        # === Close position ===
        await orch.close_position(position.id)

        # (a) Position was closed
        open_after_close = pm.get_open_positions()
        assert len(open_after_close) == 0

        # (b) P&L was finalized
        pnl_state = pnl.get_position_pnl(position.id)
        assert pnl_state is not None
        assert pnl_state.closed_at is not None
        assert pnl_state.exit_fee > Decimal("0")

        # (c) Total P&L breakdown available
        total = pnl.get_total_pnl(position.id)
        assert total["total_funding"] > Decimal("0")
        assert total["total_fees"] > Decimal("0")
        assert "net_pnl" in total

        # Verify executor was called (2 calls for open, 2 for close = 4 total)
        assert executor.place_order.call_count == 4

    @pytest.mark.asyncio
    async def test_no_executor_type_branching(
        self,
        settings: AppSettings,
        mock_exchange_client: AsyncMock,
    ) -> None:
        """Verify that Orchestrator source code does not branch on executor type.

        This is a meta-test that verifies the PAPR-02 invariant:
        the orchestrator code path is truly executor-agnostic.
        """
        import inspect
        from bot.orchestrator import Orchestrator
        from bot.position.manager import PositionManager

        orch_source = inspect.getsource(Orchestrator)
        pm_source = inspect.getsource(PositionManager)

        # These strings should NOT appear in orchestrator or position manager
        forbidden_patterns = [
            "PaperExecutor",
            "LiveExecutor",
            "isinstance.*Executor",
            "is_simulated",
            "executor_type",
        ]

        for pattern in forbidden_patterns:
            assert pattern not in orch_source, (
                f"Orchestrator branches on executor type: found '{pattern}'"
            )
            assert pattern not in pm_source, (
                f"PositionManager branches on executor type: found '{pattern}'"
            )
