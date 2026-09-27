from trading_system.data_collection.t_invest_client import TInvestMarketDataClient


def test_parse_candle_keeps_price_precision() -> None:
    raw = {
        "time": "2026-01-01T10:00:00Z",
        "open": {"units": "123", "nano": 456000000},
        "high": {"units": "124", "nano": 1},
        "low": {"units": "122", "nano": 999999999},
        "close": {"units": "123", "nano": 500000000},
        "volume": "42",
        "isComplete": True,
        "candleSource": "CANDLE_SOURCE_EXCHANGE",
    }

    candle = TInvestMarketDataClient._parse_candle("TEST", raw)
    assert candle.open_nano == 123_456_000_000
    assert candle.high_nano == 124_000_000_001
    assert candle.low_nano == 122_999_999_999
    assert candle.close_nano == 123_500_000_000
    assert candle.volume == 42
    assert candle.is_complete is True
