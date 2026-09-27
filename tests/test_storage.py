from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trading_system.data_collection.models import Candle
from trading_system.data_collection.storage import ParquetCandleStorage


duckdb = pytest.importorskip("duckdb")


def candle(close: int, *, minute: int = 0) -> Candle:
    return Candle(
        instrument_id="TEST",
        time=datetime(2026, 1, 1, 10, minute, tzinfo=timezone.utc),
        open_nano=100,
        high_nano=110,
        low_nano=90,
        close_nano=close,
        volume=5,
        is_complete=True,
        source="CANDLE_SOURCE_EXCHANGE",
    )


def test_storage_is_idempotent_and_marks_raw_dirty(tmp_path: Path) -> None:
    storage = ParquetCandleStorage(tmp_path / "market", tmp_path / "trading.duckdb")
    storage.initialize()

    assert storage.upsert([candle(101)]) == 1
    assert storage.upsert([candle(102)]) == 1

    rows = storage.read_partition("1m", "TEST", 2026, 1)
    assert len(rows) == 1
    assert rows[0].close_nano == 102
    assert storage.latest_time("TEST") == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert storage.dirty_raw_partitions() == [("TEST", 2026, 1)]


def test_duckdb_catalog_exposes_parquet_view(tmp_path: Path) -> None:
    storage = ParquetCandleStorage(tmp_path / "market", tmp_path / "trading.duckdb")
    storage.initialize()
    storage.upsert([candle(101), candle(102, minute=1)])

    queried = storage.query_candles(
        "1m",
        "TEST",
        from_=datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc),
        to=datetime(2026, 1, 1, 10, 2, tzinfo=timezone.utc),
    )
    assert [row.close_nano for row in queried] == [102]

    connection = duckdb.connect(str(tmp_path / "trading.duckdb"), read_only=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM candles_1m").fetchone()[0] == 2
        metadata = connection.execute(
            "SELECT value FROM system_metadata WHERE key = 'storage_schema_version'"
        ).fetchone()
        assert metadata == ("1",)
    finally:
        connection.close()


def test_empty_duckdb_catalog_bootstraps_from_existing_parquet(tmp_path: Path) -> None:
    market_path = tmp_path / "market"
    catalog_path = tmp_path / "trading.duckdb"
    storage = ParquetCandleStorage(market_path, catalog_path)
    storage.initialize()
    storage.upsert([candle(101), candle(102, minute=1)])

    catalog_path.unlink()

    rebuilt = ParquetCandleStorage(market_path, catalog_path)
    rebuilt.initialize()

    assert rebuilt.latest_time("TEST") == datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc)
    assert rebuilt.dirty_raw_partitions() == [("TEST", 2026, 1)]
    assert len(rebuilt.query_candles("1m", "TEST")) == 2
