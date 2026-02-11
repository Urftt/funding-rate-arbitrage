"""Tests for OpportunityRanker -- net yield scoring and ranking.

Verifies:
- Net yield formula correctly subtracts amortized round-trip fees
- Annualized yield accounts for funding interval differences (4h vs 8h)
- Filtering by min_rate, min_volume, and spot pair availability
- Results sorted by annualized_yield descending
- Edge cases: empty input, negative net yield
"""

from decimal import Decimal

import pytest

from bot.config import FeeSettings
from bot.market_data.opportunity_ranker import OpportunityRanker
from bot.models import FundingRateData


@pytest.fixture
def fee_settings() -> FeeSettings:
    """Default fee settings: spot_taker=0.1%, perp_taker=0.055%."""
    return FeeSettings(
        spot_taker=Decimal("0.001"),
        spot_maker=Decimal("0.001"),
        perp_taker=Decimal("0.00055"),
        perp_maker=Decimal("0.0002"),
    )


@pytest.fixture
def ranker(fee_settings: FeeSettings) -> OpportunityRanker:
    return OpportunityRanker(fee_settings)


@pytest.fixture
def markets() -> dict:
    """Simulated ccxt markets dict with spot and perp entries."""
    return {
        "BTC/USDT:USDT": {
            "id": "BTCUSDT",
            "symbol": "BTC/USDT:USDT",
            "base": "BTC",
            "quote": "USDT",
            "type": "swap",
            "spot": False,
            "active": True,
        },
        "BTC/USDT": {
            "id": "BTCUSDT",
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "type": "spot",
            "spot": True,
            "active": True,
        },
        "ETH/USDT:USDT": {
            "id": "ETHUSDT",
            "symbol": "ETH/USDT:USDT",
            "base": "ETH",
            "quote": "USDT",
            "type": "swap",
            "spot": False,
            "active": True,
        },
        "ETH/USDT": {
            "id": "ETHUSDT",
            "symbol": "ETH/USDT",
            "base": "ETH",
            "quote": "USDT",
            "type": "spot",
            "spot": True,
            "active": True,
        },
        "SOL/USDT:USDT": {
            "id": "SOLUSDT",
            "symbol": "SOL/USDT:USDT",
            "base": "SOL",
            "quote": "USDT",
            "type": "swap",
            "spot": False,
            "active": True,
        },
        "SOL/USDT": {
            "id": "SOLUSDT",
            "symbol": "SOL/USDT",
            "base": "SOL",
            "quote": "USDT",
            "type": "spot",
            "spot": True,
            "active": True,
        },
        # DOGE has perp but no spot market
        "DOGE/USDT:USDT": {
            "id": "DOGEUSDT",
            "symbol": "DOGE/USDT:USDT",
            "base": "DOGE",
            "quote": "USDT",
            "type": "swap",
            "spot": False,
            "active": True,
        },
        # AVAX has perp and inactive spot
        "AVAX/USDT:USDT": {
            "id": "AVAXUSDT",
            "symbol": "AVAX/USDT:USDT",
            "base": "AVAX",
            "quote": "USDT",
            "type": "swap",
            "spot": False,
            "active": True,
        },
        "AVAX/USDT": {
            "id": "AVAXUSDT",
            "symbol": "AVAX/USDT",
            "base": "AVAX",
            "quote": "USDT",
            "type": "spot",
            "spot": True,
            "active": False,  # inactive!
        },
    }


