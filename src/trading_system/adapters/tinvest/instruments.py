from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trading_system.domain import Instrument


class TInvestClientError(RuntimeError):
    """Base error for T-Invest REST access."""


class TInvestAuthenticationError(TInvestClientError):
    """Raised when an API token is not configured."""


class TInvestResponseError(TInvestClientError):
    """Raised when T-Invest returns an invalid or unsuccessful response."""


class JsonHttpTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class UrllibJsonHttpTransport:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout_seconds = timeout_seconds

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        request_headers = dict(headers)
        request_headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=json.dumps(dict(payload)).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                decoded: object = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise TInvestResponseError(
                f"T-Invest request failed with HTTP {exc.code}"
            ) from exc
        except URLError as exc:
            raise TInvestResponseError("T-Invest request failed") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TInvestResponseError("T-Invest returned invalid JSON") from exc

        if not isinstance(decoded, dict):
            raise TInvestResponseError("T-Invest response root must be an object")
        return cast(dict[str, object], decoded)


class TInvestInstrumentsRestClient:
    _SHARES_PATH = (
        "/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares"
    )

    def __init__(
        self,
        token_provider: Callable[[], str | None],
        *,
        base_url: str = "https://invest-public-api.tbank.ru/rest",
        transport: JsonHttpTransport | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._base_url = base_url.rstrip("/")
        self._transport = transport or UrllibJsonHttpTransport()

    def list_shares(self) -> tuple[Instrument, ...]:
        token = self._token_provider()
        if token is None or not token.strip():
            raise TInvestAuthenticationError("T-Invest token is not configured")

        response = self._transport.post(
            f"{self._base_url}{self._SHARES_PATH}",
            headers={"Authorization": f"Bearer {token.strip()}"},
            payload={"instrumentStatus": "INSTRUMENT_STATUS_BASE"},
        )
        raw_instruments = response.get("instruments")
        if not isinstance(raw_instruments, list):
            raise TInvestResponseError(
                "T-Invest Shares response does not contain instruments"
            )

        instruments: list[Instrument] = []
        for raw_instrument in raw_instruments:
            if not isinstance(raw_instrument, dict):
                raise TInvestResponseError("T-Invest instrument must be an object")
            item = cast(dict[str, object], raw_instrument)
            instruments.append(
                Instrument(
                    instrument_uid=self._required_str(item, "uid"),
                    ticker=self._required_str(item, "ticker").upper(),
                    lot_size=self._required_int(item, "lot"),
                    name=self._optional_str(item, "name"),
                    currency=self._optional_str(item, "currency"),
                    figi=self._optional_str(item, "figi"),
                    exchange=self._optional_str(item, "exchange"),
                    instrument_type="share",
                    active=self._optional_bool(
                        item,
                        "apiTradeAvailableFlag",
                        default=False,
                    ),
                )
            )
        return tuple(instruments)

    @staticmethod
    def _required_str(item: Mapping[str, object], key: str) -> str:
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise TInvestResponseError(f"T-Invest instrument has invalid {key}")
        return value.strip()

    @staticmethod
    def _optional_str(item: Mapping[str, object], key: str) -> str | None:
        value = item.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise TInvestResponseError(f"T-Invest instrument has invalid {key}")
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _required_int(item: Mapping[str, object], key: str) -> int:
        value = item.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise TInvestResponseError(f"T-Invest instrument has invalid {key}")
        return value

    @staticmethod
    def _optional_bool(
        item: Mapping[str, object],
        key: str,
        *,
        default: bool,
    ) -> bool:
        value = item.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise TInvestResponseError(f"T-Invest instrument has invalid {key}")
        return value
