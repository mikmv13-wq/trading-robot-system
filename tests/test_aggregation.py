from datetime import datetime, timezone

from trading_system.data_collection.aggregation import aggregate_candles, floor_time
from trading_system.data_collection.models import Candle


def make_candle(minute: int, *, open_: int, high: int, low: int, close: int, volume: int) -> Candle:
    return Candle(
        instrument_id="TEST",
        time=datetime(2026, 1, 1, 10, minute, tzinfo=timezone.utc),
        open_nano=open_,
        high_nano=high,
        low_nano=low,
        close_nano=close,
        volume=volume,
        is_complete=True,
        source="CANDLE_SOURCE_EXCHANGE",
    )


def test_floor_time_uses_standard_boundaries() -> None:
    value = datetime(2026, 1, 1, 10, 47, tzinfo=timezone.utc)
    assert floor_time(value, 15) == datetime(2026, 1, 1, 10, 45, tzinfo=timezone.utc)
    assert floor_time(value, 30) == datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc)
    assert floor_time(value, 60) == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def test_aggregate_15m_ohlcv() -> None:
    rows = [
        make_candle(0, open_=100, high=105, low=99, close=103, volume=10),
        make_candle(1, open_=103, high=108, low=102, close=104, volume=20),
        make_candle(14, open_=104, high=106, low=98, close=101, volume=30),
        make_candle(15, open_=101, high=110, low=100, close=109, volume=40),
    ]

    result = aggregate_candles(rows, "15m")

    assert len(result) == 2
    first = result[0]
    assert first.time == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert (first.open_nano, first.high_nano, first.low_nano, first.close_nano) == (
        100,
        108,
        98,
        101,
    )
    assert first.volume == 60
    assert first.source == "AGGREGATED_FROM_1M"
