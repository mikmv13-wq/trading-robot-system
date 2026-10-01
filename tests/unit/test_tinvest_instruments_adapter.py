import ssl
from collections.abc import Mapping
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from trading_system.adapters.tinvest import (
    TInvestAuthenticationError,
    TInvestInstrumentsRestClient,
    TInvestResponseError,
    UrllibJsonHttpTransport,
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


def test_http_transport_retries_transient_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            return None

        def read(self) -> bytes:
            return b'{"instruments": []}'

    def fake_urlopen(request: object, timeout: float, context: object) -> FakeResponse:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise URLError("temporary DNS failure")
        return FakeResponse()

    monkeypatch.setattr(
        "trading_system.adapters.tinvest.instruments.urlopen",
        fake_urlopen,
    )

    transport = UrllibJsonHttpTransport(
        max_attempts=3,
        backoff_seconds=0.1,
        min_request_interval_seconds=0.0,
        sleeper=sleeps.append,
    )

    assert transport.post(
        "https://example.test",
        headers={},
        payload={},
    ) == {"instruments": []}
    assert attempts == 3
    assert sleeps == [0.1, 0.2]


def test_http_transport_retries_429_using_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            return None

        def read(self) -> bytes:
            return b'{"instruments": []}'

    def fake_urlopen(request: object, timeout: float, context: object) -> FakeResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(
                "https://example.test",
                429,
                "Too Many Requests",
                {"Retry-After": "2"},
                BytesIO(b'{"message":"rate limit"}'),
            )
        return FakeResponse()

    monkeypatch.setattr(
        "trading_system.adapters.tinvest.instruments.urlopen",
        fake_urlopen,
    )

    transport = UrllibJsonHttpTransport(
        max_attempts=2,
        backoff_seconds=0.1,
        min_request_interval_seconds=0.0,
        sleeper=sleeps.append,
    )
    transport.post("https://example.test", headers={}, payload={})

    assert attempts == 2
    assert sleeps == [2.0]


def test_http_transport_reports_network_reason_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: float, context: object) -> object:
        raise URLError("connection reset by peer")

    monkeypatch.setattr(
        "trading_system.adapters.tinvest.instruments.urlopen",
        fake_urlopen,
    )

    transport = UrllibJsonHttpTransport(
        max_attempts=2,
        backoff_seconds=0.0,
        min_request_interval_seconds=0.0,
    )

    with pytest.raises(
        TInvestResponseError,
        match="connection reset by peer",
    ):
        transport.post("https://example.test", headers={}, payload={})


def test_http_transport_reports_tinvest_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: float, context: object) -> object:
        raise HTTPError(
            "https://example.test",
            400,
            "Bad Request",
            {},
            BytesIO(b'{"code":"30014","message":"invalid argument"}'),
        )

    monkeypatch.setattr(
        "trading_system.adapters.tinvest.instruments.urlopen",
        fake_urlopen,
    )

    transport = UrllibJsonHttpTransport(
        max_attempts=1,
        min_request_interval_seconds=0.0,
    )

    with pytest.raises(
        TInvestResponseError,
        match="invalid argument",
    ):
        transport.post("https://example.test", headers={}, payload={})


def test_http_transport_does_not_retry_certificate_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(
        request: object,
        timeout: float,
        context: object,
    ) -> object:
        nonlocal attempts
        attempts += 1
        reason = ssl.SSLCertVerificationError(
            1,
            "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain",
        )
        raise URLError(reason)

    monkeypatch.setattr(
        "trading_system.adapters.tinvest.instruments.urlopen",
        fake_urlopen,
    )

    transport = UrllibJsonHttpTransport(
        max_attempts=5,
        backoff_seconds=0.1,
        min_request_interval_seconds=0.0,
        sleeper=sleeps.append,
    )

    with pytest.raises(
        TInvestResponseError,
        match="operating-system trust store",
    ):
        transport.post("https://example.test", headers={}, payload={})

    assert attempts == 1
    assert sleeps == []