class TestSinglePairAboveThreshold:
    """Test case 1: Single pair above threshold with spot available."""

    def test_returns_one_result(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.001"),  # 0.1% per 8h
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 1

    def test_correct_net_yield(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        """Net yield = funding_rate - amortized_fee.

        round_trip_fee_pct = (0.001 + 0.00055) * 2 = 0.0031
        amortized_fee = 0.0031 / 3 = 0.00103333...
        net_yield = 0.001 - 0.00103333... = -0.00003333...

        Wait -- with default min_holding_periods=3 and these fee rates,
        a 0.1% rate per 8h actually has negative net yield. Use higher rate.
        """
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.005"),  # 0.5% per 8h (high rate)
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 1

        score = result[0]
        # round_trip_fee_pct = (0.001 + 0.00055) * 2 = 0.0031
        # amortized = 0.0031 / 3 = 0.001033333...
        # net_yield = 0.005 - 0.001033333... = 0.003966666...
        expected_round_trip = (Decimal("0.001") + Decimal("0.00055")) * 2
        expected_amortized = expected_round_trip / 3
        expected_net = Decimal("0.005") - expected_amortized

        assert score.net_yield_per_period == expected_net
        assert score.funding_rate == Decimal("0.005")
        assert score.spot_symbol == "BTC/USDT"
        assert score.perp_symbol == "BTC/USDT:USDT"
        assert score.passes_filters is True

    def test_correct_annualized_yield(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        score = result[0]

        # periods_per_year = 8760 / 8 = 1095
        # annualized = net_yield * 1095
        expected_round_trip = (Decimal("0.001") + Decimal("0.00055")) * 2
        expected_amortized = expected_round_trip / 3
        expected_net = Decimal("0.005") - expected_amortized
        expected_annualized = expected_net * (Decimal("8760") / Decimal("8"))

        assert score.annualized_yield == expected_annualized


class TestFilterMinRate:
    """Test case 2: Pair below min_rate is excluded."""

    def test_below_min_rate_excluded(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.0001"),  # below min_rate
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 0


class TestFilterMinVolume:
    """Test case 3: Pair below min_volume is excluded."""

    def test_below_min_volume_excluded(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("500000"),  # below 1M default
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 0


class TestFilterNoSpotSymbol:
    """Test case 4: Pair with no matching spot symbol is excluded."""

    def test_no_spot_excluded(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        rates = [
            FundingRateData(
                symbol="DOGE/USDT:USDT",  # no spot market in markets dict
                next_funding_time=1700000000000,
                rate=Decimal("0.005"),
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 0

    def test_inactive_spot_excluded(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        """AVAX has a spot market but it is inactive."""
        rates = [
            FundingRateData(
                symbol="AVAX/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 0


class TestIntervalHoursNormalization:
    """Test case 5: Different interval_hours at same raw rate produce different annualized yields."""

    def test_4h_ranked_higher_than_8h(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        """4h funding at same rate = more periods/year = higher annualized yield."""
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
            FundingRateData(
                symbol="ETH/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                interval_hours=4,  # 4h interval
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 2
        # ETH (4h) should be ranked first -- higher annualized yield
        assert result[0].perp_symbol == "ETH/USDT:USDT"
        assert result[1].perp_symbol == "BTC/USDT:USDT"
        assert result[0].annualized_yield > result[1].annualized_yield

    def test_4h_periods_per_year(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        """4h interval = 8760/4 = 2190 periods/year."""
        rates = [
            FundingRateData(
                symbol="ETH/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                interval_hours=4,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        score = result[0]

        expected_round_trip = (Decimal("0.001") + Decimal("0.00055")) * 2
        expected_amortized = expected_round_trip / 3
        expected_net = Decimal("0.005") - expected_amortized
        expected_annualized = expected_net * (Decimal("8760") / Decimal("4"))

        assert score.annualized_yield == expected_annualized


class TestNegativeNetYield:
    """Test case 6: Pair where fee exceeds funding rate has passes_filters=False."""

    def test_fee_exceeds_rate(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        """When amortized fee > funding rate, net yield is negative."""
        # round_trip_fee_pct = (0.001 + 0.00055) * 2 = 0.0031
        # amortized = 0.0031 / 3 = 0.001033...
        # rate = 0.0005 < 0.001033 -> negative net yield
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.0005"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 1
        assert result[0].passes_filters is False
        assert result[0].net_yield_per_period < 0


class TestSortingMultiplePairs:
    """Test case 7: Multiple pairs sorted by annualized_yield descending."""

    def test_sorted_descending(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.003"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
            FundingRateData(
                symbol="ETH/USDT:USDT",
                rate=Decimal("0.010"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("3000000"),
            ),
            FundingRateData(
                symbol="SOL/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("2000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003")
        )
        assert len(result) == 3
        # ETH (0.01) > SOL (0.005) > BTC (0.003) -- same interval so rate drives ordering
        assert result[0].perp_symbol == "ETH/USDT:USDT"
        assert result[1].perp_symbol == "SOL/USDT:USDT"
        assert result[2].perp_symbol == "BTC/USDT:USDT"
        assert result[0].annualized_yield > result[1].annualized_yield
        assert result[1].annualized_yield > result[2].annualized_yield


class TestEmptyInput:
    """Test case 8: Empty input returns empty output."""

    def test_empty_list(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        result = ranker.rank_opportunities(
            [], markets, min_rate=Decimal("0.0003")
        )
        assert result == []

    def test_empty_markets(self, ranker: OpportunityRanker) -> None:
        """All pairs excluded when markets dict is empty."""
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result = ranker.rank_opportunities(
            rates, {}, min_rate=Decimal("0.0003")
        )
        assert result == []


class TestCustomMinHoldingPeriods:
    """Test min_holding_periods parameter affects amortized fee."""

    def test_higher_holding_lowers_amortized_fee(
        self, ranker: OpportunityRanker, markets: dict
    ) -> None:
        rates = [
            FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.005"),
                next_funding_time=1700000000000,
                interval_hours=8,
                volume_24h=Decimal("5000000"),
            ),
        ]
        result_3 = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003"), min_holding_periods=3
        )
        result_6 = ranker.rank_opportunities(
            rates, markets, min_rate=Decimal("0.0003"), min_holding_periods=6
        )
        # Higher holding periods = lower amortized fee = higher net yield
        assert result_6[0].net_yield_per_period > result_3[0].net_yield_per_period
        assert result_6[0].annualized_yield > result_3[0].annualized_yield
