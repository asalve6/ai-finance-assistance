"""The market data the app uses: Yahoo Finance, then Alpha Vantage, then sample data, cached."""

from __future__ import annotations

from penny.market.alphavantage import AlphaVantageProvider
from penny.market.cache import CachedProvider
from penny.market.chain import FallbackChain
from penny.market.sample import SampleProvider
from penny.market.yahoo import YahooProvider


def default_market(*, demo: bool = False) -> CachedProvider:
    """`demo=True` uses only the sample data and never touches the network."""
    providers = (
        [SampleProvider()] if demo else [YahooProvider(), AlphaVantageProvider(), SampleProvider()]
    )
    return CachedProvider(FallbackChain(providers))
