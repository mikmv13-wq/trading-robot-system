from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import Candle, NANO_FACTOR

logger = logging.getLogger(__name__)

CANDLES_PATH = "/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"


class TInvestApiError(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self._minimum_interval = 60.0 / requests_per_minute
        self._last_request_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        wait_for = self._minimum_interval - (now - self._last_request_at)
        if wait_for > 0:
            time.sleep(wait_for)
        self._last_request_at = time.monotonic()


class TInvestMarketDataClient:
    def __init__(
        self,
        *,
        token: str,
        base_url: str,
        timeout_seconds: float,
        requests_per_minute: int,
        max_retries: int,
        app_name: str,
    ) -> None:
        self._max_retries = max_retries
        self._rate_limiter = RateLimiter(requests_per_minute)
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-app-name": app_name,
            },
        )

    def __enter__(self) -> "TInvestMarketDataClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_minute_candles(
        self,
        *,
        instrument_id: str,
        from_: datetime,
        to: datetime,
        candle_source: str,
    ) -> list[Candle]:
        if from_.tzinfo is None or to.tzinfo is None:
            raise ValueError("from_ and to must be timezone-aware")
        if to <= from_:
            return []

        payload = {
            "from": _format_utc(from_),
            "to": _format_utc(to),
            "interval": "CANDLE_INTERVAL_1_MIN",
            "instrumentId": instrument_id,
            "candleSourceType": candle_source,
            "limit": 2400,
        }
        data = self._post_with_retry(CANDLES_PATH, payload)
        return [self._parse_candle(instrument_id, item) for item in data.get("candles", [])]

    def _post_with_retry(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            self._rate_limiter.wait()
            try:
                response = self._client.post(path, json=payload)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                self._sleep_backoff(attempt)
                continue

            if response.status_code == 429:
                last_error = TInvestApiError(f"T-Invest rate limit: {response.text}")
                if attempt >= self._max_retries:
                    break
                retry_after = _retry_after_seconds(response)
                time.sleep(retry_after if retry_after is not None else _backoff_seconds(attempt))
                continue

            if 500 <= response.status_code <= 599:
                last_error = TInvestApiError(
                    f"T-Invest temporary error {response.status_code}: {response.text}"
                )
                if attempt >= self._max_retries:
                    break
                self._sleep_backoff(attempt)
                continue

            if response.is_error:
                raise TInvestApiError(
                    f"T-Invest request failed {response.status_code}: {response.text}"
                )

            body = response.json()
            if not isinstance(body, dict):
                raise TInvestApiError("Unexpected T-Invest response type")
            return body

        raise TInvestApiError(f"T-Invest request failed after retries: {last_error}")

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        delay = _backoff_seconds(attempt)
        logger.warning("Temporary T-Invest error; retry in %.1f seconds", delay)
        time.sleep(delay)

    @staticmethod
    def _parse_candle(instrument_id: str, raw: dict[str, Any]) -> Candle:
        return Candle(
            instrument_id=instrument_id,
            time=_parse_utc(str(raw["time"])),
            open_nano=_quotation_to_nano(raw["open"]),
            high_nano=_quotation_to_nano(raw["high"]),
            low_nano=_quotation_to_nano(raw["low"]),
            close_nano=_quotation_to_nano(raw["close"]),
            volume=int(raw.get("volume", 0)),
            is_complete=bool(raw.get("isComplete", False)),
            source=str(raw["candleSource"]) if raw.get("candleSource") is not None else None,
        )


def _quotation_to_nano(value: dict[str, Any]) -> int:
    units = int(value.get("units", 0))
    nano = int(value.get("nano", 0))
    return units * NANO_FACTOR + nano


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp from API has no timezone: {value}")
    return dt.astimezone(timezone.utc)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _backoff_seconds(attempt: int) -> float:
    return min(30.0, 0.5 * (2**attempt))
