from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from trading_system.domain import Candle1m, Instrument, Universe


class Repository(Protocol):
    """Common diagnostic contract exposed by all storage repositories."""

    def healthcheck(self) -> None: ...

    def schema_version(self) -> int: ...

    def metadata(self) -> Mapping[str, str]: ...


class MarketRepository(Repository, Protocol):
    def upsert_instrument(self, instrument: Instrument) -> None: ...

    def get_instrument(self, instrument_uid: str) -> Instrument | None: ...

    def list_instruments(self) -> tuple[Instrument, ...]: ...

    def replace_universe(self, universe: Universe) -> None: ...

    def sync_universe(
        self,
        universe: Universe,
        instruments: tuple[Instrument, ...],
    ) -> None: ...

    def get_universe(self, universe_id: str) -> Universe | None: ...

    def insert_candle(self, candle: Candle1m) -> None: ...

    def list_candles(self, instrument_uid: str) -> tuple[Candle1m, ...]: ...


class ResearchRepository(Repository, Protocol):
    pass


class LiveRepository(Repository, Protocol):
    pass
