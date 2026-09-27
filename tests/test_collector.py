from datetime import datetime, timedelta, timezone

from trading_system.config import CollectorConfig, InstrumentConfig
from trading_system.data_collection.collector import HistoricalCandleCollector, iter_windows
from trading_system.data_collection.models import Candle


class FakeStorage:
    def __init__(self) -> None:
        self.rows: list[Candle] = []
        self.latest = None

    def initialize(self) -> None:
        pass

    def upsert(self, candles):
        rows = list(candles)
        self.rows.extend(rows)
        return len(rows)

    def latest_time(self, instrument_id):
        return self.latest


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def get_minute_candles(self, *, instrument_id, from_, to, candle_source):
        self.calls.append((instrument_id, from_, to, candle_source))
        return [
            Candle(
                instrument_id=instrument_id,
                time=from_,
                open_nano=1,
                high_nano=2,
                low_nano=1,
                close_nano=2,
                volume=1,
                is_complete=True,
                source=candle_source,
            )
        ]


def test_iter_windows_has_no_gaps() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=2, hours=3)
    windows = list(iter_windows(start, end, timedelta(days=1)))
    assert windows == [
        (start, start + timedelta(days=1)),
        (start + timedelta(days=1), start + timedelta(days=2)),
        (start + timedelta(days=2), end),
    ]


def test_collector_splits_minute_history_by_day() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=2, hours=1)
    config = CollectorConfig(
        interval="1m",
        history_from=start,
        request_window_hours=24,
        overlap_minutes=5,
        candle_source="CANDLE_SOURCE_EXCHANGE",
        only_complete=True,
    )
    storage = FakeStorage()
    client = FakeClient()
    collector = HistoricalCandleCollector(client=client, storage=storage, config=config)

    result = collector.collect_instrument(
        InstrumentConfig(instrument_id="TEST", ticker="TST", enabled=True),
        until=end,
    )

    assert len(client.calls) == 3
    assert result.received == 3
    assert result.saved == 3
