"""CoinGecko market cap service for pair tier classification.

Fetches market cap data via the CoinGecko free API and classifies
pairs into tiers: mega (>$50B), large ($10B-$50B), mid ($1B-$10B),
small (<$1B). Uses urllib.request (stdlib) to avoid adding new
Python dependencies.

Results are cached in memory with a configurable TTL (default 1 hour)
since market cap tiers change slowly.
"""

import json
import time
import urllib.request
from decimal import Decimal

import structlog

logger = structlog.get_logger(__name__)

# Static mapping from ccxt-format symbols to CoinGecko coin IDs
SYMBOL_TO_COINGECKO: dict[str, str] = {
    "BTC/USDT:USDT": "bitcoin",
    "ETH/USDT:USDT": "ethereum",
    "SOL/USDT:USDT": "solana",
    "XRP/USDT:USDT": "ripple",
    "DOGE/USDT:USDT": "dogecoin",
    "ADA/USDT:USDT": "cardano",
    "AVAX/USDT:USDT": "avalanche-2",
    "DOT/USDT:USDT": "polkadot",
    "LINK/USDT:USDT": "chainlink",
    "MATIC/USDT:USDT": "matic-network",
    "SHIB/USDT:USDT": "shiba-inu",
    "LTC/USDT:USDT": "litecoin",
    "UNI/USDT:USDT": "uniswap",
    "ATOM/USDT:USDT": "cosmos",
    "FIL/USDT:USDT": "filecoin",
    "APT/USDT:USDT": "aptos",
    "ARB/USDT:USDT": "arbitrum",
    "OP/USDT:USDT": "optimism",
    "SUI/USDT:USDT": "sui",
    "NEAR/USDT:USDT": "near",
    "PEPE/USDT:USDT": "pepe",
    "WIF/USDT:USDT": "dogwifcoin",
}

# Tier boundaries in USD
TIER_MEGA = Decimal("50000000000")     # > $50B
TIER_LARGE = Decimal("10000000000")    # $10B - $50B
TIER_MID = Decimal("1000000000")       # $1B - $10B


def _classify_tier(market_cap: Decimal) -> str:
    """Classify market cap into tier name."""
    if market_cap >= TIER_MEGA:
        return "mega"
    if market_cap >= TIER_LARGE:
        return "large"
    if market_cap >= TIER_MID:
        return "mid"
    return "small"


class MarketCapService:
    """Fetches and caches market cap data from CoinGecko free API.

    Args:
        cache_ttl_seconds: How long to cache results (default 3600 = 1 hour).
        api_key: Optional CoinGecko demo API key for higher rate limits.
    """

    def __init__(self, cache_ttl_seconds: int = 3600, api_key: str | None = None):
        self._cache: dict[str, dict] = {}
        self._cache_time: float = 0
        self._ttl = cache_ttl_seconds
        self._api_key = api_key

    def _is_cache_valid(self) -> bool:
        return bool(self._cache) and (time.time() - self._cache_time < self._ttl)

    def _fetch_market_caps(self, coin_ids: list[str]) -> dict[str, Decimal]:
        """Fetch market caps from CoinGecko free API using stdlib urllib."""
        if not coin_ids:
            return {}

        ids_param = ",".join(coin_ids)
        url = (
            f"https://api.coingecko.com/api/v3/coins/markets"
            f"?vs_currency=usd&ids={ids_param}&per_page=250"
        )
        if self._api_key:
            url += f"&x_cg_demo_api_key={self._api_key}"

        headers = {"Accept": "application/json", "User-Agent": "FundingRateBot/1.0"}
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return {
                item["id"]: Decimal(str(item.get("market_cap") or 0))
                for item in data
            }
        except Exception as e:
            logger.warning("coingecko_fetch_error", error=str(e))
            return {}

    def get_pair_tiers(self, symbols: list[str]) -> dict[str, dict]:
        """Get market cap tier for each symbol.

        Returns a dict mapping symbol -> {"tier": str, "market_cap": str, "coingecko_id": str}.
        Symbols not found on CoinGecko get tier "unknown".
        Uses in-memory cache with TTL.
        """
        if self._is_cache_valid():
            return self._cache

        # Build reverse mapping
        coin_ids = []
        id_to_symbol: dict[str, str] = {}
        for symbol in symbols:
            cg_id = SYMBOL_TO_COINGECKO.get(symbol)
            if cg_id:
                coin_ids.append(cg_id)
                id_to_symbol[cg_id] = symbol

        # Fetch from CoinGecko
        market_caps = self._fetch_market_caps(coin_ids)

        result = {}
        for symbol in symbols:
            cg_id = SYMBOL_TO_COINGECKO.get(symbol)
            if cg_id and cg_id in market_caps:
                mc = market_caps[cg_id]
                result[symbol] = {
                    "tier": _classify_tier(mc),
                    "market_cap": str(mc),
                    "coingecko_id": cg_id,
                }
            else:
                result[symbol] = {
                    "tier": "unknown",
                    "market_cap": "0",
                    "coingecko_id": SYMBOL_TO_COINGECKO.get(symbol, ""),
                }

        self._cache = result
        self._cache_time = time.time()

        logger.info(
            "market_cap_tiers_loaded",
            total=len(result),
            tiers={t: sum(1 for v in result.values() if v["tier"] == t) for t in ("mega", "large", "mid", "small", "unknown")},
        )

        return result
