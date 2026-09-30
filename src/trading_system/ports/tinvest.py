from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from trading_system.domain import Candle1m, Instrument


class TInvestInstrumentsClient(Protocol):
    def list_shares(self) -> Sequence[Instrument]: ...


class TInvestMarketDataClient(Protocol):
    def get_candles(
        self,
        instrument_uid: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> Sequence[Candle1m]: ...
