from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from trading_system.domain import Bar, Instrument


class TInvestInstrumentsClient(Protocol):
    def list_shares(self) -> Sequence[Instrument]: ...


class TInvestMarketDataClient(Protocol):
    """Port for broker market data; concrete candles adapter is implemented later."""

    def get_candles(
        self,
        instrument_uid: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> Sequence[Bar]: ...
