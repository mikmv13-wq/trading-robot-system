from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from trading_system.domain import (
    Candle1m,
    CandleDataStats,
    CandleQualityCounts,
    DataGap,
    DataQualityReport,
    IngestionCheckpoint,
    Instrument,
    Universe,
)


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

    def upsert_candles(self, candles: Sequence[Candle1m]) -> None: ...

    def get_candles(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> tuple[Candle1m, ...]: ...

    def list_candles(self, instrument_uid: str) -> tuple[Candle1m, ...]: ...

    def get_candle_stats(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> CandleDataStats: ...

    def save_ingestion_checkpoint(self, checkpoint: IngestionCheckpoint) -> None: ...

    def get_ingestion_checkpoint(
        self,
        instrument_uid: str,
        interval: str,
    ) -> IngestionCheckpoint | None: ...

    def scan_data_gaps(
        self,
        universe_id: str,
        instrument_uid: str,
        *,
        from_ts: datetime,
        to_ts: datetime,
    ) -> tuple[DataGap, ...]: ...

    def replace_data_gaps(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime,
        to_ts: datetime,
        gaps: Sequence[DataGap],
    ) -> None: ...

    def get_data_gaps(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> tuple[DataGap, ...]: ...

    def get_candle_quality_counts(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime,
        to_ts: datetime,
        now: datetime,
    ) -> CandleQualityCounts: ...

    def save_data_quality_report(self, report: DataQualityReport) -> None: ...


class ResearchRepository(Repository, Protocol):
    pass


class LiveRepository(Repository, Protocol):
    pass
