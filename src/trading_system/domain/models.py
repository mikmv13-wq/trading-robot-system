from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")


class Decision(StrEnum):
    HOLD = "HOLD"
    ENTER_LONG = "ENTER_LONG"
    EXIT_LONG = "EXIT_LONG"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class IngestionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_uid: str
    ticker: str
    lot_size: int
    name: str | None = None
    currency: str | None = None
    figi: str | None = None
    exchange: str | None = None
    instrument_type: str | None = None
    active: bool = True

    def __post_init__(self) -> None:
        if not self.instrument_uid.strip():
            raise ValueError("instrument_uid must not be empty")
        if not self.ticker.strip():
            raise ValueError("ticker must not be empty")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


@dataclass(frozen=True, slots=True)
class Universe:
    universe_id: str
    name: str
    instrument_uids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.universe_id.strip():
            raise ValueError("universe_id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if any(not uid.strip() for uid in self.instrument_uids):
            raise ValueError("instrument_uids must not contain empty values")
        if len(set(self.instrument_uids)) != len(self.instrument_uids):
            raise ValueError("instrument_uids must not contain duplicates")
        object.__setattr__(self, "instrument_uids", tuple(sorted(self.instrument_uids)))


@dataclass(frozen=True, slots=True)
class Bar:
    instrument_uid: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    is_complete: bool = True

    def __post_init__(self) -> None:
        _require_utc(self.ts, "ts")
        if not self.instrument_uid.strip():
            raise ValueError("instrument_uid must not be empty")
        if min(self.open, self.high, self.low, self.close) < 0:
            raise ValueError("OHLC values must be non-negative")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must not exceed OHLC values")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must not be below OHLC values")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")


@dataclass(frozen=True, slots=True)
class Candle1m(Bar):
    def __post_init__(self) -> None:
        Bar.__post_init__(self)
        if self.ts.second != 0 or self.ts.microsecond != 0:
            raise ValueError("1m candle timestamp must be aligned to a minute boundary")


@dataclass(frozen=True, slots=True)
class CandleDataStats:
    instrument_uid: str
    row_count: int
    min_timestamp: datetime | None
    max_timestamp: datetime | None

    def __post_init__(self) -> None:
        if not self.instrument_uid.strip():
            raise ValueError("instrument_uid must not be empty")
        if self.row_count < 0:
            raise ValueError("row_count must be non-negative")
        if self.row_count == 0:
            if self.min_timestamp is not None or self.max_timestamp is not None:
                raise ValueError("empty candle stats must not have timestamps")
            return
        if self.min_timestamp is None or self.max_timestamp is None:
            raise ValueError("non-empty candle stats must have min/max timestamps")
        _require_utc(self.min_timestamp, "min_timestamp")
        _require_utc(self.max_timestamp, "max_timestamp")
        if self.min_timestamp > self.max_timestamp:
            raise ValueError("min_timestamp must not be after max_timestamp")


@dataclass(frozen=True, slots=True)
class IngestionCheckpoint:
    instrument_uid: str
    interval: str
    requested_from: datetime
    requested_to: datetime
    completed_until: datetime | None
    status: IngestionStatus
    last_error: str | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.instrument_uid.strip():
            raise ValueError("instrument_uid must not be empty")
        if not self.interval.strip():
            raise ValueError("interval must not be empty")
        _require_utc(self.requested_from, "requested_from")
        _require_utc(self.requested_to, "requested_to")
        if self.requested_from >= self.requested_to:
            raise ValueError("requested_from must be earlier than requested_to")
        if self.completed_until is not None:
            _require_utc(self.completed_until, "completed_until")
            if not self.requested_from <= self.completed_until <= self.requested_to:
                raise ValueError("completed_until must be within requested range")
        if self.updated_at is not None:
            _require_utc(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True)
class Position:
    instrument_uid: str
    quantity: int
    average_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OrderIntent:
    instrument_uid: str
    side: OrderSide
    quantity: int
    client_order_id: str

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if not self.client_order_id.strip():
            raise ValueError("client_order_id must not be empty")


@dataclass(frozen=True, slots=True)
class Fill:
    instrument_uid: str
    quantity: int
    price: Decimal
    commission: Decimal
    ts: datetime

    def __post_init__(self) -> None:
        _require_utc(self.ts, "ts")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.price < 0 or self.commission < 0:
            raise ValueError("price and commission must be non-negative")


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    strategy_version: str
    params: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_version.strip():
            raise ValueError("strategy_version must not be empty")
        object.__setattr__(self, "params", dict(self.params))
