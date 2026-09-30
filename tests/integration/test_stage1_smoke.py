# ruff: noqa: I001

import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_system.adapters.duckdb import DuckDBBootstrapper, DuckDBMarketRepository
from trading_system.application import (
    BackfillHistoricalCandlesUseCase,
    BootstrapDatabasesUseCase,
    SyncInstrumentsUseCase,
    ValidateMarketDataUseCase,
)
from trading_system.config import FileUniverseConfig, Settings
from trading_system.domain import Candle1m, DataQualityStatus, IngestionStatus, Instrument


TICKERS = tuple(f"STK{index:02d}" for index in range(10))


class FakeInstrumentsClient:
    def list_shares(self) -> tuple[Instrument, ...]:
        return tuple(
            Instrument(
                instrument_uid=f"uid-{index:02d}",
                ticker=ticker,
                lot_size=10,
                exchange="MOEX",
                instrument_type="share",
                active=True,
            )
            for index, ticker in enumerate(TICKERS)
        )


class Stage1MarketDataClient:
    def __init__(
        self,
        *,
        fail_uid: str | None = None,
        fail_from: datetime | None = None,
    ) -> None:
        self.fail_uid = fail_uid
        self.fail_from = fail_from
        self.failed_once = False
        self.calls: list[tuple[str, datetime, datetime]] = []

    def get_candles(
        self,
        instrument_uid: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> tuple[Candle1m, ...]:
        self.calls.append((instrument_uid, from_ts, to_ts))
        if (
            not self.failed_once
            and self.fail_uid == instrument_uid
            and self.fail_from == from_ts
        ):
            self.failed_once = True
            raise RuntimeError("simulated broker interruption")

        timestamps = [
            from_ts,
            from_ts + timedelta(minutes=1),
            from_ts + timedelta(minutes=2),
        ]
        # One known, explainable anomaly for the last instrument.
        if (
            instrument_uid == "uid-09"
            and from_ts == RANGE_START + timedelta(days=1)
        ):
            timestamps.remove(from_ts + timedelta(minutes=1))

        return tuple(
            Candle1m(
                instrument_uid=instrument_uid,
                ts=ts,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=100,
                is_complete=True,
            )
            for ts in timestamps
        )


RANGE_START = datetime(2026, 1, 5, tzinfo=UTC)
RANGE_END = RANGE_START + timedelta(days=3)


def _runtime(
    tmp_path: Path,
) -> tuple[Settings, DuckDBMarketRepository, FileUniverseConfig]:
    source_sql = Path(__file__).parents[2] / "sql"
    sql_dir = tmp_path / "sql"
    shutil.copytree(source_sql, sql_dir)

    settings = Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
        config_dir=tmp_path / "config",
    )
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    quoted = ", ".join(f'"{ticker}"' for ticker in TICKERS)
    settings.universe_config_path.write_text(
        (
            '[universes.default]\n'
            'name = "Stage 1 smoke universe"\n'
            f"tickers = [{quoted}]\n"
        ),
        encoding="utf-8",
    )
    BootstrapDatabasesUseCase(DuckDBBootstrapper(settings)).execute()
    return (
        settings,
        DuckDBMarketRepository(settings.market_db_path),
        FileUniverseConfig(settings.universe_config_path),
    )


