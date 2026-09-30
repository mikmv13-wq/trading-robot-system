from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from trading_system.application.data_quality import ValidateMarketDataUseCase
from trading_system.application.historical_backfill import HistoricalBackfillService
from trading_system.application.instrument_sync import (
    InstrumentSyncResult,
    SyncInstrumentsUseCase,
)
from trading_system.application.job_service import JobApplicationService
from trading_system.application.jobs import JobSnapshot
from trading_system.domain import DataQualityReport, IngestionStatus
from trading_system.ports import MarketRepository


class DataUniverseNotFoundError(RuntimeError):
    """Raised when data operations target an unknown synchronized universe."""


@dataclass(frozen=True, slots=True)
class InstrumentDataStatus:
    instrument_uid: str
    ticker: str
    row_count: int
    min_timestamp: datetime | None
    max_timestamp: datetime | None
    gap_count: int
    missing_minutes: int
    checkpoint_status: IngestionStatus | None
    completed_until: datetime | None


@dataclass(frozen=True, slots=True)
class UniverseDataStatus:
    universe_id: str
    name: str
    instruments: tuple[InstrumentDataStatus, ...]

    @property
    def total_rows(self) -> int:
        return sum(item.row_count for item in self.instruments)

    @property
    def total_gaps(self) -> int:
        return sum(item.gap_count for item in self.instruments)


class DataApplicationService:
    """Single application-facing API for market-data operations used by GUI and CLI."""

    INTERVAL = "1m"

    def __init__(
        self,
        sync_instruments: SyncInstrumentsUseCase,
        historical_backfill: HistoricalBackfillService,
        validate_market_data: ValidateMarketDataUseCase,
        jobs: JobApplicationService,
        market_repository: MarketRepository,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sync_instruments = sync_instruments
        self._historical_backfill = historical_backfill
        self._validate_market_data = validate_market_data
        self._jobs = jobs
        self._market_repository = market_repository
        self._sleeper = sleeper

    def sync_instruments(self, universe_id: str = "default") -> InstrumentSyncResult:
        return self._sync_instruments.execute(universe_id)

    def start_backfill(
        self,
        universe_id: str = "default",
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> str:
        return self._historical_backfill.start(
            universe_id,
            from_ts=from_ts,
            to_ts=to_ts,
        )

    def resume_backfill(self, universe_id: str = "default") -> str:
        return self._historical_backfill.resume(universe_id)

    def cancel_backfill(self, job_id: str) -> bool:
        return self._jobs.cancel(job_id)

    def get_job(self, job_id: str) -> JobSnapshot:
        return self._jobs.get(job_id)

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float = 0.2,
    ) -> JobSnapshot:
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")

        snapshot = self._jobs.get(job_id)
        while not snapshot.status.terminal:
            self._sleeper(poll_interval_seconds)
            snapshot = self._jobs.get(job_id)
        return snapshot

    def validate(
        self,
        universe_id: str = "default",
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> DataQualityReport:
        return self._validate_market_data.execute(
            universe_id,
            from_ts=from_ts,
            to_ts=to_ts,
        )

    def get_status(self, universe_id: str = "default") -> UniverseDataStatus:
        universe = self._market_repository.get_universe(universe_id)
        if universe is None:
            raise DataUniverseNotFoundError(
                f"universe {universe_id!r} has not been synchronized"
            )

        instruments: list[InstrumentDataStatus] = []
        for instrument_uid in universe.instrument_uids:
            instrument = self._market_repository.get_instrument(instrument_uid)
            if instrument is None:
                raise RuntimeError(
                    f"instrument {instrument_uid!r} referenced by universe is missing"
                )
            stats = self._market_repository.get_candle_stats(instrument_uid)
            gaps = self._market_repository.get_data_gaps(instrument_uid)
            checkpoint = self._market_repository.get_ingestion_checkpoint(
                instrument_uid,
                self.INTERVAL,
            )
            missing_minutes = sum(
                int((gap.end_ts - gap.start_ts).total_seconds() // 60)
                for gap in gaps
            )
            instruments.append(
                InstrumentDataStatus(
                    instrument_uid=instrument_uid,
                    ticker=instrument.ticker,
                    row_count=stats.row_count,
                    min_timestamp=stats.min_timestamp,
                    max_timestamp=stats.max_timestamp,
                    gap_count=len(gaps),
                    missing_minutes=missing_minutes,
                    checkpoint_status=(
                        None if checkpoint is None else checkpoint.status
                    ),
                    completed_until=(
                        None if checkpoint is None else checkpoint.completed_until
                    ),
                )
            )

        return UniverseDataStatus(
            universe_id=universe.universe_id,
            name=universe.name,
            instruments=tuple(instruments),
        )
