from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_system.domain import Bar, Instrument


def test_instrument_rejects_non_positive_lot_size() -> None:
    with pytest.raises(ValueError, match="lot_size"):
        Instrument(instrument_uid="uid", ticker="TEST", lot_size=0)


def test_bar_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        Bar(
            instrument_uid="uid",
            ts=datetime(2026, 1, 1),
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10.5"),
            volume=1,
        )


def test_bar_accepts_valid_utc_values() -> None:
    bar = Bar(
        instrument_uid="uid",
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=1,
    )

    assert bar.is_complete is True


def test_bar_rejects_non_utc_timestamp() -> None:
    with pytest.raises(ValueError, match="must be UTC"):
        Bar(
            instrument_uid="uid",
            ts=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=3))),
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10.5"),
            volume=1,
        )
