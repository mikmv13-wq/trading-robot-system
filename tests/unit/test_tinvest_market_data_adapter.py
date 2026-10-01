from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from trading_system.adapters.tinvest import (
    TInvestCandleNormalizer,
    TInvestGrpcSession,
    TInvestMarketDataGrpcClient,
    TInvestResponseError,
)
from trading_system.adapters.tinvest.sdk import CandleInterval, CandleSource
from trading_system.domain import Candle1m


@dataclass
class FakeQuotation:
    units: int
    nano: int = 0


@dataclass
class FakeCandle:
    open: FakeQuotation
    high: FakeQuotation
    low: FakeQuotation
    close: FakeQuotation
    volume: int
    time: datetime
    is_complete: bool = True


@dataclass
class FakeCandlesResponse:
    candles: list[FakeCandle]


class FakeMarketDataService:
    def __init__(self, response: FakeCandlesResponse) -> None:
        self.response = response
        self.kwargs: dict[str, object] | None = None

    def get_candles(self, **kwargs: object) -> FakeCandlesResponse:
        self.kwargs = kwargs
        return self.response


class FakeSdkClient:
    def __init__(self, market_data: FakeMarketDataService) -> None:
        self.market_data = market_data


class FakeClientManager:
    def __init__(self, client: FakeSdkClient) -> None:
        self._client = client

    def __enter__(self) -> FakeSdkClient:
        return self._client

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _factory(client: FakeSdkClient) -> Any:
    def create(token: str) -> FakeClientManager:
        assert token == "token"
        return FakeClientManager(client)

    return create


def _candle(
    ts: datetime | None = None,
    *,
    is_complete: bool = True,
) -> FakeCandle:
    return FakeCandle(
        open=FakeQuotation(300, 100_000_000),
        high=FakeQuotation(301, 200_000_000),
        low=FakeQuotation(299, 900_000_000),
        close=FakeQuotation(300, 800_000_000),
        volume=12_345,
        time=ts or datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
        is_complete=is_complete,
    )


def _client(
    response: FakeCandlesResponse,
) -> tuple[TInvestMarketDataGrpcClient, FakeMarketDataService]:
    service = FakeMarketDataService(response)
    session = TInvestGrpcSession(
        lambda: "token",
        client_factory=_factory(FakeSdkClient(service)),
    )
    return TInvestMarketDataGrpcClient(session), service


def test_candle_normalizer_maps_sdk_quotation_and_utc_timestamp() -> None:
    candle = TInvestCandleNormalizer().normalize("uid-sber", _candle())

    assert candle == Candle1m(
        instrument_uid="uid-sber",
        ts=datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
        open=Decimal("300.100000000"),
        high=Decimal("301.200000000"),
        low=Decimal("299.900000000"),
        close=Decimal("300.800000000"),
        volume=12_345,
        is_complete=True,
    )


def test_candle_normalizer_converts_offset_timestamp_to_utc() -> None:
    candle = TInvestCandleNormalizer().normalize(
        "uid",
        _candle(datetime(2026, 1, 5, 10, 0, tzinfo=timezone(timedelta(hours=3)))),
    )

    assert candle.ts == datetime(2026, 1, 5, 7, 0, tzinfo=UTC)


def test_candle_normalizer_rejects_invalid_ohlc_before_persistence() -> None:
    candle = _candle()
    candle.low = FakeQuotation(302)

    with pytest.raises(TInvestResponseError, match="invalid T-Invest candle"):
        TInvestCandleNormalizer().normalize("uid", candle)


def test_market_data_client_builds_one_minute_grpc_request() -> None:
    client, service = _client(FakeCandlesResponse([_candle()]))
    from_ts = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    to_ts = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    result = client.get_candles("uid-sber", from_ts, to_ts)

    assert len(result) == 1
    assert service.kwargs == {
        "instrument_id": "uid-sber",
        "from_": from_ts,
        "to": to_ts,
        "interval": CandleInterval.CANDLE_INTERVAL_1_MIN,
        "candle_source_type": CandleSource.CANDLE_SOURCE_EXCHANGE,
        "limit": 2400,
    }


def test_market_data_client_rejects_non_utc_range() -> None:
    client, _ = _client(FakeCandlesResponse([]))

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        client.get_candles(
            "uid",
            datetime(2026, 1, 5, 10),
            datetime(2026, 1, 5, 11, tzinfo=UTC),
        )


def test_market_data_client_rejects_more_than_one_day() -> None:
    client, _ = _client(FakeCandlesResponse([]))
    start = datetime(2026, 1, 5, tzinfo=UTC)

    with pytest.raises(ValueError, match="must not exceed one day"):
        client.get_candles("uid", start, start + timedelta(days=1, seconds=1))


def test_market_data_client_rejects_unsorted_candles() -> None:
    client, _ = _client(
        FakeCandlesResponse(
            [
                _candle(datetime(2026, 1, 5, 7, 1, tzinfo=UTC)),
                _candle(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
            ]
        )
    )

    with pytest.raises(TInvestResponseError, match="strictly ordered"):
        client.get_candles(
            "uid",
            datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
            datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        )
