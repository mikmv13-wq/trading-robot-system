from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator, Protocol

from trading_system.config import CollectorConfig, InstrumentConfig

from .models import Candle
from .storage import CandleStorage

logger = logging.getLogger(__name__)


class MarketDataClient(Protocol):
    def get_minute_candles(
        self,
        *,
        instrument_id: str,
        from_: datetime,
        to: datetime,
        candle_source: str,
    ) -> list[Candle]: ...


@dataclass(frozen=True, slots=True)
class CollectResult:
    instrument_id: str
    requested_from: datetime
    requested_to: datetime
    received: int
    saved: int


class HistoricalCandleCollector:
    def __init__(
        self,
        *,
        client: MarketDataClient,
        storage: CandleStorage,
        config: CollectorConfig,
    ) -> None:
        self.client = client
        self.storage = storage
        self.config = config

    def collect_instrument(
        self,
        instrument: InstrumentConfig,
        *,
        until: datetime | None = None,
    ) -> CollectResult:
        end = (until or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start = self._resolve_start(instrument.instrument_id)
        if end <= start:
            return CollectResult(instrument.instrument_id, start, end, 0, 0)

        label = instrument.ticker or instrument.instrument_id
        logger.info("Collecting %s from %s to %s", label, start.isoformat(), end.isoformat())

        received_total = 0
        saved_total = 0

        for window_from, window_to in iter_windows(
            start, end, timedelta(hours=self.config.request_window_hours)
        ):
            candles = self.client.get_minute_candles(
                instrument_id=instrument.instrument_id,
                from_=window_from,
                to=window_to,
                candle_source=self.config.candle_source,
            )
            received_total += len(candles)

            if self.config.only_complete:
                candles = [candle for candle in candles if candle.is_complete]

            saved = self.storage.upsert(candles)
            saved_total += saved
            logger.info(
                "%s window %s -> %s: received=%d saved=%d",
                label,
                window_from.isoformat(),
                window_to.isoformat(),
                len(candles),
                saved,
            )

        return CollectResult(instrument.instrument_id, start, end, received_total, saved_total)

    def _resolve_start(self, instrument_id: str) -> datetime:
        latest = self.storage.latest_time(instrument_id)
        if latest is None:
            return self.config.history_from
        resume_from = latest - timedelta(minutes=self.config.overlap_minutes)
        return max(self.config.history_from, resume_from)


def iter_windows(
    start: datetime,
    end: datetime,
    window: timedelta,
) -> Iterator[tuple[datetime, datetime]]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if window <= timedelta(0):
        raise ValueError("window must be positive")

    cursor = start
    while cursor < end:
        next_cursor = min(cursor + window, end)
        yield cursor, next_cursor
        cursor = next_cursor
