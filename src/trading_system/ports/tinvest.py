from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from trading_system.domain import Bar


class TInvestMarketDataClient(Protocol):
    """Port for broker market data; concrete SDK adapter is implemented later."""

    def get_candles(
        self,
        instrument_uid: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> Sequence[Bar]: ...
