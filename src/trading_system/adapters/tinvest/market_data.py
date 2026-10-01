from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from trading_system.adapters.tinvest.errors import TInvestResponseError
from trading_system.adapters.tinvest.sdk import CandleInterval, CandleSource
from trading_system.adapters.tinvest.session import TInvestGrpcSession
from trading_system.domain import Candle1m


class TInvestCandleNormalizer:
    """Convert T-Invest SDK HistoricCandle objects into domain Candle1m values."""

    _NANO_SCALE = Decimal("0.000000001")

    def normalize(self, instrument_uid: str, candle: object) -> Candle1m:
        try:
            return Candle1m(
                instrument_uid=instrument_uid,
                ts=self._timestamp(getattr(candle, "time", None)),
                open=self._quotation(getattr(candle, "open", None), "open"),
                high=self._quotation(getattr(candle, "high", None), "high"),
                low=self._quotation(getattr(candle, "low", None), "low"),
                close=self._quotation(getattr(candle, "close", None), "close"),
                volume=self._integer(getattr(candle, "volume", None), "volume"),
                is_complete=self._boolean(
                    getattr(candle, "is_complete", None),
                    "is_complete",
                ),
            )
        except ValueError as exc:
            raise TInvestResponseError(f"invalid T-Invest candle: {exc}") from exc

    @classmethod
    def _quotation(cls, value: object, field_name: str) -> Decimal:
        if value is None:
            raise ValueError(f"{field_name} quotation is missing")

        units = getattr(value, "units", None)
        nano = getattr(value, "nano", None)
        if isinstance(units, bool) or not isinstance(units, (str, int)):
            raise ValueError(f"{field_name}.units must be an integer")
        if isinstance(nano, bool) or not isinstance(nano, int):
            raise ValueError(f"{field_name}.nano must be an integer")
        if nano < -999_999_999 or nano > 999_999_999:
            raise ValueError(f"{field_name}.nano is outside Quotation range")

        try:
            units_decimal = Decimal(str(units))
        except InvalidOperation as exc:
            raise ValueError(f"{field_name}.units must be an integer") from exc
        if units_decimal != units_decimal.to_integral_value():
            raise ValueError(f"{field_name}.units must be an integer")

        return units_decimal + (Decimal(nano) * cls._NANO_SCALE)

    @staticmethod
    def _integer(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} must be an integer")
        return value

    @staticmethod
    def _boolean(value: object, field_name: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} must be a boolean")
        return value

    @staticmethod
    def _timestamp(value: object) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError("time must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("time must include a timezone")
        return value.astimezone(UTC)


class TInvestMarketDataGrpcClient:
    """Historical 1m candle adapter backed by the official T-Invest gRPC SDK."""

    _MAX_1M_RANGE = timedelta(days=1)
    _MAX_1M_LIMIT = 2400

    def __init__(
        self,
        session: TInvestGrpcSession,
        *,
        normalizer: TInvestCandleNormalizer | None = None,
    ) -> None:
        self._session = session
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

        response = self._session.execute(
            lambda client: client.market_data.get_candles(
                instrument_id=normalized_uid,
                from_=from_ts,
                to=to_ts,
                interval=CandleInterval.CANDLE_INTERVAL_1_MIN,
                candle_source_type=CandleSource.CANDLE_SOURCE_EXCHANGE,
                limit=self._MAX_1M_LIMIT,
            )
        )
        raw_candles = getattr(response, "candles", None)
        if raw_candles is None or isinstance(raw_candles, (str, bytes)):
            raise TInvestResponseError(
                "T-Invest GetCandles response does not contain candles"
            )

        try:
            sdk_candles = tuple(raw_candles)
        except TypeError as exc:
            raise TInvestResponseError(
                "T-Invest GetCandles response contains invalid candles"
            ) from exc

        candles: list[Candle1m] = []
        previous_ts: datetime | None = None
        for raw_candle in sdk_candles:
            candle = self._normalizer.normalize(normalized_uid, raw_candle)
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
