from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

from trading_system.adapters.tinvest.instruments import (
    JsonHttpTransport,
    TInvestAuthenticationError,
    TInvestResponseError,
    UrllibJsonHttpTransport,
)
from trading_system.domain import Candle1m


class TInvestCandleNormalizer:
    """Convert T-Invest REST candle payloads into domain Candle1m values."""

    _NANO_SCALE = Decimal("0.000000001")

    def normalize(
        self,
        instrument_uid: str,
        payload: Mapping[str, object],
    ) -> Candle1m:
        try:
            return Candle1m(
                instrument_uid=instrument_uid,
                ts=self._timestamp(payload.get("time")),
                open=self._quotation(payload.get("open"), "open"),
                high=self._quotation(payload.get("high"), "high"),
                low=self._quotation(payload.get("low"), "low"),
                close=self._quotation(payload.get("close"), "close"),
                volume=self._integer(payload.get("volume"), "volume"),
                is_complete=self._boolean(payload.get("isComplete"), "isComplete"),
            )
        except ValueError as exc:
            raise TInvestResponseError(f"invalid T-Invest candle: {exc}") from exc

    @classmethod
    def _quotation(cls, value: object, field_name: str) -> Decimal:
        if not isinstance(value, dict):
            raise ValueError(f"{field_name} quotation must be an object")

        quotation = cast(dict[str, object], value)
        units = quotation.get("units")
        nano = quotation.get("nano")

        if isinstance(units, bool) or not isinstance(units, (str, int)):
            raise ValueError(f"{field_name}.units must be an integer string")
        if isinstance(nano, bool) or not isinstance(nano, int):
            raise ValueError(f"{field_name}.nano must be an integer")
        if nano < -999_999_999 or nano > 999_999_999:
            raise ValueError(f"{field_name}.nano is outside Quotation range")

        try:
            units_decimal = Decimal(str(units))
        except InvalidOperation as exc:
            raise ValueError(f"{field_name}.units must be an integer string") from exc

        if units_decimal != units_decimal.to_integral_value():
            raise ValueError(f"{field_name}.units must be an integer string")

        return units_decimal + (Decimal(nano) * cls._NANO_SCALE)

    @staticmethod
    def _integer(value: object, field_name: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be an integer")

        if isinstance(value, int):
            return value

        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as exc:
                raise ValueError(f"{field_name} must be an integer string") from exc

        raise ValueError(f"{field_name} must be an integer string")

    @staticmethod
    def _boolean(value: object, field_name: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} must be a boolean")
        return value

    @staticmethod
    def _timestamp(value: object) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("time must be an RFC3339 timestamp")

        try:
            timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("time must be an RFC3339 timestamp") from exc

        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("time must include a timezone")
        return timestamp.astimezone(UTC)


class TInvestMarketDataRestClient:
    _GET_CANDLES_PATH = (
        "/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"
    )
    _MAX_1M_RANGE = timedelta(days=1)
    _MAX_1M_LIMIT = 2400

    def __init__(
        self,
        token_provider: Callable[[], str | None],
        *,
        base_url: str = "https://invest-public-api.tbank.ru/rest",
        transport: JsonHttpTransport | None = None,
        normalizer: TInvestCandleNormalizer | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._base_url = base_url.rstrip("/")
        self._transport = transport or UrllibJsonHttpTransport()
        self._normalizer = normalizer or TInvestCandleNormalizer()

    def get_candles(
        self,
        instrument_uid: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> tuple[Candle1m, ...]:
        normalized_uid = instrument_uid.strip()
        if not normalized_uid:
            raise ValueError("instrument_uid must not be empty")

        self._validate_utc(from_ts, "from_ts")
        self._validate_utc(to_ts, "to_ts")
        if from_ts >= to_ts:
            raise ValueError("from_ts must be earlier than to_ts")
        if to_ts - from_ts > self._MAX_1M_RANGE:
            raise ValueError("1m candle request range must not exceed one day")

        token = self._token_provider()
        if token is None or not token.strip():
            raise TInvestAuthenticationError("T-Invest token is not configured")

        response = self._transport.post(
            f"{self._base_url}{self._GET_CANDLES_PATH}",
            headers={"Authorization": f"Bearer {token.strip()}"},
            payload={
                "from": self._format_utc(from_ts),
                "to": self._format_utc(to_ts),
                "interval": "CANDLE_INTERVAL_1_MIN",
                "instrumentId": normalized_uid,
                "candleSourceType": "CANDLE_SOURCE_EXCHANGE",
                "limit": self._MAX_1M_LIMIT,
            },
        )
        raw_candles = response.get("candles")
        if not isinstance(raw_candles, list):
            raise TInvestResponseError(
                "T-Invest GetCandles response does not contain candles"
            )

        candles: list[Candle1m] = []
        previous_ts: datetime | None = None
        for raw_candle in raw_candles:
            if not isinstance(raw_candle, dict):
                raise TInvestResponseError("T-Invest candle must be an object")
            candle = self._normalizer.normalize(
                normalized_uid,
                cast(dict[str, object], raw_candle),
            )
            if candle.ts < from_ts or candle.ts > to_ts:
                raise TInvestResponseError(
                    "T-Invest candle timestamp is outside requested range"
                )
            if previous_ts is not None and candle.ts <= previous_ts:
                raise TInvestResponseError(
                    "T-Invest candles must be strictly ordered by timestamp"
                )
            previous_ts = candle.ts
            candles.append(candle)

        return tuple(candles)

    @staticmethod
    def _validate_utc(value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must be UTC")

    @staticmethod
    def _format_utc(value: datetime) -> str:
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
            "+00:00",
            "Z",
        )
