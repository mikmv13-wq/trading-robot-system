import os
from dataclasses import dataclass
from typing import Any

import pytest

from trading_system.adapters.tinvest import (
    TInvestAuthenticationError,
    TInvestGrpcSession,
    TInvestInstrumentsGrpcClient,
)
from trading_system.adapters.tinvest.sdk import InstrumentStatus
from trading_system.domain import Instrument


@dataclass
class FakeShare:
    uid: str = "uid-sber"
    ticker: str = "SBER"
    lot: int = 10
    name: str = "Sberbank"
    currency: str = "rub"
    figi: str = "BBG004730N88"
    exchange: str = "MOEX"
    api_trade_available_flag: bool = True


@dataclass
class FakeSharesResponse:
    instruments: list[FakeShare]


class FakeInstrumentsService:
    def __init__(self, response: FakeSharesResponse) -> None:
        self.response = response
        self.instrument_status: object | None = None

    def shares(self, *, instrument_status: object) -> FakeSharesResponse:
        self.instrument_status = instrument_status
        return self.response


class FakeSdkClient:
    def __init__(self, instruments: FakeInstrumentsService) -> None:
        self.instruments = instruments


class FakeClientManager:
    def __init__(self, client: FakeSdkClient, exits: list[bool]) -> None:
        self._client = client
        self._exits = exits

    def __enter__(self) -> FakeSdkClient:
        return self._client

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._exits.append(True)


def _factory(
    client: FakeSdkClient,
    tokens: list[str],
    exits: list[bool],
) -> Any:
    def create(token: str) -> FakeClientManager:
        tokens.append(token)
        return FakeClientManager(client, exits)

    return create


def test_instruments_grpc_client_maps_sdk_share_response_and_reuses_channel() -> None:
    service = FakeInstrumentsService(FakeSharesResponse([FakeShare()]))
    tokens: list[str] = []
    exits: list[bool] = []
    session = TInvestGrpcSession(
        lambda: "secret-token",
        client_factory=_factory(FakeSdkClient(service), tokens, exits),
    )
    client = TInvestInstrumentsGrpcClient(session)

    expected = (
        Instrument(
            instrument_uid="uid-sber",
            ticker="SBER",
            lot_size=10,
            name="Sberbank",
            currency="rub",
            figi="BBG004730N88",
            exchange="MOEX",
            instrument_type="share",
            active=True,
        ),
    )
    assert client.list_shares() == expected
    assert client.list_shares() == expected
    assert service.instrument_status == InstrumentStatus.INSTRUMENT_STATUS_BASE
    assert tokens == ["secret-token"]
    assert exits == []

    session.close()
    assert exits == [True]


def test_grpc_session_reopens_channel_when_token_changes() -> None:
    service = FakeInstrumentsService(FakeSharesResponse([]))
    token = ["token-a"]
    tokens: list[str] = []
    exits: list[bool] = []
    session = TInvestGrpcSession(
        lambda: token[0],
        client_factory=_factory(FakeSdkClient(service), tokens, exits),
    )
    client = TInvestInstrumentsGrpcClient(session)

    assert client.list_shares() == ()
    token[0] = "token-b"
    assert client.list_shares() == ()

    assert tokens == ["token-a", "token-b"]
    assert exits == [True]


def test_instruments_grpc_client_requires_token() -> None:
    service = FakeInstrumentsService(FakeSharesResponse([]))
    session = TInvestGrpcSession(
        lambda: None,
        client_factory=_factory(FakeSdkClient(service), [], []),
    )

    with pytest.raises(TInvestAuthenticationError, match="не настроен"):
        TInvestInstrumentsGrpcClient(session).list_shares()


def test_sdk_tls_verification_is_enabled() -> None:
    assert os.environ["SSL_TBANK_VERIFY"] == "True"


def test_grpc_session_recognizes_tinvest_authentication_errors() -> None:
    assert TInvestGrpcSession._is_authentication_error(
        "StatusCode.UNAUTHENTICATED: 40003 Authentication token is missing or invalid"
    )
    assert not TInvestGrpcSession._is_authentication_error("StatusCode.UNAVAILABLE")
