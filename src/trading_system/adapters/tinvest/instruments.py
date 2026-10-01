from __future__ import annotations

import json
import ssl
import time
from collections.abc import Callable, Mapping
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import truststore

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
    _RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        *,
        max_attempts: int = 5,
        backoff_seconds: float = 1.0,
        min_request_interval_seconds: float = 0.05,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        if min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds must be non-negative")

        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._min_request_interval_seconds = min_request_interval_seconds
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._ssl_context = ssl_context or self._system_ssl_context()
        self._last_request_started_at: float | None = None

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

        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self._throttle()
            try:
                with urlopen(
                    request,
                    timeout=self._timeout_seconds,
                    context=self._ssl_context,
                ) as response:
                    decoded: object = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = self._http_error_detail(exc)
                if (
                    exc.code in self._RETRYABLE_HTTP_CODES
                    and attempt < self._max_attempts
                ):
                    last_error = exc
                    self._sleep_before_retry(attempt, exc)
                    continue
                raise TInvestResponseError(
                    f"T-Invest request failed with HTTP {exc.code}: {detail}"
                ) from exc
            except ssl.SSLCertVerificationError as exc:
                raise self._certificate_error(exc) from exc
            except (URLError, TimeoutError) as exc:
                if self._is_certificate_verification_error(exc):
                    raise self._certificate_error(exc) from exc
                if attempt < self._max_attempts:
                    last_error = exc
                    self._sleep_before_retry(attempt)
                    continue
                reason = self._network_error_detail(exc)
                raise TInvestResponseError(
                    f"T-Invest network request failed after "
                    f"{self._max_attempts} attempts: {reason}"
                ) from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TInvestResponseError("T-Invest returned invalid JSON") from exc

            if not isinstance(decoded, dict):
                raise TInvestResponseError("T-Invest response root must be an object")
            return cast(dict[str, object], decoded)

        raise TInvestResponseError(
            f"T-Invest request failed after {self._max_attempts} attempts: {last_error}"
        )

    @staticmethod
    def _system_ssl_context() -> ssl.SSLContext:
        # Truststore delegates certificate validation to the operating system.
        # On Windows this uses CryptoAPI and therefore respects certificates
        # installed by corporate proxies, antivirus products, and administrators.
        return cast(
            ssl.SSLContext,
            truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )

    @staticmethod
    def _is_certificate_verification_error(
        error: URLError | TimeoutError,
    ) -> bool:
        if isinstance(error, URLError):
            reason = error.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                return True
            return "CERTIFICATE_VERIFY_FAILED" in str(reason).upper()
        return False

    @staticmethod
    def _certificate_error(
        error: BaseException,
    ) -> TInvestResponseError:
        detail = (
            str(error.reason)
            if isinstance(error, URLError) and error.reason is not None
            else str(error)
        )
        return TInvestResponseError(
            "T-Invest TLS certificate verification failed using the "
            f"operating-system trust store: {detail}. "
            "Install the proxy/antivirus root certificate into the Windows "
            "Trusted Root Certification Authorities store, then restart "
            "Trading Robot System."
        )

    def _throttle(self) -> None:
        if self._last_request_started_at is not None:
            elapsed = self._monotonic() - self._last_request_started_at
            delay = self._min_request_interval_seconds - elapsed
            if delay > 0:
                self._sleeper(delay)
        self._last_request_started_at = self._monotonic()

    def _sleep_before_retry(
        self,
        attempt: int,
        error: HTTPError | None = None,
    ) -> None:
        retry_after = self._retry_after_seconds(error)
        delay = (
            retry_after
            if retry_after is not None
            else self._backoff_seconds * (2 ** (attempt - 1))
        )
        if delay > 0:
            self._sleeper(delay)

    @staticmethod
    def _retry_after_seconds(error: HTTPError | None) -> float | None:
        if error is None or error.headers is None:
            return None
        value = error.headers.get("Retry-After")
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        return max(0.0, seconds)

    @staticmethod
    def _network_error_detail(error: URLError | TimeoutError) -> str:
        if isinstance(error, URLError):
            reason = error.reason
            return str(reason) if reason is not None else str(error)
        return str(error) or type(error).__name__

    @staticmethod
    def _http_error_detail(error: HTTPError) -> str:
        try:
            raw = error.read().decode("utf-8", errors="replace").strip()
        except Exception:
            raw = ""
        if not raw:
            return error.reason or "unknown error"

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw[:500]
        if not isinstance(payload, dict):
            return raw[:500]

        parts: list[str] = []
        for key in ("message", "description", "code"):
            value = payload.get(key)
            if value not in (None, ""):
                parts.append(f"{key}={value}")
        return "; ".join(parts) if parts else raw[:500]


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
