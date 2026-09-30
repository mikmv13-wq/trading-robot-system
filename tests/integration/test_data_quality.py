import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trading_system.adapters.duckdb import DuckDBBootstrapper, DuckDBMarketRepository
from trading_system.application import BootstrapDatabasesUseCase, ValidateMarketDataUseCase
from trading_system.config import Settings
from trading_system.domain import (
    Candle1m,
    DataQualityStatus,
    GapClassification,
    Instrument,
    Universe,
)


def _bootstrap(tmp_path: Path) -> DuckDBMarketRepository:
    source_sql = Path(__file__).parents[2] / "sql"
    sql_dir = tmp_path / "sql"
    shutil.copytree(source_sql, sql_dir)
    settings = Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
    )
    BootstrapDatabasesUseCase(DuckDBBootstrapper(settings)).execute()
    repository = DuckDBMarketRepository(settings.market_db_path)
    repository.sync_universe(
        Universe(
            universe_id="default",
            name="Default",
            instrument_uids=("uid-a", "uid-b"),
        ),
        (
            Instrument("uid-a", "AAA", 1),
            Instrument("uid-b", "BBB", 1),
        ),
    )
    return repository


def _candle(uid: str, ts: datetime, *, is_complete: bool = True) -> Candle1m:
    return Candle1m(
        instrument_uid=uid,
        ts=ts,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=10,
        is_complete=is_complete,
    )


def test_gap_scanner_ignores_closed_market_intervals(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    start = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    t0 = start
    t1 = start + timedelta(minutes=1)
    t2 = start + timedelta(minutes=2)
    t10 = start + timedelta(minutes=10)
    end = start + timedelta(minutes=11)

    repository.upsert_candles(
        (
            _candle("uid-a", t0),
            _candle("uid-b", t0),
            _candle("uid-b", t1),
            _candle("uid-a", t2),
            _candle("uid-b", t2),
            _candle("uid-a", t10),
            _candle("uid-b", t10),
        )
    )

    gaps = repository.scan_data_gaps(
        "default",
        "uid-a",
        from_ts=start,
        to_ts=end,
    )

    assert len(gaps) == 1
    assert gaps[0].start_ts == t1
    assert gaps[0].end_ts == t2
    assert (
        gaps[0].classification
        is GapClassification.MISSING_DURING_OBSERVED_MARKET
    )


def test_data_quality_report_persists_gaps_and_coverage(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    start = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    end = start + timedelta(minutes=4)
    repository.upsert_candles(
        (
            _candle("uid-a", start),
            _candle("uid-b", start),
            _candle("uid-b", start + timedelta(minutes=1)),
            _candle("uid-a", start + timedelta(minutes=2)),
            _candle("uid-b", start + timedelta(minutes=2)),
            _candle("uid-a", start + timedelta(minutes=3)),
            _candle("uid-b", start + timedelta(minutes=3)),
        )
    )
    validator = ValidateMarketDataUseCase(
        repository,
        now_provider=lambda: datetime(2026, 1, 6, tzinfo=UTC),
    )

    report = validator.execute("default", from_ts=start, to_ts=end)

    assert report.status is DataQualityStatus.WARNING
    by_uid = {item.instrument_uid: item for item in report.instruments}
    assert by_uid["uid-a"].status is DataQualityStatus.WARNING
    assert by_uid["uid-a"].gap_count == 1
    assert by_uid["uid-a"].missing_minutes == 1
    assert by_uid["uid-a"].stats.row_count == 3
    assert by_uid["uid-b"].status is DataQualityStatus.PASS
    assert by_uid["uid-b"].gap_count == 0
    assert by_uid["uid-b"].stats.row_count == 4
    assert len(repository.get_data_gaps("uid-a")) == 1
    assert repository.get_data_gaps("uid-b") == ()


def test_incomplete_candle_produces_warning(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    start = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    end = start + timedelta(minutes=1)
    repository.upsert_candles(
        (
            _candle("uid-a", start, is_complete=False),
            _candle("uid-b", start),
        )
    )

    report = ValidateMarketDataUseCase(
        repository,
        now_provider=lambda: datetime(2026, 1, 6, tzinfo=UTC),
    ).execute("default", from_ts=start, to_ts=end)

    by_uid = {item.instrument_uid: item for item in report.instruments}
    assert by_uid["uid-a"].status is DataQualityStatus.WARNING
    assert by_uid["uid-a"].quality.incomplete_count == 1


def test_future_candle_produces_failure(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    start = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    end = start + timedelta(minutes=2)
    repository.upsert_candles(
        (
            _candle("uid-a", start),
            _candle("uid-b", start),
            _candle("uid-a", start + timedelta(minutes=1)),
            _candle("uid-b", start + timedelta(minutes=1)),
        )
    )

    report = ValidateMarketDataUseCase(
        repository,
        now_provider=lambda: start,
    ).execute("default", from_ts=start, to_ts=end)

    assert report.status is DataQualityStatus.FAIL
    assert all(
        item.quality.future_count == 1
        and item.status is DataQualityStatus.FAIL
        for item in report.instruments
    )
