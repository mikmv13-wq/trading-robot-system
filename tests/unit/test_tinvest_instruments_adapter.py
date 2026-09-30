from collections.abc import Mapping

import pytest

from trading_system.adapters.tinvest import (
    TInvestAuthenticationError,
    TInvestInstrumentsRestClient,
)
from trading_system.domain import Instrument


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


def test_instruments_rest_client_maps_share_response() -> None:
    transport = FakeTransport(
        {
            "instruments": [
                {
                    "uid": "uid-sber",
                    "ticker": "SBER",
                    "lot": 10,
                    "name": "Sberbank",
                    "currency": "rub",
                    "figi": "BBG004730N88",
                    "exchange": "MOEX",
                    "apiTradeAvailableFlag": True,
                }
            ]
        }
    )
    client = TInvestInstrumentsRestClient(
        lambda: "secret-token",
        base_url="https://example.test/rest",
        transport=transport,
    )

    assert client.list_shares() == (
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
    assert transport.url is not None and transport.url.endswith(
        "/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares"
    )
    assert transport.headers == {"Authorization": "Bearer secret-token"}
    assert transport.payload == {"instrumentStatus": "INSTRUMENT_STATUS_BASE"}


def test_instruments_rest_client_requires_token() -> None:
    client = TInvestInstrumentsRestClient(
        lambda: None,
        transport=FakeTransport({"instruments": []}),
    )

    with pytest.raises(TInvestAuthenticationError, match="not configured"):
        client.list_shares()