def test_stage1_end_to_end_definition_of_done(tmp_path: Path) -> None:
    _, repository, universe_config = _runtime(tmp_path)

    sync_result = SyncInstrumentsUseCase(
        universe_config,
        FakeInstrumentsClient(),
        repository,
    ).execute("default")
    assert len(sync_result.instruments) == 10
    assert len(sync_result.universe.instrument_uids) == 10

    market_data = Stage1MarketDataClient(
        fail_uid="uid-00",
        fail_from=RANGE_START + timedelta(days=1),
    )
    backfill = BackfillHistoricalCandlesUseCase(market_data, repository)

    with pytest.raises(RuntimeError, match="simulated broker interruption"):
        backfill.execute(
            "default",
            from_ts=RANGE_START,
            to_ts=RANGE_END,
        )

    interrupted = repository.get_ingestion_checkpoint("uid-00", "1m")
    assert interrupted is not None
    assert interrupted.status is IngestionStatus.FAILED
    assert interrupted.completed_until == RANGE_START + timedelta(days=1)

    resumed = backfill.execute("default", resume=True)
    assert resumed.total_requests == 29
    for uid in sync_result.universe.instrument_uids:
        checkpoint = repository.get_ingestion_checkpoint(uid, "1m")
        assert checkpoint is not None
        assert checkpoint.status is IngestionStatus.COMPLETED
        assert checkpoint.completed_until == RANGE_END

    counts_after_resume = {
        uid: repository.get_candle_stats(
            uid,
            from_ts=RANGE_START,
            to_ts=RANGE_END,
        ).row_count
        for uid in sync_result.universe.instrument_uids
    }
    assert counts_after_resume["uid-09"] == 8
    assert all(
        count == 9
        for uid, count in counts_after_resume.items()
        if uid != "uid-09"
    )

    # Re-running the same range is safe and must not create duplicates.
    backfill.execute(
        "default",
        from_ts=RANGE_START,
        to_ts=RANGE_END,
    )
    counts_after_repeat = {
        uid: repository.get_candle_stats(
            uid,
            from_ts=RANGE_START,
            to_ts=RANGE_END,
        ).row_count
        for uid in sync_result.universe.instrument_uids
    }
    assert counts_after_repeat == counts_after_resume

    # Repository round-trip preserves UTC for every stored timestamp.
    for uid in sync_result.universe.instrument_uids:
        candles = repository.get_candles(
            uid,
            from_ts=RANGE_START,
            to_ts=RANGE_END,
        )
        assert candles
        assert all(candle.ts.utcoffset() == timedelta(0) for candle in candles)

    report = ValidateMarketDataUseCase(
        repository,
        now_provider=lambda: RANGE_END + timedelta(days=1),
    ).execute(
        "default",
        from_ts=RANGE_START,
        to_ts=RANGE_END,
    )

    assert report.status is DataQualityStatus.WARNING
    by_uid = {item.instrument_uid: item for item in report.instruments}
    assert len(by_uid) == 10

    # Only 3 observed market minutes per day are expected. The many hours
    # where the whole universe is silent are treated as closed/unobserved,
    # not as thousands of false gaps.
    assert all(item.expected_minutes == 9 for item in report.instruments)
    assert all(
        item.coverage_ratio == 1.0
        for uid, item in by_uid.items()
        if uid != "uid-09"
    )

    anomaly = by_uid["uid-09"]
    assert anomaly.gap_count == 1
    assert anomaly.missing_minutes == 1
    assert anomaly.coverage_ratio == pytest.approx(8 / 9)
    assert anomaly.anomaly_reasons == (
        "1 missing minute(s) during observed market activity",
    )

    # Per-instrument min/max/count coverage is available for the GUI/status layer.
    for uid, expected_count in counts_after_repeat.items():
        stats = repository.get_candle_stats(
            uid,
            from_ts=RANGE_START,
            to_ts=RANGE_END,
        )
        assert stats.row_count == expected_count
        assert stats.min_timestamp == RANGE_START
        assert stats.max_timestamp == RANGE_START + timedelta(days=2, minutes=2)

    # The default production backfill window is five calendar years.
    five_year_backfill = BackfillHistoricalCandlesUseCase(
        market_data,
        repository,
        now_provider=lambda: datetime(2026, 9, 30, 12, 34, 56, tzinfo=UTC),
    )
    default_from, default_to = five_year_backfill.default_range()
    assert default_from == datetime(2021, 9, 30, 12, 34, tzinfo=UTC)
    assert default_to == datetime(2026, 9, 30, 12, 34, tzinfo=UTC)
