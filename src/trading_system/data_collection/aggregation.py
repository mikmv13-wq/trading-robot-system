from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import Candle
from .storage import ParquetCandleStorage

logger = logging.getLogger(__name__)

TIMEFRAME_MINUTES = {"15m": 15, "30m": 30, "1h": 60}


def aggregate_candles(
    candles: Iterable[Candle],
    timeframe: str,
    *,
    as_of: datetime | None = None,
) -> list[Candle]:
    try:
        minutes = TIMEFRAME_MINUTES[timeframe]
    except KeyError as exc:
        raise ValueError(f"Unsupported aggregate timeframe: {timeframe}") from exc

    cutoff = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    grouped: dict[tuple[str, datetime], list[Candle]] = defaultdict(list)
    for candle in candles:
        if not candle.is_complete:
            continue
        bucket = floor_time(candle.time, minutes)
        if bucket + timedelta(minutes=minutes) > cutoff:
            continue
        grouped[(candle.instrument_id, bucket)].append(candle)

    result: list[Candle] = []
    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: (item[0][0], item[0][1]),
    )
    for (instrument_id, bucket), rows in ordered_groups:
        ordered = sorted(rows, key=lambda item: item.time)
        result.append(
            Candle(
                instrument_id=instrument_id,
                time=bucket,
                open_nano=ordered[0].open_nano,
                high_nano=max(item.high_nano for item in ordered),
                low_nano=min(item.low_nano for item in ordered),
                close_nano=ordered[-1].close_nano,
                volume=sum(item.volume for item in ordered),
                is_complete=True,
                source="AGGREGATED_FROM_1M",
            )
        )
    return result


def floor_time(value: datetime, minutes: int) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Candle time must be timezone-aware")
    utc_value = value.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    elapsed_seconds = int((utc_value - epoch).total_seconds())
    bucket_seconds = minutes * 60
    return epoch + timedelta(seconds=(elapsed_seconds // bucket_seconds) * bucket_seconds)


class AggregateBuilder:
    def __init__(self, storage: ParquetCandleStorage, intervals: tuple[str, ...]) -> None:
        unknown = set(intervals) - set(TIMEFRAME_MINUTES)
        if unknown:
            raise ValueError(f"Unsupported aggregate timeframes: {sorted(unknown)}")
        self.storage = storage
        self.intervals = intervals

    def rebuild(self, *, all_partitions: bool = False) -> dict[str, int]:
        partitions = (
            self.storage.all_raw_partitions()
            if all_partitions
            else self.storage.dirty_raw_partitions()
        )
        totals = {timeframe: 0 for timeframe in self.intervals}

        for instrument_id, year, month in partitions:
            raw = self.storage.read_partition("1m", instrument_id, year, month)
            for timeframe in self.intervals:
                aggregates = aggregate_candles(raw, timeframe)
                totals[timeframe] += self.storage.replace_aggregate_partition(
                    timeframe,
                    instrument_id,
                    year,
                    month,
                    aggregates,
                )
            self.storage.mark_raw_partition_clean(instrument_id, year, month)
            logger.info(
                "Aggregated %s %04d-%02d into %s",
                instrument_id,
                year,
                month,
                ", ".join(self.intervals),
            )
        return totals
