from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_system.adapters.tinvest import (
    TInvestCandleNormalizer,
    TInvestMarketDataRestClient,
    TInvestResponseError,
)
from trading_system.domain import Candle1m


class FakeTransport:
    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = response
        self.url: str | None = None
        self.headers: Mapping[str, str] | None = None
        self.payload: Mapping[str, object] | None = None

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.url = url
        self.headers = headers
        self.payload = payload
        return self.response


def _quotation(units: str, nano: int = 0) -> dict[str, object]:
    return {"units": units, "nano": nano}


def _candle(
    ts: str = "2026-01-05T07:00:00Z",
    *,
    is_complete: bool = True,
) -> dict[str, object]:
    return {
        "open": _quotation("300", 100_000_000),
        "high": _quotation("301", 200_000_000),
        "low": _quotation("299", 900_000_000),
        "close": _quotation("300", 800_000_000),
        "volume": "12345",
        "time": ts,
        "isComplete": is_complete,
    }


def test_candle_normalizer_maps_quotation_and_utc_timestamp() -> None:
    candle = TInvestCandleNormalizer().normalize("uid-sber", _candle())

    assert candle == Candle1m(
        instrument_uid="uid-sber",
        ts=datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
        open=Decimal("300.100000000"),
        high=Decimal("301.200000000"),
        low=Decimal("299.900000000"),
        close=Decimal("300.800000000"),
        volume=12345,
        is_complete=True,
    )


def test_candle_normalizer_converts_offset_timestamp_to_utc() -> None:
    candle = TInvestCandleNormalizer().normalize(
        "uid",
        _candle("2026-01-05T10:00:00+03:00"),
    )

    assert candle.ts == datetime(2026, 1, 5, 7, 0, tzinfo=UTC)


def test_candle_normalizer_rejects_invalid_ohlc_before_persistence() -> None:
    payload = _candle()
    payload["low"] = _quotation("302")

    with pytest.raises(TInvestResponseError, match="invalid T-Invest candle"):
        TInvestCandleNormalizer().normalize("uid", payload)


def test_market_data_client_builds_one_minute_request() -> None:
    transport = FakeTransport({"candles": [_candle()]})
    client = TInvestMarketDataRestClient(
        lambda: "secret-token",
        base_url="https://example.test/rest",
        transport=transport,
    )
    from_ts = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    to_ts = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    result = client.get_candles("uid-sber", from_ts, to_ts)

    assert len(result) == 1
    assert transport.url is not None and transport.url.endswith(
        "/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"
    )
    assert transport.headers == {"Authorization": "Bearer secret-token"}
    assert transport.payload == {
        "from": "2026-01-05T07:00:00.000000Z",
        "to": "2026-01-05T08:00:00.000000Z",
        "interval": "CANDLE_INTERVAL_1_MIN",
        "instrumentId": "uid-sber",
        "candleSourceType": "CANDLE_SOURCE_EXCHANGE",
        "limit": 2400,
    }


def test_market_data_client_rejects_non_utc_range() -> None:
    client = TInvestMarketDataRestClient(
        lambda: "token",
        transport=FakeTransport({"candles": []}),
    )

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        client.get_candles(
            "uid",
            datetime(2026, 1, 5, 10),
            datetime(2026, 1, 5, 11, tzinfo=UTC),
        )


def test_market_data_client_rejects_more_than_one_day() -> None:
    client = TInvestMarketDataRestClient(
        lambda: "token",
        transport=FakeTransport({"candles": []}),
    )
    start = datetime(2026, 1, 5, tzinfo=UTC)

    with pytest.raises(ValueError, match="must not exceed one day"):
        client.get_candles("uid", start, start + timedelta(days=1, seconds=1))


def test_market_data_client_rejects_unsorted_candles() -> None:
    transport = FakeTransport(
        {
            "candles": [
                _candle("2026-01-05T07:01:00Z"),
                _candle("2026-01-05T07:00:00Z"),
            ]
        }
    )
    client = TInvestMarketDataRestClient(lambda: "token", transport=transport)

    with pytest.raises(TInvestResponseError, match="strictly ordered"):
        client.get_candles(
            "uid",
            datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
            datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        )
