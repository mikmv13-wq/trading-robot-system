import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trading_system.adapters.duckdb import DuckDBBootstrapper, DuckDBMarketRepository
from trading_system.application import BootstrapDatabasesUseCase, DataApplicationService
from trading_system.config import Settings, UniverseDefinition
from trading_system.domain import (
    Candle1m,
    DataGap,
    GapClassification,
    IngestionCheckpoint,
    IngestionStatus,
    Instrument,
    Universe,
)


class _UnusedSync:
    def execute(self, universe_id: str = "default") -> object:
        raise AssertionError("not used")


class _UnusedBackfill:
    def start(self, universe_id: str = "default", **kwargs: object) -> str:
        raise AssertionError("not used")

    def resume(self, universe_id: str = "default") -> str:
        raise AssertionError("not used")


class _UnusedValidation:
    def execute(self, universe_id: str = "default", **kwargs: object) -> object:
        raise AssertionError("not used")


class _UniverseConfig:
    def list_universes(self) -> tuple[UniverseDefinition, ...]:
        return (UniverseDefinition("default", "Default", ("AAA",)),)

    def get_universe(self, universe_id: str) -> UniverseDefinition:
        return self.list_universes()[0]


class _UnusedJobs:
    def get(self, job_id: str) -> object:
        raise AssertionError("not used")

    def cancel(self, job_id: str) -> bool:
        raise AssertionError("not used")


def _repository(tmp_path: Path) -> DuckDBMarketRepository:
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
            instrument_uids=("uid-a",),
        ),
        (Instrument("uid-a", "AAA", 1),),
    )
    return repository


def test_data_application_status_aggregates_repository_state(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    start = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    repository.upsert_candles(
        (
            Candle1m(
                instrument_uid="uid-a",
                ts=start,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=10,
            ),
            Candle1m(
                instrument_uid="uid-a",
                ts=start + timedelta(minutes=2),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=11,
            ),
        )
    )
    repository.replace_data_gaps(
        "uid-a",
        from_ts=start,
        to_ts=start + timedelta(minutes=3),
        gaps=(
            DataGap(
                instrument_uid="uid-a",
                start_ts=start + timedelta(minutes=1),
                end_ts=start + timedelta(minutes=2),
                classification=GapClassification.MISSING_DURING_OBSERVED_MARKET,
            ),
        ),
    )
    repository.save_ingestion_checkpoint(
        IngestionCheckpoint(
            instrument_uid="uid-a",
            interval="1m",
            requested_from=start,
            requested_to=start + timedelta(days=1),
            completed_until=start + timedelta(hours=12),
            status=IngestionStatus.RUNNING,
        )
    )

    service = DataApplicationService(
        _UnusedSync(),  # type: ignore[arg-type]
        _UnusedBackfill(),  # type: ignore[arg-type]
        _UnusedValidation(),  # type: ignore[arg-type]
        _UnusedJobs(),  # type: ignore[arg-type]
        repository,
        _UniverseConfig(),
    )
    status = service.get_status("default")

    assert status.total_rows == 2
    assert status.total_gaps == 1
    assert len(status.instruments) == 1
    item = status.instruments[0]
    assert item.ticker == "AAA"
    assert item.row_count == 2
    assert item.gap_count == 1
    assert item.missing_minutes == 1
    assert item.checkpoint_status is IngestionStatus.RUNNING
    assert item.completed_until == start + timedelta(hours=12)
    assert item.progress == 0.5
